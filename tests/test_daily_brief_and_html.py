# -*- coding: utf-8 -*-
"""Tests for cross-strategy synthesis and AI/rule-fallback daily editorial brief."""

from __future__ import annotations

from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd

from alphasift.cli import main as cli_main
from alphasift.config import Config
from alphasift.daily_brief import (
    BRIEF_DISCLAIMER,
    build_cross_strategy_synthesis,
    generate_ai_daily_brief,
)
from alphasift.daily_report import build_daily_report, render_daily_im_card
from alphasift.daily_report_html import render_daily_report_html, write_daily_report_html
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
    placeholder_cred = "unit-test-placeholder"
    fenced_resp = "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
    llm_report = build_daily_report(
        _pack(),
        strategy_runs=_sample_runs(),
        include_announcements=False,
        ai_brief_mode="auto",
        config=Config(llm_api_key=placeholder_cred, llm_model="gpt-test"),
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
        config=Config(llm_api_key=placeholder_cred),
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


def test_render_and_write_daily_report_html_and_cli(tmp_path: Path, monkeypatch, capsys) -> None:
    from alphasift.pack import save_pack

    pack = _pack()
    pack_dir = tmp_path / "pack_cn"
    save_pack(pack_dir, pack)

    def ann_fn(df, *, max_rows: int, cache_dir=None):
        return [
            {
                "code": "000002",
                "name": "股票02<script>alert(1)</script>",
                "announcement": "股东拟减持",
                "negative_event_flags": ["减持"],
                "announcement_categories": ["减持"],
            }
        ], []

    report = build_daily_report(
        pack,
        expected_trade_date="2099-01-01",
        allow_stale_pack=True,
        strategy_runs=_sample_runs(),
        announcement_collector=ann_fn,
    )
    track_summary = {
        "strategy_names": {"dual_low": "双低稳健"},
        "track_comparison": [
            {
                "market": "cn",
                "strategy": "dual_low",
                "windows": {
                    "5": {
                        "ai_case_studies": {
                            "best_ai_adds": [{"date": "2026-10-12", "code": "600519", "name": "贵州茅台", "excess_return_pct": 5.2}],
                            "best_ai_avoids": [{"date": "2026-10-12", "code": "000002", "name": "股票02", "excess_return_pct": -4.1}],
                            "missed_by_ai": [],
                        }
                    }
                },
            }
        ],
    }
    html_out = tmp_path / "daily_report.html"
    written = write_daily_report_html(html_out, report, track_summary=track_summary)
    assert written == html_out and html_out.is_file()
    html_text = html_out.read_text(encoding="utf-8")
    assert "@media print" in html_text
    assert "@page" in html_text
    assert ".card, tr" in html_text
    assert "pat_exp_watch" in html_text or "pat_neg_watch" in html_text
    assert "policy_cn_slice" in html_text
    assert "旧包降级模式" in html_text
    assert "多策略共识" in html_text
    assert "贵州茅台" in html_text
    assert "股票02&lt;script&gt;alert(1)&lt;/script&gt;" in html_text
    assert "<script>alert(1)</script>" not in html_text
    assert 'class="kline"' in html_text
    assert 'class="dist-svg"' in html_text
    assert 'id="lang-switch"' in html_text
    assert "data-i18n=" in html_text

    import re
    import shutil
    import subprocess
    node = shutil.which("node")
    if node is not None:
        match = re.search(r"<script>(.*)</script>", html_text, flags=re.DOTALL)
        assert match is not None
        js_file = tmp_path / "daily_report.js"
        js_file.write_text(match.group(1), encoding="utf-8")
        proc = subprocess.run([node, "--check", str(js_file)], capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stderr

    # CLI --output-html and --ai-brief off smoke (offline deterministic with --no-news)
    cli_html = tmp_path / "cli_report.html"
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
            "--ai-brief",
            "off",
            "--output-html",
            str(cli_html),
            "--json",
        ],
    )
    cli_main()
    cli_payload = json.loads(capsys.readouterr().out)
    assert cli_html.is_file()
    assert cli_payload["ai_brief"]["mode"] == "rule_fallback"
    assert render_daily_report_html(cli_payload).startswith("<!doctype html>")


