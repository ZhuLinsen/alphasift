# -*- coding: utf-8 -*-
"""UI/agent overview payload for AlphaSift."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from alphasift.config import Config
from alphasift.doctor import doctor_data_sources
from alphasift.store import list_saved_runs
from alphasift.strategy import list_strategies, match_strategies, strategy_facets_from_infos


def build_overview(
    config: Config,
    *,
    strategy_name: str | None = None,
    runs_limit: int = 5,
    live_data_check: bool = False,
    strategy_match: dict[str, Any] | None = None,
    match_limit: int = 5,
) -> dict[str, Any]:
    """Build one compact payload for dashboards, agents, and notification surfaces."""
    strategies = list_strategies(config.strategies_dir)
    doctor = doctor_data_sources(
        config,
        run_live=live_data_check,
        strategy_name=strategy_name,
        all_strategies=strategy_name is None,
    ).to_dict()
    recent_runs = list_saved_runs(
        data_dir=config.data_dir,
        limit=runs_limit,
        strategy=strategy_name,
    )
    match_kwargs = dict(strategy_match or {})
    strategy_matches = []
    if _has_match_criteria(match_kwargs):
        strategy_matches = match_strategies(
            config.strategies_dir,
            **match_kwargs,
            limit=match_limit,
        )

    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "strategy_count": len(strategies),
            "daily_strategy_count": sum(1 for item in strategies if item.requires_daily_features),
            "data_source_status": doctor.get("status"),
            "strategy_match_count": len(strategy_matches),
            "recent_run_count": len(recent_runs),
            "live_data_check": bool(live_data_check),
            "strategy_filter": strategy_name or "",
        },
        "strategy_groups": _strategy_groups(strategies),
        "strategy_facets": strategy_facets_from_infos(strategies),
        "strategy_matches": strategy_matches,
        "data_sources": {
            "status": doctor.get("status"),
            "config": doctor.get("config", {}),
            "health_summary": doctor.get("health_summary", {}),
            "freshness_summary": doctor.get("freshness_summary", {}),
            "snapshot_quality": (doctor.get("snapshot", {}) or {}).get("quality_summary", {}),
            "strategy_requirements": doctor.get("strategy_requirements", {}),
            "strategy_coverage": doctor.get("strategy_coverage", []),
            "strategy_readiness_summary": doctor.get("strategy_readiness_summary", {}),
            "recommendations": doctor.get("recommendations", []),
        },
        "recent_runs": recent_runs,
        "next_actions": _next_actions(
            doctor=doctor,
            recent_runs=recent_runs,
            strategy_matches=strategy_matches,
            strategy_name=strategy_name,
            live_data_check=live_data_check,
        ),
    }
    return payload


def _has_match_criteria(criteria: dict[str, Any]) -> bool:
    return any(
        bool(criteria.get(key))
        for key in (
            "risk_profile",
            "holding_period",
            "execution_style",
            "market_regime",
            "capital_profile",
            "data_requirements",
            "tags",
            "category",
        )
    ) or criteria.get("daily_required") is not None or bool(criteria.get("strict"))


def _strategy_groups(strategies: list) -> dict[str, list[dict[str, object]]]:
    return {
        "by_category": _group_strategy_names(strategies, lambda item: item.category),
        "by_risk_profile": _group_strategy_names(
            strategies,
            lambda item: str(item.style.get("risk_profile") or "unknown"),
        ),
        "by_holding_period": _group_strategy_names(
            strategies,
            lambda item: str(item.style.get("holding_period") or "unknown"),
        ),
        "by_data_requirement": _group_by_many(strategies, lambda item: item.data_requirements),
    }


def _group_strategy_names(strategies: list, key_fn) -> list[dict[str, object]]:
    groups: dict[str, list[str]] = {}
    for item in strategies:
        key = str(key_fn(item) or "unknown")
        groups.setdefault(key, []).append(item.name)
    return _group_payload(groups)


def _group_by_many(strategies: list, values_fn) -> list[dict[str, object]]:
    groups: dict[str, list[str]] = {}
    for item in strategies:
        values = list(values_fn(item) or []) or ["unknown"]
        for value in values:
            groups.setdefault(str(value), []).append(item.name)
    return _group_payload(groups)


def _group_payload(groups: dict[str, list[str]]) -> list[dict[str, object]]:
    return [
        {"name": name, "count": len(names), "strategies": sorted(names)}
        for name, names in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    ]


def _next_actions(
    *,
    doctor: dict[str, Any],
    recent_runs: list[dict[str, object]],
    strategy_matches: list[dict[str, object]],
    strategy_name: str | None,
    live_data_check: bool,
) -> list[str]:
    actions: list[str] = []
    if not live_data_check:
        actions.append("Run `alphasift overview --live-data-check --explain` before relying on fresh data.")
    actions.extend(str(item) for item in doctor.get("recommendations", []) or [])
    if strategy_matches:
        top = strategy_matches[0]
        actions.append(f"Try `alphasift screen {top.get('name')} --explain` for the top matched strategy.")
    elif strategy_name:
        actions.append(f"Try `alphasift screen {strategy_name} --explain` to validate the focused strategy.")
    if not recent_runs:
        actions.append("Run `alphasift screen <strategy> --save-run` to populate the recent-run panel.")
    return list(dict.fromkeys(actions))


def overview_to_jsonable(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize dataclass-like values if callers extend this payload later."""
    return asdict(payload) if hasattr(payload, "__dataclass_fields__") else payload
