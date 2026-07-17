from pathlib import Path

import pandas as pd
import pytest

from alphasift.config import Config
from alphasift.pipeline import screen
from alphasift.ranker import LLMRankingResult


def _make_config() -> Config:
    return Config(
        llm_api_key="",
        llm_model="gemini/gemini-2.5-flash",
        llm_base_url="",
        snapshot_source_priority=["em_datacenter"],
        strategies_dir=Path("strategies"),
        dsa_api_url="http://localhost:8000",
        dsa_report_type="detailed",
        dsa_max_picks=2,
        dsa_timeout_sec=120.0,
        dsa_force_refresh=False,
        dsa_notify=False,
    )


def test_screen_requires_dsa_url_when_deep_analysis_enabled(monkeypatch):
    config = _make_config()
    config.dsa_api_url = ""

    df = pd.DataFrame(
        [
            {
                "code": "600519",
                "name": "贵州茅台",
                "price": 10.0,
                "change_pct": 1.0,
                "amount": 200_000_000,
                "total_mv": 10_000_000_000,
                "pe_ratio": 10.0,
                "pb_ratio": 1.0,
                "screen_score": 88.0,
            }
        ]
    )
    monkeypatch.setattr("alphasift.pipeline.fetch_snapshot_with_fallback", lambda sources, **kwargs: df)
    monkeypatch.setattr("alphasift.pipeline.apply_hard_filters", lambda frame, filters: frame)
    monkeypatch.setattr("alphasift.pipeline.compute_screen_scores", lambda frame, cfg: frame)

    with pytest.raises(ValueError):
        screen("dual_low", deep_analysis=True, config=config)


def test_screen_runs_optional_dsa_analysis(monkeypatch):
    df = pd.DataFrame(
        [
            {
                "code": "600519",
                "name": "贵州茅台",
                "price": 10.0,
                "change_pct": 1.0,
                "amount": 200_000_000,
                "total_mv": 10_000_000_000,
                "pe_ratio": 10.0,
                "pb_ratio": 1.0,
                "screen_score": 88.0,
            },
            {
                "code": "000858",
                "name": "五粮液",
                "price": 20.0,
                "change_pct": 2.0,
                "amount": 250_000_000,
                "total_mv": 11_000_000_000,
                "pe_ratio": 11.0,
                "pb_ratio": 1.2,
                "screen_score": 86.0,
            },
        ]
    )

    monkeypatch.setattr("alphasift.pipeline.fetch_snapshot_with_fallback", lambda sources, **kwargs: df)
    monkeypatch.setattr("alphasift.pipeline.apply_hard_filters", lambda frame, filters: frame)
    monkeypatch.setattr("alphasift.pipeline.compute_screen_scores", lambda frame, cfg: frame)

    def fake_post_analyze(picks, **kwargs):
        assert kwargs["analyzer_names"] == ["scorecard", "dsa"]
        picks[0].deep_analysis_status = "completed"
        picks[0].deep_analysis_summary = "建议继续跟踪"
        picks[0].deep_analysis_signal_score = 80
        picks[0].deep_analysis_sentiment_score = 82
        picks[0].deep_analysis_operation_advice = "买入"
        picks[0].deep_analysis_trend_prediction = "看多"
        picks[0].final_score = picks[0].screen_score + 1.0
        picks[1].deep_analysis_status = "skipped"
        return picks, []

    monkeypatch.setattr("alphasift.pipeline.run_post_analyzers", fake_post_analyze)

    result = screen("dual_low", deep_analysis=True, config=_make_config())

    assert result.deep_analysis_requested is True
    assert result.picks[0].deep_analysis_status == "completed"
    assert result.picks[0].deep_analysis_summary == "建议继续跟踪"
    assert result.picks[0].final_score > result.picks[0].screen_score