def test_brief_think_stripping_degradation_logging_and_html_jargon_cleanup() -> None:
    pack = _pack()
    runs = _sample_runs()
    # 1. Closed <think> block with misleading {brace} is stripped before parsing real JSON
    think_payload = {
        "headline": "低波价值共振领跑",
        "regime_interpretation": "市场温和修复。",
        "consensus_and_ai_edge": "双低选股与稳健价值共同覆盖 000001。",
        "risk_warnings": ["注意缩量分歧"],
        "watch_points": ["跟踪次日开盘承接"],
    }
    think_raw = "<think>draft {invalid: 1</think>\n" + json.dumps(think_payload, ensure_ascii=False)
    rep_think = build_daily_report(
        pack,
        strategy_runs=runs,
        include_announcements=False,
        ai_brief_mode="auto",
        config=Config(llm_api_key="k", llm_model="test-think"),
        llm_caller=lambda _p: think_raw,
    )
    assert rep_think["ai_brief"]["mode"] == "llm"
    assert rep_think["ai_brief"]["headline"] == "低波价值共振领跑"

    # 2. Truncated unclosed <think> fails cleanly and records fallback in degradation[]
    rep_err = build_daily_report(
        pack,
        strategy_runs=runs,
        include_announcements=False,
        include_news=True,
        market_news_collector=lambda **_kw: (
            [{"category": "宏观政策", "title": "盘后稳增长政策落地", "source": "东方财富7x24", "published_at": "11-20 17:30"}],
            ["东方财富7x24"],
            [],
        ),
        stock_news_collector=lambda df, **_kw: ([], []),
        ai_brief_mode="auto",
        config=Config(llm_api_key="k", llm_model="test-think"),
        llm_caller=lambda _p: "<think>cut off mid thought without closing",
        warn_if_no_runs=True,
    )
    assert rep_err["ai_brief"]["mode"] == "rule_fallback"
    assert any("AI brief fallback:" in d for d in rep_err["degradation"])
    assert "[仅切片]" not in rep_err["ai_brief"]["regime_interpretation"]
    assert "(" not in rep_err["ai_brief"]["headline"].split("阶段")[0]
    assert rep_err["market_news"]["items"][0]["title"] == "盘后稳增长政策落地"

    html_out = render_daily_report_html(rep_err)
    assert "[仅切片]" not in html_out
    assert "盘后稳增长政策落地" in html_out
    assert "双低选股" in html_out


def test_daily_report_walk_forward_regime_and_joint_oos() -> None:
    pack = _pack()
    runs = _sample_runs()
    probe = build_daily_report(
        pack,
        strategy_runs=runs,
        include_announcements=False,
        include_news=False,
    )
    cur_stage = probe["market_regime"]["regime_stage"]
    target_pat = (probe["patterns"]["experimental"] or probe["patterns"]["active"])[0]["pattern"]
    mock_replay = {
        "replay": {
            "cost_bps": 25.0,
            "patterns": [
                {
                    "pattern": target_pat,
                    "horizons": {"t5": {"net_excess_mean_pct": 0.42, "excess_win_rate_pct": 54.0, "scored": 120}},
                    "graduation": {"t5_net_excess_mean_pct": 0.42},
                    "walk_forward_regime_audit": {
                        "status": "ok",
                        "h1_adverse_regimes": [cur_stage],
                        "h2_non_adverse_low_overhead": {"days": 16, "signals": 82, "daily_mean_pct": 2.85},
                        "delta_non_adverse_low_overhead_vs_h2_baseline_pct": 2.13,
                    },
                }
            ],
        }
    }
    report = build_daily_report(
        pack,
        strategy_runs=runs,
        include_announcements=False,
        include_news=False,
        pattern_replay=mock_replay,
    )
    items = (report["patterns"]["active"] or []) + (report["patterns"]["experimental"] or [])
    matched = [p for p in items if p["pattern"] == target_pat][0]
    assert matched["wf_today_adverse"] is True
    assert matched["wf_non_adverse_low_overhead_pct"] == 2.85
    assert matched["wf_non_adverse_low_overhead_days"] == 16
    assert matched["wf_joint_delta_pct"] == 2.13

    html_text = render_daily_report_html(report)
    assert 'data-i18n="pat_wf_adverse"' in html_text
    assert 'data-i18n="pat_wf_joint"' in html_text
    assert "+2.85%(16d)" in html_text
    assert 'pat_wf_adverse: "WF Adverse Regime"' in html_text
    assert 'pat_wf_joint: " · Joint OOS {v}({d}d)"' in html_text


