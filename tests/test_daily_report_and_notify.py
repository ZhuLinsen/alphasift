# -*- coding: utf-8 -*-
"""Tests for P2-1 DailyReport schema, <1200-char IM cards, idempotent push, and doctor radar."""

from __future__ import annotations

import base64
from datetime import date
import hashlib
import hmac
import json
from pathlib import Path
import sys
import threading

import numpy as np
import pandas as pd
import pytest

from alphasift.cli import main as cli_main
from alphasift.config import Config
from alphasift.daily_report import (
    DEFAULT_DASHBOARD_URL,
    IM_CARD_MAX_CHARS,
    build_daily_report,
    ensure_im_card_length,
    load_daily_report_runs,
    render_daily_im_card,
)
from alphasift.store import save_screen_result
from alphasift.doctor import doctor_radar_readiness
from alphasift.models import Pick, ScreenResult
from alphasift.notify import push_daily_report
from alphasift.pack import DailyPack, FIELDS, save_pack
from alphasift.result_schema import daily_report_schema, screen_result_schema


def _make_pack(n_days: int = 65, n_codes: int = 3) -> DailyPack:
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-08-03", periods=n_days)]
    codes = [f"{i + 1:06d}" for i in range(n_codes)]
    matrices = {field: np.full((n_days, n_codes), np.nan, dtype=np.float32) for field in FIELDS}
    for j in range(n_codes):
        for t in range(n_days):
            px = 10.0 + 0.05 * t
            matrices["open"][t, j] = px
            matrices["high"][t, j] = px + 0.12
            matrices["low"][t, j] = px - 0.12
            matrices["close"][t, j] = px + 0.04
            matrices["pre_close"][t, j] = px
            matrices["volume"][t, j] = 10_000_000.0
            matrices["amount"][t, j] = 100_000_000.0
    # Make 000001 trigger box_breakout on last day
    last = n_days - 1
    matrices["open"][last, 0] = 13.30
    matrices["high"][last, 0] = 14.15
    matrices["low"][last, 0] = 13.25
    matrices["close"][last, 0] = 14.10
    matrices["volume"][last, 0] = 28_000_000.0
    matrices["amount"][last, 0] = 390_000_000.0

    meta = pd.DataFrame([
        {
            "code": c,
            "name": f"测试股{c[-2:]}",
            "industry": "半导体",
            "pe_ratio": 20.0,
            "pb_ratio": 2.0,
            "total_mv": 1e10,
            "circ_mv": 8e9,
            "list_date": "2018-01-01",
            "is_st": False,
        }
        for c in codes
    ])
    return DailyPack(
        dates=np.asarray(dates, dtype=str),
        codes=np.asarray(codes, dtype=str),
        matrices=matrices,
        meta=meta,
        sources=("test",),
    )


def _dummy_run(strategy: str, *, track: str, code: str, name: str) -> ScreenResult:
    return ScreenResult(
        strategy=strategy,
        market="cn",
        run_id=f"{strategy}_{track}",
        track=track,
        llm_ranked=(track == "ai"),
        picks=[
            Pick(rank=1, code=code, name=name, industry="半导体", final_score=88.5, screen_score=85.0, change_pct=3.2),
        ],
    )


def test_result_schemas_include_track_and_daily_report() -> None:
    sr_schema = screen_result_schema()
    assert "track" in sr_schema["top_level_fields"]

    dr_schema = daily_report_schema()
    assert dr_schema["object"] == "DailyReport"
    assert dr_schema["im_card_max_chars"] == IM_CARD_MAX_CHARS
    assert "im_card_markdown" in dr_schema["top_level_fields"]
    assert "announcement_risks" in dr_schema["top_level_fields"]


def test_build_daily_report_with_announcements_and_card_limit() -> None:
    pack = _make_pack()
    runs = [
        _dummy_run("dual_low", track="rules", code="000001", name="测试股01"),
        _dummy_run("dual_low", track="ai", code="000002", name="测试股02"),
    ]

    def fake_ann(df: pd.DataFrame, *, max_rows: int, cache_dir=None):
        rows = []
        for row in df.itertuples(index=False):
            if row.code == "000001":
                rows.append({
                    "code": "000001",
                    "name": "测试股01",
                    "announcement": "2026-11-20 股东拟减持不超过2%",
                    "negative_event_flags": ["减持"],
                    "announcement_categories": ["减持"],
                })
            else:
                rows.append({
                    "code": row.code,
                    "name": row.name,
                    "announcement": "2026-11-20 日常经营公告",
                    "negative_event_flags": [],
                    "announcement_categories": [],
                })
        return rows, []

    report = build_daily_report(
        pack,
        strategy_runs=runs,
        announcement_collector=fake_ann,
    )
    assert report["object"] == "DailyReport"
    assert report["market"] == "cn"
    assert report["usage_policy"] == "cn_only_regime_slice_only"
    assert len(report["strategies"]) == 2
    assert report["announcement_risks"]["flagged_count"] == 1
    assert report["strategies"][0]["picks"][0]["announcement_risk_flags"] == ["减持"]
    assert "减持" in report["im_card_markdown"]
    assert "[AI]" in report["im_card_markdown"]
    assert report["im_card_chars"] == len(report["im_card_markdown"])
    assert report["im_card_chars"] < 1200

    # Stress-test hard <1200 char budget with lots of noisy strategy/pattern entries.
    bloated = dict(report)
    bloated["strategies"] = [
        {
            "strategy": f"very_long_strategy_{i}",
            "track": "rules",
            "llm_ranked": False,
            "picks": [
                {"code": f"60000{k}", "name": f"超长股票名称样本{i}{k}" * 3, "announcement_risk_flags": ["减持", "监管"]}
                for k in range(3)
            ],
        }
        for i in range(10)
    ]
    bloated_card = render_daily_im_card(bloated)
    assert len(bloated_card) < 1200
    assert "量化形态观测与回测基准" in bloated_card

    # Announcement failure must degrade cleanly instead of crashing daily_report.
    def broken_ann(df, *, max_rows: int, cache_dir=None):
        raise RuntimeError("cninfo timeout")

    report_err = build_daily_report(pack, strategy_runs=runs, announcement_collector=broken_ann)
    assert report_err["degradation"]
    assert "cninfo timeout" in report_err["degradation"][0]
    assert report_err["im_card_chars"] < 1200


class _DummyResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._payload


def test_notify_silent_skip_idempotency_signatures_and_redaction(tmp_path: Path, monkeypatch) -> None:
    pack = _make_pack()
    report = build_daily_report(pack, include_announcements=False)
    state_path = tmp_path / "notify_state.json"

    # 1. No configured webhooks -> silent skip, 0 HTTP calls.
    calls: list[tuple[str, dict]] = []

    def fail_if_called(*args, **kwargs):
        raise AssertionError("HTTP post should not be called when no channels are configured")

    cfg_empty = Config(notify_state_path=state_path)
    res_skip = push_daily_report(report, config=cfg_empty, post_fn=fail_if_called)
    assert res_skip["status"] == "skipped_no_channels"
    assert res_skip["sent"] == []

    # 2. All 3 channels configured -> verify payloads + Feishu HMAC signature + idempotency.
    monkeypatch.setattr("alphasift.notify.time.time", lambda: 1763632800)

    def mock_post(url: str, *, json: dict, timeout: float):
        calls.append((url, json))
        if "qyapi.weixin.qq.com" in url:
            return _DummyResponse(200, {"errcode": 0, "errmsg": "ok"})
        if "open.feishu.cn" in url:
            return _DummyResponse(200, {"code": 0, "msg": "success"})
        return _DummyResponse(200, {"ok": True})

    wecom_hook_id = "unit-test-wecom-hook"
    feishu_hook_id = "unit-test-feishu-hook"
    feishu_sign_fixture = "unit-test-" + "hmac-fixture"
    tg_fixture_token = "000000:" + "unit-test-tg-fixture"
    cfg = Config(
        wecom_webhook_url=f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={wecom_hook_id}",
        feishu_webhook_url=f"https://open.feishu.cn/open-apis/bot/v2/hook/{feishu_hook_id}",
        feishu_webhook_secret=feishu_sign_fixture,
        telegram_bot_token=tg_fixture_token,
        telegram_chat_id="-10012345",
        notify_state_path=state_path,
    )
    res1 = push_daily_report(report, config=cfg, post_fn=mock_post)
    assert res1["status"] == "ok"
    assert res1["sent"] == ["wecom", "feishu", "telegram"]
    assert res1["card_chars"] < 1200
    assert len(calls) == 3

    # Verify Feishu v2 HMAC signature calculation.
    feishu_body = calls[1][1]
    expected_sign = base64.b64encode(
        hmac.new(f"1763632800\n{feishu_sign_fixture}".encode("utf-8"), msg=b"", digestmod=hashlib.sha256).digest()
    ).decode("utf-8")
    assert feishu_body["timestamp"] == "1763632800"
    assert feishu_body["sign"] == expected_sign

    # Re-running on same trade_date -> idempotent skip with 0 HTTP calls!
    calls.clear()
    res2 = push_daily_report(report, config=cfg, post_fn=fail_if_called)
    assert res2["status"] == "skipped_duplicate"
    assert res2["sent"] == []
    assert len(res2["skipped"]) == 3

    # force=True dispatches again, while HTTP failures redact secret URLs/tokens.
    def broken_post(url: str, *, json: dict, timeout: float):
        raise RuntimeError(f"failed connecting to {url} with {feishu_sign_fixture}")

    res_err = push_daily_report(report, config=cfg, force=True, post_fn=broken_post)
    assert res_err["status"] == "error"
    for err_entry in res_err["errors"]:
        msg = err_entry["error"]
        assert wecom_hook_id not in msg
        assert feishu_hook_id not in msg
        assert feishu_sign_fixture not in msg
        assert tg_fixture_token not in msg


