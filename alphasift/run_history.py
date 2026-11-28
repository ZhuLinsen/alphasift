# -*- coding: utf-8 -*-
"""Saved-run history summaries for UI and agent integrations."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from alphasift.jsonutil import finite_float, safe_int
from alphasift.normalize import safe_bool, safe_text
from alphasift.store import list_saved_runs
from alphasift.timeutil import MIN_TIMESTAMP, parse_timestamp


def build_strategy_run_summary(
    *,
    data_dir: Path,
    limit: int = 100,
    strategy: str | None = None,
) -> dict[str, object]:
    """Summarize saved runs by strategy without loading full run payloads."""
    limit_val = max(safe_int(limit, default=0), 0)
    strategy_filter = safe_text(strategy)
    runs = [
        item
        for item in list_saved_runs(
            data_dir=data_dir,
            limit=limit_val,
            strategy=strategy_filter or None,
        )
        if isinstance(item, dict)
    ]
    strategy_rows = [_strategy_summary(item) for item in _group_runs_by_key(runs, "strategy").values()]
    strategy_rows.sort(
        key=lambda item: (
            _parse_created_at(item.get("latest_created_at")),
            safe_text(item.get("strategy")),
        ),
        reverse=True,
    )
    return {
        "schema_version": 1,
        "run_count": len(runs),
        "strategy_count": len(strategy_rows),
        "limit": limit_val,
        "strategy_filter": strategy_filter,
        "summary": _run_history_summary(runs),
        "strategies": strategy_rows,
    }


def _group_runs_by_key(
    runs: list[dict[str, object]],
    field: str,
) -> dict[str, list[dict[str, object]]]:
    groups: dict[str, list[dict[str, object]]] = {}
    for item in runs:
        key = safe_text(item.get(field)) or "unknown"
        groups.setdefault(key, []).append(item)
    return groups


def _group_runs_by_strategy(runs: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    return _group_runs_by_key(runs, "strategy")


def _strategy_summary(runs: list[dict[str, object]]) -> dict[str, object]:
    ordered = sorted(runs, key=_run_sort_key, reverse=True)
    latest = ordered[0] if ordered else {}
    llm_values = [
        val
        for item in ordered
        if (val := finite_float(item.get("llm_coverage"))) is not None
    ]
    return {
        "strategy": safe_text(latest.get("strategy")) or "unknown",
        "strategy_category": safe_text(latest.get("strategy_category")),
        "run_count": len(ordered),
        "latest_run_id": safe_text(latest.get("run_id")),
        "latest_created_at": safe_text(latest.get("created_at")),
        "latest_report_path": safe_text(latest.get("report_path")),
        "latest_snapshot_source": safe_text(latest.get("snapshot_source")),
        "total_picks": sum(_non_neg_int(item.get("picks")) for item in ordered),
        "average_picks": _average(_non_neg_int(item.get("picks")) for item in ordered),
        "snapshot_sources": _unique_values(item.get("snapshot_source") for item in ordered),
        "runs_with_source_errors": sum(1 for item in ordered if _non_neg_int(item.get("source_error_count")) > 0),
        "source_error_count": sum(_non_neg_int(item.get("source_error_count")) for item in ordered),
        "source_error_samples": _sample_values(ordered, "source_errors"),
        "runs_with_degradation": sum(1 for item in ordered if _non_neg_int(item.get("degradation_count")) > 0),
        "degradation_count": sum(_non_neg_int(item.get("degradation_count")) for item in ordered),
        "degradation_samples": _sample_values(ordered, "degradation"),
        "llm_ranked_runs": sum(1 for item in ordered if _is_flag_enabled(item.get("llm_ranked"))),
        "average_llm_coverage": _average(llm_values),
        "daily_enriched_runs": sum(1 for item in ordered if _is_flag_enabled(item.get("daily_enriched"))),
        "daily_enrich_count": sum(_non_neg_int(item.get("daily_enrich_count")) for item in ordered),
        "post_analyzers": _unique_post_analyzers(ordered),
        "recent_runs": [_compact_run(item) for item in ordered[:5]],
    }


def _run_history_summary(runs: list[dict[str, object]]) -> dict[str, object]:
    ordered = sorted(runs, key=_run_sort_key, reverse=True)
    return {
        "runs_with_source_errors": sum(1 for item in runs if _non_neg_int(item.get("source_error_count")) > 0),
        "source_error_samples": _sample_values(ordered, "source_errors"),
        "runs_with_degradation": sum(1 for item in runs if _non_neg_int(item.get("degradation_count")) > 0),
        "degradation_samples": _sample_values(ordered, "degradation"),
        "llm_ranked_runs": sum(1 for item in runs if _is_flag_enabled(item.get("llm_ranked"))),
        "daily_enriched_runs": sum(1 for item in runs if _is_flag_enabled(item.get("daily_enriched"))),
        "total_picks": sum(_non_neg_int(item.get("picks")) for item in runs),
        "latest_run": _compact_run(ordered[0]) if ordered else {},
    }


def _non_neg_int(value: object) -> int:
    return max(safe_int(value, default=0), 0)


def _is_flag_enabled(value: object) -> bool:
    return safe_bool(value) is True


def _compact_run(item: dict[str, object]) -> dict[str, object]:
    return {
        "run_id": safe_text(item.get("run_id")),
        "strategy": safe_text(item.get("strategy")),
        "created_at": safe_text(item.get("created_at")),
        "picks": _non_neg_int(item.get("picks")),
        "snapshot_source": safe_text(item.get("snapshot_source")),
        "source_error_count": _non_neg_int(item.get("source_error_count")),
        "source_errors": _sample_list(item.get("source_errors"), limit=3),
        "degradation_count": _non_neg_int(item.get("degradation_count")),
        "degradation": _sample_list(item.get("degradation"), limit=3),
        "report_path": safe_text(item.get("report_path")),
    }


def _unique_post_analyzers(runs: list[dict[str, object]]) -> list[str]:
    values: list[str] = []
    for item in runs:
        values.extend(_sample_list(item.get("post_analyzers"), limit=100))
    return list(dict.fromkeys(values))


def _unique_values(values) -> list[str]:
    return list(dict.fromkeys(text for value in values if (text := safe_text(value))))


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
    if isinstance(value, (list, tuple, set)):
        cleaned = [text for item in value if (text := safe_text(item))]
        return cleaned[:limit]
    if isinstance(value, str) and value:
        return [text for item in value.split(",") if (text := safe_text(item))][:limit]
    return []


def _average(values) -> float | None:
    items = [val for value in values if (val := finite_float(value)) is not None]
    if not items:
        return None
    return round(sum(items) / len(items), 4)


def _run_sort_key(item: dict[str, object]) -> tuple[datetime, str]:
    return (_parse_created_at(item.get("created_at")), safe_text(item.get("run_id")))


def _parse_created_at(value: object) -> datetime:
    # Aware for both old naive and new offset timestamps, so they sort together.
    return parse_timestamp(safe_text(value)) or MIN_TIMESTAMP