def test_im_card_and_html_prioritize_non_adverse_joint_oos_and_flag_adverse() -> None:
    report: dict = {
        "trade_date": "2026-11-24",
        "pack_trade_date": "2026-11-24",
        "expected_trade_date": "2026-11-24",
        "pack_is_stale": False,
        "market_regime": {"regime_stage": "divergence", "regime_stage_label": "分歧"},
        "strategies": [],
        "ai_highlights": [],
        "patterns": {
            "active": [],
            "experimental": [
                {
                    "pattern": "ma20_shrink_pullback",
                    "display_name": "20日线低波缩量回踩",
                    "status": "experimental",
                    "expectancy_tier": "neutral_watch",
                    "hit_count": 30,
                    "wf_today_adverse": True,
                    "wf_non_adverse_low_overhead_pct": -0.38,
                    "wf_non_adverse_low_overhead_days": 14,
                    "signals": [{"code": "300760", "name": "迈瑞医疗"}, {"code": "601766", "name": "中国中车"}],
                },
                {
                    "pattern": "double_bottom_breakout",
                    "display_name": "双底突破",
                    "status": "experimental",
                    "expectancy_tier": "negative_watch",
                    "hit_count": 3,
                    "wf_today_adverse": False,
                    "wf_non_adverse_low_overhead_pct": 0.24,
                    "wf_non_adverse_low_overhead_days": 60,
                    "signals": [{"code": "000001", "name": "平安银行"}, {"code": "600036", "name": "招商银行"}],
                },
                {
                    "pattern": "shooting_star_confirm",
                    "display_name": "仙人指路确认",
                    "status": "experimental",
                    "expectancy_tier": "negative_watch",
                    "hit_count": 5,
                    "wf_today_adverse": False,
                    "wf_non_adverse_low_overhead_pct": 1.21,
                    "wf_non_adverse_low_overhead_days": 8,
                    "signals": [{"code": "600519", "name": "贵州茅台"}],
                },
            ],
        },
        "announcement_risks": {"checked_count": 0, "flagged_count": 0, "flagged_items": [], "errors": []},
        "market_news": {"items": [], "sources": [], "candidate_news": {}, "errors": []},
        "degradation": [],
        "cross_strategy_synthesis": {},
        "ai_brief": {},
    }

    card = render_daily_im_card(report)
    assert len(card) < 1200
    assert "双底突破(3只·观察期·联合OOS+0.24%" in card
    assert "20日线低波缩量回踩(30只·观察期·逆风" in card
    assert card.index("双底突破") < card.index("20日线低波缩量回踩")
    assert "仙人指路" not in card

    html = render_daily_report_html(report)
    assert html.index('data-pattern="double_bottom_breakout"') < html.index('data-pattern="ma20_shrink_pullback"')
    assert html.index('data-pattern="ma20_shrink_pullback"') < html.index('data-pattern="shooting_star_confirm"')


def test_daily_report_html_contextual_dashboard_deep_links() -> None:
    import re
    import shutil
    import subprocess
    import tempfile

    base_report: dict = {
        "trade_date": "2026-11-24",
        "pack_trade_date": "2026-11-24",
        "expected_trade_date": "2026-11-24",
        "pack_is_stale": False,
        "market_regime": {"regime_stage": "divergence", "regime_stage_label": "分歧"},
        "strategies": [],
        "ai_highlights": [],
        "patterns": {
            "active": [],
            "experimental": [
                {
                    "pattern": "double_bottom_breakout",
                    "display_name": "双底突破",
                    "status": "experimental",
                    "expectancy_tier": "negative_watch",
                    "hit_count": 3,
                    "wf_today_adverse": False,
                    "wf_non_adverse_low_overhead_pct": 0.24,
                    "wf_non_adverse_low_overhead_days": 60,
                    "signals": [{"code": "000001", "name": "平安银行"}],
                }
            ],
        },
        "announcement_risks": {"checked_count": 0, "flagged_count": 0, "flagged_items": [], "errors": []},
        "market_news": {"items": [], "sources": [], "candidate_news": {}, "errors": []},
        "degradation": [],
        "cross_strategy_synthesis": {},
        "ai_brief": {},
    }

    rel_html = render_daily_report_html(base_report)
    assert 'data-dash-hash="track-comparison-section"' in rel_html
    assert 'data-dash-hash="leaderboard"' in rel_html
    assert 'data-dash-hash="walk-forward-wrap"' in rel_html
    assert 'data-dash-pat="double_bottom_breakout"' in rel_html
    assert 'class="dash-link no-print"' in rel_html
    assert 'href="../index.html?pat=double_bottom_breakout#walk-forward-wrap"' in rel_html
    assert 'link_pat_wf: "OOS Audit →"' in rel_html
    assert 'link_wf_board: "250D Walk-Forward Audit →"' in rel_html

    custom_report = dict(base_report, detail_url="https://example.com/dash")
    custom_html = render_daily_report_html(custom_report)
    assert 'href="https://example.com/dash?pat=double_bottom_breakout#walk-forward-wrap"' in custom_html

    node = shutil.which("node")
    if node is not None:
        match = re.search(r"<script>(.*)</script>", rel_html, flags=re.DOTALL)
        assert match is not None
        with tempfile.TemporaryDirectory() as td:
            js_file = Path(td) / "daily_report.js"
            js_file.write_text(match.group(1), encoding="utf-8")
            proc = subprocess.run([node, "--check", str(js_file)], capture_output=True, text=True, check=False)
            assert proc.returncode == 0, proc.stderr


