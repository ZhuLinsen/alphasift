import pandas as pd
import pytest

from alphasift.filter import (
    SnapshotFieldMissingError,
    apply_hard_filters,
    hard_filter_rejection_summary,
    hard_filter_waterfall,
)
from alphasift.models import HardFilterConfig


def test_apply_hard_filters_fails_when_required_snapshot_field_is_missing():
    df = pd.DataFrame(
        [
            {"name": "示例A", "price": 10.0, "amount": 100_000_000, "pe_ratio": 12.0},
        ]
    )

    with pytest.raises(SnapshotFieldMissingError):
        apply_hard_filters(df, HardFilterConfig(pb_max=2.0))


def test_apply_hard_filters_accepts_empty_frame_without_name_column():
    filtered = apply_hard_filters(pd.DataFrame(), HardFilterConfig())

    assert filtered.empty


def test_apply_hard_filters_drops_rows_with_unverifiable_numeric_values():
    df = pd.DataFrame(
        [
            {"name": "示例A", "price": 10.0, "amount": 100_000_000, "pb_ratio": None},
            {"name": "示例B", "price": 10.0, "amount": 100_000_000, "pb_ratio": 1.5},
        ]
    )

    filtered = apply_hard_filters(df, HardFilterConfig(pb_max=2.0))

    assert filtered["name"].tolist() == ["示例B"]


def test_apply_hard_filters_returns_empty_before_later_missing_fields():
    df = pd.DataFrame(
        [
            {"name": "示例A", "price": 10.0, "amount": 1},
        ]
    )

    filtered = apply_hard_filters(
        df,
        HardFilterConfig(amount_min=100_000_000, pb_max=2.0),
    )

    assert filtered.empty


def test_apply_hard_filters_fails_when_required_daily_features_are_missing():
    df = pd.DataFrame(
        [
            {"name": "示例A", "price": 10.0, "amount": 100_000_000},
        ]
    )

    with pytest.raises(SnapshotFieldMissingError, match="daily feature"):
        apply_hard_filters(df, HardFilterConfig(require_ma_bullish=True))


def test_apply_hard_filters_uses_daily_features_when_present():
    df = pd.DataFrame(
        [
            {"name": "示例A", "price": 10.0, "amount": 100_000_000, "ma_bullish": True, "signal_score": 70},
            {"name": "示例B", "price": 11.0, "amount": 100_000_000, "ma_bullish": False, "signal_score": 80},
        ]
    )

    result = apply_hard_filters(
        df,
        HardFilterConfig(require_ma_bullish=True, signal_score_min=65),
    )

    assert result["name"].tolist() == ["示例A"]


def test_hard_filter_rejection_summary_reports_sequential_counts():
    df = pd.DataFrame([
        {"name": "A", "amount": 200_000_000, "ma_bullish": True, "signal_score": 80},
        {"name": "B", "amount": 20_000_000, "ma_bullish": True, "signal_score": 90},
        {"name": "C", "amount": 210_000_000, "ma_bullish": False, "signal_score": 95},
        {"name": "D", "amount": 220_000_000, "ma_bullish": True, "signal_score": 40},
    ])

    summary = hard_filter_rejection_summary(
        df,
        HardFilterConfig(amount_min=100_000_000, require_ma_bullish=True, signal_score_min=70),
    )

    assert summary == [
        "amount_min removed 1 (4->3)",
        "require_ma_bullish removed 1 (3->2)",
        "signal_score_min removed 1 (2->1)",
    ]


