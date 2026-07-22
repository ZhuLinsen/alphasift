from pathlib import Path

import pandas as pd
import pytest

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
            enriched.at[idx, "ma_bullish"] = is_target
            enriched.at[idx, "price_above_ma20"] = True
            enriched.at[idx, "signal_score"] = 72 if is_target else 80
            enriched.at[idx, "change_60d"] = 12 if is_target else 10
            enriched.at[idx, "macd_status"] = "bullish"
            enriched.at[idx, "rsi_status"] = "neutral"
            enriched.at[idx, "volume_ratio_20d"] = 1.0 if is_target else 1.8
            enriched.at[idx, "pullback_to_ma20_pct"] = 4 if is_target else 12
            enriched.at[idx, "volatility_20d_pct"] = 25 if is_target else 60
            enriched.at[idx, "max_drawdown_20d_pct"] = -5 if is_target else -18
            enriched.at[idx, "atr_20_pct"] = 3 if is_target else 9
            enriched.at[idx, "daily_quality_score"] = 100 if is_target else 70
            enriched.at[idx, "daily_quality_flags"] = "" if is_target else "fallback_errors"
            enriched.at[idx, "daily_source"] = "tencent"
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
    assert result.universe_audit["counts_monotonic"] is True
    assert result.universe_audit["candidate_codes_unique"] is True
    assert result.universe_audit["daily_coverage_complete"] is True
    assert result.universe_audit["status"] == "ok"


def _main_wave_snapshot(count: int = 4000) -> pd.DataFrame:
    frame = pd.DataFrame({
        "code": [f"{index:06d}" for index in range(1, count + 1)],
        "name": [f"样本{index}" for index in range(1, count + 1)],
        "price": [10.0] * count,
        "change_pct": [0.0] * count,
        "amount": [100_000_000.0] * count,
        "turnover_rate": [1.0] * count,
        "volume_ratio": [1.0] * count,
        "pe_ratio": [12.0] * count,
        "pb_ratio": [1.2] * count,
        "total_mv": [10_000_000_000.0] * count,
    })
    frame.attrs["snapshot_source"] = "test"
    return frame


def _main_wave_config(*, daily_limit: int = 4000) -> Config:
    return Config(
        llm_api_key="",
        snapshot_source_priority=["test"],
        strategies_dir=Path("strategies"),
        daily_enrich_max_candidates=daily_limit,
        risk_enabled=False,
    )


def test_main_wave_rejects_snapshot_below_full_market_minimum(monkeypatch):
    snapshot = _main_wave_snapshot(3999)
    monkeypatch.setattr(
        "alphasift.pipeline.fetch_snapshot_with_fallback",
        lambda sources, **kwargs: snapshot,
    )

    with pytest.raises(RuntimeError, match="rows=3999, minimum_required=4000"):
        screen(
            "main_wave_v2",
            use_llm=False,
            post_analyzers=[],
            config=_main_wave_config(),
        )


@pytest.mark.parametrize("invalid_code", ["", "ABC"])
def test_main_wave_rejects_empty_or_invalid_cn_security_codes(monkeypatch, invalid_code):
    snapshot = _main_wave_snapshot()
    snapshot.loc[0, "code"] = invalid_code
    monkeypatch.setattr(
        "alphasift.pipeline.fetch_snapshot_with_fallback",
        lambda sources, **kwargs: snapshot,
    )

    with pytest.raises(RuntimeError, match="invalid_rows=1"):
        screen(
            "main_wave_v2",
            use_llm=False,
            post_analyzers=[],
            config=_main_wave_config(),
        )


def test_main_wave_rejects_duplicate_security_codes(monkeypatch):
    snapshot = _main_wave_snapshot()
    snapshot.loc[1, "code"] = snapshot.loc[0, "code"]
    monkeypatch.setattr(
        "alphasift.pipeline.fetch_snapshot_with_fallback",
        lambda sources, **kwargs: snapshot,
    )

    with pytest.raises(RuntimeError, match="duplicate_rows=1"):
        screen(
            "main_wave_v2",
            use_llm=False,
            post_analyzers=[],
            config=_main_wave_config(),
        )


def test_main_wave_strategy_daily_limit_overrides_global_default(monkeypatch):
    snapshot = _main_wave_snapshot()
    captured: dict[str, int] = {}

    def fake_enrich(frame, **kwargs):
        captured["max_rows"] = kwargs["max_rows"]
        enriched = frame.copy()
        enriched.attrs["daily_success_count"] = len(enriched)
        return enriched

    def fake_score(frame, _screening):
        scored = frame.copy()
        scored["screen_score"] = 50.0
        return scored

    monkeypatch.setattr(
        "alphasift.pipeline.fetch_snapshot_with_fallback",
        lambda sources, **kwargs: snapshot,
    )
    monkeypatch.setattr("alphasift.pipeline.enrich_daily_features", fake_enrich)
    monkeypatch.setattr("alphasift.pipeline.apply_hard_filters", lambda frame, _filters: frame)
    monkeypatch.setattr("alphasift.pipeline.hard_filter_rejection_summary", lambda *args, **kwargs: [])
    monkeypatch.setattr("alphasift.pipeline.compute_screen_scores", fake_score)

    result = screen(
        "main_wave_v2",
        max_output=1,
        use_llm=False,
        collect_llm_candidate_context=False,
        post_analyzers=[],
        config=_main_wave_config(daily_limit=100),
    )

    assert captured["max_rows"] == 4000
    assert result.daily_enrich_count == 4000
    assert result.universe_audit["daily_coverage_complete"] is True


def test_main_wave_explicit_low_daily_limit_still_fails_closed(monkeypatch):
    snapshot = _main_wave_snapshot()
    monkeypatch.setattr(
        "alphasift.pipeline.fetch_snapshot_with_fallback",
        lambda sources, **kwargs: snapshot,
    )

    with pytest.raises(RuntimeError, match="configured limit is too low"):
        screen(
            "main_wave_v2",
            use_llm=False,
            daily_enrich_max_candidates=100,
            post_analyzers=[],
            config=_main_wave_config(daily_limit=100),
        )


def test_main_wave_rejects_incomplete_daily_coverage(monkeypatch):
    snapshot = _main_wave_snapshot()

    def fake_enrich(frame, **kwargs):
        enriched = frame.copy()
        enriched.attrs["daily_success_count"] = len(enriched) - 1
        return enriched

    monkeypatch.setattr(
        "alphasift.pipeline.fetch_snapshot_with_fallback",
        lambda sources, **kwargs: snapshot,
    )
    monkeypatch.setattr("alphasift.pipeline.enrich_daily_features", fake_enrich)

    with pytest.raises(RuntimeError, match="succeeded=3999, target=4000"):
        screen(
            "main_wave_v2",
            use_llm=False,
            post_analyzers=[],
            config=_main_wave_config(),
        )


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