def test_daily_report_html_section_and_pattern_anchors() -> None:
    report: dict = {
        "trade_date": "2026-11-24",
        "pack_trade_date": "2026-11-24",
        "expected_trade_date": "2026-11-24",
        "pack_is_stale": False,
        "market_regime": {"regime_stage": "divergence", "regime_stage_label": "分歧"},
        "strategies": [],
        "ai_highlights": [
            {
                "strategy": "dual_low",
                "rules_pick_count": 5,
                "ai_pick_count": 5,
                "overlap_pct": 80.0,
                "added_by_ai": [{"code": "600519", "name": "贵州茅台"}],
                "dropped_by_ai": [{"code": "000001", "name": "平安银行"}],
            }
        ],
        "patterns": {
            "active": [],
            "experimental": [
                {
                    "pattern": "double_bottom_breakout",
                    "display_name": "双底突破",
                    "status": "experimental",
                    "expectancy_tier": "negative_watch",
                    "hit_count": 3,
                    "signals": [{"code": "000001", "name": "平安银行"}],
                }
            ],
        },
        "announcement_risks": {"checked_count": 0, "flagged_count": 0, "flagged_items": [], "errors": []},
        "market_news": {
            "items": [{"category": "政策", "title": "盘后要闻示例", "source": "Test", "published_at": "11-24"}],
            "sources": ["Test"],
            "candidate_news": {},
            "errors": [],
        },
        "degradation": [],
        "cross_strategy_synthesis": {},
        "ai_brief": {},
    }
    html_text = render_daily_report_html(report)
    for anchor in (
        'id="brief"',
        'id="panorama"',
        'id="announcements"',
        'id="news"',
        'id="synthesis"',
        'id="ai-rebalance"',
        'id="strategies"',
        'id="patterns"',
        'id="pat-double_bottom_breakout"',
    ):
        assert anchor in html_text, f"missing anchor {anchor}"
    assert "scroll-margin-top: 64px" in html_text
    assert ".card:target" in html_text