def test_doctor_radar_and_cli_smoke(tmp_path: Path, monkeypatch, capsys) -> None:
    pack = _make_pack()
    pack_dir = tmp_path / "pack_cn"
    save_pack(pack_dir, pack)

    cfg = Config(
        wecom_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=DO_NOT_LEAK",
        telegram_bot_token="999:DO_NOT_LEAK_TOKEN",
        telegram_chat_id="-100999",
        notify_state_path=tmp_path / "notify.json",
    )
    doc = doctor_radar_readiness(cfg, pack_dir=pack_dir, trade_date=pack.trade_date)
    assert doc["status"] == "ok"
    assert doc["pack"]["fresh"] is True
    assert doc["patterns"]["mirror_sync_ok"] is True
    assert doc["notify"]["configured_channels"] == ["wecom", "telegram"]
    doc_str = json.dumps(doc, ensure_ascii=False)
    assert "DO_NOT_LEAK" not in doc_str

    # CLI doctor radar + daily-report smoke
    monkeypatch.setattr(
        sys,
        "argv",
        ["alphasift", "doctor", "radar", "--pack-dir", str(pack_dir), "--trade-date", pack.trade_date, "--json"],
    )
    cli_main()
    cli_doc = json.loads(capsys.readouterr().out)
    assert cli_doc["status"] == "ok"

    out_json = tmp_path / "report.json"
    out_card = tmp_path / "card.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "alphasift",
            "daily-report",
            "--pack-dir",
            str(pack_dir),
            "--no-announcements",
            "--no-news",
            "--output-json",
            str(out_json),
            "--output-card",
            str(out_card),
            "--push",
            "--json",
        ],
    )
    cli_main()
    cli_rep = json.loads(capsys.readouterr().out)
    assert out_json.is_file() and out_card.is_file()
    assert cli_rep["im_card_chars"] < 1200
    assert cli_rep["push"]["status"] == "skipped_no_channels"

    # When a webhook IS configured, daily-report --push without --expected-trade-date guards against stale historical packs
    monkeypatch.setenv("WECOM_WEBHOOK_URL", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=TEST")
    monkeypatch.setattr("alphasift.markets.latest_settled_close", lambda _m: (date(2099, 1, 1), 60.0))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "alphasift",
            "daily-report",
            "--pack-dir",
            str(pack_dir),
            "--no-announcements",
            "--no-news",
            "--push",
            "--json",
        ],
    )
    cli_main()
    stale_rep = json.loads(capsys.readouterr().out)
    assert stale_rep["pack_is_stale"] is True
    assert stale_rep["push"]["status"] == "skipped_stale_pack"


def test_daily_report_alert_first_order_and_reserved_budget() -> None:
    pack = _make_pack()
    runs = [
        _dummy_run("dual_low", track="rules", code="000001", name="测试股01"),
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="dual_low_ai",
            track="ai",
            llm_ranked=True,
            llm_market_view="成长占优但高标分歧加大，控仓为主",
            picks=[
                Pick(
                    rank=1,
                    code="000002",
                    name="测试股02",
                    industry="半导体",
                    final_score=91.0,
                    screen_score=86.0,
                    change_pct=4.1,
                    ranking_reason="景气与趋势共振",
                )
            ],
        ),
    ]

    def fake_ann(df: pd.DataFrame, *, max_rows: int, cache_dir=None):
        return [
            {
                "code": "000001",
                "name": "测试股01",
                "announcement": "2026-11-20 股东拟减持不超过2%",
                "negative_event_flags": ["减持"],
                "announcement_categories": ["减持"],
            }
        ], []

    report = build_daily_report(
        pack,
        strategy_runs=runs,
        announcement_collector=fake_ann,
        detail_url="https://example.com/radar/",
    )
    card = report["im_card_markdown"]
    assert report["detail_url"] == "https://example.com/radar/"
    assert isinstance(report["ai_highlights"], list) and len(report["ai_highlights"]) == 1
    assert report["ai_highlights"][0]["added_by_ai"][0]["code"] == "000002"
    assert report["ai_highlights"][0]["dropped_by_ai"][0]["code"] == "000001"
    # Alert section appears BEFORE strategy overview and pattern radar summary.
    assert card.index("公告排雷") < card.index("策略与 [AI]")
    assert card.index("策略与 [AI]") < card.index("形态雷达")
    assert "https://example.com/radar/" in card
    assert DEFAULT_DASHBOARD_URL != report["detail_url"]

    # Reserved budget preserves alert bullets, detail link, and footer even when squeezed.
    noisy = "\n".join([
        "**AlphaSift A股量化观测日报 (2026-10-30)**",
        "> 盘面 **启动(startup)**[仅切片]｜上涨 60.0%",
        "**⚠️ 公告排雷预警(5检/1中)**",
        "- 000001 测试股01[减持]: 股东拟减持2%",
        *([f"**策略补充行 {i}**：" + ("冗长候选明细 " * 8) for i in range(12)]),
        "**形态雷达**：正式(active) 0 组(0只) / 观察期(experimental) 6 组(12只，详见看板)",
        "🔗 完整候选、AI归因与K线详情：https://example.com/dash",
        "注：量化形态观测与回测基准，非投资建议。",
    ])
    trimmed = ensure_im_card_length(noisy, max_chars=420)
    assert len(trimmed) <= 420
    assert "减持" in trimmed
    assert "https://example.com/dash" in trimmed
    assert "量化形态观测与回测基准" in trimmed


def test_load_daily_report_runs_timezone_and_stale_pack_guards(tmp_path: Path) -> None:
    pack = _make_pack()  # last date is 2026-10-30
    cfg = Config(
        data_dir=tmp_path / "data",
        wecom_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=SECRET_WECOM",
        notify_state_path=tmp_path / "notify_state.json",
    )
    # 2026-10-30 18:10 UTC == 2026-10-31 02:10+08:00 (after Friday close, before next Monday open)
    # CST session date resolves to Friday 2026-10-30.
    utc_late_run = ScreenResult(
        strategy="momentum",
        market="cn",
        run_id="mom_rules_late_utc",
        track="rules",
        llm_ranked=False,
        created_at="2026-10-30T18:10:00Z",
        picks=[Pick(rank=1, code="000001", name="测试股01", industry="半导体", final_score=82.0, screen_score=80.0)],
    )
    save_screen_result(utc_late_run, data_dir=cfg.data_dir)

    loaded = load_daily_report_runs(cfg, trade_date=pack.trade_date)
    assert [r.run_id for r in loaded] == ["mom_rules_late_utc"]

    with pytest.raises(ValueError, match="stale"):
        build_daily_report(
            pack,
            expected_trade_date="2026-11-20",
            allow_stale_pack=False,
            include_announcements=False,
        )

    stale_rep = build_daily_report(
        pack,
        expected_trade_date="2026-11-20",
        allow_stale_pack=True,
        include_announcements=False,
    )
    assert stale_rep["pack_is_stale"] is True
    assert "2026-11-20" in stale_rep["stale_reason"]
    assert "旧包降级" in stale_rep["im_card_markdown"]
    assert any("Stale pack" in item for item in stale_rep["degradation"])

    push_res = push_daily_report(
        stale_rep,
        config=cfg,
        post_fn=lambda *a, **kw: (_ for _ in ()).throw(AssertionError("stale pack must not push")),
    )
    assert push_res["status"] == "skipped_stale_pack"
    assert push_res["sent"] == []


