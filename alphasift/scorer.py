# -*- coding: utf-8 -*-
"""screen_score calculation."""

import re

import pandas as pd

from alphasift.jsonutil import finite_float
from alphasift.models import ScreeningConfig

_FACTOR_COLUMNS = {
    "value": "factor_value_score",
    "liquidity": "factor_liquidity_score",
    "momentum": "factor_momentum_score",
    "reversal": "factor_reversal_score",
    "activity": "factor_activity_score",
    "stability": "factor_stability_score",
    "size": "factor_size_score",
    "theme_heat": "factor_theme_heat_score",
    "topic_alignment": "factor_topic_alignment_score",
}
_RANK_BLENDABLE_FACTORS = frozenset({"momentum", "reversal", "activity", "stability"})
_DEFAULT_SCORING_PROFILE = {
    "momentum_base": 60.0,
    "momentum_intraday_slope": 5.0,
    "momentum_chase_start_pct": 5.0,
    "momentum_chase_penalty_slope": 10.0,
    "momentum_downside_start_pct": -2.0,
    "momentum_downside_penalty_slope": 3.0,
    "momentum_60d_base": 55.0,
    "momentum_60d_slope": 0.9,
    "momentum_60d_overheat_pct": 45.0,
    "momentum_60d_overheat_penalty_slope": 0.8,
    "momentum_60d_breakdown_pct": -20.0,
    "momentum_60d_breakdown_penalty_slope": 0.7,
    "macd_bullish_bonus": 6.0,
    "macd_bearish_penalty": 8.0,
    "reversal_ideal_change_pct": -3.0,
    "reversal_distance_penalty_slope": 13.0,
    "reversal_collapse_start_pct": -8.0,
    "reversal_collapse_penalty_slope": 10.0,
    "reversal_chase_start_pct": 1.0,
    "reversal_chase_penalty_slope": 8.0,
    "rsi_oversold_bonus": 10.0,
    "rsi_overbought_penalty": 14.0,
    "activity_ideal_volume_ratio": 2.0,
    "activity_volume_ratio_distance_slope": 15.0,
    "activity_high_volume_ratio": 5.0,
    "activity_high_volume_ratio_penalty_slope": 8.0,
    "activity_ideal_turnover_rate": 4.0,
    "activity_turnover_distance_slope": 8.0,
    "activity_high_turnover_rate": 12.0,
    "activity_high_turnover_penalty_slope": 5.0,
    "stability_base": 78.0,
    "stability_change_abs_penalty_slope": 3.0,
    "stability_hot_change_pct": 7.0,
    "stability_hot_change_penalty_slope": 5.0,
    "stability_high_turnover_rate": 10.0,
    "stability_high_turnover_penalty_slope": 2.0,
    "stability_high_volume_ratio": 5.0,
    "stability_high_volume_ratio_penalty_slope": 4.0,
    "stability_invalid_pe_penalty": 18.0,
    "stability_high_volatility_pct": 45.0,
    "stability_high_volatility_penalty_slope": 0.45,
    "stability_max_drawdown_floor_pct": -12.0,
    "stability_drawdown_penalty_slope": 1.2,
    "stability_high_atr_pct": 6.0,
    "stability_high_atr_penalty_slope": 2.0,
    "stability_low_daily_quality_score": 80.0,
    "stability_low_daily_quality_penalty_slope": 0.35,
    "stability_bad_daily_quality_flag_penalty": 8.0,
    "theme_heat_unknown_score": 50.0,
    "theme_heat_change_slope": 6.0,
    "theme_heat_rank_bonus": 10.0,
    "theme_heat_trend_min_observations": 2.0,
    "theme_heat_trend_slope": 0.8,
    "theme_heat_trend_bonus_cap": 10.0,
    "theme_heat_cooling_penalty_slope": 0.8,
    "theme_heat_cooling_penalty_cap": 12.0,
    "theme_heat_persistence_min_score": 60.0,
    "theme_heat_persistence_slope": 0.08,
    "theme_heat_persistence_bonus_cap": 6.0,
    "theme_heat_cooling_score_penalty_slope": 0.6,
    "theme_heat_cooling_score_penalty_cap": 10.0,
    "theme_heat_overheat_score": 88.0,
    "theme_heat_overheat_penalty_slope": 0.5,
    "topic_alignment_unknown_score": 50.0,
    "topic_alignment_match_bonus": 25.0,
    "topic_alignment_heat_weight": 0.25,
    "topic_alignment_unmatched_penalty": 12.0,
    "factor_rank_blend": 0.0,
}