def test_daily_report_wf_cli_copy_and_low_sample_guardrail() -> None:
    import re
    import shutil
    import subprocess
    import tempfile

    from alphasift.daily_report import _extract_pattern_replay_map

    mock_replay = {
        "replay": {
            "patterns": [
                {
                    "pattern": "double_bottom_breakout",
                    "horizons": {"t5": {"net_excess_mean_pct": 0.24, "excess_win_rate_pct": 52.0, "scored": 90}},
                    "walk_forward_regime_audit": {
                        "h1_adverse_regimes": ["freezing", "ebb"],
                        "h1_positive_regimes": ["startup"],
                        "low_overhead_threshold_pct": 12.0,
                        "h2_non_adverse_low_overhead": {"days": 22, "daily_mean_pct": 0.91},
                    },
                },
                {
                    "pattern": "box_breakout",
                    "horizons": {"t5": {"net_excess_mean_pct": 0.11, "excess_win_rate_pct": 50.0, "scored": 40}},
                    "walk_forward_regime_audit": {
                        "h1_positive_regimes": ["startup", "main_up"],
                    },
                },
            ]
        }
    }
    rmap = _extract_pattern_replay_map(mock_replay)
    assert rmap["double_bottom_breakout"]["wf_h1_positive_regimes"] == ["startup"]
    assert rmap["double_bottom_breakout"]["wf_low_overhead_threshold_pct"] == 12
    assert rmap["box_breakout"]["wf_h1_positive_regimes"] == ["startup", "main_up"]
    assert rmap["box_breakout"]["wf_low_overhead_threshold_pct"] == 15

    report: dict = {
        "trade_date": "2026-11-24",
        "pack_trade_date": "2026-11-24",
        "expected_trade_date": "2026-11-24",
        "pack_is_stale": False,
        "market_regime": {"regime_stage": "divergence", "regime_stage_label": "分歧"},
        "strategies": [],
        "ai_highlights": [],
        "patterns": {
            "active": [],
            "experimental": [
                {
                    "pattern": "double_bottom_breakout",
                    "display_name": "双底突破",
                    "status": "experimental",
                    "expectancy_tier": "positive_watch",
                    "hit_count": 2,
                    "wf_h1_adverse_regimes": ["freezing", "ebb"],
                    "wf_h1_positive_regimes": ["startup"],
                    "wf_low_overhead_threshold_pct": 12,
                    "wf_non_adverse_low_overhead_pct": 0.91,
                    "wf_non_adverse_low_overhead_days": 22,
                    "signals": [{"code": "000001", "name": "平安银行"}],
                },
                {
                    "pattern": "ma20_shrink_pullback",
                    "display_name": "20日线低波缩量回踩",
                    "status": "experimental",
                    "expectancy_tier": "neutral_watch",
                    "hit_count": 1,
                    "wf_h1_adverse_regimes": ["freezing"],
                    "wf_non_adverse_low_overhead_pct": 1.15,
                    "wf_non_adverse_low_overhead_days": 9,
                    "signals": [{"code": "300760", "name": "迈瑞医疗"}],
                },
                {
                    "pattern": "box_breakout",
                    "display_name": "箱体突破",
                    "status": "experimental",
                    "expectancy_tier": "negative_watch",
                    "hit_count": 1,
                    "wf_h1_positive_regimes": ["startup", "main_up"],
                    "signals": [{"code": "600519", "name": "贵州茅台"}],
                },
                {
                    "pattern": "single_yang_hold",
                    "display_name": "单阳不破",
                    "status": "experimental",
                    "expectancy_tier": "unrated",
                    "hit_count": 0,
                    "signals": [],
                },
            ],
        },
        "announcement_risks": {"checked_count": 0, "flagged_count": 0, "flagged_items": [], "errors": []},
        "market_news": {"items": [], "sources": [], "candidate_news": {}, "errors": []},
        "degradation": [],
        "cross_strategy_synthesis": {},
        "ai_brief": {},
    }

    html_text = render_daily_report_html(report)
    assert 'data-cli="alphasift patterns replay --pattern double_bottom_breakout --exclude-regimes freezing,ebb --max-overhead-pct 12"' in html_text
    assert 'data-cli="alphasift patterns replay --pattern ma20_shrink_pullback --exclude-regimes freezing --max-overhead-pct 15"' in html_text
    assert 'data-cli="alphasift patterns replay --pattern box_breakout --allowed-regimes startup,main_up"' in html_text
    assert 'data-cli="alphasift patterns replay --pattern single_yang_hold"' in html_text

    # Small-sample (<15d) warning on ma20_shrink_pullback (9d), absent on double_bottom_breakout (22d)
    assert '<span class="wf-low" data-i18n="pat_wf_joint"' in html_text
    assert html_text.count('<span class="tag-low">&lt;15d</span>') == 1

    assert 'wf_cli_copied: "已复制"' in html_text
    assert 'wf_cli_copied: "Copied"' in html_text
    assert 'wf_cli_copied: "コピー済"' in html_text
    assert "copyPlainText" in html_text

    node = shutil.which("node")
    if node is not None:
        match = re.search(r"<script>(.*)</script>", html_text, flags=re.DOTALL)
        assert match is not None
        with tempfile.TemporaryDirectory() as td:
            js_file = Path(td) / "daily_report_wf.js"
            js_file.write_text(match.group(1), encoding="utf-8")
            proc = subprocess.run([node, "--check", str(js_file)], capture_output=True, text=True, check=False)
            assert proc.returncode == 0, proc.stderr


