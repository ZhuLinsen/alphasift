import math

import pandas as pd
import pytest

from alphasift.models import ScreeningConfig
from alphasift.scorer import _effective_rank_blend, compute_screen_scores


def test_value_factor_favors_lower_positive_pe_and_pb():
    df = pd.DataFrame(
        [
            {
                "code": "low",
                "pe_ratio": 5.0,
                "pb_ratio": 0.6,
                "amount": 100_000_000,
                "turnover_rate": 3.0,
                "volume_ratio": 1.2,
                "change_pct": 0.0,
            },
            {
                "code": "high",
                "pe_ratio": 15.0,
                "pb_ratio": 2.0,
                "amount": 100_000_000,
                "turnover_rate": 3.0,
                "volume_ratio": 1.2,
                "change_pct": 0.0,
            },
        ]
    )

    scored = compute_screen_scores(
        df,
        ScreeningConfig(factor_weights={"value": 1.0}),
    ).set_index("code")

    assert scored.loc["low", "screen_score"] > scored.loc["high", "screen_score"]
    assert scored.loc["low", "factor_value_score"] > scored.loc["high", "factor_value_score"]


def test_dynamic_value_weights_narrow_static_deep_value_advantage():
    df = pd.DataFrame([
        {
            "code": "static_deep_value",
            "pe_ratio": 5.0,
            "pb_ratio": 0.5,
            "amount": 80_000_000,
            "turnover_rate": 0.2,
            "volume_ratio": 0.4,
            "change_pct": -4.0,
        },
        {
            "code": "active_value",
            "pe_ratio": 7.0,
            "pb_ratio": 0.7,
            "amount": 200_000_000,
            "turnover_rate": 2.0,
            "volume_ratio": 1.2,
            "change_pct": 1.0,
        },
    ])

    static_scored = compute_screen_scores(
        df,
        ScreeningConfig(factor_weights={"value": 0.55, "liquidity": 0.15, "stability": 0.20, "size": 0.10}),
    ).set_index("code")
    dynamic_scored = compute_screen_scores(
        df,
        ScreeningConfig(
            factor_weights={
                "value": 0.34,
                "stability": 0.20,
                "liquidity": 0.14,
                "momentum": 0.10,
                "activity": 0.10,
                "reversal": 0.06,
                "size": 0.06,
            },
            scoring_profile={
                "momentum_chase_start_pct": 2.5,
                "momentum_chase_penalty_slope": 18.0,
                "activity_ideal_volume_ratio": 1.2,
                "activity_ideal_turnover_rate": 2.0,
            },
        ),
    ).set_index("code")

    static_gap = float(static_scored.loc["static_deep_value", "screen_score"]) - float(
        static_scored.loc["active_value", "screen_score"]
    )
    dynamic_gap = float(dynamic_scored.loc["static_deep_value", "screen_score"]) - float(
        dynamic_scored.loc["active_value", "screen_score"]
    )

    assert float(dynamic_scored.loc["active_value", "factor_momentum_score"]) > float(
        dynamic_scored.loc["static_deep_value", "factor_momentum_score"]
    )
    assert float(dynamic_scored.loc["active_value", "factor_activity_score"]) > float(
        dynamic_scored.loc["static_deep_value", "factor_activity_score"]
    )
    assert dynamic_gap < static_gap


def test_scoring_profile_can_tighten_intraday_chase_penalty():
    df = pd.DataFrame([{"code": "hot", "change_pct": 6.0}])

    default_score = compute_screen_scores(
        df,
        ScreeningConfig(factor_weights={"momentum": 1.0}),
    ).loc[0, "factor_momentum_score"]
    stricter_score = compute_screen_scores(
        df,
        ScreeningConfig(
            factor_weights={"momentum": 1.0},
            scoring_profile={
                "momentum_chase_start_pct": 1.0,
                "momentum_chase_penalty_slope": 40.0,
            },
        ),
    ).loc[0, "factor_momentum_score"]

    assert stricter_score < default_score


def test_theme_heat_factor_uses_board_heat_score_when_available():
    df = pd.DataFrame([
        {"code": "hot", "board_heat_score": 82},
        {"code": "cold", "board_heat_score": 35},
    ])

    scored = compute_screen_scores(
        df,
        ScreeningConfig(factor_weights={"theme_heat": 1.0}),
    ).set_index("code")

    assert scored.loc["hot", "factor_theme_heat_score"] > scored.loc["cold", "factor_theme_heat_score"]
    assert scored.loc["hot", "screen_score"] > scored.loc["cold", "screen_score"]