def test_screen_uses_dsa_as_final_stage_overlay(monkeypatch):
    df = pd.DataFrame(
        [
            {
                "code": "000001",
                "name": "A",
                "price": 10.0,
                "change_pct": 1.0,
                "amount": 200_000_000,
                "total_mv": 10_000_000_000,
                "pe_ratio": 10.0,
                "pb_ratio": 1.0,
                "screen_score": 80.0,
            },
            {
                "code": "000002",
                "name": "B",
                "price": 20.0,
                "change_pct": 2.0,
                "amount": 250_000_000,
                "total_mv": 11_000_000_000,
                "pe_ratio": 11.0,
                "pb_ratio": 1.2,
                "screen_score": 82.0,
            },
            {
                "code": "000003",
                "name": "C",
                "price": 18.0,
                "change_pct": 0.5,
                "amount": 180_000_000,
                "total_mv": 9_000_000_000,
                "pe_ratio": 12.0,
                "pb_ratio": 1.3,
                "screen_score": 78.0,
            },
        ]
    )

    monkeypatch.setattr("alphasift.pipeline.fetch_snapshot_with_fallback", lambda sources, **kwargs: df)
    monkeypatch.setattr("alphasift.pipeline.apply_hard_filters", lambda frame, filters: frame)
    monkeypatch.setattr("alphasift.pipeline.compute_screen_scores", lambda frame, cfg: frame)

    def fake_analyze(picks, **kwargs):
        assert [pick.code for pick in picks] == ["000002", "000001"]

        picks[0].deep_analysis_status = "completed"
        picks[0].deep_analysis_signal_score = 35
        picks[0].deep_analysis_sentiment_score = 40
        picks[0].deep_analysis_operation_advice = "观望"
        picks[0].deep_analysis_trend_prediction = "震荡"
        picks[0].deep_analysis_risk_flags = ["短线超买"]

        picks[1].deep_analysis_status = "completed"
        picks[1].deep_analysis_signal_score = 85
        picks[1].deep_analysis_sentiment_score = 90
        picks[1].deep_analysis_operation_advice = "买入"
        picks[1].deep_analysis_trend_prediction = "看多"
        return picks, []

    monkeypatch.setattr("alphasift.post_analysis.analyze_picks_with_dsa", fake_analyze)

    result = screen(
        "dual_low",
        post_analyzers=["dsa"],
        deep_analysis=True,
        max_output=2,
        deep_analysis_max_picks=2,
        config=_make_config(),
    )

    assert [pick.code for pick in result.picks] == ["000001", "000002"]
    assert result.picks[0].rank == 1
    assert result.picks[1].rank == 2


def test_screen_applies_dsa_provider_context_before_llm_ranking(monkeypatch):
    config = _make_config()
    config.llm_api_key = "test-key"

    df = pd.DataFrame(
        [
            {
                "code": "600519",
                "name": "贵州茅台",
                "price": 10.0,
                "change_pct": 1.0,
                "amount": 200_000_000,
                "total_mv": 10_000_000_000,
                "pe_ratio": 10.0,
                "pb_ratio": 1.0,
                "screen_score": 88.0,
            }
        ]
    )

    captured: dict[str, object] = {}

    monkeypatch.setattr("alphasift.pipeline.fetch_snapshot_with_fallback", lambda sources, **kwargs: df)
    monkeypatch.setattr("alphasift.pipeline.apply_hard_filters", lambda frame, filters: frame)
    monkeypatch.setattr("alphasift.pipeline.compute_screen_scores", lambda frame, cfg: frame)

    def fake_ranker(picks, *_args, **_kwargs):
        captured["dsa_context"] = picks[0].dsa_context
        captured["dsa_news"] = picks[0].dsa_news
        captured["dsa_summary"] = picks[0].dsa_analysis_summary
        picks[0].llm_score = 90.0
        return LLMRankingResult(picks=picks, ranked=True, coverage=1.0)

    monkeypatch.setattr("alphasift.pipeline.rank_candidates_with_metadata", fake_ranker)

    def get_candidate_context(stock_code: str, stock_name: str = ""):
        assert stock_code == "600519"
        assert stock_name == "贵州茅台"
        return {
            "enriched": True,
            "quote": {"price": 1688.0, "change_pct": 1.2, "amount": 100_000_000.0},
            "fundamentals": {"coverage": {"valuation": "available"}},
            "news": {
                "success": True,
                "results": [{"title": "贵州茅台最新公告", "source": "测试源"}],
            },
            "warnings": [],
        }

    result = screen(
        "dual_low",
        max_output=1,
        use_llm=True,
        context={"dsa": {"get_candidate_context": get_candidate_context}},
        config=config,
    )

    assert captured["dsa_context"]["enriched"] is True
    assert captured["dsa_news"][0]["title"] == "贵州茅台最新公告"
    assert "DSA新闻" in captured["dsa_summary"]
    assert result.llm_ranked is True
    assert result.llm_rank_status == "complete"
    assert result.llm_matched_count == 1
    assert result.llm_requested_count == 1
    assert result.llm_repair_status == "not_run"
    assert result.picks[0].dsa_context["quote"]["price"] == 1688.0
    assert any("DSA provider context applied 1 of 1 candidates" in item for item in result.degradation)