def test_daily_report_boundary_verification_and_unverified_badge() -> None:
    import re
    import shutil
    import subprocess
    import tempfile

    from alphasift.daily_report import _extract_pattern_replay_map

    rmap = _extract_pattern_replay_map({
        "replay": {
            "patterns": [
                {
                    "pattern": "verified_pat",
                    "horizons": {"t5": {"net_excess_mean_pct": 0.1, "excess_win_rate_pct": 50.0, "scored": 50}},
                    "walk_forward_regime_audit": {
                        "boundary_policy": "purged_by_exit_date",
                        "eval_mid_date": "2026-06-30",
                        "h1_adverse_regimes": ["freezing"],
                        "h1_purged_signals": 12,
                        "h1_purged_days": 4,
                        "h2_non_adverse_low_overhead": {"days": 20, "daily_mean_pct": 0.5},
                    },
                },
                {
                    "pattern": "legacy_pat",
                    "horizons": {"t5": {"net_excess_mean_pct": -0.2, "excess_win_rate_pct": 48.0, "scored": 50}},
                    "walk_forward_regime_audit": {
                        "h1_adverse_regimes": ["divergence"],
                        "h2_non_adverse_low_overhead": {"days": 20, "daily_mean_pct": 0.2},
                    },
                },
            ]
        }
    })
    assert rmap["verified_pat"]["wf_boundary_policy"] == "purged_by_exit_date"
    assert rmap["verified_pat"]["wf_boundary_verified"] is True
    assert rmap["verified_pat"]["wf_eval_mid_date"] == "2026-06-30"
    assert rmap["verified_pat"]["wf_h1_purged_signals"] == 12
    assert rmap["verified_pat"]["wf_h1_purged_days"] == 4
    assert rmap["legacy_pat"]["wf_boundary_policy"] == ""
    assert rmap["legacy_pat"]["wf_boundary_verified"] is False
    assert rmap["legacy_pat"]["wf_eval_mid_date"] == ""

    html_text = render_daily_report_html({
        "trade_date": "2026-11-24",
        "pack_trade_date": "2026-11-24",
        "expected_trade_date": "2026-11-24",
        "pack_is_stale": False,
        "market_regime": {"regime_stage": "divergence", "regime_stage_label": "分歧"},
        "strategies": [],
        "ai_highlights": [],
        "patterns": {
            "active": [],
            "experimental": [
                {
                    "pattern": "verified_pat",
                    "display_name": "已复核形态",
                    "status": "experimental",
                    "expectancy_tier": "positive_watch",
                    "hit_count": 1,
                    "wf_today_adverse": True,
                    "wf_boundary_verified": True,
                    "wf_eval_mid_date": "2026-06-30",
                    "wf_h1_purged_signals": 12,
                    "wf_h1_purged_days": 4,
                    "wf_non_adverse_low_overhead_pct": 0.5,
                    "wf_non_adverse_low_overhead_days": 20,
                    "signals": [],
                },
                {
                    "pattern": "legacy_pat",
                    "display_name": "待复核形态",
                    "status": "experimental",
                    "expectancy_tier": "negative_watch",
                    "hit_count": 1,
                    "wf_today_adverse": True,
                    "wf_boundary_verified": False,
                    "signals": [],
                },
            ],
        },
        "announcement_risks": {"checked_count": 0, "flagged_count": 0, "flagged_items": [], "errors": []},
        "market_news": {"items": [], "sources": [], "candidate_news": {}, "errors": []},
        "degradation": [],
        "cross_strategy_synthesis": {},
        "ai_brief": {},
    })
    assert html_text.count('data-i18n="pat_wf_pending"') == 1
    assert 'data-i18n="pat_wf_boundary_note_stats"' in html_text
    assert "2026-06-30" in html_text
    assert "累计剔除 12 条跨界信号" in html_text
    assert 'title="H1 exit_date &lt; 2026-06-30 · purged 12 (4d)"' in html_text
    assert 'pat_wf_pending: "Boundary Unverified"' in html_text
    assert 'pat_wf_pending: "境界未検証"' in html_text
    assert "pat_wf_boundary_note_stats:" in html_text

    node = shutil.which("node")
    if node is not None:
        match = re.search(r"<script>(.*)</script>", html_text, flags=re.DOTALL)
        assert match is not None
        with tempfile.TemporaryDirectory() as td:
            js_file = Path(td) / "daily_report_boundary.js"
            js_file.write_text(match.group(1), encoding="utf-8")
            proc = subprocess.run([node, "--check", str(js_file)], capture_output=True, text=True, check=False)
            assert proc.returncode == 0, proc.stderr


