# -*- coding: utf-8 -*-
"""Deterministic V2 main-wave rule scoring from adjusted daily bars."""

from __future__ import annotations

from typing import Any

import pandas as pd


MAIN_WAVE_RAW_MAX_SCORE = 50.0
MAIN_WAVE_NORMALIZED_MAX_SCORE = 100.0

MAIN_WAVE_FACTOR_WEIGHTS = {
    "main_wave_near_low": 0.16,
    "main_wave_volume_contraction": 0.16,
    "main_wave_doji_cluster": 0.08,
    "main_wave_limit_up_test": 0.12,
    "main_wave_upward_gap": 0.12,
    "main_wave_volume_doubling": 0.12,
    "main_wave_bullish_streak": 0.08,
    "main_wave_ma_alignment": 0.16,
}

_ADJUSTED_PRICE_MODES = {"qfq", "hfq", "auto_adjusted", "split_adjusted"}
_UNADJUSTED_PRICE_MODES = {"none", "raw", "unadjusted"}


def normalize_adjustment(value: object) -> str:
    """Normalize source-specific adjustment labels to a stable vocabulary."""
    text = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "forward": "qfq",
        "forward_adjusted": "qfq",
        "pre": "qfq",
        "backward": "hfq",
        "backward_adjusted": "hfq",
        "post": "hfq",
        "auto": "auto_adjusted",
        "adjusted": "auto_adjusted",
        "no": "none",
    }
    return aliases.get(text, text) if text else "unknown"


def is_explicitly_unadjusted(value: object) -> bool:
    return normalize_adjustment(value) in _UNADJUSTED_PRICE_MODES


def compute_main_wave_features(
    df: pd.DataFrame,
    *,
    code: str = "",
    name: str = "",
    adjustment: object = "",
    stale: bool = False,
    as_of: str = "",
) -> dict[str, object]:
    """Score the eight rules shown in the V2 main-wave report.

    The original eight-rule section is worth 50 points. ``main_wave_score`` is
    the same result normalized to 100 for ranking and display. Missing or
    untrusted data makes the whole rule set ineligible instead of being guessed.
    """
    mode = normalize_adjustment(adjustment)
    reasons = _eligibility_reasons(df, adjustment=mode, stale=stale)
    if reasons:
        rules = _unavailable_rules(reasons, as_of=as_of)
        return _result(rules, eligible=False, reasons=reasons)

    recent60 = df.tail(60).copy()
    recent20 = df.tail(20).copy()
    close = pd.to_numeric(df["close"], errors="coerce")
    open_ = pd.to_numeric(df["open"], errors="coerce")

    last_close = float(close.iloc[-1])
    low_60d = float(pd.to_numeric(recent60["low"], errors="coerce").min())
    distance_to_low = (last_close / low_60d - 1.0) * 100.0

    volume_5d = float(pd.to_numeric(df.tail(5)["volume"], errors="coerce").mean())
    volume_60d = float(pd.to_numeric(recent60["volume"], errors="coerce").mean())
    volume_ratio = volume_5d / volume_60d

    doji_count = _doji_count(recent20)
    limit_up_count = _limit_up_count(df, code=code, name=name)
    upward_gap_count = _upward_gap_count(df)
    volume_doubling_count = _volume_doubling_count(df)
    bullish_streak = _trailing_bullish_streak(open_, close)

    ma5 = float(close.tail(5).mean())
    ma10 = float(close.tail(10).mean())
    ma20 = float(close.tail(20).mean())
    ma_aligned = ma5 > ma10 > ma20

    rules = [
        _rule(
            rule_id="near_60d_low",
            name="靠近60日低点",
            stage="建仓区",
            observed=distance_to_low,
            operator="<",
            threshold=20.0,
            unit="pct",
            matched=distance_to_low < 20.0,
            raw_max_score=8.0,
            window=60,
            as_of=as_of,
            evidence={"latest_close": last_close, "low_60d": low_60d},
        ),
        _rule(
            rule_id="volume_contraction",
            name="缩量筑底",
            stage="建仓区",
            observed=volume_ratio,
            operator="<",
            threshold=0.60,
            unit="ratio",
            matched=volume_ratio < 0.60,
            raw_max_score=8.0,
            window=60,
            as_of=as_of,
            evidence={"average_volume_5d": volume_5d, "average_volume_60d": volume_60d},
        ),
        _rule(
            rule_id="doji_cluster",
            name="十字星密集",
            stage="洗盘区",
            observed=doji_count,
            operator=">=",
            threshold=3,
            unit="count",
            matched=doji_count >= 3,
            raw_max_score=4.0,
            window=20,
            as_of=as_of,
            evidence={"definition": "abs(close-open)/(high-low) <= 0.10; zero-range bars excluded"},
        ),
        _rule(
            rule_id="limit_up_test",
            name="横盘涨停试盘",
            stage="试盘区",
            observed=limit_up_count,
            operator=">=",
            threshold=1,
            unit="count",
            matched=limit_up_count >= 1,
            raw_max_score=6.0,
            window=60,
            as_of=as_of,
            evidence={"limit_threshold_pct": _limit_up_threshold_pct(code, name)},
        ),
        _rule(
            rule_id="upward_gap",
            name="向上跳空缺口",
            stage="试盘区",
            observed=upward_gap_count,
            operator=">=",
            threshold=2,
            unit="count",
            matched=upward_gap_count >= 2,
            raw_max_score=6.0,
            window=60,
            as_of=as_of,
            evidence={"definition": "current low > previous high"},
        ),
        _rule(
            rule_id="volume_doubling",
            name="成交倍量",
            stage="启动区",
            observed=volume_doubling_count,
            operator=">=",
            threshold=2,
            unit="count",
            matched=volume_doubling_count >= 2,
            raw_max_score=6.0,
            window=60,
            as_of=as_of,
            evidence={"definition": "current volume >= 2 * previous volume"},
        ),
        _rule(
            rule_id="bullish_streak",
            name="连续阳线",
            stage="启动区",
            observed=bullish_streak,
            operator=">=",
            threshold=2,
            unit="trading_days",
            matched=bullish_streak >= 2,
            raw_max_score=4.0,
            window=None,
            as_of=as_of,
            evidence={"definition": "trailing close > open"},
        ),
        _rule(
            rule_id="ma_alignment",
            name="均线多头排列",
            stage="主升确认",
            observed=ma_aligned,
            operator="is",
            threshold=True,
            unit="boolean",
            matched=ma_aligned,
            raw_max_score=8.0,
            window=20,
            as_of=as_of,
            evidence={"ma5": ma5, "ma10": ma10, "ma20": ma20},
        ),
    ]
    return _result(rules, eligible=True, reasons=[])