def test_hard_filter_waterfall_reports_samples_and_suggestions():
    df = pd.DataFrame([
        {"code": "000001", "name": "A", "amount": 200_000_000, "signal_score": 80},
        {"code": "000002", "name": "B", "amount": 20_000_000, "signal_score": 90},
        {"code": "000003", "name": "C", "amount": 210_000_000, "signal_score": 40},
    ])

    waterfall = hard_filter_waterfall(
        df,
        HardFilterConfig(amount_min=100_000_000, signal_score_min=95),
    )

    assert waterfall[0]["filter"] == "exclude_st"
    assert waterfall[0]["before"] == 3
    assert waterfall[0]["after"] == 3
    assert waterfall[1] == {
        "filter": "amount_min",
        "before": 3,
        "after": 2,
        "removed": 1,
        "removed_pct": 33.3333,
        "samples": [{"code": "000002", "name": "B", "value": 20_000_000}],
    }
    assert waterfall[2]["filter"] == "signal_score_min"
    assert waterfall[2]["before"] == 2
    assert waterfall[2]["after"] == 0
    assert waterfall[2]["removed"] == 2
    assert "eliminated all remaining candidates" in str(waterfall[2]["suggestion"])


def test_apply_hard_filters_uses_daily_shape_features_when_present():
    df = pd.DataFrame(
        [
            {
                "name": "突破A",
                "price": 10.0,
                "amount": 100_000_000,
                "breakout_20d_pct": 0.8,
                "range_20d_pct": 18,
                "volume_ratio_20d": 1.8,
                "body_pct": 1.2,
                "pullback_to_ma20_pct": 4.0,
                "consolidation_days_20d": 10,
                "volatility_20d_pct": 28.0,
                "max_drawdown_20d_pct": -5.5,
                "atr_20_pct": 3.2,
            },
            {
                "name": "伪突破B",
                "price": 11.0,
                "amount": 100_000_000,
                "breakout_20d_pct": -3.5,
                "range_20d_pct": 42,
                "volume_ratio_20d": 0.8,
                "body_pct": -0.5,
                "pullback_to_ma20_pct": 14.0,
                "consolidation_days_20d": 3,
                "volatility_20d_pct": 62.0,
                "max_drawdown_20d_pct": -18.0,
                "atr_20_pct": 8.5,
            },
        ]
    )

    result = apply_hard_filters(
        df,
        HardFilterConfig(
            breakout_20d_pct_min=-1.0,
            range_20d_pct_max=30,
            volume_ratio_20d_min=1.2,
            body_pct_min=0,
            pullback_to_ma20_pct_max=8,
            consolidation_days_20d_min=8,
            volatility_20d_pct_max=40,
            max_drawdown_20d_pct_min=-10,
            atr_20_pct_max=5,
        ),
    )

    assert result["name"].tolist() == ["突破A"]