def test_theme_heat_factor_uses_reliable_trend_and_cooling_signal():
    df = pd.DataFrame([
        {
            "code": "warming",
            "board_heat_score": 60,
            "board_heat_trend_score": 10,
            "board_heat_persistence_score": 100,
            "board_heat_cooling_score": 0,
            "board_heat_observations": 2,
        },
        {
            "code": "cooling",
            "board_heat_score": 60,
            "board_heat_trend_score": -10,
            "board_heat_persistence_score": 40,
            "board_heat_cooling_score": 8,
            "board_heat_observations": 2,
        },
        {
            "code": "thin",
            "board_heat_score": 60,
            "board_heat_trend_score": 10,
            "board_heat_persistence_score": 100,
            "board_heat_cooling_score": 0,
            "board_heat_observations": 1,
        },
    ])

    scored = compute_screen_scores(
        df,
        ScreeningConfig(factor_weights={"theme_heat": 1.0}),
    ).set_index("code")

    assert scored.loc["warming", "factor_theme_heat_score"] > scored.loc["thin", "factor_theme_heat_score"]
    assert scored.loc["thin", "factor_theme_heat_score"] > scored.loc["cooling", "factor_theme_heat_score"]


def test_topic_alignment_factor_matches_candidate_topics_to_hotspot_summary():
    df = pd.DataFrame([
        {
            "code": "aligned",
            "industry": "银行",
            "concepts": "低估值,中特估",
            "board_heat_summary": "银行:+1.20%:rank=3|地产:+0.20%:rank=8",
            "board_heat_score": 82,
        },
        {
            "code": "mismatch",
            "industry": "医药",
            "concepts": "创新药",
            "board_heat_summary": "银行:+1.20%:rank=3|地产:+0.20%:rank=8",
            "board_heat_score": 82,
        },
        {
            "code": "unknown",
            "industry": "",
            "concepts": "",
            "board_heat_summary": "银行:+1.20%:rank=3",
            "board_heat_score": 82,
        },
    ])

    scored = compute_screen_scores(
        df,
        ScreeningConfig(factor_weights={"topic_alignment": 1.0}),
    ).set_index("code")

    assert scored.loc["aligned", "factor_topic_alignment_score"] > scored.loc["unknown", "factor_topic_alignment_score"]
    assert scored.loc["unknown", "factor_topic_alignment_score"] > scored.loc["mismatch", "factor_topic_alignment_score"]
    assert scored.loc["aligned", "screen_score"] > scored.loc["mismatch", "screen_score"]


def test_stability_factor_penalizes_high_daily_volatility_and_deep_drawdown():
    df = pd.DataFrame([
        {"code": "controlled", "change_pct": 0.5, "volatility_20d_pct": 22.0, "max_drawdown_20d_pct": -4.0, "atr_20_pct": 2.5, "daily_quality_score": 100, "daily_quality_flags": ""},
        {"code": "wild", "change_pct": 0.5, "volatility_20d_pct": 75.0, "max_drawdown_20d_pct": -24.0, "atr_20_pct": 9.0, "daily_quality_score": 60, "daily_quality_flags": "invalid_ohlc"},
    ])

    scored = compute_screen_scores(
        df,
        ScreeningConfig(factor_weights={"stability": 1.0}),
    ).set_index("code")

    assert scored.loc["controlled", "factor_stability_score"] > scored.loc["wild", "factor_stability_score"]
    assert scored.loc["controlled", "screen_score"] > scored.loc["wild", "screen_score"]


def test_topic_alignment_handles_pd_na_nullable_strings():
    df = pd.DataFrame([
        {
            "code": "000001",
            "industry": pd.NA,
            "concepts": pd.NA,
            "board_heat_summary": pd.NA,
        }
    ])
    df["industry"] = df["industry"].astype("string")
    scored = compute_screen_scores(
        df,
        ScreeningConfig(factor_weights={"topic_alignment": 1.0}),
    )
    assert float(scored.loc[0, "factor_topic_alignment_score"]) == 50.0