def _effective_rank_blend(raw_blend: object, sample_size: int) -> float:
    """Compute sample-size-tapered rank blend weight in [0.0, 1.0]."""
    val = finite_float(raw_blend)
    if val is None:
        return 0.0
    clamped = min(max(val, 0.0), 1.0)
    if clamped <= 0.0 or sample_size <= 5:
        return 0.0
    if sample_size >= 30:
        return clamped
    return clamped * ((sample_size - 5) / 25.0)


def _blend_factor_rank(series: pd.Series, effective_blend: float) -> pd.Series:
    """Blend a raw continuous factor score with its cross-sectional rank percentile."""
    if effective_blend <= 0.0:
        return series
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.nunique(dropna=True) <= 1:
        return series
    ranked = _rank_score(numeric, lower_is_better=False, na_score=50.0)
    return ((1.0 - effective_blend) * numeric.fillna(50.0) + effective_blend * ranked).clip(0, 100)


def compute_screen_scores(df: pd.DataFrame, config: ScreeningConfig) -> pd.DataFrame:
    """Compute screen_score for each candidate row.

    Adds a 'screen_score' column (0-100). Higher is better.
    """
    result = df.copy()
    factors = _compute_factor_scores(result, config)
    for name, series in factors.items():
        result[_FACTOR_COLUMNS[name]] = series.round(4)

    profile = _scoring_profile(config)
    effective_blend = _effective_rank_blend(profile.get("factor_rank_blend", 0.0), len(result))
    weights = _normalized_factor_weights(config)
    result["screen_score"] = 0.0
    for factor, weight in weights.items():
        if factor in factors:
            component = (
                _blend_factor_rank(factors[factor], effective_blend)
                if factor in _RANK_BLENDABLE_FACTORS and effective_blend > 0.0
                else factors[factor]
            )
            result["screen_score"] += component * weight

    result["screen_score"] = result["screen_score"].clip(0, 100)

    return result


def factor_score_columns() -> dict[str, str]:
    """Return the stable factor-score column mapping used in Pick output."""
    return dict(_FACTOR_COLUMNS)


def _normalized_factor_weights(config: ScreeningConfig) -> dict[str, float]:
    """Use explicit factor weights, or derive a sane legacy default from tech_weight."""
    tech_weight = finite_float(config.tech_weight)
    safe_tech = 0.3 if tech_weight is None else min(max(tech_weight, 0.0), 1.0)
    raw_weights = config.factor_weights or {
        "value": (1.0 - safe_tech) * 0.50,
        "liquidity": (1.0 - safe_tech) * 0.25,
        "stability": (1.0 - safe_tech) * 0.25,
        "momentum": safe_tech * 0.55,
        "activity": safe_tech * 0.45,
    }
    weights: dict[str, float] = {}
    for factor, raw_weight in raw_weights.items():
        if factor not in _FACTOR_COLUMNS:
            continue
        num = finite_float(raw_weight)
        if num is not None:
            weights[factor] = max(num, 0.0)
    total = sum(weights.values())
    if total <= 0:
        return {"value": 0.4, "liquidity": 0.2, "momentum": 0.2, "activity": 0.2}
    return {factor: weight / total for factor, weight in weights.items()}


def _compute_factor_scores(df: pd.DataFrame, config: ScreeningConfig | None = None) -> dict[str, pd.Series]:
    config = config or ScreeningConfig()
    profile = _scoring_profile(config)
    return {
        "value": _compute_value_score(df),
        "liquidity": _compute_liquidity_score(df),
        "momentum": _compute_momentum_score(df, profile),
        "reversal": _compute_reversal_score(df, profile),
        "activity": _compute_activity_score(df, profile),
        "stability": _compute_stability_score(df, profile),
        "size": _compute_size_score(df),
        "theme_heat": _compute_theme_heat_score(df, profile),
        "topic_alignment": _compute_topic_alignment_score(df, profile),
    }


def _scoring_profile(config: ScreeningConfig) -> dict[str, float]:
    profile = dict(_DEFAULT_SCORING_PROFILE)
    for key, value in (config.scoring_profile or {}).items():
        if key not in profile:
            continue
        numeric = finite_float(value)
        if numeric is not None:
            profile[key] = numeric
    return profile


