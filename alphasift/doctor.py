# -*- coding: utf-8 -*-
"""Runtime diagnostic helpers for AlphaSift data sources."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from alphasift.config import Config
from alphasift.daily import compute_daily_features, daily_source_health_snapshot, fetch_daily_history
from alphasift.snapshot import (
    fetch_cn_snapshot,
    fetch_snapshot_with_fallback,
    snapshot_source_health_snapshot,
)
from alphasift.strategy import list_strategies


@dataclass
class SourceCheckResult:
    """Single source-family diagnostic result."""

    status: str
    sources: list[str] = field(default_factory=list)
    source: str = ""
    rows: int = 0
    fallback_used: bool = False
    stale: bool = False
    stale_age_hours: float | None = None
    errors: list[str] = field(default_factory=list)
    health: dict[str, dict[str, float | bool | str]] = field(default_factory=dict)
    required_fields: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    quality_summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class DataSourcesDoctorResult:
    """Machine-readable data-source doctor report."""

    status: str
    generated_at: str
    config: dict[str, Any]
    snapshot: SourceCheckResult
    daily: SourceCheckResult | None = None
    strategy_requirements: dict[str, Any] = field(default_factory=dict)
    strategy_coverage: list[dict[str, Any]] = field(default_factory=list)
    strategy_readiness_summary: dict[str, Any] = field(default_factory=dict)
    health_summary: dict[str, Any] = field(default_factory=dict)
    freshness_summary: dict[str, Any] = field(default_factory=dict)
    snapshot_reconciliation: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_health"] = {
            "snapshot": self.snapshot.health,
            "daily": self.daily.health if self.daily is not None else {},
        }
        return payload


def doctor_data_sources(
    config: Config,
    *,
    snapshot_sources: list[str] | None = None,
    daily_source: str | None = None,
    daily_code: str = "000001",
    run_live: bool = True,
    check_daily: bool = True,
    strategy_name: str | None = None,
    all_strategies: bool = False,
    compare_snapshot_sources: bool = False,
) -> DataSourcesDoctorResult:
    """Check snapshot and daily K-line source health without exposing secrets."""
    sources = list(snapshot_sources or config.snapshot_source_priority)
    daily_source_name = daily_source or config.daily_source
    strategy_requirements, coverage_requirements = _strategy_preflight_plan(
        config,
        strategy_name=strategy_name,
        all_strategies=all_strategies,
    )
    snapshot_required_fields = _required_fields_for_check(
        strategy_requirements.get("required_snapshot_fields"),
        default=["code", "name", "price"],
    )
    daily_required_fields = list(strategy_requirements.get("required_daily_fields", []) or [])
    snapshot = _check_snapshot_sources(
        config,
        sources=sources,
        run_live=run_live,
        required_fields=snapshot_required_fields,
    )
    daily = (
        _check_daily_sources(
            config,
            source=daily_source_name,
            code=daily_code,
            run_live=run_live,
            required_fields=daily_required_fields,
        )
        if check_daily
        else None
    )
    strategy_coverage = _build_strategy_coverage(coverage_requirements, snapshot, daily)
    strategy_readiness_summary = _build_strategy_readiness_summary(strategy_coverage)
    health_summary = _build_health_summary(snapshot, daily)
    freshness_summary = _build_freshness_summary(snapshot, daily)
    snapshot_reconciliation = _snapshot_source_reconciliation(
        sources,
        required_fields=snapshot_required_fields,
        run_live=run_live,
        enabled=compare_snapshot_sources,
    )
    recommendations = _build_recommendations(snapshot, daily)
    statuses = [snapshot.status, daily.status if daily is not None else "skipped"]
    status = _overall_status(statuses)
    return DataSourcesDoctorResult(
        status=status,
        generated_at=datetime.now(timezone.utc).isoformat(),
        config={
            "snapshot_source_priority": sources,
            "daily_source": daily_source_name,
            "daily_code": daily_code if check_daily else "",
            "fallback_snapshot_path": str(config.fallback_snapshot_path or ""),
            "daily_history_cache_dir": str(config.daily_history_cache_dir or ""),
            "tushare_configured": bool(_has_configured_tushare()),
            "live_checks": bool(run_live),
        },
        snapshot=snapshot,
        daily=daily,
        strategy_requirements=strategy_requirements,
        strategy_coverage=strategy_coverage,
        strategy_readiness_summary=strategy_readiness_summary,
        health_summary=health_summary,
        freshness_summary=freshness_summary,
        snapshot_reconciliation=snapshot_reconciliation,
        recommendations=recommendations,
    )


def _check_snapshot_sources(
    config: Config,
    *,
    sources: list[str],
    run_live: bool,
    required_fields: list[str],
) -> SourceCheckResult:
    health = snapshot_source_health_snapshot(sources)
    if not run_live:
        return SourceCheckResult(
            status="skipped",
            sources=sources,
            health=health,
            required_fields=required_fields,
        )
    try:
        df = fetch_snapshot_with_fallback(
            sources,
            required_columns=required_fields,
            fallback_snapshot_path=config.fallback_snapshot_path,
            fallback_max_age_hours=config.snapshot_fallback_max_age_hours,
            market="cn",
        )
    except Exception as exc:  # noqa: BLE001 - doctor must aggregate failures.
        return SourceCheckResult(
            status="failed",
            sources=sources,
            errors=[str(exc)],
            health=snapshot_source_health_snapshot(sources),
            required_fields=required_fields,
        )
    missing_fields = [field for field in required_fields if field not in df.columns]
    quality_summary = _snapshot_quality_summary(df, required_fields=required_fields)
    quality_degraded = str(quality_summary.get("status", "")) not in {"", "ok"}
    return SourceCheckResult(
        status="degraded"
        if bool(df.attrs.get("fallback_used")) or missing_fields or quality_degraded
        else "ok",
        sources=sources,
        source=str(df.attrs.get("snapshot_source", "")),
        rows=int(len(df)),
        fallback_used=bool(df.attrs.get("fallback_used")),
        stale=bool(df.attrs.get("stale")),
        stale_age_hours=df.attrs.get("stale_age_hours"),
        errors=[str(item) for item in list(df.attrs.get("source_errors", []) or [])],
        health=snapshot_source_health_snapshot(sources),
        required_fields=required_fields,
        missing_fields=missing_fields,
        quality_summary=quality_summary,
    )


def _check_daily_sources(
    config: Config,
    *,
    source: str,
    code: str,
    run_live: bool,
    required_fields: list[str],
) -> SourceCheckResult:
    health = daily_source_health_snapshot()
    if not run_live:
        return SourceCheckResult(
            status="skipped",
            sources=[source],
            health=health,
            required_fields=required_fields,
        )
    try:
        df = fetch_daily_history(
            code,
            lookback_days=config.daily_lookback_days,
            source=source,
            retries=0,
            cache_dir=config.daily_history_cache_dir,
            cache_ttl_seconds=config.daily_history_cache_ttl_hours * 3600,
        )
        missing_fields = _missing_daily_feature_fields(df, required_fields)
    except Exception as exc:  # noqa: BLE001 - doctor must aggregate failures.
        return SourceCheckResult(
            status="failed",
            sources=[source],
            errors=[str(exc)],
            health=daily_source_health_snapshot(),
            required_fields=required_fields,
        )
    degraded = bool(df.attrs.get("daily_stale")) or bool(missing_fields)
    return SourceCheckResult(
        status="degraded" if degraded else "ok",
        sources=[source],
        source=str(df.attrs.get("daily_source", "")),
        rows=int(len(df)),
        fallback_used=bool(df.attrs.get("source_errors")),
        stale=bool(df.attrs.get("daily_stale")),
        errors=[str(item) for item in list(df.attrs.get("source_errors", []) or [])],
        health=daily_source_health_snapshot(),
        required_fields=required_fields,
        missing_fields=missing_fields,
    )


def _strategy_preflight_plan(
    config: Config,
    *,
    strategy_name: str | None,
    all_strategies: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if strategy_name and all_strategies:
        raise ValueError("--strategy and --all-strategies cannot be combined")
    if all_strategies:
        requirements = [_strategy_requirement_payload(item) for item in list_strategies(config.strategies_dir)]
        return (
            {
                "mode": "all",
                "strategy_count": len(requirements),
                "daily_strategy_count": sum(
                    1 for item in requirements if item["requires_daily_features"]
                ),
                "data_requirements": _union_fields(requirements, "data_requirements"),
                "required_snapshot_fields": _union_fields(requirements, "required_snapshot_fields"),
                "required_daily_fields": _union_fields(requirements, "required_daily_fields"),
            },
            requirements,
        )
    strategy_requirements = _strategy_requirements(config, strategy_name)
    return strategy_requirements, [strategy_requirements] if strategy_requirements else []


def _strategy_requirements(config: Config, strategy_name: str | None) -> dict[str, Any]:
    if not strategy_name:
        return {}
    for item in list_strategies(config.strategies_dir):
        if item.name == strategy_name:
            return _strategy_requirement_payload(item)
    raise ValueError(f"Strategy '{strategy_name}' not found")


def _strategy_requirement_payload(item) -> dict[str, Any]:
    return {
        "strategy": item.name,
        "display_name": item.display_name,
        "category": item.category,
        "style": dict(item.style),
        "data_requirements": list(item.data_requirements),
        "requires_daily_features": bool(item.requires_daily_features),
        "required_snapshot_fields": list(item.required_snapshot_fields),
        "required_daily_fields": list(item.required_daily_fields),
    }


def _union_fields(items: list[dict[str, Any]], key: str) -> list[str]:
    values: list[str] = []
    for item in items:
        values.extend(str(value) for value in item.get(key, []) or [])
    return list(dict.fromkeys(values))


def _required_fields_for_check(value: object, *, default: list[str]) -> list[str]:
    fields = [str(item) for item in (value or []) if str(item).strip()]
    if not fields:
        fields = list(default)
    if "code" not in fields:
        fields.insert(0, "code")
    return list(dict.fromkeys(fields))


def _missing_daily_feature_fields(df, required_fields: list[str]) -> list[str]:
    if not required_fields:
        return []
    features = compute_daily_features(df)
    return [field for field in required_fields if field not in features]


def _snapshot_quality_summary(df, *, required_fields: list[str]) -> dict[str, Any]:
    checked_fields = _snapshot_quality_fields(df, required_fields)
    anomalies: list[str] = []
    field_stats: dict[str, dict[str, Any]] = {}
    row_count = int(len(df))
    if row_count == 0:
        anomalies.append("snapshot_empty")

    duplicate_code_count = 0
    if "code" in df.columns:
        duplicate_code_count = int(df["code"].astype(str).duplicated().sum())
        if duplicate_code_count > 0:
            anomalies.append(f"duplicate_code_count:{duplicate_code_count}")

    for field_name in checked_fields:
        if field_name not in df.columns:
            field_stats[field_name] = {
                "present": False,
                "missing_count": row_count,
                "missing_ratio": 1.0 if row_count else 0.0,
                "invalid_numeric_count": 0,
                "non_positive_count": 0,
            }
            anomalies.append(f"{field_name}:missing_column")
            continue
        series = df[field_name]
        missing_mask = series.isna() | (series.astype(str).str.strip() == "")
        missing_count = int(missing_mask.sum())
        missing_ratio = _ratio(missing_count, row_count)
        stats: dict[str, Any] = {
            "present": True,
            "missing_count": missing_count,
            "missing_ratio": missing_ratio,
            "invalid_numeric_count": 0,
            "non_positive_count": 0,
        }
        if field_name in _SNAPSHOT_NUMERIC_FIELDS:
            numeric = pd.to_numeric(series, errors="coerce")
            invalid_numeric_count = int((numeric.isna() & ~missing_mask).sum())
            non_positive_count = (
                int((numeric <= 0).sum())
                if field_name in _SNAPSHOT_POSITIVE_FIELDS
                else 0
            )
            stats["invalid_numeric_count"] = invalid_numeric_count
            stats["non_positive_count"] = non_positive_count
            if invalid_numeric_count > 0:
                anomalies.append(f"{field_name}:invalid_numeric={invalid_numeric_count}")
            if non_positive_count > 0:
                anomalies.append(f"{field_name}:non_positive={non_positive_count}")
        if missing_count > 0 and field_name in required_fields:
            anomalies.append(f"{field_name}:missing_values={missing_count}")
        elif missing_ratio >= 0.25 and row_count > 0:
            anomalies.append(f"{field_name}:missing_ratio={missing_ratio:.2f}")
        field_stats[field_name] = stats

    return {
        "status": "degraded" if anomalies else "ok",
        "row_count": row_count,
        "duplicate_code_count": duplicate_code_count,
        "checked_fields": checked_fields,
        "anomalies": anomalies,
        "field_stats": field_stats,
    }


_SNAPSHOT_DEFAULT_QUALITY_FIELDS = [
    "code",
    "name",
    "price",
    "change_pct",
    "amount",
    "total_mv",
    "pe_ratio",
    "pb_ratio",
    "turnover_rate",
    "volume_ratio",
]
_SNAPSHOT_NUMERIC_FIELDS = {
    "price",
    "change_pct",
    "amount",
    "total_mv",
    "pe_ratio",
    "pb_ratio",
    "turnover_rate",
    "volume_ratio",
}
_SNAPSHOT_POSITIVE_FIELDS = {"price", "amount", "total_mv"}


def _snapshot_quality_fields(df, required_fields: list[str]) -> list[str]:
    fields: list[str] = []
    fields.extend(required_fields)
    fields.extend(field for field in _SNAPSHOT_DEFAULT_QUALITY_FIELDS if field in df.columns)
    return list(dict.fromkeys(field for field in fields if field))


def _snapshot_source_reconciliation(
    sources: list[str],
    *,
    required_fields: list[str],
    run_live: bool,
    enabled: bool,
) -> dict[str, Any]:
    if not enabled:
        return {}
    if not run_live:
        return {
            "status": "skipped",
            "reason": "live_checks_disabled",
            "required_fields": list(required_fields),
            "sources": [],
            "summary": {
                "source_count": len(sources),
                "ok_source_count": 0,
                "degraded_source_count": 0,
                "failed_source_count": 0,
                "field_coverage": {},
                "warnings": ["snapshot_reconciliation_skipped:no_live"],
            },
        }

    rows: list[dict[str, Any]] = []
    code_sets: dict[str, set[str]] = {}
    for source in sources:
        try:
            df = fetch_cn_snapshot(source)
        except Exception as exc:  # noqa: BLE001 - doctor should capture provider failures.
            rows.append({
                "source": source,
                "status": "failed",
                "rows": 0,
                "missing_fields": list(required_fields),
                "quality_status": "",
                "quality_anomaly_count": 0,
                "overlap_with_baseline_count": 0,
                "overlap_with_baseline_ratio": None,
                "sample_codes": [],
                "errors": [str(exc)],
            })
            continue

        missing_fields = [field for field in required_fields if field not in df.columns]
        quality_summary = _snapshot_quality_summary(df, required_fields=required_fields)
        quality_status = str(quality_summary.get("status", ""))
        status = "degraded" if missing_fields or quality_status == "degraded" else "ok"
        codes = _snapshot_reconciliation_codes(df)
        code_sets[source] = codes
        rows.append({
            "source": source,
            "status": status,
            "rows": int(len(df)),
            "missing_fields": missing_fields,
            "quality_status": quality_status,
            "quality_anomaly_count": len(quality_summary.get("anomalies", []) or []),
            "overlap_with_baseline_count": 0,
            "overlap_with_baseline_ratio": None,
            "sample_codes": sorted(codes)[:5],
            "errors": [],
        })

    baseline_source = _snapshot_reconciliation_baseline(rows)
    baseline_codes = code_sets.get(baseline_source, set())
    if baseline_codes:
        for row in rows:
            source = str(row.get("source", ""))
            codes = code_sets.get(source, set())
            shared_count = len(codes & baseline_codes)
            row["overlap_with_baseline_count"] = shared_count
            row["overlap_with_baseline_ratio"] = _ratio(shared_count, len(baseline_codes))

    summary = _snapshot_reconciliation_summary(rows, required_fields)
    if not any(row.get("status") in {"ok", "degraded"} for row in rows):
        status = "failed"
    elif summary["failed_source_count"] or summary["degraded_source_count"]:
        status = "degraded"
    else:
        status = "ok"
    return {
        "status": status,
        "baseline_source": baseline_source,
        "required_fields": list(required_fields),
        "sources": rows,
        "summary": summary,
    }


def _snapshot_reconciliation_codes(df: pd.DataFrame) -> set[str]:
    if "code" not in df.columns:
        return set()
    return {
        str(value).strip()
        for value in df["code"].tolist()
        if str(value).strip()
    }


def _snapshot_reconciliation_baseline(rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("status") in {"ok", "degraded"}:
            return str(row.get("source", ""))
    return ""


def _snapshot_reconciliation_summary(
    rows: list[dict[str, Any]],
    required_fields: list[str],
) -> dict[str, Any]:
    warnings: list[str] = []
    field_coverage: dict[str, dict[str, Any]] = {}
    for field_name in required_fields:
        present_sources: list[str] = []
        missing_sources: list[str] = []
        for row in rows:
            source = str(row.get("source", ""))
            if row.get("status") == "failed":
                continue
            if field_name in (row.get("missing_fields") or []):
                missing_sources.append(source)
            else:
                present_sources.append(source)
        if missing_sources:
            warnings.append(f"{field_name}:missing_in={','.join(missing_sources)}")
        field_coverage[field_name] = {
            "present_source_count": len(present_sources),
            "missing_sources": missing_sources,
        }

    failed_sources = [str(row.get("source", "")) for row in rows if row.get("status") == "failed"]
    if failed_sources:
        warnings.append("failed_sources:" + ",".join(failed_sources))
    return {
        "source_count": len(rows),
        "ok_source_count": sum(1 for row in rows if row.get("status") == "ok"),
        "degraded_source_count": sum(1 for row in rows if row.get("status") == "degraded"),
        "failed_source_count": len(failed_sources),
        "field_coverage": field_coverage,
        "warnings": warnings,
    }


def _ratio(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(float(count) / float(total), 4)


def _build_strategy_coverage(
    requirements: list[dict[str, Any]],
    snapshot: SourceCheckResult,
    daily: SourceCheckResult | None,
) -> list[dict[str, Any]]:
    if not requirements:
        return []
    snapshot_missing = set(snapshot.missing_fields)
    daily_missing = set(daily.missing_fields if daily is not None else [])
    coverage: list[dict[str, Any]] = []
    for item in requirements:
        required_snapshot = list(item.get("required_snapshot_fields", []) or [])
        required_daily = list(item.get("required_daily_fields", []) or [])
        item_snapshot_missing = [field for field in required_snapshot if field in snapshot_missing]
        item_daily_missing = [field for field in required_daily if field in daily_missing]
        coverage.append(
            {
                "strategy": item.get("strategy", ""),
                "display_name": item.get("display_name", ""),
                "category": item.get("category", ""),
                "style": dict(item.get("style", {}) or {}),
                "data_requirements": list(item.get("data_requirements", []) or []),
                "requires_daily_features": bool(item.get("requires_daily_features")),
                "status": _strategy_coverage_status(
                    item,
                    snapshot,
                    daily,
                    snapshot_missing=item_snapshot_missing,
                    daily_missing=item_daily_missing,
                ),
                "required_snapshot_fields": required_snapshot,
                "required_daily_fields": required_daily,
                "snapshot_missing_fields": item_snapshot_missing,
                "daily_missing_fields": item_daily_missing,
            }
        )
    return coverage


def _strategy_coverage_status(
    item: dict[str, Any],
    snapshot: SourceCheckResult,
    daily: SourceCheckResult | None,
    *,
    snapshot_missing: list[str],
    daily_missing: list[str],
) -> str:
    requires_daily = bool(item.get("requires_daily_features")) or bool(
        item.get("required_daily_fields")
    )
    if snapshot.status == "failed" or (requires_daily and daily is not None and daily.status == "failed"):
        return "failed"
    if snapshot.status == "skipped" or (requires_daily and (daily is None or daily.status == "skipped")):
        return "skipped"
    if snapshot_missing or daily_missing:
        return "degraded"
    if snapshot.status == "degraded" or (requires_daily and daily is not None and daily.status == "degraded"):
        return "degraded"
    return "ok"


def _build_strategy_readiness_summary(coverage: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = {status: 0 for status in ("ok", "degraded", "failed", "skipped")}
    for item in coverage:
        status = str(item.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    impacted = [
        _strategy_readiness_item(item)
        for item in coverage
        if str(item.get("status") or "") in {"degraded", "failed"}
    ]
    unchecked = [
        _strategy_readiness_item(item)
        for item in coverage
        if str(item.get("status") or "") == "skipped"
    ]
    next_actions: list[str] = []
    if unchecked:
        next_actions.append("Run a live data-source check before relying on strategy readiness.")
    if impacted:
        next_actions.append("Review missing snapshot/daily fields for degraded or failed strategies.")

    return {
        "schema_version": 1,
        "strategy_count": len(coverage),
        "ready_strategy_count": status_counts.get("ok", 0),
        "attention_strategy_count": status_counts.get("degraded", 0) + status_counts.get("failed", 0),
        "unchecked_strategy_count": status_counts.get("skipped", 0),
        "daily_strategy_count": sum(1 for item in coverage if bool(item.get("requires_daily_features"))),
        "status_counts": status_counts,
        "impacted_strategies": impacted,
        "unchecked_strategies": unchecked,
        "missing_snapshot_fields": _missing_field_impacts(coverage, "snapshot_missing_fields"),
        "missing_daily_fields": _missing_field_impacts(coverage, "daily_missing_fields"),
        "next_actions": next_actions,
    }


def _strategy_readiness_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "strategy": item.get("strategy", ""),
        "display_name": item.get("display_name", ""),
        "status": item.get("status", ""),
        "requires_daily_features": bool(item.get("requires_daily_features")),
        "snapshot_missing_fields": list(item.get("snapshot_missing_fields", []) or []),
        "daily_missing_fields": list(item.get("daily_missing_fields", []) or []),
    }


def _missing_field_impacts(coverage: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    impacts: dict[str, list[str]] = {}
    for item in coverage:
        strategy_name = str(item.get("strategy") or "")
        for field_name in item.get(key, []) or []:
            impacts.setdefault(str(field_name), []).append(strategy_name)
    rows = [
        {
            "field": field_name,
            "strategy_count": len(strategy_names),
            "strategies": sorted(strategy_names),
        }
        for field_name, strategy_names in impacts.items()
    ]
    rows.sort(key=lambda item: (-int(item["strategy_count"]), str(item["field"])))
    return rows


def _overall_status(statuses: list[str]) -> str:
    active = [status for status in statuses if status != "skipped"]
    if not active:
        return "skipped"
    if all(status == "ok" for status in active):
        return "ok"
    if any(status == "ok" for status in active) or any(
        status == "degraded" for status in active
    ):
        return "degraded"
    return "failed"


def _build_health_summary(
    snapshot: SourceCheckResult,
    daily: SourceCheckResult | None,
) -> dict[str, Any]:
    return {
        "snapshot": _source_family_health_summary(snapshot),
        "daily": _source_family_health_summary(daily) if daily is not None else {
            "status": "skipped",
            "requested_sources": [],
            "selected_source": "",
            "available_source_count": 0,
            "healthy_sources": [],
            "failing_sources": [],
            "disabled_sources": [],
            "never_seen_sources": [],
            "last_errors": [],
            "fallback_used": False,
            "stale": False,
            "missing_fields": [],
            "error_count": 0,
        },
    }


def _build_freshness_summary(
    snapshot: SourceCheckResult,
    daily: SourceCheckResult | None,
) -> dict[str, Any]:
    snapshot_summary = _source_freshness_summary(snapshot, family="snapshot")
    daily_summary = (
        _source_freshness_summary(daily, family="daily")
        if daily is not None
        else _skipped_freshness_summary("daily")
    )
    family_summaries = [snapshot_summary, daily_summary]
    warnings = [
        f"{item['family']}:{item['data_state']}"
        for item in family_summaries
        if item.get("data_state") not in {"fresh", "not_requested"}
    ]
    return {
        "snapshot": snapshot_summary,
        "daily": daily_summary,
        "fresh_enough": not warnings,
        "fresh_family_count": sum(1 for item in family_summaries if item.get("data_state") == "fresh"),
        "stale_family_count": sum(1 for item in family_summaries if item.get("data_state") == "stale"),
        "fallback_family_count": sum(1 for item in family_summaries if item.get("fallback_used")),
        "unavailable_family_count": sum(1 for item in family_summaries if item.get("data_state") == "unavailable"),
        "not_checked_family_count": sum(1 for item in family_summaries if item.get("data_state") == "not_checked"),
        "warnings": warnings,
    }


def _source_freshness_summary(
    result: SourceCheckResult,
    *,
    family: str,
) -> dict[str, Any]:
    quality_status = str(result.quality_summary.get("status", ""))
    quality_anomaly_count = len(result.quality_summary.get("anomalies", []) or [])
    if result.status == "skipped":
        data_state = "not_checked"
        cache_state = "not_checked"
        recommendation = f"Run live {family} check before relying on fresh data."
    elif result.status == "failed":
        data_state = "unavailable"
        cache_state = "unavailable"
        recommendation = f"Fix {family} source errors before running live screening."
    elif result.stale:
        data_state = "stale"
        cache_state = "stale_cache"
        recommendation = f"Refresh {family} data; current result came from stale cache."
    elif result.fallback_used:
        data_state = "fallback"
        cache_state = "last_good_cache" if family == "snapshot" else "provider_fallback"
        recommendation = f"Review {family} source errors; data used a fallback path."
    elif result.missing_fields or quality_status == "degraded":
        data_state = "degraded"
        cache_state = "live"
        recommendation = f"Review {family} missing fields or quality anomalies before trusting filters."
    else:
        data_state = "fresh"
        cache_state = "live"
        recommendation = ""
    return {
        "family": family,
        "status": result.status,
        "data_state": data_state,
        "cache_state": cache_state,
        "selected_source": result.source,
        "rows": result.rows,
        "fallback_used": result.fallback_used,
        "stale": result.stale,
        "stale_age_hours": result.stale_age_hours,
        "missing_fields": list(result.missing_fields),
        "error_count": len(result.errors),
        "quality_status": quality_status,
        "quality_anomaly_count": quality_anomaly_count,
        "recommendation": recommendation,
    }


def _skipped_freshness_summary(family: str) -> dict[str, Any]:
    return {
        "family": family,
        "status": "skipped",
        "data_state": "not_requested",
        "cache_state": "not_requested",
        "selected_source": "",
        "rows": 0,
        "fallback_used": False,
        "stale": False,
        "stale_age_hours": None,
        "missing_fields": [],
        "error_count": 0,
        "quality_status": "",
        "quality_anomaly_count": 0,
        "recommendation": "",
    }


def _source_family_health_summary(result: SourceCheckResult) -> dict[str, Any]:
    health = result.health or {}
    requested_sources = list(dict.fromkeys([*result.sources, *health.keys()]))
    healthy_sources: list[str] = []
    failing_sources: list[str] = []
    disabled_sources: list[str] = []
    never_seen_sources: list[str] = []
    last_errors: list[dict[str, Any]] = []

    for source in requested_sources:
        state = health.get(source, {}) or {}
        successes = float(state.get("successes", 0.0))
        failures = float(state.get("failures", 0.0))
        total_failures = float(state.get("total_failures", 0.0))
        disabled = bool(state.get("disabled", False))
        last_error = str(state.get("last_error", ""))
        if disabled:
            disabled_sources.append(source)
        elif failures > 0:
            failing_sources.append(source)
        elif successes > 0:
            healthy_sources.append(source)
        elif total_failures == 0:
            never_seen_sources.append(source)
        if last_error:
            last_errors.append({
                "source": source,
                "error": last_error,
                "failures": failures,
                "total_failures": total_failures,
                "disabled": disabled,
                "cooldown_remaining_seconds": float(state.get("cooldown_remaining_seconds", 0.0)),
            })

    return {
        "status": result.status,
        "requested_sources": requested_sources,
        "selected_source": result.source,
        "available_source_count": len(requested_sources) - len(disabled_sources),
        "healthy_sources": healthy_sources,
        "failing_sources": failing_sources,
        "disabled_sources": disabled_sources,
        "never_seen_sources": never_seen_sources,
        "last_errors": last_errors,
        "fallback_used": result.fallback_used,
        "stale": result.stale,
        "missing_fields": list(result.missing_fields),
        "error_count": len(result.errors),
        "quality_status": result.quality_summary.get("status", ""),
        "quality_anomaly_count": len(result.quality_summary.get("anomalies", []) or []),
    }


def _build_recommendations(
    snapshot: SourceCheckResult,
    daily: SourceCheckResult | None,
) -> list[str]:
    recommendations: list[str] = []
    if snapshot.status == "skipped" and (daily is None or daily.status == "skipped"):
        recommendations.append(
            "Live data-source checks were skipped: rerun without --no-live before relying on fresh screening."
        )
    if snapshot.status == "failed":
        recommendations.append(
            "Snapshot failed: check network access and SNAPSHOT_SOURCE_PRIORITY; attach this doctor output to issue #18."
        )
    elif snapshot.fallback_used:
        recommendations.append(
            "Snapshot used last-good cache: live sources are degraded; inspect snapshot.errors for the failing provider."
        )
    if snapshot.quality_summary.get("anomalies"):
        anomalies = [
            str(item)
            for item in list(snapshot.quality_summary.get("anomalies", []) or [])[:4]
        ]
        recommendations.append(
            "Snapshot quality anomalies detected: "
            + ", ".join(anomalies)
            + "; inspect snapshot.quality_summary before trusting hard filters."
        )
    if daily is not None:
        if daily.status == "failed":
            recommendations.append(
                "Daily K-line failed: try DAILY_SOURCE=auto or verify TUSHARE_TOKEN/Tencent/Sina/Akshare connectivity."
            )
        elif daily.stale:
            recommendations.append(
                "Daily K-line used stale cache: refresh network-backed sources before relying on fresh technical filters."
            )
    recommendations.extend(_source_health_recommendations("Snapshot", snapshot))
    if daily is not None:
        recommendations.extend(_source_health_recommendations("Daily K-line", daily))
    if not recommendations:
        recommendations.append("Data sources look usable for a basic AlphaSift run.")
    return recommendations


def _source_health_recommendations(label: str, result: SourceCheckResult) -> list[str]:
    summary = _source_family_health_summary(result)
    recommendations: list[str] = []
    disabled = summary.get("disabled_sources", []) or []
    failing = summary.get("failing_sources", []) or []
    if disabled:
        recommendations.append(
            f"{label} health guard disabled sources: {','.join(disabled)}; wait for cooldown or lower their priority."
        )
    if failing:
        recommendations.append(
            f"{label} sources have recent failures: {','.join(failing)}; inspect health_summary.last_errors."
        )
    return recommendations


def _has_configured_tushare() -> bool:
    import os

    return bool(
        os.getenv("TUSHARE_TOKEN", "").strip()
        or os.getenv("TUSHARE_API_TOKEN", "").strip()
    )


def write_doctor_report(path: str | Path, result: DataSourcesDoctorResult) -> Path:
    import json

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output
