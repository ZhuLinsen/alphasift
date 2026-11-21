# -*- coding: utf-8 -*-
"""Tests for pack pull_with_wait polling, radar HTTP API routes, and top-level exports."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import alphasift
from alphasift import pack as pack_mod
from alphasift.config import Config
from alphasift.pack import DailyPack, FIELDS, PackError, save_pack
from alphasift.server import build_api_response, build_html_response


def _make_pack(n_days: int = 70) -> DailyPack:
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-07-01", periods=n_days)]
    codes = ["000001", "000002"]
    matrices = {field: np.full((n_days, 2), np.nan, dtype=np.float32) for field in FIELDS}
    for j in range(2):
        for t in range(n_days):
            px = 10.0
            matrices["open"][t, j] = px
            matrices["high"][t, j] = px + 0.12
            matrices["low"][t, j] = px - 0.12
            matrices["close"][t, j] = px + 0.02
            matrices["pre_close"][t, j] = px
            matrices["volume"][t, j] = 10_000_000.0
            matrices["amount"][t, j] = 100_000_000.0
    last = n_days - 1
    matrices["open"][last, 0] = 10.05
    matrices["high"][last, 0] = 10.72
    matrices["low"][last, 0] = 10.02
    matrices["close"][last, 0] = 10.65
    matrices["volume"][last, 0] = 30_000_000.0
    matrices["amount"][last, 0] = 320_000_000.0

    meta = pd.DataFrame([
        {
            "code": c,
            "name": f"样本{c}",
            "industry": "电子",
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


def test_pull_with_wait_polls_until_fresh_or_timeout(tmp_path: Path, monkeypatch) -> None:
    responses = iter([
        {"trade_date": "2026-11-19", "files": {}},
        {"trade_date": "2026-11-20", "files": {}},
    ])
    monkeypatch.setattr(pack_mod, "pull", lambda directory, **kw: next(responses))
    slept: list[float] = []

    res = pack_mod.pull_with_wait(
        tmp_path,
        expected_trade_date="2026-11-20",
        max_wait_sec=60.0,
        poll_interval_sec=15.0,
        sleep_fn=slept.append,
    )
    assert res["fresh"] is True
    assert res["trade_date"] == "2026-11-20"
    assert res["attempts"] == 2
    assert slept == [15.0]

    monkeypatch.setattr(pack_mod, "pull", lambda directory, **kw: {"trade_date": "2026-11-19"})
    slept.clear()
    stale = pack_mod.pull_with_wait(
        tmp_path,
        expected_trade_date="2026-11-20",
        max_wait_sec=20.0,
        poll_interval_sec=10.0,
        sleep_fn=slept.append,
    )
    assert stale["fresh"] is False
    assert stale["attempts"] == 3
    assert slept == [10.0, 10.0]

    monkeypatch.setattr(pack_mod, "pull", lambda *a, **kw: (_ for _ in ()).throw(PackError("404")))
    with pytest.raises(PackError, match="404"):
        pack_mod.pull_with_wait(tmp_path, expected_trade_date="2026-11-20", max_wait_sec=0.0)


def test_server_radar_endpoints_and_top_level_exports(tmp_path: Path) -> None:
    for sym in (
        "compute_market_regime",
        "compute_market_regime_series",
        "list_patterns",
        "scan_patterns",
        "build_daily_report",
        "generate_ai_daily_brief",
        "render_daily_report_html",
        "push_daily_report",
        "doctor_radar_readiness",
    ):
        assert hasattr(alphasift, sym)

    missing_pack_cfg = Config(
        data_dir=tmp_path / "data",
        daily_pack_dir=tmp_path / "missing_pack",
        wecom_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=TOP_SECRET",
    )
    s_schema, p_schema = build_api_response(missing_pack_cfg, "/daily-report-schema")
    assert s_schema == 200 and p_schema["object"] == "DailyReport"

    s_pat, p_pat = build_api_response(missing_pack_cfg, "/patterns")
    assert s_pat == 200 and len(p_pat["patterns"]) == 7

    s_doc, p_doc = build_api_response(missing_pack_cfg, "/doctor/radar", query="trade_date=2026-10-08")
    assert s_doc == 200 and p_doc["status"] == "degraded"
    assert "TOP_SECRET" not in str(p_doc)

    s_503, p_503 = build_api_response(missing_pack_cfg, "/market-stats")
    assert s_503 == 503 and p_503["error"] == "pack_unavailable"

    pack_dir = tmp_path / "pack"
    pack = _make_pack(70)
    save_pack(pack_dir, pack)
    ok_cfg = Config(data_dir=tmp_path / "data", daily_pack_dir=pack_dir)

    s_ms, p_ms = build_api_response(ok_cfg, "/market-stats", query="days=3")
    assert s_ms == 200 and len(p_ms["days"]) == 3

    s_sc, p_sc = build_api_response(ok_cfg, "/patterns/scan", query="include_experimental=true&pattern=box_breakout")
    assert s_sc == 200 and p_sc["counts_by_pattern"]["box_breakout"] == 1

    s_dr, p_dr = build_api_response(ok_cfg, "/daily-report")
    assert s_dr == 200 and p_dr["im_card_chars"] < 1200

    # Save rules + AI runs matching pack trade_date -> /daily-report loads them cleanly like CLI.
    from alphasift.models import Pick, ScreenResult
    from alphasift.store import save_screen_result

    cst_ts = f"{pack.trade_date}T16:00:00+08:00"
    save_screen_result(
        ScreenResult(
            strategy="momentum",
            market="cn",
            run_id="api_mom_rules",
            track="rules",
            llm_ranked=False,
            created_at=cst_ts,
            picks=[Pick(rank=1, code="000001", name="样本1", industry="银行", final_score=80.0, screen_score=80.0)],
        ),
        data_dir=ok_cfg.data_dir,
    )
    save_screen_result(
        ScreenResult(
            strategy="momentum",
            market="cn",
            run_id="api_mom_ai",
            track="ai",
            llm_ranked=True,
            llm_market_view="科技成长偏强",
            created_at=cst_ts,
            picks=[Pick(rank=1, code="000002", name="样本2", industry="电子", final_score=88.0, screen_score=82.0)],
        ),
        data_dir=ok_cfg.data_dir,
    )
    s_dr2, p_dr2 = build_api_response(ok_cfg, "/daily-report", query="detail_url=https://example.com/u")
    assert s_dr2 == 200
    assert len(p_dr2["strategies"]) == 2
    assert len(p_dr2["ai_highlights"]) == 1
    assert "[AI]" in p_dr2["im_card_markdown"]
    assert "https://example.com/u" in p_dr2["im_card_markdown"]

    s_stale_ok, p_stale_ok = build_api_response(
        ok_cfg, "/daily-report", query="expected_trade_date=2099-01-01&allow_stale_pack=true"
    )
    assert s_stale_ok == 200 and p_stale_ok["pack_is_stale"] is True
    s_stale_err, p_stale_err = build_api_response(
        ok_cfg, "/daily-report", query="expected_trade_date=2099-01-01&allow_stale_pack=false"
    )
    assert s_stale_err == 400 and p_stale_err["error"] == "invalid_request"

    s_bad, p_bad = build_api_response(ok_cfg, "/market-stats", query="trade_date=1999-01-01")
    assert s_bad == 400 and p_bad["error"] == "invalid_request"

    s_html, html_body = build_html_response(ok_cfg, "/daily-report.html")
    assert s_html == 200 and "AlphaSift · A 股盘后量化投研日报" in html_body and "样本2" in html_body
    s_html_503, html_err = build_html_response(missing_pack_cfg, "/daily-report.html")
    assert s_html_503 == 503 and "503" in html_err
    s_html_404, _ = build_html_response(ok_cfg, "/missing.html")
    assert s_html_404 == 404