def _compute_snapshot_score(df: pd.DataFrame) -> pd.Series:
    """Score based on snapshot fundamentals (0-100).

    Components:
    - PE ratio: lower is better (for value), normalized
    - PB ratio: lower is better, normalized
    - Turnover rate: moderate is best
    - Amount (liquidity): higher is better, log-scaled
    - Change pct: near zero or moderate positive preferred
    """
    factors = _compute_factor_scores(df)
    return (
        factors["value"] * 0.50
        + factors["liquidity"] * 0.25
        + factors["stability"] * 0.25
    ).clip(0, 100)


def _compute_tech_score(df: pd.DataFrame) -> pd.Series:
    """Score based on technical features (0-100).

    Uses available columns like volume_ratio, change_pct patterns.
    Full tech scoring (MA structure, MACD/RSI) needs daily data,
    which is not in the snapshot — scored conservatively here.
    """
    factors = _compute_factor_scores(df)
    return (factors["momentum"] * 0.55 + factors["activity"] * 0.45).clip(0, 100)


def _compute_value_score(df: pd.DataFrame) -> pd.Series:
    score = pd.Series(50.0, index=df.index)

    if "pe_ratio" in df.columns:
        pe = _numeric_column(df, "pe_ratio")
        pe_score = _rank_score(pe.where((pe > 0) & (pe < 500)), lower_is_better=True, na_score=25)
        score = score * 0.35 + pe_score * 0.65

    if "pb_ratio" in df.columns:
        pb = _numeric_column(df, "pb_ratio")
        pb_score = _rank_score(pb.where((pb > 0) & (pb < 50)), lower_is_better=True, na_score=25)
        score = score * 0.55 + pb_score * 0.45

    return score.clip(0, 100)


def _compute_liquidity_score(df: pd.DataFrame) -> pd.Series:
    if "amount" not in df.columns:
        return pd.Series(50.0, index=df.index)

    import numpy as np

    amount = _numeric_column(df, "amount")
    log_amount = np.log10(amount.clip(lower=1))
    return _rank_score(log_amount.where(amount > 0), lower_is_better=False, na_score=20)


def _compute_momentum_score(df: pd.DataFrame, profile: dict[str, float]) -> pd.Series:
    score = pd.Series(50.0, index=df.index)

    if "change_pct" in df.columns:
        change = _numeric_column(df, "change_pct", default=0.0)
        # Prefer constructive positive moves, but penalize chase-risk near limit-up.
        intraday_score = profile["momentum_base"] + change * profile["momentum_intraday_slope"]
        intraday_score = intraday_score - (
            change - profile["momentum_chase_start_pct"]
        ).clip(lower=0) * profile["momentum_chase_penalty_slope"]
        intraday_score = intraday_score - (
            -change + profile["momentum_downside_start_pct"]
        ).clip(lower=0) * profile["momentum_downside_penalty_slope"]
        score = score * 0.35 + intraday_score.clip(5, 100) * 0.65

    if "change_60d" in df.columns:
        change_60d = _numeric_column(df, "change_60d", default=0.0)
        trend_score = profile["momentum_60d_base"] + change_60d * profile["momentum_60d_slope"]
        trend_score = trend_score - (
            change_60d - profile["momentum_60d_overheat_pct"]
        ).clip(lower=0) * profile["momentum_60d_overheat_penalty_slope"]
        trend_score = trend_score - (
            -change_60d + profile["momentum_60d_breakdown_pct"]
        ).clip(lower=0) * profile["momentum_60d_breakdown_penalty_slope"]
        score = score * 0.60 + trend_score.clip(5, 100) * 0.40

    if "signal_score" in df.columns:
        signal = _numeric_column(df, "signal_score", default=50.0)
        score = score * 0.70 + signal.clip(0, 100) * 0.30

    if "macd_status" in df.columns:
        macd = df["macd_status"].astype(str)
        score = score + macd.map({
            "bullish": profile["macd_bullish_bonus"],
            "bearish": -profile["macd_bearish_penalty"],
        }).fillna(0)

    return score.clip(5, 100)