def test_daily_report_html_formats_nonfinite_metrics_as_dash(tmp_path):
    from alphasift.daily_report_html import _fmt_num, _fmt_pct

    for bad in (float("nan"), float("inf"), float("-inf")):
        assert _fmt_pct(bad) == '<span class="dim">–</span>'
        assert _fmt_num(bad) == '<span class="dim">–</span>'

    out = write_daily_report_html(
        tmp_path / "daily.html",
        {
            "trade_date": "2026-11-25",
            "pack_trade_date": "2026-11-25",
            "expected_trade_date": "2026-11-25",
            "pack_is_stale": False,
            "market_regime": {"regime_stage": "neutral", "regime_stage_label": "中性"},
            "strategies": [
                {
                    "strategy": "dual_low",
                    "display_name": "双低",
                    "count": 1,
                    "picks": [{"code": "000001", "name": "测试股", "change_pct": float("inf"), "score": float("-inf")}],
                }
            ],
            "ai_highlights": [],
            "patterns": {
                "active": [],
                "experimental": [
                    {
                        "pattern": "inf_pat",
                        "display_name": "无限值测试",
                        "status": "experimental",
                        "expectancy_tier": "positive_watch",
                        "hit_count": 1,
                        "wf_non_adverse_low_overhead_pct": float("inf"),
                        "signals": [],
                    }
                ],
            },
            "announcement_risks": {"checked_count": 0, "flagged_count": 0, "flagged_items": [], "errors": []},
            "market_news": {"items": [], "sources": [], "candidate_news": {}, "errors": []},
            "degradation": [],
            "cross_strategy_synthesis": {},
            "ai_brief": {},
        },
    )
    rendered = out.read_text(encoding="utf-8")
    assert "inf%" not in rendered.lower()
    assert "+inf" not in rendered.lower()
    assert [p.name for p in tmp_path.iterdir()] == ["daily.html"]


def test_daily_brief_synthesis_and_rule_brief_scrub_nonfinite_and_bool():
    from alphasift.daily_brief import build_cross_strategy_synthesis, generate_ai_daily_brief
    from alphasift.jsonutil import dumps_strict_json

    bad_report = {
        "trade_date": "2026-11-26",
        "market_regime": {
            "regime_stage_label": "震荡",
            "advance_ratio_pct": float("nan"),
            "median_return_pct": float("inf"),
            "non_st_limit_up_count": True,
            "non_st_limit_down_count": float("nan"),
            "seal_rate_pct": float("-inf"),
            "prev_limit_up_avg_return_pct": True,
            "max_consecutive_limit_up": float("inf"),
            "total_amount_yi": float("nan"),
        },
        "announcement_risks": {"checked_count": True, "flagged_items": []},
        "strategies": [
            {
                "strategy": "dual_low",
                "track": "rules",
                "picks": [
                    {
                        "code": "600519",
                        "name": "贵州茅台",
                        "industry": "白酒",
                        "final_score": float("inf"),
                        "change_pct": float("nan"),
                        "price": True,
                        "pe_ratio": float("-inf"),
                        "pb_ratio": float("nan"),
                        "market_cap_yi": float("inf"),
                    }
                ],
            },
            {
                "strategy": "quality_value",
                "track": "rules",
                "picks": [
                    {
                        "code": "600519",
                        "name": "贵州茅台",
                        "industry": "白酒",
                        "final_score": 82.5,
                        "change_pct": 1.2,
                        "price": 1500.0,
                    }
                ],
            },
        ],
        "patterns": {"active": [], "experimental": []},
        "ai_highlights": [],
    }

    syn = build_cross_strategy_synthesis(bad_report)
    assert len(syn["consensus_picks"]) == 1
    c0 = syn["consensus_picks"][0]
    assert c0["avg_final_score"] == 82.5
    assert c0["change_pct"] == 1.2
    assert c0["price"] == 1500.0
    assert "pe_ratio" not in c0
    assert "pb_ratio" not in c0
    assert "market_cap_yi" not in c0
    assert dumps_strict_json(syn)

    bad_report["cross_strategy_synthesis"] = syn
    brief = generate_ai_daily_brief(bad_report, config=None)
    assert brief["mode"] == "rule_fallback"
    text_blob = dumps_strict_json(brief).lower()
    assert "nan" not in text_blob
    assert "inf" not in text_blob
    assert "真" not in text_blob and "true" not in text_blob.replace("rule_fallback", "")