def _eligibility_reasons(
    df: pd.DataFrame,
    *,
    adjustment: str,
    stale: bool,
) -> list[str]:
    reasons: list[str] = []
    if adjustment not in _ADJUSTED_PRICE_MODES:
        reasons.append(
            "unadjusted_price_history"
            if adjustment in _UNADJUSTED_PRICE_MODES
            else "adjustment_unknown"
        )
    if stale:
        reasons.append("stale_daily_history")
    if len(df) < 60:
        reasons.append("history_lt60")

    required = ("open", "high", "low", "close", "volume")
    missing = [column for column in required if column not in df.columns]
    if missing:
        reasons.append("missing_columns:" + ",".join(missing))
        return reasons

    recent = df.tail(60)
    numeric = recent.loc[:, required].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        reasons.append("incomplete_ohlcv_60d")
    prices = numeric.loc[:, ("open", "high", "low", "close")]
    if (prices <= 0).any().any():
        reasons.append("non_positive_price_60d")
    invalid_ohlc = (
        (numeric["high"] < numeric["low"])
        | (numeric["high"] < numeric["open"])
        | (numeric["high"] < numeric["close"])
        | (numeric["low"] > numeric["open"])
        | (numeric["low"] > numeric["close"])
    )
    if invalid_ohlc.fillna(False).any():
        reasons.append("invalid_ohlc_60d")
    if (numeric["volume"] < 0).any():
        reasons.append("negative_volume_60d")
    if float(numeric["volume"].mean()) <= 0:
        reasons.append("zero_average_volume_60d")
    if "date" in df.columns and df.tail(60)["date"].astype(str).duplicated().any():
        reasons.append("duplicate_trade_dates_60d")
    return list(dict.fromkeys(reasons))


def _doji_count(df: pd.DataFrame) -> int:
    body = (pd.to_numeric(df["close"], errors="coerce") - pd.to_numeric(df["open"], errors="coerce")).abs()
    span = pd.to_numeric(df["high"], errors="coerce") - pd.to_numeric(df["low"], errors="coerce")
    ratio = body / span.where(span > 0)
    return int((ratio <= 0.10).fillna(False).sum())


def _limit_up_count(df: pd.DataFrame, *, code: str, name: str) -> int:
    close = pd.to_numeric(df["close"], errors="coerce")
    changes = close.pct_change(fill_method=None) * 100.0
    return int((changes.tail(60) >= _limit_up_threshold_pct(code, name)).fillna(False).sum())


def _limit_up_threshold_pct(code: str, name: str) -> float:
    normalized = "".join(character for character in str(code) if character.isdigit()).zfill(6)[-6:]
    upper_name = str(name or "").upper()
    if "ST" in upper_name:
        return 4.5
    if normalized.startswith(("300", "301", "688", "689")):
        return 19.5
    if normalized.startswith(("4", "8", "920")):
        return 29.5
    return 9.5