def _compute_reversal_score(df: pd.DataFrame, profile: dict[str, float]) -> pd.Series:
    if "change_pct" not in df.columns:
        return pd.Series(50.0, index=df.index)

    change = _numeric_column(df, "change_pct", default=0.0)
    # Reversal setups prefer controlled weakness, not collapse.
    score = 100 - (
        change - profile["reversal_ideal_change_pct"]
    ).abs() * profile["reversal_distance_penalty_slope"]
    score = score - (
        -change + profile["reversal_collapse_start_pct"]
    ).clip(lower=0) * profile["reversal_collapse_penalty_slope"]
    score = score - (
        change - profile["reversal_chase_start_pct"]
    ).clip(lower=0) * profile["reversal_chase_penalty_slope"]

    if "rsi_status" in df.columns:
        rsi = df["rsi_status"].astype(str)
        score = score + rsi.map({
            "oversold": profile["rsi_oversold_bonus"],
            "overbought": -profile["rsi_overbought_penalty"],
        }).fillna(0)
    if "change_60d" in df.columns:
        change_60d = _numeric_column(df, "change_60d", default=0.0)
        score = score - (change_60d - 35).clip(lower=0) * 0.5
        score = score - (-change_60d - 35).clip(lower=0) * 0.8
    return score.clip(5, 100)


def _compute_activity_score(df: pd.DataFrame, profile: dict[str, float]) -> pd.Series:
    score = pd.Series(50.0, index=df.index)

    if "volume_ratio" in df.columns:
        volume_ratio = _numeric_column(df, "volume_ratio", default=1.0)
        vr_score = 100 - (
            volume_ratio - profile["activity_ideal_volume_ratio"]
        ).abs() * profile["activity_volume_ratio_distance_slope"]
        vr_score = vr_score - (
            volume_ratio - profile["activity_high_volume_ratio"]
        ).clip(lower=0) * profile["activity_high_volume_ratio_penalty_slope"]
        score = score * 0.45 + vr_score.clip(5, 100) * 0.55

    if "turnover_rate" in df.columns:
        turnover = _numeric_column(df, "turnover_rate", default=0.0)
        turnover_score = 100 - (
            turnover - profile["activity_ideal_turnover_rate"]
        ).abs() * profile["activity_turnover_distance_slope"]
        turnover_score = turnover_score - (
            turnover - profile["activity_high_turnover_rate"]
        ).clip(lower=0) * profile["activity_high_turnover_penalty_slope"]
        turnover_score = turnover_score.where(turnover > 0, 40)
        score = score * 0.55 + turnover_score.clip(5, 100) * 0.45

    return score.clip(0, 100)


def _compute_stability_score(df: pd.DataFrame, profile: dict[str, float]) -> pd.Series:
    score = pd.Series(profile["stability_base"], index=df.index)

    if "change_pct" in df.columns:
        change = _numeric_column(df, "change_pct", default=0.0)
        score -= change.abs().clip(upper=10) * profile["stability_change_abs_penalty_slope"]
        score -= (
            change - profile["stability_hot_change_pct"]
        ).clip(lower=0) * profile["stability_hot_change_penalty_slope"]

    if "turnover_rate" in df.columns:
        turnover = _numeric_column(df, "turnover_rate", default=0.0)
        score -= (
            turnover - profile["stability_high_turnover_rate"]
        ).clip(lower=0) * profile["stability_high_turnover_penalty_slope"]

    if "volume_ratio" in df.columns:
        volume_ratio = _numeric_column(df, "volume_ratio", default=1.0)
        score -= (
            volume_ratio - profile["stability_high_volume_ratio"]
        ).clip(lower=0) * profile["stability_high_volume_ratio_penalty_slope"]

    if "pe_ratio" in df.columns:
        pe = _numeric_column(df, "pe_ratio")
        score = score.where((pe.isna()) | (pe > 0), score - profile["stability_invalid_pe_penalty"])

    if "signal_score" in df.columns:
        signal = _numeric_column(df, "signal_score", default=50.0)
        score = score + (signal - 50) * 0.12

    if "volatility_20d_pct" in df.columns:
        volatility = _numeric_column(df, "volatility_20d_pct")
        score -= (
            volatility - profile["stability_high_volatility_pct"]
        ).clip(lower=0).fillna(0) * profile["stability_high_volatility_penalty_slope"]

    if "max_drawdown_20d_pct" in df.columns:
        drawdown = _numeric_column(df, "max_drawdown_20d_pct")
        score -= (
            profile["stability_max_drawdown_floor_pct"] - drawdown
        ).clip(lower=0).fillna(0) * profile["stability_drawdown_penalty_slope"]

    if "atr_20_pct" in df.columns:
        atr = _numeric_column(df, "atr_20_pct")
        score -= (
            atr - profile["stability_high_atr_pct"]
        ).clip(lower=0).fillna(0) * profile["stability_high_atr_penalty_slope"]

    if "daily_quality_score" in df.columns:
        quality = _numeric_column(df, "daily_quality_score")
        score -= (
            profile["stability_low_daily_quality_score"] - quality
        ).clip(lower=0).fillna(0) * profile["stability_low_daily_quality_penalty_slope"]

    if "daily_quality_flags" in df.columns:
        flags = df["daily_quality_flags"].fillna("").astype(str)
        severe_flags = flags.str.contains("invalid_ohlc|non_positive_price|negative_volume|stale_cache")
        score -= severe_flags.astype(float) * profile["stability_bad_daily_quality_flag_penalty"]

    return score.clip(0, 100)