def test_apply_hard_filters_matches_one_pass_numeric_and_daily_filters():
    df = pd.DataFrame([
        {
            "name": "保留A",
            "price": 10.0,
            "amount": 200_000_000,
            "pb_ratio": 1.2,
            "change_pct": 2.0,
            "ma_bullish": True,
            "signal_score": 80,
            "macd_status": "bullish",
            "rsi_status": "neutral",
            "breakout_20d_pct": 0.6,
            "range_20d_pct": 20,
            "volume_ratio_20d": 1.5,
            "body_pct": 1.0,
            "pullback_to_ma20_pct": 3.0,
            "consolidation_days_20d": 10,
            "volatility_20d_pct": 25.0,
            "max_drawdown_20d_pct": -4.0,
            "atr_20_pct": 2.8,
        },
        {
            "name": "金额不足B",
            "price": 9.0,
            "amount": 50_000_000,
            "pb_ratio": 1.1,
            "change_pct": 1.0,
            "ma_bullish": True,
            "signal_score": 90,
            "macd_status": "bullish",
            "rsi_status": "neutral",
            "breakout_20d_pct": 0.8,
            "range_20d_pct": 18,
            "volume_ratio_20d": 1.6,
            "body_pct": 0.8,
            "pullback_to_ma20_pct": 2.0,
            "consolidation_days_20d": 12,
            "volatility_20d_pct": 24.0,
            "max_drawdown_20d_pct": -3.0,
            "atr_20_pct": 2.6,
        },
        {
            "name": "日线不符C",
            "price": 11.0,
            "amount": 220_000_000,
            "pb_ratio": 1.3,
            "change_pct": 2.5,
            "ma_bullish": False,
            "signal_score": 85,
            "macd_status": "bullish",
            "rsi_status": "neutral",
            "breakout_20d_pct": 1.0,
            "range_20d_pct": 22,
            "volume_ratio_20d": 1.8,
            "body_pct": 1.4,
            "pullback_to_ma20_pct": 2.5,
            "consolidation_days_20d": 11,
            "volatility_20d_pct": 35.0,
            "max_drawdown_20d_pct": -6.0,
            "atr_20_pct": 3.5,
        },
        {
            "name": "形态不符D",
            "price": 12.0,
            "amount": 230_000_000,
            "pb_ratio": 1.4,
            "change_pct": 2.8,
            "ma_bullish": True,
            "signal_score": 82,
            "macd_status": "bearish",
            "rsi_status": "neutral",
            "breakout_20d_pct": -3.0,
            "range_20d_pct": 35,
            "volume_ratio_20d": 0.9,
            "body_pct": -0.2,
            "pullback_to_ma20_pct": 12.0,
            "consolidation_days_20d": 4,
            "volatility_20d_pct": 70.0,
            "max_drawdown_20d_pct": -20.0,
            "atr_20_pct": 9.0,
        },
    ])
    filters = HardFilterConfig(
        amount_min=100_000_000,
        price_min=8,
        price_max=15,
        pb_max=2,
        change_pct_min=0,
        change_pct_max=5,
        require_ma_bullish=True,
        signal_score_min=75,
        macd_status_whitelist=["bullish"],
        rsi_status_whitelist=["neutral"],
        breakout_20d_pct_min=-1,
        range_20d_pct_max=30,
        volume_ratio_20d_min=1.2,
        body_pct_min=0,
        pullback_to_ma20_pct_max=8,
        consolidation_days_20d_min=8,
        volatility_20d_pct_max=45,
        max_drawdown_20d_pct_min=-12,
        atr_20_pct_max=5,
    )

    result = apply_hard_filters(df, filters)

    expected_mask = (
        (df["amount"] >= 100_000_000)
        & df["price"].between(8, 15)
        & (df["pb_ratio"] <= 2)
        & df["change_pct"].between(0, 5)
        & (df["ma_bullish"] == True)  # noqa: E712
        & (df["signal_score"] >= 75)
        & df["macd_status"].isin(["bullish"])
        & df["rsi_status"].isin(["neutral"])
        & (df["breakout_20d_pct"] >= -1)
        & (df["range_20d_pct"] <= 30)
        & (df["volume_ratio_20d"] >= 1.2)
        & (df["body_pct"] >= 0)
        & (df["pullback_to_ma20_pct"] <= 8)
        & (df["consolidation_days_20d"] >= 8)
        & (df["volatility_20d_pct"] <= 45)
        & (df["max_drawdown_20d_pct"] >= -12)
        & (df["atr_20_pct"] <= 5)
    )
    assert result["name"].tolist() == df.loc[expected_mask, "name"].tolist()


def test_exclude_st_blocks_romanized_st_prefixes_while_preserving_english_names():
    df = pd.DataFrame([
        {"name": "*ST Alpha", "amount": 100_000_000},
        {"name": "S*ST Beta", "amount": 100_000_000},
        {"name": "ST", "amount": 100_000_000},
        {"name": "SST", "amount": 100_000_000},
        {"name": "*ST华泰", "amount": 100_000_000},
        {"name": "ST Engineering", "amount": 100_000_000},
        {"name": "COST", "amount": 100_000_000},
        {"name": "STERIS", "amount": 100_000_000},
        {"name": "FIRST SOLAR", "amount": 100_000_000},
    ])
    filtered = apply_hard_filters(df, HardFilterConfig(exclude_st=True))
    assert filtered["name"].tolist() == ["ST Engineering", "COST", "STERIS", "FIRST SOLAR"]