def test_effective_rank_blend_tapers_small_samples_and_sanitizes_inputs():
    assert _effective_rank_blend(1.0, 1) == 0.0
    assert _effective_rank_blend(1.0, 5) == 0.0
    assert _effective_rank_blend(1.0, 6) == pytest.approx(0.04)
    assert _effective_rank_blend(1.0, 17) == pytest.approx(0.48)
    assert _effective_rank_blend(1.0, 30) == 1.0
    assert _effective_rank_blend(1.0, 31) == 1.0
    assert _effective_rank_blend(0.0, 100) == 0.0
    assert _effective_rank_blend(1.5, 50) == 1.0
    assert _effective_rank_blend(-0.5, 50) == 0.0
    assert _effective_rank_blend(True, 50) == 0.0
    assert _effective_rank_blend(float("nan"), 50) == 0.0
    assert _effective_rank_blend(float("inf"), 50) == 0.0


def test_factor_rank_blend_restores_linear_factor_dispersion_while_keeping_raw_factor_columns():
    rows = []
    for i in range(36):
        rows.append({
            "code": f"MEGA_{i:02d}",
            "amount": 5_000_000_000 - i * 10_000_000,
            "change_pct": -2.0 + i * 0.05,
        })
    for i in range(4):
        rows.append({
            "code": f"MOMO_{i:02d}",
            "amount": 600_000_000 + i * 50_000_000,
            "change_pct": 3.0 + i * 0.2,
        })
    df = pd.DataFrame(rows)

    weights = {"momentum": 0.55, "liquidity": 0.45}
    scored_raw = compute_screen_scores(df, ScreeningConfig(factor_weights=weights)).set_index("code")
    scored_blend = compute_screen_scores(
        df,
        ScreeningConfig(
            factor_weights=weights,
            scoring_profile={"factor_rank_blend": 1.0},
        ),
    ).set_index("code")

    assert scored_raw["screen_score"].idxmax().startswith("MEGA_")
    assert scored_blend["screen_score"].idxmax().startswith("MOMO_")
    assert scored_blend["factor_momentum_score"].equals(scored_raw["factor_momentum_score"])
    assert math.isfinite(float(scored_blend["screen_score"].iloc[0]))


def test_factor_rank_blend_preserves_flat_constant_factor_and_small_post_daily_pool():
    flat_df = pd.DataFrame(
        [{"code": f"F_{i:02d}", "amount": 100_000_000 + i * 1_000_000, "change_pct": 1.5} for i in range(40)]
    )
    weights = {"momentum": 0.6, "liquidity": 0.4}
    flat_raw = compute_screen_scores(flat_df, ScreeningConfig(factor_weights=weights))
    flat_blend = compute_screen_scores(
        flat_df,
        ScreeningConfig(factor_weights=weights, scoring_profile={"factor_rank_blend": 1.0}),
    )
    assert flat_blend["screen_score"].equals(flat_raw["screen_score"])

    small_df = pd.DataFrame(
        [{"code": f"S_{i}", "amount": 100_000_000 + i * 1_000_000, "change_pct": float(i - 2)} for i in range(5)]
    )
    small_raw = compute_screen_scores(small_df, ScreeningConfig(factor_weights=weights))
    small_blend = compute_screen_scores(
        small_df,
        ScreeningConfig(factor_weights=weights, scoring_profile={"factor_rank_blend": 1.0}),
    )
    assert small_blend["screen_score"].equals(small_raw["screen_score"])


@pytest.mark.parametrize("factor", ["momentum", "reversal", "activity", "stability"])
@pytest.mark.parametrize("blend,sample_size", [(0.4, 35), (1.0, 15)])
def test_factor_rank_blend_exact_arithmetic_partial_taper_and_ties(factor, blend, sample_size):
    df = pd.DataFrame({
        "change_pct": [(-2.0 + (i % 5) * 1.25) if i not in (3, 7) else 0.5 for i in range(sample_size)],
        "volume_ratio": [0.8 + (i % 6) * 0.4 for i in range(sample_size)],
        "turnover_rate": [1.0 + (i % 7) * 1.1 for i in range(sample_size)],
    })
    raw = compute_screen_scores(df, ScreeningConfig(factor_weights={factor: 1.0}))
    blended = compute_screen_scores(
        df,
        ScreeningConfig(
            factor_weights={factor: 1.0},
            scoring_profile={"factor_rank_blend": blend},
        ),
    )

    effective = blend * min(1.0, max(0.0, (sample_size - 5) / 25.0))
    raw_series = raw["screen_score"]
    expected = ((1.0 - effective) * raw_series + effective * (raw_series.rank(pct=True) * 100.0)).clip(0, 100)

    pd.testing.assert_series_equal(blended["screen_score"], expected, check_names=False)
    pd.testing.assert_series_equal(blended[f"factor_{factor}_score"], raw[f"factor_{factor}_score"])