def _upward_gap_count(df: pd.DataFrame) -> int:
    low = pd.to_numeric(df["low"], errors="coerce")
    previous_high = pd.to_numeric(df["high"], errors="coerce").shift(1)
    return int((low > previous_high).tail(60).fillna(False).sum())


def _volume_doubling_count(df: pd.DataFrame) -> int:
    volume = pd.to_numeric(df["volume"], errors="coerce")
    previous = volume.shift(1)
    doubled = (previous > 0) & (volume >= previous * 2.0)
    return int(doubled.tail(60).fillna(False).sum())


def _trailing_bullish_streak(open_: pd.Series, close: pd.Series) -> int:
    count = 0
    for is_bullish in (close > open_).iloc[::-1]:
        if not bool(is_bullish):
            break
        count += 1
    return count


def _rule(
    *,
    rule_id: str,
    name: str,
    stage: str,
    observed: Any,
    operator: str,
    threshold: Any,
    unit: str,
    matched: bool,
    raw_max_score: float,
    window: int | None,
    as_of: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "name": name,
        "stage": stage,
        "available": True,
        "matched": bool(matched),
        "observed": _round_value(observed),
        "operator": operator,
        "threshold": threshold,
        "unit": unit,
        "window_trading_days": window,
        "raw_score": raw_max_score if matched else 0.0,
        "raw_max_score": raw_max_score,
        "normalized_score": raw_max_score * 2.0 if matched else 0.0,
        "normalized_max_score": raw_max_score * 2.0,
        "as_of": as_of,
        "evidence": {key: _round_value(value) for key, value in evidence.items()},
        "unavailable_reasons": [],
    }


def _unavailable_rules(reasons: list[str], *, as_of: str) -> list[dict[str, Any]]:
    definitions = [
        ("near_60d_low", "靠近60日低点", "建仓区", 8.0, 60),
        ("volume_contraction", "缩量筑底", "建仓区", 8.0, 60),
        ("doji_cluster", "十字星密集", "洗盘区", 4.0, 20),
        ("limit_up_test", "横盘涨停试盘", "试盘区", 6.0, 60),
        ("upward_gap", "向上跳空缺口", "试盘区", 6.0, 60),
        ("volume_doubling", "成交倍量", "启动区", 6.0, 60),
        ("bullish_streak", "连续阳线", "启动区", 4.0, None),
        ("ma_alignment", "均线多头排列", "主升确认", 8.0, 20),
    ]
    return [
        {
            "id": rule_id,
            "name": name,
            "stage": stage,
            "available": False,
            "matched": False,
            "observed": None,
            "operator": "",
            "threshold": None,
            "unit": "",
            "window_trading_days": window,
            "raw_score": 0.0,
            "raw_max_score": raw_max_score,
            "normalized_score": 0.0,
            "normalized_max_score": raw_max_score * 2.0,
            "as_of": as_of,
            "evidence": {},
            "unavailable_reasons": list(reasons),
        }
        for rule_id, name, stage, raw_max_score, window in definitions
    ]


def _result(
    rules: list[dict[str, Any]],
    *,
    eligible: bool,
    reasons: list[str],
) -> dict[str, object]:
    raw_score = sum(float(rule["raw_score"]) for rule in rules)
    normalized_score = raw_score * 2.0
    factor_by_rule = {
        "near_60d_low": "main_wave_near_low_score",
        "volume_contraction": "main_wave_volume_contraction_score",
        "doji_cluster": "main_wave_doji_cluster_score",
        "limit_up_test": "main_wave_limit_up_test_score",
        "upward_gap": "main_wave_upward_gap_score",
        "volume_doubling": "main_wave_volume_doubling_score",
        "bullish_streak": "main_wave_bullish_streak_score",
        "ma_alignment": "main_wave_ma_alignment_score",
    }
    result: dict[str, object] = {
        "main_wave_eligible": eligible,
        "main_wave_ineligible_reasons": ";".join(reasons),
        "main_wave_raw_score": round(raw_score, 4),
        "main_wave_raw_max_score": MAIN_WAVE_RAW_MAX_SCORE,
        "main_wave_score": round(normalized_score, 4),
        "main_wave_max_score": MAIN_WAVE_NORMALIZED_MAX_SCORE,
        "main_wave_hit_count": sum(1 for rule in rules if rule["matched"]),
        "main_wave_rules": rules,
    }
    for rule in rules:
        result[factor_by_rule[str(rule["id"])]] = 100.0 if rule["matched"] else 0.0
    return result


def _round_value(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 4)
    return value