def test_hard_filter_waterfall_attaches_quantiles_and_tight_threshold_hints():
    from alphasift.filter import hard_filter_waterfall

    df = pd.DataFrame([
        {"name": f"S{i}", "amount": 100_000_000 * (i + 1), "pe_ratio": 10.0 + i * 2.0, "ma_bullish": i % 2 == 0}
        for i in range(10)
    ])
    steps = hard_filter_waterfall(
        df,
        HardFilterConfig(exclude_st=True, amount_min=950_000_000, pe_ttm_max=15.0, require_ma_bullish=True),
        include_quantiles=True,
    )
    amt_step = next(s for s in steps if s["filter"] == "amount_min")
    assert amt_step["threshold"] == 950_000_000
    assert amt_step["removed"] == 9
    assert amt_step["after"] == 1
    assert amt_step["quantiles"]["valid_count"] == 10
    assert amt_step["quantiles"]["p50"] == 550_000_000.0
    assert "p50=" in amt_step["suggestion"]

    pe_step = next(s for s in steps if s["filter"] == "pe_ttm_max")
    assert pe_step["after"] == 0
    assert pe_step["threshold"] == 15.0
    assert "p50=" in pe_step["suggestion"]

    bool_step = next(s for s in steps if s["filter"] == "require_ma_bullish")
    assert "quantiles" not in bool_step

    import json

    inf_df = pd.DataFrame([
        {"name": "A", "amount": 1.0},
        {"name": "B", "amount": float("inf")},
        {"name": "C", "amount": float("-inf")},
        {"name": "D", "amount": 5.0},
    ])
    inf_steps = hard_filter_waterfall(
        inf_df,
        HardFilterConfig(amount_min=10.0),
        include_quantiles=True,
    )
    inf_amt = next(s for s in inf_steps if s["filter"] == "amount_min")
    assert inf_amt["quantiles"]["valid_count"] == 2
    assert inf_amt["quantiles"]["p50"] == 3.0
    json.dumps(inf_steps, allow_nan=False)

    # Object dtype bool + pd.NA columns should NOT produce numeric quantiles
    obj_bool_df = pd.DataFrame([
        {"name": "X1", "amount": 200_000_000, "ma_bullish": True},
        {"name": "X2", "amount": 200_000_000, "ma_bullish": False},
        {"name": "X3", "amount": 200_000_000, "ma_bullish": pd.NA},
    ])
    obj_steps = hard_filter_waterfall(
        obj_bool_df,
        HardFilterConfig(require_ma_bullish=True),
        include_quantiles=True,
    )
    assert "quantiles" not in obj_steps[0]


def test_apply_hard_filters_and_waterfall_reject_inf_and_bool_values():
    df = pd.DataFrame([
        {"name": "NormalPass", "amount": 200.0, "pe_ratio": 12.0},
        {"name": "InfAmount", "amount": float("inf"), "pe_ratio": 12.0},
        {"name": "NegInfPE", "amount": 200.0, "pe_ratio": float("-inf")},
        {"name": "BoolAmount", "amount": True, "pe_ratio": 12.0},
        {"name": "BoolPE", "amount": 200.0, "pe_ratio": False},
    ])

    filtered = apply_hard_filters(
        df,
        HardFilterConfig(amount_min=10.0, pe_ttm_max=20.0),
    )
    assert filtered["name"].tolist() == ["NormalPass"]

    steps = hard_filter_waterfall(
        df,
        HardFilterConfig(amount_min=10.0, pe_ttm_max=20.0),
        include_quantiles=True,
    )
    amt_step = next(s for s in steps if s["filter"] == "amount_min")
    assert amt_step["removed"] == 2
    assert amt_step["after"] == 3
    pe_step = next(s for s in steps if s["filter"] == "pe_ttm_max")
    assert pe_step["removed"] == 2
    assert pe_step["after"] == 1

    bool_col_df = pd.DataFrame([
        {"name": "B1", "amount": True, "pe_ratio": False},
        {"name": "B2", "amount": False, "pe_ratio": True},
    ])
    assert apply_hard_filters(
        bool_col_df,
        HardFilterConfig(amount_min=0.5, pe_ttm_max=5.0),
    ).empty