def _compute_size_score(df: pd.DataFrame) -> pd.Series:
    if "total_mv" not in df.columns:
        return pd.Series(50.0, index=df.index)

    import numpy as np

    mv = _numeric_column(df, "total_mv")
    log_mv = np.log10(mv.clip(lower=1))
    return _rank_score(log_mv.where(mv > 0), lower_is_better=False, na_score=35)


def _compute_theme_heat_score(df: pd.DataFrame, profile: dict[str, float]) -> pd.Series:
    base = pd.Series(profile["theme_heat_unknown_score"], index=df.index)
    if "board_heat_score" in df.columns:
        score = _numeric_column(df, "board_heat_score").fillna(base)
    elif "industry_heat_score" in df.columns or "concept_heat_score" in df.columns:
        industry = _numeric_column(df, "industry_heat_score")
        concept = _numeric_column(df, "concept_heat_score")
        score = pd.concat([industry, concept], axis=1).max(axis=1).fillna(base)
    elif "industry_change_pct" in df.columns:
        change = _numeric_column(df, "industry_change_pct", default=0.0)
        score = base + change * profile["theme_heat_change_slope"]
        if "industry_rank" in df.columns:
            rank = _numeric_column(df, "industry_rank")
            score += (
                (profile["theme_heat_rank_bonus"] - rank.clip(lower=1, upper=10))
                .clip(lower=0)
                .fillna(0)
            )
    else:
        return base.clip(0, 100)

    if "board_heat_trend_score" in df.columns:
        trend = _numeric_column(df, "board_heat_trend_score", default=0.0)
        if "board_heat_observations" in df.columns:
            observations = _numeric_column(df, "board_heat_observations", default=0.0)
        else:
            observations = pd.Series(profile["theme_heat_trend_min_observations"], index=df.index)
        trend_is_reliable = observations >= profile["theme_heat_trend_min_observations"]
        trend_bonus = (trend.clip(lower=0) * profile["theme_heat_trend_slope"]).clip(
            upper=profile["theme_heat_trend_bonus_cap"]
        )
        cooling_penalty = ((-trend).clip(lower=0) * profile["theme_heat_cooling_penalty_slope"]).clip(
            upper=profile["theme_heat_cooling_penalty_cap"]
        )
        score = score + (trend_bonus - cooling_penalty).where(trend_is_reliable, 0)

    if "board_heat_persistence_score" in df.columns:
        persistence = _numeric_column(df, "board_heat_persistence_score", default=0.0)
        persistence_bonus = (
            (persistence - profile["theme_heat_persistence_min_score"]).clip(lower=0)
            * profile["theme_heat_persistence_slope"]
        ).clip(upper=profile["theme_heat_persistence_bonus_cap"])
        score = score + persistence_bonus

    if "board_heat_cooling_score" in df.columns:
        cooling = _numeric_column(df, "board_heat_cooling_score", default=0.0)
        cooling_penalty = (cooling * profile["theme_heat_cooling_score_penalty_slope"]).clip(
            upper=profile["theme_heat_cooling_score_penalty_cap"]
        )
        score = score - cooling_penalty

    overheat = (score - profile["theme_heat_overheat_score"]).clip(lower=0)
    score = score - overheat * profile["theme_heat_overheat_penalty_slope"]
    return score.clip(0, 100)


