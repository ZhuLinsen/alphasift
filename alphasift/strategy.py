# -*- coding: utf-8 -*-
"""Strategy YAML loader."""

import hashlib
import logging
from dataclasses import fields
from pathlib import Path

import yaml

from alphasift.models import (
    HardFilterConfig,
    ScreeningConfig,
    Strategy,
    StrategyInfo,
)

logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BUNDLED_STRATEGIES_DIR = Path(__file__).resolve().parent / "strategies"
_TOP_LEVEL_KEYS = {
    "name",
    "display_name",
    "description",
    "version",
    "category",
    "tags",
    "screening",
}
_SCREENING_KEYS = {
    "enabled",
    "market_scope",
    "hard_filters",
    "tech_weight",
    "factor_weights",
    "scoring_profile",
    "risk_profile",
    "portfolio_profile",
    "scorecard_profile",
    "event_profile",
    "ranking_hints",
    "max_output",
}
_HARD_FILTER_KEYS = set(HardFilterConfig.__dataclass_fields__.keys())
_SCORING_PROFILE_KEYS = {
    "momentum_base",
    "momentum_intraday_slope",
    "momentum_chase_start_pct",
    "momentum_chase_penalty_slope",
    "momentum_downside_start_pct",
    "momentum_downside_penalty_slope",
    "momentum_60d_base",
    "momentum_60d_slope",
    "momentum_60d_overheat_pct",
    "momentum_60d_overheat_penalty_slope",
    "momentum_60d_breakdown_pct",
    "momentum_60d_breakdown_penalty_slope",
    "macd_bullish_bonus",
    "macd_bearish_penalty",
    "reversal_ideal_change_pct",
    "reversal_distance_penalty_slope",
    "reversal_collapse_start_pct",
    "reversal_collapse_penalty_slope",
    "reversal_chase_start_pct",
    "reversal_chase_penalty_slope",
    "rsi_oversold_bonus",
    "rsi_overbought_penalty",
    "activity_ideal_volume_ratio",
    "activity_volume_ratio_distance_slope",
    "activity_high_volume_ratio",
    "activity_high_volume_ratio_penalty_slope",
    "activity_ideal_turnover_rate",
    "activity_turnover_distance_slope",
    "activity_high_turnover_rate",
    "activity_high_turnover_penalty_slope",
    "stability_base",
    "stability_change_abs_penalty_slope",
    "stability_hot_change_pct",
    "stability_hot_change_penalty_slope",
    "stability_high_turnover_rate",
    "stability_high_turnover_penalty_slope",
    "stability_high_volume_ratio",
    "stability_high_volume_ratio_penalty_slope",
    "stability_invalid_pe_penalty",
    "stability_high_volatility_pct",
    "stability_high_volatility_penalty_slope",
    "stability_max_drawdown_floor_pct",
    "stability_drawdown_penalty_slope",
    "stability_high_atr_pct",
    "stability_high_atr_penalty_slope",
    "stability_low_daily_quality_score",
    "stability_low_daily_quality_penalty_slope",
    "stability_bad_daily_quality_flag_penalty",
    "theme_heat_unknown_score",
    "theme_heat_change_slope",
    "theme_heat_rank_bonus",
    "theme_heat_trend_min_observations",
    "theme_heat_trend_slope",
    "theme_heat_trend_bonus_cap",
    "theme_heat_cooling_penalty_slope",
    "theme_heat_cooling_penalty_cap",
    "theme_heat_persistence_min_score",
    "theme_heat_persistence_slope",
    "theme_heat_persistence_bonus_cap",
    "theme_heat_cooling_score_penalty_slope",
    "theme_heat_cooling_score_penalty_cap",
    "theme_heat_overheat_score",
    "theme_heat_overheat_penalty_slope",
}
_RISK_PROFILE_KEYS = {
    "chase_change_pct",
    "chase_points",
    "breakdown_change_pct",
    "breakdown_points",
    "abnormal_volume_ratio",
    "abnormal_volume_ratio_points",
    "high_turnover_rate",
    "high_turnover_points",
    "invalid_pe_points",
    "high_pb",
    "high_pb_points",
    "weak_signal_score",
    "weak_signal_points",
    "macd_bearish_points",
    "rsi_overbought_points",
    "low_llm_confidence",
    "low_llm_confidence_points",
    "llm_risk_points",
    "llm_risk_points_cap",
    "deep_risk_points",
    "deep_risk_points_cap",
    "low_daily_quality_score",
    "low_daily_quality_points",
    "bad_daily_quality_flag_points",
    "stale_daily_cache_points",
    "fallback_daily_errors_points",
    "fetch_failed_daily_points",
}
_PORTFOLIO_PROFILE_KEYS = {"max_same_bucket", "concentration_penalty", "buckets"}
_SCORECARD_PROFILE_KEYS = {
    "value_quality_value_min",
    "value_quality_stability_min",
    "value_quality_bonus",
    "capital_confirmed_momentum_min",
    "capital_confirmed_activity_min",
    "capital_confirmed_bonus",
    "controlled_reversal_min",
    "controlled_reversal_bonus",
    "hot_money_activity_min",
    "hot_money_stability_max",
    "hot_money_penalty",
    "volume_spike_ratio",
    "volume_spike_penalty",
    "high_llm_confidence",
    "high_llm_confidence_bonus",
    "low_llm_confidence",
    "low_llm_confidence_penalty",
    "catalyst_bonus",
    "catalyst_bonus_cap",
    "llm_risk_penalty",
    "llm_risk_penalty_cap",
    "score_delta_cap",
}
_EVENT_PROFILE_KEYS = {
    "preferred_event_tags",
    "avoided_event_tags",
    "preferred_announcement_categories",
    "avoided_announcement_categories",
    "source_weights",
    "notes",
}
_STRATEGY_DIR_CACHE: dict[
    Path,
    tuple[tuple[tuple[str, int, int, str], ...], dict[str, Strategy]],
] = {}


