from pathlib import Path

import pandas as pd

from alphasift.config import Config
from alphasift.pipeline import _daily_source_health_notes, _sort_screened_candidates, screen
from alphasift.strategy import ScreeningConfig


def test_pipeline_enriches_daily_features_for_daily_strategy(monkeypatch):
    df = pd.DataFrame(
        [
            {
                "code": "000001",
                "name": "平安银行",
                "price": 10.0,
                "change_pct": -0.5,
                "amount": 200_000_000,
                "turnover_rate": 2.0,
                "volume_ratio": 1.2,
                "pe_ratio": 8.0,
                "pb_ratio": 0.8,
                "total_mv": 100_000_000_000,
            },
            {
                "code": "600000",
                "name": "浦发银行",
                "price": 11.0,
                "change_pct": -0.8,
                "amount": 190_000_000,
                "turnover_rate": 2.0,
                "volume_ratio": 1.1,
                "pe_ratio": 9.0,
                "pb_ratio": 0.9,
                "total_mv": 90_000_000_000,
            },
        ]
    )
    df.attrs["snapshot_source"] = "test"

    def fake_enrich(frame, **kwargs):
        enriched = frame.copy()
        for idx, row in enriched.iterrows():
            is_target = row["code"] == "000001"
            enriched.loc[idx, "ma_bullish"] = is_target
            enriched.loc[idx, "price_above_ma20"] = True
            enriched.loc[idx, "signal_score"] = 72 if is_target else 80
            enriched.loc[idx, "change_60d"] = 12 if is_target else 10
            enriched.loc[idx, "macd_status"] = "bullish"
            enriched.loc[idx, "rsi_status"] = "neutral"
            enriched.loc[idx, "volume_ratio_20d"] = 1.0 if is_target else 1.8
            enriched.loc[idx, "pullback_to_ma20_pct"] = 4 if is_target else 12
            enriched.loc[idx, "volatility_20d_pct"] = 25 if is_target else 60
            enriched.loc[idx, "max_drawdown_20d_pct"] = -5 if is_target else -18
            enriched.loc[idx, "atr_20_pct"] = 3 if is_target else 9
            enriched.loc[idx, "daily_quality_score"] = 100 if is_target else 70
            enriched.loc[idx, "daily_quality_flags"] = "" if is_target else "fallback_errors"
            enriched.loc[idx, "daily_source"] = "tencent"
        enriched.attrs["daily_success_count"] = len(enriched)
        enriched.attrs["daily_source_counts"] = {"tencent": 2}
        enriched.attrs["daily_quality_flag_counts"] = {"fallback_errors": 1}
        enriched.attrs["daily_source_order_notes"] = ["daily source order adjusted by health: tencent,sina"]
        enriched.attrs["daily_source_health"] = {
            "sina": {"failures": 0.0, "total_failures": 1.0, "last_rows": 30.0, "disabled": False},
            "tencent": {"failures": 2.0, "total_failures": 2.0, "last_rows": 0.0, "disabled": True},
        }
        return enriched

    monkeypatch.setattr("alphasift.pipeline.fetch_snapshot_with_fallback", lambda sources, **kwargs: df)
    monkeypatch.setattr("alphasift.pipeline.enrich_daily_features", fake_enrich)

    result = screen(
        "shrink_pullback",
        use_llm=False,
        explain_filters=True,
        config=Config(
            llm_api_key="",
            snapshot_source_priority=["test"],
            strategies_dir=Path("strategies"),
            risk_enabled=False,
        ),
    )

    assert result.daily_enriched is True
    assert result.after_filter_count == 1
    assert result.picks[0].code == "000001"
    assert result.picks[0].ma_bullish is True
    assert result.picks[0].volatility_20d_pct == 25
    assert result.picks[0].max_drawdown_20d_pct == -5
    assert result.picks[0].atr_20_pct == 3
    assert result.picks[0].daily_quality_score == 100
    assert result.picks[0].daily_quality_flags == ""
    assert result.picks[0].daily_source == "tencent"
    assert any("Daily K-line enrichment attempted 2 candidates" in item for item in result.degradation)
    assert "Daily K-line sources: tencent=2" in result.degradation
    assert "Daily K-line quality flags: fallback_errors=1" in result.degradation
    assert "Daily K-line source ordering: daily source order adjusted by health: tencent,sina" in result.degradation
    assert any("Daily K-line source health:" in item for item in result.degradation)
    assert any("tencent disabled,failures=2" in item for item in result.degradation)
    assert any("sina total_failures=1,last_rows=30" in item for item in result.degradation)
    assert any("Daily hard-filter rejections:" in item for item in result.degradation)
    assert any("require_ma_bullish removed 1" in item for item in result.degradation)
    assert any("Snapshot hard-filter waterfall:" in item for item in result.degradation)
    assert any("Daily hard-filter waterfall:" in item for item in result.degradation)