def _compute_topic_alignment_score(df: pd.DataFrame, profile: dict[str, float]) -> pd.Series:
    """Score whether industry/concept labels align with hotspot route summaries."""
    base = pd.Series(profile["topic_alignment_unknown_score"], index=df.index)
    if not {"industry", "concepts", "board_heat_summary"} & set(df.columns):
        return base

    scores = []
    for _, row in df.iterrows():
        candidate_topics = _topic_tokens(row.get("industry")) | _topic_tokens(row.get("concepts"))
        route_topics = _topic_tokens(row.get("board_heat_summary"))
        if not candidate_topics or not route_topics:
            scores.append(float(profile["topic_alignment_unknown_score"]))
            continue
        overlap = candidate_topics & route_topics
        score = float(profile["topic_alignment_unknown_score"])
        if overlap:
            score += profile["topic_alignment_match_bonus"]
            heat = finite_float(row.get("board_heat_score"))
            if heat is not None:
                score += max(heat - 50.0, 0.0) * profile["topic_alignment_heat_weight"]
        else:
            score -= profile["topic_alignment_unmatched_penalty"]
        scores.append(score)
    return pd.Series(scores, index=df.index).clip(0, 100)


def explain_topic_alignment(
    industry: object,
    concepts: object,
    board_heat_summary: object,
) -> dict[str, object]:
    """Return deterministic topic alignment metadata for one candidate."""
    ind_tokens = _topic_tokens(industry)
    con_tokens = _topic_tokens(concepts)
    cand_tokens = ind_tokens | con_tokens
    route_tokens = _topic_tokens(board_heat_summary)
    if not cand_tokens or not route_tokens:
        return {
            "status": "unassessed",
            "role": "none" if cand_tokens else "",
            "reason": "缺少题材或热点路线标签，无法评估对齐",
            "matched_topics": [],
            "unmatched_topics": sorted(route_tokens),
        }
    matched = sorted(cand_tokens & route_tokens)
    unmatched = sorted(route_tokens - cand_tokens)
    if matched:
        direct_ind = bool(ind_tokens & route_tokens)
        role = "direct_industry" if direct_ind else "concept_match"
        reason = f"{'直接行业' if direct_ind else '概念题材'}命中热点路线: {', '.join(matched[:4])}"
        return {
            "status": "aligned",
            "role": role,
            "reason": reason,
            "matched_topics": matched,
            "unmatched_topics": unmatched,
        }
    return {
        "status": "unmatched",
        "role": "none",
        "reason": f"候选标签({', '.join(sorted(cand_tokens)[:3])})未命中当前热点({', '.join(unmatched[:3])})",
        "matched_topics": [],
        "unmatched_topics": unmatched,
    }


def _topic_tokens(value: object) -> set[str]:
    if value is None:
        return set()
    try:
        if bool(pd.isna(value)):
            return set()
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "<na>"}:
        return set()
    tokens = set()
    for part in re.split(r"[|,，;；/\n、]+", text):
        raw = " ".join(part.split()).strip()
        if not raw:
            continue
        token = raw.split(":", 1)[0].strip()
        if token and token.lower() not in {"rank", "nan", "none", "<na>"}:
            tokens.add(token)
    return tokens


def _numeric_column(df: pd.DataFrame, column: str, *, default: float | None = None) -> pd.Series:
    if column not in df.columns:
        fill = float("nan") if default is None else default
        return pd.Series(fill, index=df.index, dtype="float64")
    numeric = pd.to_numeric(df[column], errors="coerce").astype("float64")
    cleaned = numeric.replace([float("inf"), float("-inf")], float("nan"))
    return cleaned if default is None else cleaned.fillna(default)


def _rank_score(
    series: pd.Series,
    *,
    lower_is_better: bool,
    na_score: float = 50.0,
) -> pd.Series:
    safe_na = finite_float(na_score)
    fill_val = 50.0 if safe_na is None else safe_na
    numeric = pd.to_numeric(series, errors="coerce").astype("float64").replace(
        [float("inf"), float("-inf")], float("nan")
    )
    if numeric.notna().sum() == 0:
        return pd.Series(fill_val, index=series.index)

    ranks = numeric.rank(
        ascending=not lower_is_better,
        na_option="keep",
        pct=True,
    ) * 100
    return ranks.fillna(fill_val).clip(0, 100)
