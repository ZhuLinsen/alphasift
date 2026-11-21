# -*- coding: utf-8 -*-
"""Tests for P2-1 DailyReport schema, <1200-char IM cards, idempotent push, and doctor radar."""

from __future__ import annotations

import base64
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

    cfg = Config(
        wecom_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=SECRET_WECOM",
        feishu_webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/SECRET_FEISHU",
        feishu_webhook_secret="FEISHU_SIGN_SECRET",
        telegram_bot_token="123456:SECRET_TG_TOKEN",
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
        hmac.new(b"1763632800\nFEISHU_SIGN_SECRET", msg=b"", digestmod=hashlib.sha256).digest()
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
        raise RuntimeError(f"failed connecting to {url} with FEISHU_SIGN_SECRET")

    res_err = push_daily_report(report, config=cfg, force=True, post_fn=broken_post)
    assert res_err["status"] == "error"
    for err_entry in res_err["errors"]:
        msg = err_entry["error"]
        assert "SECRET_WECOM" not in msg
        assert "SECRET_FEISHU" not in msg
        assert "FEISHU_SIGN_SECRET" not in msg
        assert "SECRET_TG_TOKEN" not in msg


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
