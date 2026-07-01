# -*- coding: utf-8 -*-
"""Saved-run history summaries for UI and agent integrations."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from alphasift.store import list_saved_runs


def build_strategy_run_summary(
    *,
    data_dir: Path,
    limit: int = 100,
    strategy: str | None = None,
) -> dict[str, object]:
    """Summarize saved runs by strategy without loading full run payloads."""
    runs = list_saved_runs(data_dir=data_dir, limit=limit, strategy=strategy)
    strategy_rows = [_strategy_summary(item) for item in _group_runs_by_strategy(runs).values()]
    strategy_rows.sort(
        key=lambda item: (
            str(item.get("latest_created_at") or ""),
            str(item.get("strategy") or ""),
        ),
        reverse=True,
    )
    return {
        "schema_version": 1,
        "run_count": len(runs),
        "strategy_count": len(strategy_rows),
        "limit": int(limit),
        "strategy_filter": strategy or "",
        "summary": _run_history_summary(runs),
        "strategies": strategy_rows,
    }


def _group_runs_by_strategy(runs: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    groups: dict[str, list[dict[str, object]]] = {}
    for item in runs:
        strategy_name = str(item.get("strategy") or "unknown")
        groups.setdefault(strategy_name, []).append(item)
    return groups


def _strategy_summary(runs: list[dict[str, object]]) -> dict[str, object]:
    ordered = sorted(runs, key=_run_sort_key, reverse=True)
    latest = ordered[0] if ordered else {}
    llm_values = [
        float(item["llm_coverage"])
        for item in ordered
        if isinstance(item.get("llm_coverage"), (int, float))
    ]
    return {
        "strategy": str(latest.get("strategy") or "unknown"),
        "strategy_category": str(latest.get("strategy_category") or ""),
        "run_count": len(ordered),
        "latest_run_id": str(latest.get("run_id") or ""),
        "latest_created_at": str(latest.get("created_at") or ""),
        "latest_report_path": str(latest.get("report_path") or ""),
        "latest_snapshot_source": str(latest.get("snapshot_source") or ""),
        "total_picks": sum(_int_value(item.get("picks")) for item in ordered),
        "average_picks": _average(_int_value(item.get("picks")) for item in ordered),
        "snapshot_sources": _unique_values(item.get("snapshot_source") for item in ordered),
        "runs_with_source_errors": sum(1 for item in ordered if _int_value(item.get("source_error_count")) > 0),
        "source_error_count": sum(_int_value(item.get("source_error_count")) for item in ordered),
        "source_error_samples": _sample_values(ordered, "source_errors"),
        "runs_with_degradation": sum(1 for item in ordered if _int_value(item.get("degradation_count")) > 0),
        "degradation_count": sum(_int_value(item.get("degradation_count")) for item in ordered),
        "degradation_samples": _sample_values(ordered, "degradation"),
        "llm_ranked_runs": sum(1 for item in ordered if bool(item.get("llm_ranked"))),
        "average_llm_coverage": _average(llm_values),
        "daily_enriched_runs": sum(1 for item in ordered if bool(item.get("daily_enriched"))),
        "daily_enrich_count": sum(_int_value(item.get("daily_enrich_count")) for item in ordered),
        "post_analyzers": _unique_post_analyzers(ordered),
        "recent_runs": [_compact_run(item) for item in ordered[:5]],
    }


def _run_history_summary(runs: list[dict[str, object]]) -> dict[str, object]:
    ordered = sorted(runs, key=_run_sort_key, reverse=True)
    return {
        "runs_with_source_errors": sum(1 for item in runs if _int_value(item.get("source_error_count")) > 0),
        "source_error_samples": _sample_values(ordered, "source_errors"),
        "runs_with_degradation": sum(1 for item in runs if _int_value(item.get("degradation_count")) > 0),
        "degradation_samples": _sample_values(ordered, "degradation"),
        "llm_ranked_runs": sum(1 for item in runs if bool(item.get("llm_ranked"))),
        "daily_enriched_runs": sum(1 for item in runs if bool(item.get("daily_enriched"))),
        "total_picks": sum(_int_value(item.get("picks")) for item in runs),
        "latest_run": _compact_run(ordered[0]) if ordered else {},
    }


def _compact_run(item: dict[str, object]) -> dict[str, object]:
    return {
        "run_id": str(item.get("run_id") or ""),
        "strategy": str(item.get("strategy") or ""),
        "created_at": str(item.get("created_at") or ""),
        "picks": _int_value(item.get("picks")),
        "snapshot_source": str(item.get("snapshot_source") or ""),
        "source_error_count": _int_value(item.get("source_error_count")),
        "source_errors": _sample_list(item.get("source_errors"), limit=3),
        "degradation_count": _int_value(item.get("degradation_count")),
        "degradation": _sample_list(item.get("degradation"), limit=3),
        "report_path": str(item.get("report_path") or ""),
    }


def _unique_post_analyzers(runs: list[dict[str, object]]) -> list[str]:
    values: list[str] = []
    for item in runs:
        raw = item.get("post_analyzers") or []
        if isinstance(raw, list):
            values.extend(str(value) for value in raw if str(value))
    return list(dict.fromkeys(values))


def _unique_values(values) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value or "")))


def _sample_values(
    runs: list[dict[str, object]],
    field: str,
    *,
    limit: int = 5,
) -> list[str]:
    values: list[str] = []
    for item in runs:
        values.extend(_sample_list(item.get(field), limit=limit))
    return list(dict.fromkeys(values))[:limit]


def _sample_list(value: object, *, limit: int) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)][:limit]
    if isinstance(value, str) and value:
        return [item.strip() for item in value.split(",") if item.strip()][:limit]
    return []


def _average(values) -> float | None:
    items = [float(value) for value in values]
    if not items:
        return None
    return round(sum(items) / len(items), 4)


def _int_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _run_sort_key(item: dict[str, object]) -> tuple[datetime, str]:
    return (_parse_created_at(str(item.get("created_at") or "")), str(item.get("run_id") or ""))


def _parse_created_at(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.min