def test_notify_concurrent_dedup_and_failure_recovery(tmp_path: Path) -> None:
    pack = _make_pack()
    report = build_daily_report(pack, include_announcements=False)
    state_path = tmp_path / "notify_state.json"
    cfg = Config(
        wecom_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=SECRET_WECOM",
        notify_state_path=state_path,
    )

    entered = threading.Event()
    release = threading.Event()
    call_count = 0
    count_lock = threading.Lock()

    def slow_post(url: str, *, json: dict, timeout: float):
        nonlocal call_count
        with count_lock:
            call_count += 1
        entered.set()
        assert release.wait(timeout=5.0)
        return _DummyResponse(200, {"errcode": 0, "errmsg": "ok"})

    results: list[dict] = []

    def worker() -> None:
        results.append(push_daily_report(report, config=cfg, post_fn=slow_post))

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    assert entered.wait(timeout=5.0)
    t2.start()
    t2.join(timeout=5.0)
    release.set()
    t1.join(timeout=5.0)

    assert call_count == 1
    statuses = sorted(r["status"] for r in results)
    assert statuses == ["ok", "skipped_duplicate"]

    # Test automatic failure recovery without force=True on a fresh trade_date.
    report_retry = dict(report, trade_date="2026-11-19")
    fail_cfg = Config(
        wecom_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=SECRET_WECOM",
        notify_state_path=tmp_path / "notify_retry_state.json",
    )

    def broken_post(url: str, *, json: dict, timeout: float):
        raise RuntimeError("transient timeout")

    res_fail = push_daily_report(report_retry, config=fail_cfg, post_fn=broken_post)
    assert res_fail["status"] == "error"
    ledger = json.loads((tmp_path / "notify_retry_state.json").read_text(encoding="utf-8"))
    assert ledger["2026-11-19:wecom"]["status"] == "failed"

    recovered = push_daily_report(
        report_retry,
        config=fail_cfg,
        post_fn=lambda url, *, json, timeout: _DummyResponse(200, {"errcode": 0, "errmsg": "ok"}),
    )
    assert recovered["status"] == "ok"
    ledger_after = json.loads((tmp_path / "notify_retry_state.json").read_text(encoding="utf-8"))
    assert ledger_after["2026-11-19:wecom"]["status"] == "sent"

    res_dup = push_daily_report(
        report_retry,
        config=fail_cfg,
        post_fn=lambda *a, **kw: (_ for _ in ()).throw(AssertionError("already sent must skip")),
    )
    assert res_dup["status"] == "skipped_duplicate"


def test_notify_dingtalk_discord_custom_redaction_and_cli_test(tmp_path: Path, monkeypatch, capsys) -> None:
    from urllib.parse import quote_plus
    from alphasift.notify import notify_readiness, send_test_notification

    pack = _make_pack()
    report = build_daily_report(pack, include_announcements=False)
    monkeypatch.setattr("alphasift.notify.time.time", lambda: 1763632800.0)

    calls: list[tuple[str, dict, dict]] = []

    def mock_post(url: str, *, json: dict, timeout: float, headers: dict | None = None):
        calls.append((url, json, headers or {}))
        if "oapi.dingtalk.com" in url:
            return _DummyResponse(200, {"errcode": 0, "errmsg": "ok"})
        return _DummyResponse(200, {"ok": True})

    cfg = Config(
        dingtalk_webhook_url="https://oapi.dingtalk.com/robot/send?access_token=SECRET_DT",
        dingtalk_webhook_secret="DT_SECRET",
        discord_webhook_url="https://discord.com/api/webhooks/123/SECRET_DISCORD",
        custom_webhook_url="https://hooks.example.com/alphasift",
        custom_webhook_token="CUSTOM_BEARER_SECRET",
        notify_state_path=tmp_path / "notify_6ch.json",
    )
    info = notify_readiness(cfg)
    assert info["configured_channels"] == ["dingtalk", "discord", "custom"]
    assert info["dingtalk_signed"] is True
    assert info["discord_configured"] is True
    assert info["custom_authenticated"] is True

    res = push_daily_report(report, config=cfg, post_fn=mock_post)
    assert res["status"] == "ok"
    assert res["sent"] == ["dingtalk", "discord", "custom"]
    assert len(calls) == 3

    # Verify DingTalk timestamp + signed query parameter.
    dt_url, dt_body, _ = calls[0]
    expected_dt_sign = quote_plus(
        base64.b64encode(hmac.new(b"DT_SECRET", b"1763632800000\nDT_SECRET", digestmod=hashlib.sha256).digest())
    )
    assert "timestamp=1763632800000" in dt_url
    assert f"sign={expected_dt_sign}" in dt_url
    assert dt_body["msgtype"] == "markdown"

    # Verify Discord embed payload & custom webhook JSON + Bearer auth.
    dc_url, dc_body, _ = calls[1]
    assert "discord.com" in dc_url
    assert dc_body["embeds"][0]["url"] == DEFAULT_DASHBOARD_URL

    cu_url, cu_body, cu_hdrs = calls[2]
    assert cu_url == "https://hooks.example.com/alphasift"
    assert cu_body["event"] == "alphasift.daily_report"
    assert cu_hdrs["Authorization"] == "Bearer CUSTOM_BEARER_SECRET"

    # Error redaction across new secrets.
    def broken_post(url: str, *, json: dict, timeout: float, headers: dict | None = None):
        raise RuntimeError(f"post {url} DT_SECRET CUSTOM_BEARER_SECRET failed")

    res_err = push_daily_report(report, config=cfg, force=True, post_fn=broken_post)
    assert res_err["status"] == "error"
    for entry in res_err["errors"]:
        assert "SECRET_DT" not in entry["error"]
        assert "DT_SECRET" not in entry["error"]
        assert "SECRET_DISCORD" not in entry["error"]
        assert "CUSTOM_BEARER_SECRET" not in entry["error"]

    # Non-persistent connectivity test + CLI `notify status` & `notify test --dry-run`.
    calls.clear()
    test_res = send_test_notification(config=cfg, channels=["discord", "custom"], post_fn=mock_post)
    assert test_res["status"] == "ok"
    assert test_res["sent"] == ["discord", "custom"]
    assert calls[1][1]["event"] == "alphasift.notify_test"

    monkeypatch.setenv("ALPHASIFT_DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/XYZ")
    monkeypatch.setattr(sys, "argv", ["alphasift", "notify", "status", "--json"])
    cli_main()
    status_out = json.loads(capsys.readouterr().out)
    assert "discord" in status_out["configured_channels"]

    monkeypatch.setattr(sys, "argv", ["alphasift", "notify", "test", "--channel", "discord", "--dry-run", "--json"])
    cli_main()
    dry_out = json.loads(capsys.readouterr().out)
    assert dry_out["status"] == "dry_run"
    assert dry_out["skipped"] == [{"channel": "discord", "reason": "dry_run"}]