def load_strategy(filepath: Path) -> Strategy:
    """Load a screening strategy from a YAML file."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid strategy file: {filepath}")

    _raise_unknown_keys(data, _TOP_LEVEL_KEYS, f"strategy file {filepath.name}")

    screening_data = data.get("screening", {})
    if not isinstance(screening_data, dict):
        raise ValueError(f"Invalid screening section in strategy file: {filepath}")
    _raise_unknown_keys(screening_data, _SCREENING_KEYS, f"screening section of {filepath.name}")

    hf_data = screening_data.get("hard_filters", {})
    if not isinstance(hf_data, dict):
        raise ValueError(f"Invalid hard_filters section in strategy file: {filepath}")
    _raise_unknown_keys(hf_data, _HARD_FILTER_KEYS, f"hard_filters section of {filepath.name}")

    hard_filters = HardFilterConfig(**hf_data)

    screening = ScreeningConfig(
        enabled=screening_data.get("enabled", False),
        market_scope=screening_data.get("market_scope", ["cn"]),
        hard_filters=hard_filters,
        tech_weight=screening_data.get("tech_weight", 0.35),
        factor_weights=screening_data.get("factor_weights", {}),
        scoring_profile=_optional_mapping(
            screening_data, "scoring_profile", filepath, allowed_keys=_SCORING_PROFILE_KEYS
        ),
        risk_profile=_optional_mapping(
            screening_data, "risk_profile", filepath, allowed_keys=_RISK_PROFILE_KEYS
        ),
        portfolio_profile=_optional_mapping(
            screening_data, "portfolio_profile", filepath, allowed_keys=_PORTFOLIO_PROFILE_KEYS
        ),
        scorecard_profile=_optional_mapping(
            screening_data, "scorecard_profile", filepath, allowed_keys=_SCORECARD_PROFILE_KEYS
        ),
        event_profile=_optional_mapping(
            screening_data, "event_profile", filepath, allowed_keys=_EVENT_PROFILE_KEYS
        ),
        ranking_hints=screening_data.get("ranking_hints", ""),
        max_output=screening_data.get("max_output", 5),
    )

    return Strategy(
        name=data.get("name", filepath.stem),
        display_name=data.get("display_name", data.get("name", filepath.stem)),
        description=data.get("description", ""),
        version=str(data.get("version", "1")),
        category=data.get("category", "trend"),
        tags=list(data.get("tags", []) or []),
        screening=screening,
    )


def load_all_strategies(strategies_dir: Path) -> dict[str, Strategy]:
    """Load all strategies from a directory."""
    resolved_dir = strategies_dir.resolve()
    signature = _strategy_dir_signature(resolved_dir)
    cached = _STRATEGY_DIR_CACHE.get(resolved_dir)
    if cached is not None and cached[0] == signature:
        return dict(cached[1])

    _validate_strategy_dir_sync(strategies_dir)
    strategies = {}
    if not strategies_dir.is_dir():
        _STRATEGY_DIR_CACHE[resolved_dir] = (signature, strategies)
        return strategies
    for f in sorted(strategies_dir.glob("*.yaml")):
        try:
            s = load_strategy(f)
            if s.screening.enabled:
                strategies[s.name] = s
        except Exception as e:
            logger.warning("Failed to load strategy %s: %s", f.name, e)
            continue
    _STRATEGY_DIR_CACHE[resolved_dir] = (signature, dict(strategies))
    return dict(strategies)


def _strategy_dir_signature(strategies_dir: Path) -> tuple[tuple[str, int, int, str], ...]:
    if not strategies_dir.is_dir():
        return ()
    signature = []
    for filepath in sorted(strategies_dir.glob("*.yaml")):
        try:
            stat = filepath.stat()
            digest = hashlib.sha256(filepath.read_bytes()).hexdigest()
        except OSError:
            continue
        signature.append((filepath.name, stat.st_mtime_ns, stat.st_size, digest))
    return tuple(signature)


def list_strategies(strategies_dir: Path | None = None) -> list[StrategyInfo]:
    """List available screening strategies."""
    from alphasift.config import Config
    from alphasift.filter import requires_daily_features

    if strategies_dir is None:
        strategies_dir = Config.from_env().strategies_dir

    strategies = load_all_strategies(strategies_dir)
    infos: list[StrategyInfo] = []
    for s in strategies.values():
        daily_required = requires_daily_features(s.screening.hard_filters)
        infos.append(StrategyInfo(
            name=s.name,
            display_name=s.display_name,
            description=s.description,
            version=s.version,
            category=s.category,
            tags=s.tags,
            market_scope=s.screening.market_scope,
            requires_daily_features=daily_required,
            data_requirements=_strategy_data_requirements(s, daily_required=daily_required),
            required_snapshot_fields=_required_snapshot_fields(s.screening.hard_filters),
            required_daily_fields=_required_daily_fields(s.screening.hard_filters),
            active_filters=_active_hard_filters(s.screening.hard_filters),
            factor_weights={key: float(value) for key, value in s.screening.factor_weights.items()},
            profile_keys=_strategy_profile_keys(s.screening),
        ))
    return infos


def _strategy_data_requirements(strategy: Strategy, *, daily_required: bool) -> list[str]:
    requirements = ["snapshot"]
    if daily_required:
        requirements.append("daily_k")
    factors = set(strategy.screening.factor_weights)
    if factors & {"theme_heat", "topic_alignment"}:
        requirements.append("industry_context")
    if strategy.screening.event_profile:
        requirements.append("event_context")
    return requirements


def _active_hard_filters(filters_config: HardFilterConfig) -> list[str]:
    active: list[str] = []
    defaults = HardFilterConfig()
    for item in fields(HardFilterConfig):
        name = item.name
        value = getattr(filters_config, name)
        default = getattr(defaults, name)
        if name == "exclude_st":
            if bool(value):
                active.append(name)
            continue
        if value != default and value is not None and value is not False:
            active.append(name)
    return active


def _required_snapshot_fields(filters_config: HardFilterConfig) -> list[str]:
    fields: list[str] = []
    if filters_config.exclude_st:
        fields.append("name")
    if filters_config.amount_min is not None:
        fields.append("amount")
    if filters_config.price_min is not None or filters_config.price_max is not None:
        fields.append("price")
    if filters_config.market_cap_min is not None or filters_config.market_cap_max is not None:
        fields.append("total_mv")
    if filters_config.pe_ttm_min is not None or filters_config.pe_ttm_max is not None:
        fields.append("pe_ratio")
    if filters_config.pb_min is not None or filters_config.pb_max is not None:
        fields.append("pb_ratio")
    if filters_config.volume_ratio_min is not None:
        fields.append("volume_ratio")
    if filters_config.turnover_rate_min is not None:
        fields.append("turnover_rate")
    if filters_config.change_pct_min is not None or filters_config.change_pct_max is not None:
        fields.append("change_pct")
    return list(dict.fromkeys(fields))


def _required_daily_fields(filters_config: HardFilterConfig) -> list[str]:
    checks = [
        ("change_60d", filters_config.change_60d_min is not None or filters_config.change_60d_max is not None),
        ("ma_bullish", filters_config.require_ma_bullish),
        ("price_above_ma20", filters_config.require_price_above_ma20),
        ("signal_score", filters_config.signal_score_min is not None),
        ("macd_status", bool(filters_config.macd_status_whitelist)),
        ("rsi_status", bool(filters_config.rsi_status_whitelist)),
        (
            "breakout_20d_pct",
            filters_config.breakout_20d_pct_min is not None
            or filters_config.breakout_20d_pct_max is not None,
        ),
        ("range_20d_pct", filters_config.range_20d_pct_max is not None),
        (
            "volume_ratio_20d",
            filters_config.volume_ratio_20d_min is not None
            or filters_config.volume_ratio_20d_max is not None,
        ),
        ("body_pct", filters_config.body_pct_min is not None or filters_config.body_pct_max is not None),
        (
            "pullback_to_ma20_pct",
            filters_config.pullback_to_ma20_pct_min is not None
            or filters_config.pullback_to_ma20_pct_max is not None,
        ),
        (
            "consolidation_days_20d",
            filters_config.consolidation_days_20d_min is not None
            or filters_config.consolidation_days_20d_max is not None,
        ),
        (
            "volatility_20d_pct",
            filters_config.volatility_20d_pct_min is not None
            or filters_config.volatility_20d_pct_max is not None,
        ),
        (
            "max_drawdown_20d_pct",
            filters_config.max_drawdown_20d_pct_min is not None
            or filters_config.max_drawdown_20d_pct_max is not None,
        ),
        ("atr_20_pct", filters_config.atr_20_pct_min is not None or filters_config.atr_20_pct_max is not None),
    ]
    return [field for field, enabled in checks if enabled]


def _strategy_profile_keys(screening: ScreeningConfig) -> dict[str, list[str]]:
    profile_values = {
        "scoring": screening.scoring_profile,
        "risk": screening.risk_profile,
        "portfolio": screening.portfolio_profile,
        "scorecard": screening.scorecard_profile,
        "event": screening.event_profile,
    }
    return {
        name: sorted(value)
        for name, value in profile_values.items()
        if value
    }


def _validate_strategy_dir_sync(strategies_dir: Path) -> None:
    """Fail fast if bundled strategy mirrors drift apart from built-in repo files."""
    resolved = strategies_dir.resolve()
    repo_dir = (_PROJECT_ROOT / "strategies").resolve()
    bundled_dir = _BUNDLED_STRATEGIES_DIR.resolve()
    if resolved != repo_dir or not bundled_dir.is_dir():
        return

    repo_files = {f.name: f for f in repo_dir.glob("*.yaml")}
    bundled_files = {f.name: f for f in bundled_dir.glob("*.yaml")}
    missing_from_repo = bundled_files.keys() - repo_files.keys()
    if missing_from_repo:
        raise RuntimeError(
            "Strategy directories are out of sync: bundled strategies are missing from "
            f"strategies/: {', '.join(sorted(missing_from_repo))}."
        )

    for name, bundled_file in bundled_files.items():
        repo_file = repo_files[name]
        if repo_file.read_bytes() != bundled_files[name].read_bytes():
            raise RuntimeError(
                "Strategy directories are out of sync: "
                f"strategies/{name} does not match alphasift/strategies/{name}."
            )


def _raise_unknown_keys(data: dict, allowed_keys: set[str], context: str) -> None:
    unknown_keys = sorted(set(data.keys()) - allowed_keys)
    if unknown_keys:
        raise ValueError(
            f"Unknown keys in {context}: {', '.join(unknown_keys)}"
        )


def _optional_mapping(
    data: dict,
    key: str,
    filepath: Path,
    *,
    allowed_keys: set[str],
) -> dict:
    value = data.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Invalid {key} section in strategy file: {filepath}")
    _raise_unknown_keys(value, allowed_keys, f"{key} section of {filepath.name}")
    return value
