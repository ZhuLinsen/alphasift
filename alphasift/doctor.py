# -*- coding: utf-8 -*-
"""Runtime diagnostic helpers for AlphaSift data sources."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alphasift.config import Config
from alphasift.daily import compute_daily_features, daily_source_health_snapshot, fetch_daily_history
from alphasift.snapshot import (
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


@dataclass
class DataSourcesDoctorResult:
    """Machine-readable data-source doctor report."""

    status: str
    generated_at: str
    config: dict[str, Any]
    snapshot: SourceCheckResult
    daily: SourceCheckResult | None = None
    strategy_requirements: dict[str, Any] = field(default_factory=dict)
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
) -> DataSourcesDoctorResult:
    """Check snapshot and daily K-line source health without exposing secrets."""
    sources = list(snapshot_sources or config.snapshot_source_priority)
    daily_source_name = daily_source or config.daily_source
    strategy_requirements = _strategy_requirements(config, strategy_name)
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
    return SourceCheckResult(
        status="degraded" if bool(df.attrs.get("fallback_used")) or missing_fields else "ok",
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


def _strategy_requirements(config: Config, strategy_name: str | None) -> dict[str, Any]:
    if not strategy_name:
        return {}
    for item in list_strategies(config.strategies_dir):
        if item.name == strategy_name:
            return {
                "strategy": item.name,
                "display_name": item.display_name,
                "category": item.category,
                "data_requirements": list(item.data_requirements),
                "requires_daily_features": bool(item.requires_daily_features),
                "required_snapshot_fields": list(item.required_snapshot_fields),
                "required_daily_fields": list(item.required_daily_fields),
            }
    raise ValueError(f"Strategy '{strategy_name}' not found")


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


def _build_recommendations(
    snapshot: SourceCheckResult,
    daily: SourceCheckResult | None,
) -> list[str]:
    recommendations: list[str] = []
    if snapshot.status == "skipped" and (daily is None or daily.status == "skipped"):
        recommendations.append(
            "Live data-source checks were skipped: rerun without --no-live before relying on fresh screening."
        )
        return recommendations
    if snapshot.status == "failed":
        recommendations.append(
            "Snapshot failed: check network access and SNAPSHOT_SOURCE_PRIORITY; attach this doctor output to issue #18."
        )
    elif snapshot.fallback_used:
        recommendations.append(
            "Snapshot used last-good cache: live sources are degraded; inspect snapshot.errors for the failing provider."
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
    if not recommendations:
        recommendations.append("Data sources look usable for a basic AlphaSift run.")
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