def test_notify_urls_parsing_readiness_and_dispatch(tmp_path, monkeypatch) -> None:
    from alphasift.config import Config
    from alphasift.notify import notify_readiness, push_daily_report, send_test_notification

    for var in (
        "ALPHASIFT_WECOM_WEBHOOK_URL",
        "WECOM_WEBHOOK_URL",
        "ALPHASIFT_FEISHU_WEBHOOK_URL",
        "FEISHU_WEBHOOK_URL",
        "ALPHASIFT_DINGTALK_WEBHOOK_URL",
        "DINGTALK_WEBHOOK_URL",
        "ALPHASIFT_TELEGRAM_BOT_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "ALPHASIFT_TELEGRAM_CHAT_ID",
        "TELEGRAM_CHAT_ID",
        "ALPHASIFT_DISCORD_WEBHOOK_URL",
        "DISCORD_WEBHOOK_URL",
        "ALPHASIFT_CUSTOM_WEBHOOK_URL",
        "CUSTOM_WEBHOOK_URL",
    ):
        monkeypatch.delenv(var, raising=False)

    urls = "\n".join(
        [
            "pushplus://PP_SECRET_TOKEN/finance_topic",
            "sct://SCT_PLAIN_KEY",
            "sct://sctp456tSECRET",
            "bark://BARK_SECRET_KEY",
            "https://hooks.slack.com/services/T00/B00/SECRET_SLACK",
            "ntfy://alphasift-alerts",
            "mailto://sender@qq.com:EMAIL_AUTH_SECRET@qq.com?to=recv1@example.com,recv2@example.com",
            "tgram://123456:TG_SECRET_TOKEN/-100999888",
        ]
    )
    monkeypatch.setenv("ALPHASIFT_NOTIFY_URLS", urls)

    cfg = Config.from_env()
    readiness = notify_readiness(cfg)
    assert readiness["notify_urls_count"] == 8
    assert readiness["target_count"] == 8
    for ch in ("pushplus", "serverchan", "bark", "email", "telegram", "slack", "ntfy"):
        assert ch in readiness["configured_channels"]
        assert readiness[f"{ch}_configured"] is True

    posted: list[tuple[str, dict]] = []

    class _FakeResp:
        def __init__(self, body: dict) -> None:
            self._body = body

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._body

    def fake_post(url: str, **kwargs):
        posted.append((url, kwargs))
        if "pushplus.plus" in url:
            return _FakeResp({"code": 200, "msg": "ok"})
        if "ftqq.com" in url or "ft07.com" in url:
            return _FakeResp({"code": 0, "message": "ok"})
        if "api.day.app" in url:
            return _FakeResp({"code": 200, "message": "ok"})
        if "api.telegram.org" in url:
            return _FakeResp({"ok": True})
        return _FakeResp({"ok": True})

    smtp_calls: list[dict] = []

    class _FakeSMTP:
        def __init__(self, host: str, port: int, *, mode: str, timeout: float) -> None:
            self.record = {"host": host, "port": port, "mode": mode, "timeout": timeout, "quit": False}
            smtp_calls.append(self.record)

        def login(self, user: str, password: str) -> None:
            self.record["login"] = (user, password)

        def send_message(self, msg) -> None:
            self.record["subject"] = msg["Subject"]
            self.record["to"] = msg["To"]

        def quit(self) -> None:
            self.record["quit"] = True

    ledger = tmp_path / "notify_state.json"
    res = push_daily_report(
        {
            "trade_date": "2026-11-21",
            "im_card_markdown": "**AlphaSift 2026-11-21 Brief**\nTop pick: 601997",
            "detail_url": "https://zhulinsen.github.io/alphasift/",
        },
        config=cfg,
        state_path=ledger,
        post_fn=fake_post,
        smtp_factory=_FakeSMTP,
    )
    assert res["status"] == "ok"
    assert res["errors"] == []
    assert len(res["sent"]) == 8

    urls_hit = [u for u, _ in posted]
    assert "https://www.pushplus.plus/send" in urls_hit
    assert "https://sctapi.ftqq.com/SCT_PLAIN_KEY.send" in urls_hit
    assert "https://456.push.ft07.com/send/sctp456tSECRET.send" in urls_hit
    assert "https://api.day.app/BARK_SECRET_KEY" in urls_hit
    assert "https://hooks.slack.com/services/T00/B00/SECRET_SLACK" in urls_hit
    assert "https://ntfy.sh/alphasift-alerts" in urls_hit
    assert "https://api.telegram.org/bot123456:TG_SECRET_TOKEN/sendMessage" in urls_hit

    pp_call = next(kw for u, kw in posted if "pushplus.plus" in u)
    assert pp_call["json"]["token"] == "PP_SECRET_TOKEN"
    assert pp_call["json"]["topic"] == "finance_topic"

    assert len(smtp_calls) == 1
    assert smtp_calls[0]["host"] == "smtp.qq.com"
    assert smtp_calls[0]["port"] == 465
    assert smtp_calls[0]["mode"] == "ssl"
    assert smtp_calls[0]["login"] == ("sender@qq.com", "EMAIL_AUTH_SECRET")
    assert "recv1@example.com" in smtp_calls[0]["to"]
    assert "recv2@example.com" in smtp_calls[0]["to"]
    assert smtp_calls[0]["quit"] is True

    # Idempotency skips duplicate targets on second run for the same trade_date.
    dup = push_daily_report(
        {
            "trade_date": "2026-11-21",
            "im_card_markdown": "**AlphaSift 2026-11-21 Brief**",
        },
        config=cfg,
        state_path=ledger,
        post_fn=fake_post,
        smtp_factory=_FakeSMTP,
    )
    assert dup["status"] == "skipped_duplicate"
    assert len(dup["skipped"]) == 8

    # Errors redact every secret/token from NOTIFY_URLS.
    def failing_post(url: str, **kwargs):
        raise RuntimeError(f"failed posting to {url} payload={kwargs}")

    def failing_smtp(host: str, port: int, *, mode: str, timeout: float):
        raise RuntimeError(f"smtp failure EMAIL_AUTH_SECRET on {host}:{port}")

    err_res = send_test_notification(config=cfg, post_fn=failing_post, smtp_factory=failing_smtp)
    assert err_res["status"] == "error"
    serialized = json.dumps(err_res)
    for leaked in ("PP_SECRET_TOKEN", "SCT_PLAIN_KEY", "sctp456tSECRET", "BARK_SECRET_KEY", "SECRET_SLACK", "TG_SECRET_TOKEN", "EMAIL_AUTH_SECRET"):
        assert leaked not in serialized


def test_notify_urls_comma_preserves_mailto_recipients(monkeypatch) -> None:
    from alphasift.config import Config

    monkeypatch.setenv(
        "NOTIFY_URLS",
        "mailto://sender@qq.com:auth@qq.com?to=r1@example.com,r2@example.com, pushplus://TOK1 , sct://SCT1",
    )
    monkeypatch.delenv("ALPHASIFT_NOTIFY_URLS", raising=False)
    cfg = Config.from_env()
    assert cfg.notify_urls == [
        "mailto://sender@qq.com:auth@qq.com?to=r1@example.com,r2@example.com",
        "pushplus://TOK1",
        "sct://SCT1",
    ]


def test_notify_shorthand_schemes_retry_redaction_ntfy_title_and_stable_keys(tmp_path, monkeypatch) -> None:
    from alphasift.config import Config
    from alphasift.notify import push_daily_report, resolve_notify_targets

    monkeypatch.setattr("alphasift.notify.time.sleep", lambda *_a, **_kw: None)
    monkeypatch.setenv(
        "NOTIFY_URLS",
        ",".join(
            [
                "wecom://WECOM_SECRET_KEY",
                "feishu://FEISHU_TOK#secret=FEISHU_HMAC_SEC",
                "dingtalk://DING_TOK#secret=DING_HMAC_SEC",
                "discord://12345/DISC_TOK",
                "slack://T1/B2/SLACK_TOK",
                "custom://https://hook.example.com/in#token=CUSTOM_BEARER_TOK",
                "ntfy://alphasift-topic",
                "bark://BARK_KEY_1",
                "bark://BARK_KEY_2",
            ]
        ),
    )
    monkeypatch.delenv("ALPHASIFT_NOTIFY_URLS", raising=False)
    cfg = Config.from_env()
    targets = resolve_notify_targets(cfg)
    by_ch = {t["channel"]: t for t in targets}
    assert by_ch["wecom"]["target"] == "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=WECOM_SECRET_KEY"
    assert by_ch["feishu"]["secret"] == "FEISHU_HMAC_SEC"
    assert by_ch["dingtalk"]["secret"] == "DING_HMAC_SEC"
    assert by_ch["discord"]["target"] == "https://discord.com/api/webhooks/12345/DISC_TOK"
    assert by_ch["slack"]["target"] == "https://hooks.slack.com/services/T1/B2/SLACK_TOK"
    assert by_ch["custom"]["target"] == "https://hook.example.com/in"
    assert by_ch["custom"]["token"] == "CUSTOM_BEARER_TOK"

    calls: list[tuple[str, dict]] = []
    flaky_attempts = {"slack": 0}

    class _Resp:
        def __init__(self, status_code: int, body: dict | None = None, text: str = "") -> None:
            self.status_code = status_code
            self._body = body
            self.text = text

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                import requests as _req

                err = _req.HTTPError(f"HTTP {self.status_code} key=INLINE_SECRET bot99:XYZ")
                err.response = self
                raise err

        def json(self) -> dict:
            if self._body is None:
                raise ValueError("non-json")
            return self._body

    def fake_post(url: str, **kwargs):
        calls.append((url, kwargs))
        if "hooks.slack.com" in url:
            flaky_attempts["slack"] += 1
            if flaky_attempts["slack"] == 1:
                return _Resp(502, text="<html>Bad Gateway</html>")
            return _Resp(200, {})
        if "pushplus.plus" in url or "api.day.app" in url:
            return _Resp(200, {"code": 200})
        if "wecom" in url or "qyapi" in url or "oapi.dingtalk.com" in url:
            return _Resp(200, {"errcode": 0})
        if "open.feishu.cn" in url:
            return _Resp(200, {"code": 0})
        return _Resp(200, {})

    ledger = tmp_path / "ledger.json"
    res = push_daily_report(
        {"trade_date": "2026-11-21", "im_card_markdown": "**Brief**"},
        config=cfg,
        state_path=ledger,
        post_fn=fake_post,
    )
    assert res["status"] == "ok"
    assert flaky_attempts["slack"] == 2
    ntfy_call = next(kw for u, kw in calls if "ntfy.sh" in u)
    assert ntfy_call["headers"]["Title"] == "AlphaSift Daily Brief (2026-11-21)"

    ledger_data = json.loads(ledger.read_text(encoding="utf-8"))
    bark_keys = sorted(k for k in ledger_data if k.startswith("2026-11-21:bark:"))
    assert len(bark_keys) == 2

    # Non-JSON 200 and regex redaction test
    def broken_json_post(url: str, **kwargs):
        return _Resp(200, None, text="<html>gateway bot12345:SECRET_PART key=ABC999</html>")

    from alphasift.notify import send_test_notification

    err = send_test_notification(config=cfg, channels=["wecom"], post_fn=broken_json_post)
    assert err["status"] == "error"
    msg = json.dumps(err)
    assert "SECRET_PART" not in msg
    assert "ABC999" not in msg
    assert "non-JSON response body" in msg


