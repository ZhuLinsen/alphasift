# -*- coding: utf-8 -*-
"""UI-ready strategy cards combining catalog, readiness, and run history."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from alphasift.config import Config
from alphasift.doctor import doctor_data_sources
from alphasift.models import StrategyInfo
from alphasift.performance_history import build_strategy_performance_summary
from alphasift.run_history import build_strategy_run_summary
from alphasift.strategy import list_strategies


def build_strategy_cards(
    config: Config,
    *,
    strategy_name: str | None = None,
    runs_limit: int = 100,
    live_data_check: bool = False,
) -> dict[str, Any]:
    """Build strategy cards for dashboards and agents."""
    strategies = _filtered_strategies(
        list_strategies(config.strategies_dir),
        strategy_name=strategy_name,
    )
    doctor = doctor_data_sources(
        config,
        run_live=live_data_check,
        strategy_name=strategy_name,
        all_strategies=strategy_name is None,
    ).to_dict()
    run_history = build_strategy_run_summary(
        data_dir=config.data_dir,
        limit=runs_limit,
        strategy=strategy_name,
    )
    performance = build_strategy_performance_summary(
        data_dir=config.data_dir,
        limit=runs_limit,
        strategy=strategy_name,
    )
    return build_strategy_cards_from_parts(
        strategies,
        strategy_coverage=doctor.get("strategy_coverage", []),
        run_history_summary=run_history,
        performance_summary=performance,
        live_data_check=live_data_check,
        strategy_filter=strategy_name or "",
    )


def build_strategy_cards_from_parts(
    strategies: list[StrategyInfo],
    *,
    strategy_coverage: list[dict[str, Any]] | None = None,
    run_history_summary: dict[str, Any] | None = None,
    performance_summary: dict[str, Any] | None = None,
    live_data_check: bool = False,
    strategy_filter: str = "",
) -> dict[str, Any]:
    """Build cards from data already gathered by overview or the API layer."""
    coverage_by_strategy = {
        str(item.get("strategy") or ""): item
        for item in (strategy_coverage or [])
    }
    history_by_strategy = {
        str(item.get("strategy") or ""): item
        for item in ((run_history_summary or {}).get("strategies", []) or [])
    }
    performance_by_strategy = {
        str(item.get("strategy") or ""): item
        for item in ((performance_summary or {}).get("strategies", []) or [])
    }
    cards = [
        _strategy_card(
            strategy,
            coverage=coverage_by_strategy.get(strategy.name, {}),
            history=history_by_strategy.get(strategy.name, {}),
            performance=performance_by_strategy.get(strategy.name, {}),
            live_data_check=live_data_check,
        )
        for strategy in strategies
    ]
    lanes = _card_lanes(cards)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy_filter": strategy_filter,
        "summary": _cards_summary(cards, lanes=lanes, live_data_check=live_data_check),
        "lanes": lanes,
        "cards": cards,
    }


def _filtered_strategies(
    strategies: list[StrategyInfo],
    *,
    strategy_name: str | None,
) -> list[StrategyInfo]:
    if not strategy_name:
        return strategies
    matches = [item for item in strategies if item.name == strategy_name]
    if not matches:
        raise ValueError(f"Strategy '{strategy_name}' not found")
    return matches


def _strategy_card(
    strategy: StrategyInfo,
    *,
    coverage: dict[str, Any],
    history: dict[str, Any],
    performance: dict[str, Any],
    live_data_check: bool,
) -> dict[str, Any]:
    readiness_status = str(coverage.get("status") or "skipped")
    history_payload = _history_payload(history)
    performance_payload = _performance_payload(performance)
    return {
        "name": strategy.name,
        "display_name": strategy.display_name,
        "description": strategy.description,
        "version": strategy.version,
        "category": strategy.category,
        "tags": list(strategy.tags),
        "style": dict(strategy.style),
        "use_case": _use_case(strategy),
        "data": {
            "requirements": list(strategy.data_requirements),
            "requires_daily_features": bool(strategy.requires_daily_features),
            "required_snapshot_fields": list(strategy.required_snapshot_fields),
            "required_daily_fields": list(strategy.required_daily_fields),
            "active_filters": list(strategy.active_filters),
        },
        "scoring": {
            "factor_weights": dict(strategy.factor_weights),
            "top_factors": _top_factors(strategy.factor_weights),
            "profile_keys": dict(strategy.profile_keys),
        },
        "readiness": {
            "status": readiness_status,
            "live_data_check": bool(live_data_check),
            "snapshot_missing_fields": list(coverage.get("snapshot_missing_fields", []) or []),
            "daily_missing_fields": list(coverage.get("daily_missing_fields", []) or []),
        },
        "history": history_payload,
        "performance": performance_payload,
        "actions": _card_actions(
            strategy,
            readiness_status=readiness_status,
            history=history_payload,
            performance=performance_payload,
        ),
    }


def _cards_summary(
    cards: list[dict[str, Any]],
    *,
    lanes: dict[str, dict[str, Any]],
    live_data_check: bool,
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for card in cards:
        status = str((card.get("readiness") or {}).get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "strategy_count": len(cards),
        "daily_strategy_count": sum(
            1 for card in cards if bool((card.get("data") or {}).get("requires_daily_features"))
        ),
        "snapshot_only_strategy_count": sum(
            1 for card in cards if not bool((card.get("data") or {}).get("requires_daily_features"))
        ),
        "ready_strategy_count": status_counts.get("ok", 0),
        "attention_strategy_count": status_counts.get("degraded", 0) + status_counts.get("failed", 0),
        "unchecked_strategy_count": status_counts.get("skipped", 0),
        "history_seeded_strategy_count": sum(
            1 for card in cards if _int_value((card.get("history") or {}).get("run_count")) > 0
        ),
        "evaluated_strategy_count": sum(
            1 for card in cards if _int_value((card.get("performance") or {}).get("evaluation_count")) > 0
        ),
        "needs_history_count": _lane_count(lanes, "needs_history"),
        "needs_evaluation_count": _lane_count(lanes, "needs_evaluation"),
        "performance_leader_count": _lane_count(lanes, "performance_leaders"),
        "operational_attention_count": _lane_count(lanes, "attention"),
        "status_counts": status_counts,
        "live_data_check": bool(live_data_check),
    }


def _card_lanes(cards: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    needs_history = [
        card for card in cards if _int_value((card.get("history") or {}).get("run_count")) <= 0
    ]
    needs_evaluation = [
        card
        for card in cards
        if _int_value((card.get("history") or {}).get("run_count")) > 0
        and _int_value((card.get("performance") or {}).get("evaluation_count")) <= 0
    ]
    performance_leaders = [
        card
        for card in cards
        if str((card.get("performance") or {}).get("outcome") or "") in {"strong", "positive"}
    ]
    attention = [
        card for card in cards if _needs_attention(card)
    ]
    return {
        "needs_history": _lane_payload(
            sorted(needs_history, key=_card_name),
            reason="no_saved_runs",
        ),
        "needs_evaluation": _lane_payload(
            sorted(needs_evaluation, key=_card_name),
            reason="runs_without_saved_evaluations",
        ),
        "performance_leaders": _lane_payload(
            sorted(performance_leaders, key=_performance_card_sort_key, reverse=True),
            reason="positive_saved_evaluation_outcome",
        ),
        "attention": _lane_payload(
            sorted(attention, key=_attention_card_sort_key, reverse=True),
            reason="readiness_source_or_performance_attention",
        ),
    }


def _lane_payload(cards: list[dict[str, Any]], *, reason: str) -> dict[str, Any]:
    return {
        "reason": reason,
        "count": len(cards),
        "cards": [_compact_card(card) for card in cards[:10]],
    }


def _compact_card(card: dict[str, Any]) -> dict[str, Any]:
    history = card.get("history") or {}
    performance = card.get("performance") or {}
    readiness = card.get("readiness") or {}
    return {
        "name": str(card.get("name") or ""),
        "display_name": str(card.get("display_name") or ""),
        "category": str(card.get("category") or ""),
        "readiness_status": str(readiness.get("status") or "unknown"),
        "run_count": _int_value(history.get("run_count")),
        "evaluation_count": _int_value(performance.get("evaluation_count")),
        "performance_score": performance.get("performance_score"),
        "outcome": str(performance.get("outcome") or "insufficient_data"),
        "latest_run_id": str(history.get("latest_run_id") or performance.get("latest_run_id") or ""),
        "actions": list(card.get("actions", []) or [])[:2],
    }


def _needs_attention(card: dict[str, Any]) -> bool:
    readiness = card.get("readiness") or {}
    history = card.get("history") or {}
    performance = card.get("performance") or {}
    return (
        str(readiness.get("status") or "") in {"degraded", "failed"}
        or _int_value(history.get("source_error_count")) > 0
        or _int_value(history.get("degradation_count")) > 0
        or str(performance.get("outcome") or "") in {"negative", "mixed"}
    )


def _lane_count(lanes: dict[str, dict[str, Any]], lane_name: str) -> int:
    return _int_value((lanes.get(lane_name) or {}).get("count"))


def _card_name(card: dict[str, Any]) -> str:
    return str(card.get("name") or "")


def _performance_card_sort_key(card: dict[str, Any]) -> tuple[float, str]:
    performance = card.get("performance") or {}
    return (_float_value(performance.get("performance_score")), _card_name(card))


def _attention_card_sort_key(card: dict[str, Any]) -> tuple[int, int, float, str]:
    readiness = card.get("readiness") or {}
    history = card.get("history") or {}
    performance = card.get("performance") or {}
    status_rank = {"failed": 4, "degraded": 3, "skipped": 1, "ok": 0}.get(
        str(readiness.get("status") or ""),
        0,
    )
    source_issues = _int_value(history.get("source_error_count")) + _int_value(history.get("degradation_count"))
    performance_rank = {"negative": 3, "mixed": 2}.get(str(performance.get("outcome") or ""), 0)
    return (
        status_rank + performance_rank,
        source_issues,
        _float_value(performance.get("performance_score")),
        _card_name(card),
    )


def _use_case(strategy: StrategyInfo) -> dict[str, object]:
    style = strategy.style or {}
    regimes = list(style.get("market_regime", []) or [])
    risk = str(style.get("risk_profile") or "balanced")
    holding = str(style.get("holding_period") or "watchlist")
    execution = str(style.get("execution_style") or strategy.category)
    data_mode = "daily-confirmed" if strategy.requires_daily_features else "snapshot-only"
    return {
        "risk_profile": risk,
        "holding_period": holding,
        "execution_style": execution,
        "market_regime": regimes,
        "capital_profile": str(style.get("capital_profile") or ""),
        "ui_badge": str(style.get("ui_badge") or ""),
        "summary": (
            f"{risk} {holding} strategy for {','.join(regimes) or 'general'} "
            f"using {execution}; {data_mode}"
        ),
    }


def _history_payload(history: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_count": _int_value(history.get("run_count")),
        "latest_run_id": str(history.get("latest_run_id") or ""),
        "latest_created_at": str(history.get("latest_created_at") or ""),
        "latest_report_path": str(history.get("latest_report_path") or ""),
        "latest_snapshot_source": str(history.get("latest_snapshot_source") or ""),
        "total_picks": _int_value(history.get("total_picks")),
        "average_picks": history.get("average_picks"),
        "source_error_count": _int_value(history.get("source_error_count")),
        "source_error_samples": _string_list(history.get("source_error_samples", []))[:5],
        "degradation_count": _int_value(history.get("degradation_count")),
        "degradation_samples": _string_list(history.get("degradation_samples", []))[:5],
        "llm_ranked_runs": _int_value(history.get("llm_ranked_runs")),
        "daily_enriched_runs": _int_value(history.get("daily_enriched_runs")),
        "recent_runs": list(history.get("recent_runs", []) or [])[:3],
    }


def _performance_payload(performance: dict[str, Any]) -> dict[str, Any]:
    return {
        "evaluation_count": _int_value(performance.get("evaluation_count")),
        "latest_run_id": str(performance.get("latest_run_id") or ""),
        "latest_evaluated_at": str(performance.get("latest_evaluated_at") or ""),
        "latest_elapsed_days": performance.get("latest_elapsed_days"),
        "pick_count": _int_value(performance.get("pick_count")),
        "evaluated_pick_count": _int_value(performance.get("evaluated_pick_count")),
        "missing_count": _int_value(performance.get("missing_count")),
        "average_return_pct": performance.get("average_return_pct"),
        "median_return_pct": performance.get("median_return_pct"),
        "win_rate": performance.get("win_rate"),
        "average_run_return_pct": performance.get("average_run_return_pct"),
        "run_win_rate": performance.get("run_win_rate"),
        "performance_score": performance.get("performance_score"),
        "outcome": str(performance.get("outcome") or "insufficient_data"),
        "next_actions": _string_list(performance.get("next_actions", []))[:3],
        "recent_evaluations": list(performance.get("recent_evaluations", []) or [])[:3],
    }


def _top_factors(weights: dict[str, float]) -> list[dict[str, object]]:
    rows = [
        {"name": str(name), "weight": float(weight)}
        for name, weight in weights.items()
        if float(weight) > 0
    ]
    rows.sort(key=lambda item: (-float(item["weight"]), str(item["name"])))
    return rows[:3]


def _card_actions(
    strategy: StrategyInfo,
    *,
    readiness_status: str,
    history: dict[str, Any],
    performance: dict[str, Any],
) -> list[str]:
    actions: list[str] = []
    if readiness_status == "skipped":
        actions.append(f"Run `alphasift doctor data-sources --strategy {strategy.name} --explain`.")
    elif readiness_status in {"degraded", "failed"}:
        actions.append(f"Review missing fields before screening `{strategy.name}`.")
    if strategy.requires_daily_features:
        actions.append(f"Check daily data quality before running `{strategy.name}`.")
    if _int_value(history.get("run_count")) <= 0:
        actions.append(f"Run `alphasift screen {strategy.name} --save-run` to seed history.")
    elif _int_value(history.get("degradation_count")) > 0:
        actions.append(f"Review latest report for `{strategy.name}` data degradation.")
    if _int_value(performance.get("evaluation_count")) <= 0:
        actions.append(f"Run `alphasift evaluate <run_id> --save` to seed `{strategy.name}` performance.")
    elif str(performance.get("outcome") or "") in {"negative", "mixed"}:
        actions.extend(_string_list(performance.get("next_actions", []))[:1])
    return list(dict.fromkeys(actions))


def _int_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_value(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str) and value:
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def strategy_cards_to_jsonable(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize dataclass-like values if callers extend this payload later."""
    return asdict(payload) if hasattr(payload, "__dataclass_fields__") else payload
