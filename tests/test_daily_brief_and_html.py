# -*- coding: utf-8 -*-
"""Tests for cross-strategy synthesis and AI/rule-fallback daily editorial brief."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from alphasift.config import Config
from alphasift.daily_brief import (
    BRIEF_DISCLAIMER,
    build_cross_strategy_synthesis,
    generate_ai_daily_brief,
)
from alphasift.daily_report import build_daily_report
from alphasift.models import Pick, ScreenResult
from alphasift.pack import DailyPack, FIELDS


def _pack() -> DailyPack:
    n_days, n_codes = 65, 3
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-08-03", periods=n_days)]
    codes = ["000001", "000002", "600519"]
    matrices = {f: np.full((n_days, n_codes), np.nan, dtype=np.float32) for f in FIELDS}
    for j in range(n_codes):
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
            "name": f"股票{c[-2:]}",
            "industry": "银行" if c != "000002" else "地产",
            "pe_ratio": 10.0,
            "pb_ratio": 1.0,
            "total_mv": 1e11,
            "circ_mv": 8e10,
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


def _sample_runs() -> list[ScreenResult]:
    return [
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="r1",
            track="rules",
            picks=[
                Pick(rank=1, code="000001", name="股票01", industry="银行", final_score=90.0, screen_score=88.0),
                Pick(rank=2, code="000002", name="股票02", industry="地产", final_score=80.0, screen_score=80.0, risk_level="high", risk_flags=["高波动"]),
            ],
        ),
        ScreenResult(
            strategy="quality_value",
            market="cn",
            run_id="r2",
            track="rules",
            picks=[
                Pick(rank=1, code="000001", name="股票01", industry="银行", final_score=86.0, screen_score=86.0),
            ],
        ),
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="r3",
            track="ai",
            llm_ranked=True,
            llm_market_view="低波红利占优",
            picks=[
                Pick(rank=1, code="000001", name="股票01", industry="银行", final_score=92.0, screen_score=88.0, ranking_reason="共振领涨"),
                Pick(rank=2, code="600519", name="股票19", industry="银行", final_score=84.0, screen_score=81.0),
            ],
        ),
    ]


def test_cross_strategy_synthesis_consensus_resonance_and_risk() -> None:
    def ann_fn(df, *, max_rows: int, cache_dir=None):
        return [
            {
                "code": "000002",
                "name": "股票02",
                "announcement": "股东拟减持3%",
                "negative_event_flags": ["减持"],
                "announcement_categories": ["减持"],
            }
        ], []

    report = build_daily_report(
        _pack(),
        strategy_runs=_sample_runs(),
        announcement_collector=ann_fn,
    )
    syn = report["cross_strategy_synthesis"]
    assert len(syn["consensus_picks"]) == 1
    assert syn["consensus_picks"][0]["code"] == "000001"
    # Running dual_low in both rules & ai counts as 1 strategy; total distinct strategies = 2 (dual_low, quality_value)
    assert syn["consensus_picks"][0]["strategy_count"] == 2
    assert syn["consensus_picks"][0]["tracks"] == ["ai", "rules"]
    assert syn["sector_concentration"][0]["industry"] == "银行"
    assert any(r["code"] == "000001" for r in syn["strategy_pattern_resonance"])
    assert syn["risk_spotlight"][0]["code"] == "000002"
    assert "000001" in report["im_card_markdown"]
    assert "多策略共识" in report["im_card_markdown"]
    assert report["im_card_chars"] < 1200


def test_generate_ai_daily_brief_modes_and_fallbacks() -> None:
    report = build_daily_report(_pack(), strategy_runs=_sample_runs(), include_announcements=False)

    off_brief = generate_ai_daily_brief(report, use_llm="off")
    assert off_brief["mode"] == "rule_fallback"
    assert off_brief["disclaimer"] == BRIEF_DISCLAIMER
    assert off_brief["fallback_reason"] is None
    assert "000001" in off_brief["consensus_and_ai_edge"]

    unconfigured_auto = generate_ai_daily_brief(report, config=Config(llm_api_key=""), use_llm="auto")
    assert unconfigured_auto["mode"] == "rule_fallback"
    assert unconfigured_auto["fallback_reason"] == "no_llm_configured"

    payload = {
        "headline": "两策略共振银行低波主线，留意公告排雷预警",
        "regime_interpretation": "当前盘面全部上涨、暂无一字涨停堵塞。",
        "consensus_and_ai_edge": "000001 获得 dual_low 与 quality_value 双重覆盖，AI 新增 600519。",
        "risk_warnings": ["注意样本外流动性变化"],
        "watch_points": ["次日开盘竞价换手"],
    }
    fenced_resp = "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
    llm_report = build_daily_report(
        _pack(),
        strategy_runs=_sample_runs(),
        include_announcements=False,
        ai_brief_mode="auto",
        config=Config(llm_api_key="dummy-key", llm_model="gpt-test"),
        llm_caller=lambda prompt: fenced_resp,
    )
    assert llm_report["ai_brief"]["mode"] == "llm"
    assert llm_report["ai_brief"]["model"] == "gpt-test"
    assert "000001" in llm_report["ai_brief"]["consensus_and_ai_edge"]
    assert "[AI] 简评" in llm_report["im_card_markdown"]
    assert llm_report["im_card_chars"] < 1200

    # Malformed LLM response falls back safely without raising.
    bad_brief = generate_ai_daily_brief(
        report,
        config=Config(llm_api_key="dummy-key"),
        use_llm="on",
        llm_caller=lambda prompt: "not valid json",
    )
    assert bad_brief["mode"] == "rule_fallback"
    assert bad_brief["fallback_reason"] and "llm_error" in bad_brief["fallback_reason"]
    # Grounding synthesis directly on dict works cleanly
    syn2 = build_cross_strategy_synthesis({"strategies": [], "patterns": {}, "announcement_risks": {}})
    assert syn2 == {
        "consensus_picks": [],
        "sector_concentration": [],
        "strategy_pattern_resonance": [],
        "risk_spotlight": [],
    }