def test_notify_round6_hardening_url_redaction_retries_and_ledger_transitions(tmp_path, monkeypatch):
    from alphasift.notify import _CRED_REDACT_RE, _parse_notify_url, push_daily_report

    # 1. Embedded https:// URL inside shorthand scheme retains full query string and strips ?secret= / ?token=
    dt = _parse_notify_url("dingtalk://https://oapi.dingtalk.com/robot/send?access_token=TOK_DT#secret=SEC_DT")
    assert dt is not None
    assert dt["target"] == "https://oapi.dingtalk.com/robot/send?access_token=TOK_DT"
    assert dt["secret"] == "SEC_DT"

    fs = _parse_notify_url("feishu://https://open.feishu.cn/open-apis/bot/v2/hook/HOOK_FS?secret=SEC_FS&extra=1")
    assert fs is not None
    assert fs["secret"] == "SEC_FS"
    assert "SEC_FS" not in fs["target"]
    assert "extra=1" in fs["target"]

    # 2. JSON-quoted secret scrubbing via _CRED_REDACT_RE
    scrubbed = _CRED_REDACT_RE.sub(
        lambda m: f"{m.group(1) or m.group(3) or m.group(5) or ''}***",
        'error body {"token":"MY_JSON_TOK","secret": "SEC99"}',
    )
    assert "MY_JSON_TOK" not in scrubbed
    assert "SEC99" not in scrubbed

    # 3. 500 is NOT retried while 429 honors Retry-After
    class _HdrResp:
        def __init__(self, status_code: int, headers: dict | None = None, body: dict | None = None) -> None:
            self.status_code = status_code
            self.headers = headers or {}
            self._body = body or {"errcode": 0}
            self.text = ""

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                import requests as _req

                err = _req.HTTPError(f"HTTP {self.status_code}")
                err.response = self
                raise err

        def json(self) -> dict:
            return self._body

    monkeypatch.setenv("WECOM_WEBHOOK_URL", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=KEY_A")
    monkeypatch.delenv("NOTIFY_URLS", raising=False)
    monkeypatch.delenv("ALPHASIFT_NOTIFY_URLS", raising=False)
    cfg_a = Config.from_env()
    ledger = tmp_path / "ledger.json"

    attempts_500 = {"n": 0}

    def post_500(url: str, **kwargs):
        attempts_500["n"] += 1
        return _HdrResp(500)

    res_500 = push_daily_report(
        {"trade_date": "2026-11-21", "im_card_markdown": "**Brief**"},
        config=cfg_a,
        state_path=ledger,
        post_fn=post_500,
    )
    assert res_500["status"] == "error"
    assert attempts_500["n"] == 1  # HTTP 500 not retried

    # Reset failed status via 429 -> Retry-After honored -> sent
    slept: list[float] = []
    monkeypatch.setattr("alphasift.notify.time.sleep", lambda s: slept.append(s))
    calls_429 = {"n": 0}

    def post_429_then_ok(url: str, **kwargs):
        calls_429["n"] += 1
        if calls_429["n"] == 1:
            return _HdrResp(429, headers={"Retry-After": "1.2"})
        return _HdrResp(200, body={"errcode": 0})

    res_a = push_daily_report(
        {"trade_date": "2026-11-21", "im_card_markdown": "**Brief**"},
        config=cfg_a,
        state_path=ledger,
        post_fn=post_429_then_ok,
    )
    assert res_a["status"] == "ok"
    assert calls_429["n"] == 2
    assert slept == [1.2]

    # 4. Target replacement A -> B sends B cleanly (not falsely skipped by legacy key)
    monkeypatch.setenv("WECOM_WEBHOOK_URL", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=KEY_B")
    cfg_b = Config.from_env()
    sent_urls: list[str] = []

    def track_post(url: str, **kwargs):
        sent_urls.append(url)
        return _HdrResp(200, body={"errcode": 0})

    res_b = push_daily_report(
        {"trade_date": "2026-11-21", "im_card_markdown": "**Brief**"},
        config=cfg_b,
        state_path=ledger,
        post_fn=track_post,
    )
    assert res_b["status"] == "ok"
    assert any("KEY_B" in u for u in sent_urls)

    # 5. Expansion A -> A,B skips both since A is in legacy key (matching target_fp) and B is in fp key
    monkeypatch.delenv("WECOM_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("NOTIFY_URLS", "wecom://KEY_A,wecom://KEY_B")
    cfg_ab = Config.from_env()
    sent_ab: list[str] = []
    res_ab = push_daily_report(
        {"trade_date": "2026-11-21", "im_card_markdown": "**Brief**"},
        config=cfg_ab,
        state_path=ledger,
        post_fn=lambda url, **kw: sent_ab.append(url) or _HdrResp(200, body={"errcode": 0}),
    )
    assert res_ab["status"] == "skipped_duplicate"
    assert sent_ab == []


def test_channel_renderers_feishu_telegram_email_and_snippet(tmp_path: Path) -> None:
    from alphasift.config import Config
    from alphasift.daily_report import _clean_announcement_snippet, render_daily_im_card
    from alphasift.notify import push_daily_report

    assert _clean_announcement_snippet("2026-11-10 16:36:08 关于控股股东诉讼进展公告") == "关于控股股东诉讼进展公告"
    assert _clean_announcement_snippet("2026-11-10T09:15:00  减持股份公告") == "减持股份公告"

    rich_report = {
        "trade_date": "2026-11-20",
        "detail_url": "https://zhulinsen.github.io/alphasift/?lang=zh",
        "pack_is_stale": False,
        "market_regime": {
            "regime_stage": "freezing",
            "regime_stage_label": "冰点",
            "advance_ratio_pct": 5.7,
            "median_return_pct": -5.12,
            "non_st_limit_up_count": 28,
            "non_st_limit_down_count": 63,
            "seal_rate_pct": 71.8,
            "max_consecutive_limit_up": 4,
            "prev_limit_up_avg_return_pct": -3.50,
            "total_amount_yi": 14215.0,
            "up_count": 295,
            "flat_count": 15,
            "down_count": 4890,
            "return_distribution": {
                "le_neg7": 210, "neg7_neg3": 1900, "neg3_0": 2780, "flat": 15, "pos0_3": 210, "pos3_7": 55, "ge_pos7": 30,
            },
        },
        "announcement_risks": {
            "checked_count": 12,
            "flagged_count": 1,
            "flagged_items": [{
                "code": "300760",
                "name": "迈瑞医疗",
                "negative_event_flags": ["诉讼风险"],
                "announcement_summary": "2026-11-10 16:36:08 关于控股股东涉诉进展<script>alert(1)</script>",
            }],
            "errors": [],
        },
        "ai_brief": {
            "mode": "llm",
            "headline": "冰点普跌下高共识银行股抗跌",
            "market_summary": "全市场中位数下跌 5.12%，防御型权重占优。",
        },
        "cross_strategy_synthesis": {
            "consensus_picks": [{
                "code": "601668",
                "name": "中国建筑",
                "industry": "建筑",
                "strategy_count": 6,
                "strategies": ["balanced_alpha", "blue_chip_income"],
                "avg_final_score": 80.1,
                "change_pct": 1.25,
                "announcement_risk_flags": [],
            }],
        },
        "strategies": [{"strategy": "dual_low", "track": "rules", "llm_ranked": False, "pick_count": 5}],
        "patterns": {
            "active": [],
            "experimental": [{
                "pattern": "bottom_volume_yang",
                "display_name": "底部倍量阳",
                "status": "experimental",
                "hit_count": 3,
                "signals": [{"code": "002348", "name": "高乐股份", "change_pct": 7.78, "overhead_supply_10pct": 7}],
            }],
        },
    }
    card_md = render_daily_im_card(rich_report)
    assert "[仅切片]" not in card_md
    assert "14,215亿" in card_md
    assert "2026-11-10 16:36:08" not in card_md
    assert "中国建筑" in card_md
    assert "底部倍量阳" in card_md

    posted: list[tuple[str, dict]] = []
    sent_msgs: list[object] = []

    def fake_post(url: str, *, json: dict, timeout: float):
        posted.append((url, json))
        if "open.feishu.cn" in url:
            return _DummyResponse(200, {"code": 0, "msg": "ok"})
        return _DummyResponse(200, {"ok": True})

    class _CaptureSMTP:
        def __init__(self, host: str, port: int, *, mode: str, timeout: float) -> None:
            pass

        def login(self, user: str, password: str) -> None:
            pass

        def send_message(self, msg) -> None:
            sent_msgs.append(msg)

        def quit(self) -> None:
            pass

    cfg = Config(
        feishu_webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/FEISHU_KEY",
        telegram_bot_token="123456:TG_KEY",
        telegram_chat_id="-100999",
        notify_urls=["mailto://sender@qq.com:SMTP_SECRET@smtp.qq.com:465?to=recv@example.com"],
        notify_state_path=tmp_path / "notify_state.json",
    )
    res = push_daily_report(rich_report, config=cfg, post_fn=fake_post, smtp_factory=_CaptureSMTP)
    assert res["status"] == "ok" and sorted(res["sent"]) == ["email", "feishu", "telegram"]

    feishu_card = next(j["card"] for u, j in posted if "open.feishu.cn" in u)
    assert feishu_card["config"]["wide_screen_mode"] is True
    assert feishu_card["header"]["template"] == "red"
    assert any(el.get("tag") == "div" and len(el.get("fields", [])) == 4 for el in feishu_card["elements"])
    assert any(el.get("tag") == "action" for el in feishu_card["elements"])

    tg_payload = next(j for u, j in posted if "api.telegram.org" in u)
    assert tg_payload["parse_mode"] == "HTML"
    assert len(tg_payload["text"]) <= 4096
    assert "<b>" in tg_payload["text"] and "<blockquote>" in tg_payload["text"]
    assert "<script>alert(1)</script>" not in tg_payload["text"]
    assert "2026-11-10 16:36:08" not in tg_payload["text"]

    assert len(sent_msgs) == 1
    email_msg = sent_msgs[0]
    assert email_msg.is_multipart()
    parts = {p.get_content_type(): p.get_content() for p in email_msg.iter_parts()}
    assert "text/plain" in parts and "text/html" in parts
    html_part = parts["text/html"]
    assert "<script>alert(1)</script>" not in html_part
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_part
    assert "中国建筑" in html_part and "底部倍量阳" in html_part
    assert "均衡多因子" in html_part
    assert "AlphaSift" in email_msg["From"]


def test_consensus_announcement_prioritization_pattern_tiering_and_multi_market_digest(tmp_path: Path, monkeypatch) -> None:
    from alphasift.market_digest import build_markets_digest, load_multi_market_runs

    pack = _make_pack()
    # Create 5 strategies so max_codes=4 forces prioritization of consensus pick 000003 over early noise
    runs = [
        ScreenResult(
            strategy="balanced_alpha",
            market="cn",
            run_id="r_ba",
            track="rules",
            picks=[
                Pick(rank=1, code="000001", name="唯一一", industry="银行", price=10.5, pe_ratio=6.2, pb_ratio=0.7, total_mv=5e10, final_score=80.0, screen_score=80.0, factor_scores={"value": 90, "quality": 85}),
                Pick(rank=2, code="000003", name="共识三", industry="半导体", price=25.0, pe_ratio=30.0, pb_ratio=3.2, total_mv=2e10, final_score=95.0, screen_score=92.0),
            ],
        ),
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="r_dl",
            track="rules",
            picks=[
                Pick(rank=1, code="000002", name="唯一二", industry="化工", price=8.2, final_score=82.0, screen_score=82.0),
                Pick(rank=2, code="000003", name="共识三", industry="半导体", price=25.0, pe_ratio=30.0, pb_ratio=3.2, total_mv=2e10, final_score=93.0, screen_score=91.0),
            ],
        ),
    ]
    checked_order: list[str] = []

    def fake_ann(df, *, max_rows: int, cache_dir=None):
        checked_order.extend(df["code"].tolist())
        return [
            {
                "code": "000003",
                "name": "共识三",
                "announcement": "2026-10-01 控股股东涉诉进展 | 2026-11-18 日常经营公告",
                "negative_event_flags": ["诉讼风险"],
                "announcement_categories": ["诉讼担保"],
            }
        ], []

    replay_mock = {
        "cost_bps": 25.0,
        "patterns": [
            {"pattern": "box_breakout", "horizons": {"t5": {"gross_excess_mean_pct": -0.31, "net_excess_mean_pct": -0.56, "win_rate_pct": 41.0, "scored": 320}}},
            {"pattern": "bottom_volume_yang", "horizons": {"t5": {"gross_excess_mean_pct": 0.45, "net_excess_mean_pct": 0.20, "win_rate_pct": 51.0, "scored": 280}}},
        ],
    }
    report = build_daily_report(
        pack,
        strategy_runs=runs,
        announcement_max_codes=3,
        announcement_collector=fake_ann,
        pattern_replay=replay_mock,
        detail_url="",
    )
    assert checked_order[0] == "000003"
    assert len(checked_order) <= 3
    flagged0 = report["announcement_risks"]["flagged_items"][0]
    assert flagged0["announcement_date"] == "2026-10-01"
    assert flagged0["recency"] in {"mid", "old"}
    assert "控股股东涉诉进展" in flagged0["matched_announcement"]
    cons0 = report["cross_strategy_synthesis"]["consensus_picks"][0]
    assert cons0["price"] == 25.0 and cons0["pe_ratio"] == 30.0
    assert cons0["strategy_display_names"] == ["均衡多因子", "双低选股"]
    assert "均衡多因子" in cons0["strategy_display_names"]
    # Negative-expectancy box_breakout still marked negative_watch
    exp_map = {p["pattern"]: p for p in report["patterns"]["experimental"]}
    assert exp_map["box_breakout"]["expectancy_tier"] == "negative_watch"

    # Multi-market digest & isolated ledger keys (us vs cn)
    cfg = Config(
        data_dir=tmp_path / "data",
        wecom_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=WECOM_SEC",
        discord_webhook_url="https://discord.com/api/webhooks/1/DC_SEC",
        slack_webhook_url="https://hooks.slack.com/services/T/B/SL_SEC",
        notify_state_path=tmp_path / "notify_state.json",
    )
    us_run = ScreenResult(
        strategy="us_momentum_quality",
        market="us",
        run_id="2026-11-20_us",
        track="rules",
        created_at="2026-11-20T22:00:00Z",
        picks=[Pick(rank=1, code="NVDA", name="NVIDIA", industry="Semis", price=140.5, change_pct=2.1, final_score=91.0, screen_score=91.0)],
    )
    save_screen_result(us_run, data_dir=cfg.data_dir)
    loaded_multi = load_multi_market_runs(cfg, markets=["us", "hk"])
    assert len(loaded_multi["us"]) == 1 and loaded_multi["hk"] == []
    digest = build_markets_digest(loaded_multi, markets=["us", "hk"], detail_url="")
    assert digest["object"] == "MarketDigest"
    assert "NVDA" in digest["im_card_markdown"]
    assert "http" not in digest["im_card_markdown"]

    calls: list[tuple[str, dict]] = []

    def ok_post(url: str, *, json: dict, timeout: float):
        calls.append((url, json))
        return _DummyResponse(200, {"errcode": 0} if "qyapi" in url else {"ok": True})

    res_cn = push_daily_report(report, config=cfg, post_fn=ok_post)
    assert res_cn["status"] == "ok" and sorted(res_cn["sent"]) == ["discord", "slack", "wecom"]
    # detail_url == "" suppresses embed.url on Discord and URLs on WeCom/Slack
    dc_call = next(j for u, j in calls if "discord" in u)
    assert "url" not in dc_call["embeds"][0]
    assert dc_call["embeds"][0]["fields"]
    sl_call = next(j for u, j in calls if "slack" in u)
    assert sl_call["blocks"][0]["type"] == "header"

    calls.clear()
    res_us = push_daily_report(digest, config=cfg, post_fn=ok_post)
    assert res_us["status"] == "ok" and sorted(res_us["sent"]) == ["discord", "slack", "wecom"]
    ledger = json.loads(cfg.notify_state_path.read_text(encoding="utf-8"))
    assert f"{digest['trade_date']}:us+hk:wecom" in ledger


def test_daily_report_scrubs_nonfinite_and_bool_metrics():
    from alphasift.daily_report import _extract_pattern_replay_map, _extract_strategy_track_stats, _format_strategy_entry, render_daily_im_card
    from alphasift.jsonutil import dumps_strict_json

    bad_run = ScreenResult(
        strategy="dual_low",
        market="cn",
        run_id="2026-11-26_cn",
        track="rules",
        created_at="2026-11-26T08:00:00Z",
        picks=[
            Pick(
                rank=1,
                code="600519",
                name="贵州茅台",
                industry="白酒",
                price=float("inf"),
                pe_ratio=float("nan"),
                pb_ratio=True,
                total_mv=float("inf"),
                change_pct=float("-inf"),
                final_score=float("nan"),
                screen_score=float("inf"),
                factor_scores={"value": float("nan"), "quality": True, "growth": 0.9},
            )
        ],
    )
    entry = _format_strategy_entry(bad_run)
    p0 = entry["picks"][0]
    assert p0["price"] is None
    assert p0["pe_ratio"] is None
    assert p0["pb_ratio"] is None
    assert p0["market_cap_yi"] is None
    assert p0["change_pct"] is None
    assert p0["final_score"] == 0.0
    assert p0["screen_score"] == 0.0
    assert "成长因子靠前" in p0["ranking_reason"]

    track_stats = _extract_strategy_track_stats({
        "scorecard": [{
            "market": "cn",
            "strategy": "dual_low",
            "track": "rules",
            "windows": {"5": {"matched": True, "average_excess_return_pct": float("inf"), "beat_rate": float("nan")}},
        }]
    })
    assert track_stats == {}

    replay_map = _extract_pattern_replay_map({
        "cost_bps": float("inf"),
        "patterns": [{
            "pattern": "double_bottom_breakout",
            "horizons": {"t5": {"net_excess_mean_pct": float("nan"), "win_rate_pct": float("inf"), "scored": True}},
            "walk_forward_regime_audit": {
                "low_overhead_threshold_pct": float("inf"),
                "h1_purged_signals": True,
                "h2_non_adverse_low_overhead": {"days": float("nan"), "daily_mean_pct": float("inf")},
                "delta_non_adverse_low_overhead_vs_h2_baseline_pct": float("-inf"),
            },
        }],
    })
    rm = replay_map["double_bottom_breakout"]
    assert rm["replay_t5_net_excess_pct"] is None
    assert rm["replay_t5_win_rate_pct"] is None
    assert rm["replay_samples"] is None
    assert rm["wf_low_overhead_threshold_pct"] == 15
    assert rm["wf_non_adverse_low_overhead_days"] == 0
    assert rm["wf_non_adverse_low_overhead_pct"] is None
    assert rm["wf_joint_delta_pct"] is None
    assert rm["wf_h1_purged_signals"] == 0

    card = render_daily_im_card({
        "trade_date": "2026-11-26",
        "market_regime": {
            "regime_stage_label": "震荡",
            "advance_ratio_pct": float("nan"),
            "seal_rate_pct": float("inf"),
            "prev_limit_up_avg_return_pct": float("-inf"),
            "total_amount_yi": float("nan"),
            "median_return_pct": True,
        },
        "strategies": [entry],
    })
    assert "nan" not in card.lower() and "inf" not in card.lower()
    assert dumps_strict_json({"entry": entry, "replay": replay_map})


def test_notify_retry_fmt_title_and_markdown_digest_scrub_nonfinite_and_bool():
    import types
    from alphasift.notify import (
        _build_report_title,
        _fmt_report_pct,
        _post_with_retry,
        _render_markdown_digest,
        _retry_delay,
        _split_hit_patterns,
    )

    assert _fmt_report_pct(None) == "–"
    assert _fmt_report_pct(float("nan")) == "–"
    assert _fmt_report_pct(float("inf")) == "–"
    assert _fmt_report_pct(float("-inf")) == "–"
    assert _fmt_report_pct(True) == "–"
    assert _fmt_report_pct(2.5) == "+2.50%"

    assert _retry_delay(types.SimpleNamespace(status_code=429, headers={"Retry-After": "nan"}), default=0.7) == 0.7
    assert _retry_delay(types.SimpleNamespace(status_code=429, headers={"Retry-After": "inf"}), default=0.7) == 0.7
    assert _retry_delay(types.SimpleNamespace(status_code=429, headers={"Retry-After": "-2"}), default=0.7) == 0.0
    assert _retry_delay(types.SimpleNamespace(status_code=429, headers={"Retry-After": "12"}), default=0.7) == 5.0

    calls = []
    sleeps = []

    def fake_post(url, **kw):
        calls.append(url)
        return types.SimpleNamespace(status_code=503 if len(calls) == 1 else 200, headers={}, raise_for_status=lambda: None)

    resp = _post_with_retry(fake_post, "https://example.com", max_retries=True, sleep_fn=sleeps.append)  # type: ignore[arg-type]
    assert resp.status_code == 200
    assert len(calls) == 2

    dirty_cn_report = {
        "schema_version": 1,
        "trade_date": "2026-11-26",
        "market_regime": {
            "regime_stage": "divergence",
            "regime_stage_label": "震荡分歧",
            "advance_ratio_pct": float("nan"),
            "median_return_pct": float("inf"),
            "seal_rate_pct": True,
            "total_amount_yi": float("-inf"),
            "prev_limit_up_avg_return_pct": True,
            "non_st_limit_up_count": float("nan"),
            "non_st_limit_down_count": True,
            "max_consecutive_limit_up": "bad",
        },
        "announcement_risks": {"checked_count": float("nan"), "flagged_count": True, "flagged_items": []},
        "cross_strategy_synthesis": {
            "consensus_picks": [{
                "code": "000001",
                "name": "平安银行",
                "price": float("nan"),
                "pe_ratio": True,
                "change_pct": float("inf"),
                "strategy_count": float("nan"),
                "strategies": ["dual_low"],
            }],
        },
        "patterns": {
            "active": [{
                "pattern": "double_bottom_breakout",
                "display_name": "双底突破",
                "status": "active",
                "hit_count": True,
                "replay_t5_net_excess_pct": float("nan"),
            }, {
                "pattern": "valid_pat",
                "display_name": "放量突破",
                "status": "active",
                "hit_count": 2,
                "replay_t5_net_excess_pct": float("inf"),
                "signals": [{"name": "测试股", "code": "600000", "change_pct": float("nan")}],
            }],
            "experimental": [],
        },
    }
    title = _build_report_title(dirty_cn_report, fallback_title="fallback")
    assert "涨0%" in title and "预警0" in title and "nan" not in title.lower()

    primary, neg = _split_hit_patterns(dirty_cn_report)
    assert [p["pattern"] for p in primary] == ["valid_pat"]
    assert neg == []

    md = _render_markdown_digest(dirty_cn_report, "fallback", title=title)
    assert "nan" not in md.lower() and "inf" not in md.lower()
    assert "封板 -" in md and "成交 -" in md and "0策略" in md

    dirty_global = {
        "object": "MarketDigest",
        "trade_date": "2026-11-26",
        "markets": ["us"],
        "market_sections": [{
            "market": "us",
            "market_name": "美股",
            "trade_date": "2026-11-26",
            "strategy_count": True,
            "top_picks": [{
                "code": "AAPL",
                "name": "Apple",
                "price": float("inf"),
                "change_pct": True,
                "avg_final_score": float("nan"),
                "strategies": ["global_value"],
            }],
        }],
    }
    global_md = _render_markdown_digest(dirty_global, "fallback", title="Global")
    assert "0 组策略" in global_md and "0.0分" in global_md
    assert "nan" not in global_md.lower() and "inf" not in global_md.lower()


def test_notify_feishu_card_and_telegram_html_scrub_nonfinite_and_bool():
    import json
    from alphasift.notify import _build_feishu_card, _render_telegram_html

    dirty_cn = {
        "schema_version": 1,
        "trade_date": "2026-11-26",
        "market_regime": {
            "regime_stage": "divergence",
            "regime_stage_label": "震荡",
            "advance_ratio_pct": float("nan"),
            "median_return_pct": float("inf"),
            "seal_rate_pct": True,
            "total_amount_yi": float("-inf"),
            "prev_limit_up_avg_return_pct": True,
            "non_st_limit_up_count": True,
            "non_st_limit_down_count": float("nan"),
            "max_consecutive_limit_up": "bad",
        },
        "announcement_risks": {"checked_count": True, "flagged_count": 0, "flagged_items": []},
        "cross_strategy_synthesis": {
            "consensus_picks": [{
                "code": "000001",
                "name": "平安银行",
                "industry": "银行",
                "price": float("nan"),
                "pe_ratio": True,
                "change_pct": float("inf"),
                "avg_final_score": float("-inf"),
                "strategy_count": True,
                "strategies": ["dual_low"],
            }],
        },
        "patterns": {
            "active": [{
                "pattern": "valid_pat",
                "display_name": "放量突破",
                "status": "active",
                "hit_count": 2,
                "replay_t5_net_excess_pct": float("nan"),
                "signals": [{"name": "测试股", "code": "600000", "change_pct": float("inf")}],
            }],
            "experimental": [],
        },
    }

    card = _build_feishu_card(dirty_cn, "fallback", title="Feishu")
    card_json = json.dumps(card, allow_nan=False, ensure_ascii=False)
    assert "0 涨停 / 0 跌停 · -" in card_json
    assert "最高 0 板 · 昨涨停 -" in card_json
    assert "**0 策略**" in card_json
    assert "True 涨停" not in card_json and "nan" not in card_json.lower() and "inf" not in card_json.lower()

    tg = _render_telegram_html(dirty_cn, "fallback", title="TG")
    assert "上涨 <b>0.0%</b>" in tg
    assert "涨跌停 <b>0/0</b>（封板 -）" in tg
    assert "<b>0策略</b>" in tg
    assert "nan" not in tg.lower() and "inf" not in tg.lower()

    dirty_global = {
        "object": "MarketDigest",
        "trade_date": "2026-11-26",
        "markets": ["us"],
        "market_sections": [{
            "market": "us",
            "market_name": "美股",
            "trade_date": "2026-11-26",
            "strategy_count": True,
            "top_picks": [{
                "code": "AAPL",
                "name": "Apple",
                "price": float("nan"),
                "change_pct": float("inf"),
                "avg_final_score": True,
                "strategies": ["global_value"],
            }],
        }],
    }
    g_card = json.dumps(_build_feishu_card(dirty_global, "fallback", title="Global"), allow_nan=False, ensure_ascii=False)
    assert "0 组策略" in g_card and "0.0分" in g_card
    assert "nan" not in g_card.lower() and "inf" not in g_card.lower()

    g_tg = _render_telegram_html(dirty_global, "fallback", title="Global")
    assert "0组策略" in g_tg and "0.0分" in g_tg
    assert "nan" not in g_tg.lower() and "inf" not in g_tg.lower()


def test_notify_email_html_discord_and_webhook_scrub_nonfinite_and_bool():
    import types
    from alphasift.notify import _build_discord_embed, _render_email_html, _send_custom_webhook

    dirty_cn = {
        "schema_version": 1,
        "trade_date": "2026-11-26",
        "market_regime": {
            "regime_stage": "divergence",
            "regime_stage_label": "震荡",
            "advance_ratio_pct": float("nan"),
            "median_return_pct": float("inf"),
            "seal_rate_pct": True,
            "total_amount_yi": float("-inf"),
            "prev_limit_up_avg_return_pct": True,
            "non_st_limit_up_count": True,
            "non_st_limit_down_count": float("nan"),
            "max_consecutive_limit_up": "bad",
            "return_distribution": {"pos0_3": True, "flat": float("nan"), "le_neg7": "bad"},
            "consecutive_board_ladder": {"2": True, "bad": 3, "3": 1},
        },
        "announcement_risks": {"checked_count": True, "flagged_count": True, "flagged_items": []},
        "strategy_track_stats": {"dual_low": {"t5_avg_excess_pct": float("nan")}},
        "strategies": [{"strategy": "dual_low", "picks": [{"code": "000001", "name": "平安", "change_pct": float("inf")}]}],
        "cross_strategy_synthesis": {
            "consensus_picks": [{
                "code": "000001",
                "name": "平安银行",
                "industry": "银行",
                "price": float("nan"),
                "pe_ratio": True,
                "pb_ratio": float("inf"),
                "market_cap_yi": float("-inf"),
                "change_pct": True,
                "avg_final_score": float("nan"),
                "strategy_count": True,
                "strategies": ["dual_low"],
            }],
        },
        "patterns": {
            "active": [{
                "pattern": "valid_pat",
                "display_name": "放量突破",
                "status": "active",
                "hit_count": 2,
                "replay_t5_net_excess_pct": float("nan"),
                "signals": [{
                    "name": "测试股",
                    "code": "600000",
                    "change_pct": float("inf"),
                    "overhead_supply_10pct": True,
                }],
            }],
            "experimental": [{
                "pattern": "neg_pat",
                "display_name": "负观察",
                "status": "experimental",
                "expectancy_tier": "negative_watch",
                "hit_count": 1,
                "replay_t5_net_excess_pct": float("-inf"),
            }],
        },
    }

    email_cn = _render_email_html(dirty_cn, "fallback", title="Email")
    assert "0.0%" in email_cn and "封板率 –" in email_cn and "0 策略" in email_cn
    assert "3板</strong> 1只" in email_cn and "2板" not in email_cn
    assert "nan" not in email_cn.lower() and "inf" not in email_cn.lower()

    discord_embed = _build_discord_embed(dirty_cn, "fallback", title="Discord")
    assert "上涨 0.0%" in discord_embed["fields"][0]["value"]
    assert "涨跌停 0/0 · 最高 0板" in discord_embed["fields"][0]["value"]

    sent = []
    _send_custom_webhook(
        "https://example.com/hook",
        report=dirty_cn,
        content="body",
        title="Hook",
        timeout_sec=5.0,
        post_fn=lambda url, **kw: (sent.append(kw["json"]), types.SimpleNamespace(status_code=200, headers={}, raise_for_status=lambda: None))[1],
    )
    assert sent[0]["summary"]["flagged_announcements"] == 0

    dirty_global = {
        "object": "MarketDigest",
        "trade_date": "2026-11-26",
        "markets": ["us"],
        "market_sections": [{
            "market": "us",
            "market_name": "美股",
            "trade_date": "2026-11-26",
            "strategy_count": True,
            "top_picks": [{
                "code": "AAPL",
                "name": "Apple",
                "price": float("nan"),
                "change_pct": True,
                "avg_final_score": float("inf"),
                "strategies": ["global_value"],
            }],
        }],
    }
    email_global = _render_email_html(dirty_global, "fallback", title="Global")
    assert "0 组策略" in email_global
    assert "nan" not in email_global.lower() and "inf" not in email_global.lower()
