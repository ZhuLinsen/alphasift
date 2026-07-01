# -*- coding: utf-8 -*-
"""Saved-run data-source reliability summaries for UI and agents."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from alphasift.store import list_saved_runs


def build_data_source_history(
    *,
    data_dir: Path,
    limit: int = 100,
    strategy: str | None = None,
) -> dict[str, object]:
    """Summarize recent saved-run source reliability without loading full runs."""
    runs = list_saved_runs(data_dir=data_dir, limit=limit, strategy=strategy)
    source_rows = [_source_summary(items) for items in _group_runs_by_snapshot_source(runs).values()]
    source_rows.sort(
        key=lambda item: (
            float(item.get("source_error_rate") or 0.0) + float(item.get("degradation_rate") or 0.0),
            str(item.get("latest_created_at") or ""),
            str(item.get("snapshot_source") or ""),
        ),
        reverse=True,
    )
    return {
        "schema_version": 1,
        "run_count": len(runs),
        "source_count": len(source_rows),
        "limit": int(limit),
        "strategy_filter": strategy or "",
        "summary": _history_summary(runs),
        "snapshot_sources": source_rows,
        "watchlist": _watchlist(source_rows),
    }


def _group_runs_by_snapshot_source(
    runs: list[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    groups: dict[str, list[dict[str, object]]] = {}
    for item in runs:
        source_name = str(item.get("snapshot_source") or "unknown")
        groups.setdefault(source_name, []).append(item)
    return groups


def _source_summary(runs: list[dict[str, object]]) -> dict[str, object]:
    ordered = sorted(runs, key=_run_sort_key, reverse=True)
    latest = ordered[0] if ordered else {}
    source_error_runs = [
        item for item in ordered if _int_value(item.get("source_error_count")) > 0
    ]
    degraded_runs = [
        item for item in ordered if _int_value(item.get("degradation_count")) > 0
    ]
    fallback_run_count = sum(
        1 for item in ordered if str(item.get("snapshot_source") or "") == "last_good_cache"
    )
    source_error_rate = _rate(len(source_error_runs), len(ordered))
    degradation_rate = _rate(len(degraded_runs), len(ordered))
    fallback_rate = _rate(fallback_run_count, len(ordered))
    stability_status = _stability_status(
        run_count=len(ordered),
        source_error_rate=source_error_rate,
        degradation_rate=degradation_rate,
        fallback_rate=fallback_rate,
    )
    source_name = str(latest.get("snapshot_source") or "unknown")
    return {
        "snapshot_source": source_name,
        "run_count": len(ordered),
        "strategy_count": len(_unique_values(item.get("strategy") for item in ordered)),
        "strategies": _unique_values(item.get("strategy") for item in ordered),
        "latest_run_id": str(latest.get("run_id") or ""),
        "latest_created_at": str(latest.get("created_at") or ""),
        "total_picks": sum(_int_value(item.get("picks")) for item in ordered),
        "average_picks": _average(_int_value(item.get("picks")) for item in ordered),
        "runs_with_source_errors": len(source_error_runs),
        "source_error_count": sum(_int_value(item.get("source_error_count")) for item in ordered),
        "source_error_rate": source_error_rate,
        "source_error_samples": _sample_values(ordered, "source_errors"),
        "runs_with_degradation": len(degraded_runs),
        "degradation_count": sum(_int_value(item.get("degradation_count")) for item in ordered),
        "degradation_rate": degradation_rate,
        "degradation_samples": _sample_values(ordered, "degradation"),
        "fallback_run_count": fallback_run_count,
        "fallback_rate": fallback_rate,
        "stability_status": stability_status,
        "stability_score": _stability_score(
            run_count=len(ordered),
            source_error_rate=source_error_rate,
            degradation_rate=degradation_rate,
            fallback_rate=fallback_rate,
        ),
        "next_actions": _stability_actions(
            stability_status,
            snapshot_source=source_name,
        ),
        "daily_enriched_runs": sum(1 for item in ordered if bool(item.get("daily_enriched"))),
        "daily_enrich_count": sum(_int_value(item.get("daily_enrich_count")) for item in ordered),
        "recent_runs": [_compact_run(item) for item in ordered[:5]],
    }


def _history_summary(runs: list[dict[str, object]]) -> dict[str, object]:
    ordered = sorted(runs, key=_run_sort_key, reverse=True)
    error_runs = [item for item in runs if _int_value(item.get("source_error_count")) > 0]
    degraded_runs = [item for item in runs if _int_value(item.get("degradation_count")) > 0]
    fallback_runs = [
        item for item in runs if str(item.get("snapshot_source") or "") == "last_good_cache"
    ]
    source_error_rate = _rate(len(error_runs), len(runs))
    degradation_rate = _rate(len(degraded_runs), len(runs))
    fallback_rate = _rate(len(fallback_runs), len(runs))
    stability_status = _stability_status(
        run_count=len(runs),
        source_error_rate=source_error_rate,
        degradation_rate=degradation_rate,
        fallback_rate=fallback_rate,
    )
    return {
        "runs_with_source_errors": len(error_runs),
        "source_error_rate": source_error_rate,
        "source_error_samples": _sample_values(ordered, "source_errors"),
        "runs_with_degradation": len(degraded_runs),
        "degradation_rate": degradation_rate,
        "degradation_samples": _sample_values(ordered, "degradation"),
        "fallback_run_count": len(fallback_runs),
        "fallback_rate": fallback_rate,
        "stability_status": stability_status,
        "stability_score": _stability_score(
            run_count=len(runs),
            source_error_rate=source_error_rate,
            degradation_rate=degradation_rate,
            fallback_rate=fallback_rate,
        ),
        "next_actions": _stability_actions(stability_status),
        "daily_enriched_runs": sum(1 for item in runs if bool(item.get("daily_enriched"))),
        "snapshot_sources": _unique_values(item.get("snapshot_source") for item in runs),
        "latest_run": _compact_run(ordered[0]) if ordered else {},
    }


def _watchlist(source_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows = []
    for item in source_rows:
        if (
            float(item.get("source_error_rate") or 0.0) > 0
            or float(item.get("degradation_rate") or 0.0) > 0
            or _int_value(item.get("fallback_run_count")) > 0
        ):
            rows.append(
                {
                    "snapshot_source": item.get("snapshot_source", ""),
                    "run_count": item.get("run_count", 0),
                    "source_error_rate": item.get("source_error_rate", 0.0),
                    "degradation_rate": item.get("degradation_rate", 0.0),
                    "fallback_run_count": item.get("fallback_run_count", 0),
                    "fallback_rate": item.get("fallback_rate", 0.0),
                    "stability_status": item.get("stability_status", "unknown"),
                    "stability_score": item.get("stability_score"),
                    "latest_run_id": item.get("latest_run_id", ""),
                    "strategies": item.get("strategies", []),
                    "source_error_samples": item.get("source_error_samples", []),
                    "degradation_samples": item.get("degradation_samples", []),
                    "next_actions": item.get("next_actions", []),
                }
            )
    rows.sort(
        key=lambda item: (
            _status_rank(str(item.get("stability_status") or "")),
            float(item.get("source_error_rate") or 0.0) + float(item.get("degradation_rate") or 0.0),
            _int_value(item.get("fallback_run_count")),
            str(item.get("snapshot_source") or ""),
        ),
        reverse=True,
    )
    return rows


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


def _rate(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(float(count) / float(total), 4)


def _stability_status(
    *,
    run_count: int,
    source_error_rate: float,
    degradation_rate: float,
    fallback_rate: float,
) -> str:
    if run_count <= 0:
        return "unknown"
    if fallback_rate > 0:
        return "fallback"
    if source_error_rate >= 0.5 or degradation_rate >= 0.5:
        return "degraded"
    if source_error_rate > 0 or degradation_rate > 0:
        return "watch"
    return "ok"


def _stability_score(
    *,
    run_count: int,
    source_error_rate: float,
    degradation_rate: float,
    fallback_rate: float,
) -> float | None:
    if run_count <= 0:
        return None
    score = 100.0 - (source_error_rate * 45.0) - (degradation_rate * 35.0) - (fallback_rate * 30.0)
    return round(max(0.0, score), 1)


def _stability_actions(status: str, *, snapshot_source: str = "") -> list[str]:
    if status == "unknown":
        return ["Run saved screens to collect data-source history."]
    if status == "fallback":
        return ["Refresh live snapshot providers before relying on last-good cache runs."]
    if status == "degraded":
        source = f" `{snapshot_source}`" if snapshot_source else ""
        return [f"Compare{source} with alternate snapshot providers and inspect issue samples."]
    if status == "watch":
        source = f" `{snapshot_source}`" if snapshot_source else ""
        return [f"Monitor{source} over the next saved runs and keep alternate providers configured."]
    return []


def _status_rank(status: str) -> int:
    return {
        "fallback": 4,
        "degraded": 3,
        "watch": 2,
        "ok": 1,
        "unknown": 0,
    }.get(status, 0)


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
