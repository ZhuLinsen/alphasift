# -*- coding: utf-8 -*-
"""UI/agent overview payload for AlphaSift."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from alphasift.config import Config
from alphasift.doctor import doctor_data_sources
from alphasift.jsonutil import safe_int
from alphasift.normalize import safe_text
from alphasift.performance_history import build_strategy_performance_summary
from alphasift.run_history import build_strategy_run_summary
from alphasift.source_history import build_data_source_history
from alphasift.store import list_saved_runs
from alphasift.strategy import list_strategies, match_strategies, strategy_facets_from_infos
from alphasift.strategy_cards import build_strategy_cards_from_parts


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
    runs_limit_val = max(safe_int(runs_limit, default=5), 0)
    history_limit = max(runs_limit_val, 20)
    match_limit_val = max(safe_int(match_limit, default=5), 1)
    strategies = list_strategies(config.strategies_dir)
    doctor = doctor_data_sources(
        config,
        run_live=live_data_check,
        strategy_name=strategy_name,
        all_strategies=strategy_name is None,
    ).to_dict()
    recent_runs = list_saved_runs(
        data_dir=config.data_dir,
        limit=runs_limit_val,
        strategy=strategy_name,
    )
    run_history = build_strategy_run_summary(
        data_dir=config.data_dir,
        limit=history_limit,
        strategy=strategy_name,
    )
    source_history = build_data_source_history(
        data_dir=config.data_dir,
        limit=history_limit,
        strategy=strategy_name,
    )
    performance = build_strategy_performance_summary(
        data_dir=config.data_dir,
        limit=history_limit,
        strategy=strategy_name,
    )
    card_strategies = [
        item
        for item in strategies
        if not strategy_name or item.name == strategy_name
    ]
    match_kwargs = dict(strategy_match) if isinstance(strategy_match, dict) else {}
    strategy_matches = []
    if _has_match_criteria(match_kwargs):
        strategy_matches = match_strategies(
            config.strategies_dir,
            **match_kwargs,
            limit=match_limit_val,
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
        "strategy_cards": build_strategy_cards_from_parts(
            card_strategies,
            strategy_coverage=doctor.get("strategy_coverage", []),
            run_history_summary=run_history,
            performance_summary=performance,
            live_data_check=live_data_check,
            strategy_filter=strategy_name or "",
        ),
        "strategy_matches": strategy_matches,
        "data_sources": {
            "status": doctor.get("status"),
            "config": doctor.get("config", {}),
            "health_summary": doctor.get("health_summary", {}),
            "freshness_summary": doctor.get("freshness_summary", {}),
            "snapshot_quality": _snapshot_quality(doctor),
            "strategy_requirements": doctor.get("strategy_requirements", {}),
            "strategy_coverage": doctor.get("strategy_coverage", []),
            "strategy_readiness_summary": doctor.get("strategy_readiness_summary", {}),
            "recommendations": _clean_strings(doctor.get("recommendations")),
        },
        "run_history_summary": run_history,
        "data_source_history": source_history,
        "performance_summary": performance,
        "recent_runs": recent_runs,
        "next_actions": _next_actions(
            doctor=doctor,
            recent_runs=recent_runs,
            source_history=source_history,
            performance_summary=performance,
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


def _snapshot_quality(doctor: dict[str, Any]) -> Any:
    snapshot = doctor.get("snapshot")
    return snapshot.get("quality_summary", {}) if isinstance(snapshot, dict) else {}


def _clean_strings(raw: object) -> list[str]:
    if raw is None or isinstance(raw, (bool, dict)):
        return []
    if isinstance(raw, str):
        text = safe_text(raw)
        return [text] if text else []
    if not isinstance(raw, (list, tuple, set)):
        text = safe_text(raw)
        return [text] if text else []
    values: list[str] = []
    for item in raw:
        text = safe_text(item)
        if text:
            values.append(text)
    return values


def _style_field(item: Any, key: str) -> str:
    style = getattr(item, "style", None)
    if not isinstance(style, dict):
        return "unknown"
    return safe_text(style.get(key)) or "unknown"


def _strategy_groups(strategies: list) -> dict[str, list[dict[str, object]]]:
    return {
        "by_category": _group_strategy_names(strategies, lambda item: getattr(item, "category", None)),
        "by_risk_profile": _group_strategy_names(
            strategies,
            lambda item: _style_field(item, "risk_profile"),
        ),
        "by_holding_period": _group_strategy_names(
            strategies,
            lambda item: _style_field(item, "holding_period"),
        ),
        "by_data_requirement": _group_by_many(strategies, lambda item: getattr(item, "data_requirements", None)),
    }


def _group_strategy_names(strategies: list, key_fn) -> list[dict[str, object]]:
    groups: dict[str, list[str]] = {}
    for item in strategies:
        name = safe_text(getattr(item, "name", None))
        if not name:
            continue
        key = safe_text(key_fn(item)) or "unknown"
        groups.setdefault(key, []).append(name)
    return _group_payload(groups)


def _group_by_many(strategies: list, values_fn) -> list[dict[str, object]]:
    groups: dict[str, list[str]] = {}
    for item in strategies:
        name = safe_text(getattr(item, "name", None))
        if not name:
            continue
        values = _clean_strings(values_fn(item)) or ["unknown"]
        for value in values:
            groups.setdefault(value, []).append(name)
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
    source_history: dict[str, object],
    performance_summary: dict[str, object],
    strategy_matches: list[dict[str, object]],
    strategy_name: str | None,
    live_data_check: bool,
) -> list[str]:
    actions: list[str] = []
    if not live_data_check:
        actions.append("Run `alphasift overview --live-data-check --explain` before relying on fresh data.")
    actions.extend(_clean_strings(doctor.get("recommendations")))
    actions.extend(_source_history_actions(source_history))
    actions.extend(_performance_actions(performance_summary, has_recent_runs=bool(recent_runs)))
    top_name = (
        safe_text(strategy_matches[0].get("name"))
        if strategy_matches and isinstance(strategy_matches[0], dict)
        else ""
    )
    focused_name = safe_text(strategy_name)
    if top_name:
        actions.append(f"Try `alphasift screen {top_name} --explain` for the top matched strategy.")
    elif focused_name:
        actions.append(f"Try `alphasift screen {focused_name} --explain` to validate the focused strategy.")
    if not recent_runs:
        actions.append("Run `alphasift screen <strategy> --save-run` to populate the recent-run panel.")
    return list(dict.fromkeys(actions))


def _source_history_actions(source_history: dict[str, object]) -> list[str]:
    if not isinstance(source_history, dict):
        return []
    watchlist = source_history.get("watchlist") or []
    if not isinstance(watchlist, list):
        return []
    actions: list[str] = []
    for item in watchlist[:2]:
        if isinstance(item, dict):
            actions.extend(_clean_strings(item.get("next_actions")))
    return actions


def _performance_actions(performance_summary: dict[str, object], *, has_recent_runs: bool) -> list[str]:
    if not isinstance(performance_summary, dict):
        return []
    if not has_recent_runs and safe_int(performance_summary.get("evaluation_count"), default=0) <= 0:
        return []
    summary = performance_summary.get("summary") or {}
    if not isinstance(summary, dict):
        return []
    return _clean_strings(summary.get("next_actions"))


def overview_to_jsonable(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize dataclass-like values if callers extend this payload later."""
    return asdict(payload) if hasattr(payload, "__dataclass_fields__") else payload
