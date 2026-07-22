import pandas as pd
import pytest

from alphasift.daily import compute_daily_features
from alphasift.filter import apply_hard_filters
from alphasift.main_wave import MAIN_WAVE_FACTOR_WEIGHTS
from alphasift.models import HardFilterConfig, ScreeningConfig
from alphasift.scorer import compute_screen_scores


def _full_score_history() -> pd.DataFrame:
    periods = 65
    close = [10.0] * periods
    open_ = [9.98] * periods
    high = [10.1] * periods
    low = [9.9] * periods

    close[10] = 11.0
    open_[10] = 10.2
    high[10] = 11.0
    low[10] = 10.2
    close[11] = 10.0
    open_[11] = 10.1
    high[11] = 10.1
    low[11] = 9.9

    close[20] = 10.3
    open_[20] = 10.2
    high[20] = 10.35
    low[20] = 10.2
    close[21] = 10.0
    open_[21] = 10.05
    high[21] = 10.1
    low[21] = 9.9

    for index in range(45, periods):
        value = 10.0 + (index - 44) * 0.07
        close[index] = value
        open_[index] = value - 0.03
        high[index] = value + 0.08
        low[index] = value - 0.08
    for index in (48, 52, 56):
        open_[index] = close[index]

    volume = [1000.0] * periods
    volume[14], volume[15] = 400.0, 900.0
    volume[24], volume[25] = 400.0, 900.0
    volume[-5:] = [400.0] * 5

    frame = pd.DataFrame({
        "date": pd.date_range("2026-03-01", periods=periods).astype(str),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })
    frame.attrs.update({
        "daily_source": "tencent",
        "daily_adjustment": "qfq",
        "daily_as_of": "2026-05-04",
        "daily_fetched_at": "2026-05-04T08:00:00+00:00",
    })
    return frame


def test_main_wave_rules_preserve_original_50_and_normalized_100_scores():
    features = compute_daily_features(
        _full_score_history(),
        code="600001",
        name="示例股份",
    )

    assert features["main_wave_eligible"] is True
    assert features["main_wave_hit_count"] == 8
    assert features["main_wave_raw_score"] == 50.0
    assert features["main_wave_raw_max_score"] == 50.0
    assert features["main_wave_score"] == 100.0
    assert features["main_wave_max_score"] == 100.0
    assert sum(rule["raw_max_score"] for rule in features["main_wave_rules"]) == 50.0
    assert all(rule["available"] for rule in features["main_wave_rules"])
    assert all(rule["matched"] for rule in features["main_wave_rules"])
    assert features["daily_adjustment"] == "qfq"
    assert features["daily_as_of"] == "2026-05-04"


def test_main_wave_screen_score_equals_normalized_eight_rule_score():
    features = compute_daily_features(_full_score_history(), code="600001")
    row = {"code": "600001", **features}

    scored = compute_screen_scores(
        pd.DataFrame([row]),
        ScreeningConfig(factor_weights=MAIN_WAVE_FACTOR_WEIGHTS),
    )

    assert scored.loc[0, "screen_score"] == pytest.approx(features["main_wave_score"])


def test_unadjusted_corporate_action_history_cannot_emit_price_signals():
    history = _full_score_history()
    history.attrs["daily_source"] = "sina"
    history.attrs["daily_adjustment"] = "none"
    history.loc[50:, ["open", "high", "low", "close"]] *= 0.64

    features = compute_daily_features(history, code="603629")

    assert features["main_wave_eligible"] is False
    assert features["main_wave_score"] == 0.0
    assert features["main_wave_ineligible_reasons"] == "unadjusted_price_history"
    assert features["atr_20_pct"] is None
    assert features["breakout_20d_pct"] is None
    assert features["change_60d"] is None
    assert "unadjusted_price_history" in features["daily_quality_flags"]
    assert all(not rule["available"] for rule in features["main_wave_rules"])


def test_main_wave_hard_filter_fails_closed_for_missing_adjustment_metadata():
    history = _full_score_history()
    history.attrs.pop("daily_adjustment")
    features = compute_daily_features(history, code="600001")
    frame = pd.DataFrame([{"name": "示例股份", **features}])

    filtered = apply_hard_filters(
        frame,
        HardFilterConfig(require_main_wave_eligible=True),
    )

    assert features["main_wave_eligible"] is False
    assert features["main_wave_ineligible_reasons"] == "adjustment_unknown"
    assert filtered.empty


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("high", 9.0),
        ("low", 12.0),
    ],
)
def test_main_wave_fails_closed_for_invalid_ohlc(column, value):
    history = _full_score_history()
    history.loc[history.index[-1], column] = value

    features = compute_daily_features(history, code="600001")

    assert features["main_wave_eligible"] is False
    assert features["main_wave_score"] == 0.0
    assert "invalid_ohlc_60d" in features["main_wave_ineligible_reasons"]
    assert "invalid_ohlc" in features["daily_quality_flags"]
    assert all(not rule["available"] for rule in features["main_wave_rules"])


def test_main_wave_does_not_fill_missing_ohlc_before_validation():
    history = _full_score_history().drop(columns=["high"])

    features = compute_daily_features(history, code="600001")

    assert features["main_wave_eligible"] is False
    assert "missing_columns:high" in features["main_wave_ineligible_reasons"]
    assert features["main_wave_score"] == 0.0


def test_main_wave_rejects_nan_ohlc_even_when_legacy_features_can_fill_it():
    history = _full_score_history()
    history.loc[history.index[-1], "high"] = pd.NA

    features = compute_daily_features(history, code="600001")

    assert features["main_wave_eligible"] is False
    assert "incomplete_ohlcv_60d" in features["main_wave_ineligible_reasons"]
    assert features["main_wave_score"] == 0.0


def test_main_wave_factor_weights_match_original_rule_weights():
    assert sum(MAIN_WAVE_FACTOR_WEIGHTS.values()) == pytest.approx(1.0)
    assert MAIN_WAVE_FACTOR_WEIGHTS == {
        "main_wave_near_low": 8 / 50,
        "main_wave_volume_contraction": 8 / 50,
        "main_wave_doji_cluster": 4 / 50,
        "main_wave_limit_up_test": 6 / 50,
        "main_wave_upward_gap": 6 / 50,
        "main_wave_volume_doubling": 6 / 50,
        "main_wave_bullish_streak": 4 / 50,
        "main_wave_ma_alignment": 8 / 50,
    }