def test_daily_source_health_notes_prioritize_severe_states_and_limit_noise():
    notes = _daily_source_health_notes(
        {
            "akshare": {"failures": 0, "total_failures": 1, "last_rows": 40, "disabled": False},
            "baostock": {"failures": 1, "total_failures": 3, "disabled": False},
            "sina": {"failures": 0, "total_failures": 2, "last_rows": 30, "disabled": False},
            "tencent": {"failures": 2, "total_failures": 2, "disabled": True},
            "tushare": {"failures": 0, "total_failures": 0, "disabled": False},
        },
        limit=2,
    )

    assert notes == [
        "tencent disabled,failures=2",
        "baostock failures=1",
        "+2 more",
    ]


def test_pipeline_preserves_degradation_when_hard_filter_empty(monkeypatch):
    df = pd.DataFrame([
        {
            "code": "000001",
            "name": "平安银行",
            "price": 10.0,
            "change_pct": 0.0,
            "amount": 1,
            "total_mv": 1,
            "pe_ratio": 1000.0,
            "pb_ratio": 100.0,
        }
    ])
    df.attrs["snapshot_source"] = "test"
    df.attrs["source_errors"] = ["efinance failed"]
    monkeypatch.setattr("alphasift.pipeline.fetch_snapshot_with_fallback", lambda sources, **kwargs: df)

    result = screen(
        "dual_low",
        use_llm=False,
        post_analyzers=[],
        config=Config(
            llm_api_key="",
            snapshot_source_priority=["test"],
            strategies_dir=Path("strategies"),
            risk_enabled=False,
        ),
    )

    assert result.picks == []
    assert any("Snapshot source fallback: efinance failed" in item for item in result.degradation)
    assert "No candidates after hard filter" in result.degradation


def test_pipeline_passes_industry_provider_cache_config(monkeypatch, tmp_path):
    df = pd.DataFrame([
        {
            "code": "000001",
            "name": "骞冲畨閾惰",
            "price": 10.0,
            "change_pct": 0.0,
            "amount": 100_000_000,
            "turnover_rate": 2.0,
            "volume_ratio": 1.2,
            "pe_ratio": 8.0,
            "pb_ratio": 0.8,
            "total_mv": 100_000_000_000,
        }
    ])
    df.attrs["snapshot_source"] = "test"
    calls = []

    def fake_enrich(frame, **kwargs):
        calls.append(kwargs)
        return frame, []

    monkeypatch.setattr("alphasift.pipeline.fetch_snapshot_with_fallback", lambda sources, **kwargs: df)
    monkeypatch.setattr("alphasift.pipeline.enrich_industry_concepts", fake_enrich)

    cache_dir = tmp_path / "industry-cache"
    screen(
        "dual_low",
        use_llm=False,
        post_analyzers=[],
        config=Config(
            llm_api_key="",
            snapshot_source_priority=["test"],
            strategies_dir=Path("strategies"),
            industry_provider="akshare",
            industry_provider_cache_dir=cache_dir,
            industry_provider_cache_ttl_hours=7,
            risk_enabled=False,
        ),
    )

    assert calls == [{
        "map_files": [],
        "provider": "akshare",
        "max_boards": 80,
        "provider_cache_dir": cache_dir,
        "provider_cache_ttl_hours": 7,
    }]


def test_sort_screened_candidates_uses_strategy_factor_tie_breakers_then_code():
    df = pd.DataFrame([
        {"code": "600000", "screen_score": 80, "factor_momentum_score": 70, "factor_stability_score": 90},
        {"code": "000001", "screen_score": 80, "factor_momentum_score": 70, "factor_stability_score": 90},
        {"code": "300001", "screen_score": 80, "factor_momentum_score": 75, "factor_stability_score": 10},
        {"code": "002001", "screen_score": 81, "factor_momentum_score": 20, "factor_stability_score": 20},
    ])
    screening = ScreeningConfig(factor_weights={"momentum": 0.7, "stability": 0.3})

    sorted_df = _sort_screened_candidates(df, screening)

    assert list(sorted_df["code"]) == ["002001", "300001", "000001", "600000"]


def test_sort_screened_candidates_keeps_default_tie_breakers_without_weights():
    df = pd.DataFrame([
        {"code": "600000", "screen_score": 80, "factor_stability_score": 70, "factor_activity_score": 50},
        {"code": "000001", "screen_score": 80, "factor_stability_score": 70, "factor_activity_score": 50},
        {"code": "300001", "screen_score": 80, "factor_stability_score": 75, "factor_activity_score": 10},
    ])

    sorted_df = _sort_screened_candidates(df, ScreeningConfig())

    assert list(sorted_df["code"]) == ["300001", "000001", "600000"]
