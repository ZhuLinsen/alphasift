# -*- coding: utf-8 -*-
"""Runtime diagnostic helpers for AlphaSift data sources."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alphasift.config import Config
from alphasift.daily import daily_source_health_snapshot, fetch_daily_history
from alphasift.snapshot import (
    fetch_snapshot_with_fallback,
    snapshot_source_health_snapshot,
)


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


@dataclass
class DataSourcesDoctorResult:
    """Machine-readable data-source doctor report."""

    status: str
    generated_at: str
    config: dict[str, Any]
    snapshot: SourceCheckResult
    daily: SourceCheckResult | None = None
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
) -> DataSourcesDoctorResult:
    """Check snapshot and daily K-line source health without exposing secrets."""
    sources = list(snapshot_sources or config.snapshot_source_priority)
    daily_source_name = daily_source or config.daily_source
    snapshot = _check_snapshot_sources(config, sources=sources, run_live=run_live)
    daily = (
        _check_daily_sources(
            config,
            source=daily_source_name,
            code=daily_code,
            run_live=run_live,
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
        recommendations=recommendations,
    )


def _check_snapshot_sources(
    config: Config,
    *,
    sources: list[str],
    run_live: bool,
) -> SourceCheckResult:
    health = snapshot_source_health_snapshot(sources)
    if not run_live:
        return SourceCheckResult(status="skipped", sources=sources, health=health)
    try:
        df = fetch_snapshot_with_fallback(
            sources,
            required_columns=["code", "name", "price"],
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
        )
    return SourceCheckResult(
        status="ok" if not bool(df.attrs.get("fallback_used")) else "degraded",
        sources=sources,
        source=str(df.attrs.get("snapshot_source", "")),
        rows=int(len(df)),
        fallback_used=bool(df.attrs.get("fallback_used")),
        stale=bool(df.attrs.get("stale")),
        stale_age_hours=df.attrs.get("stale_age_hours"),
        errors=[str(item) for item in list(df.attrs.get("source_errors", []) or [])],
        health=snapshot_source_health_snapshot(sources),
    )


def _check_daily_sources(
    config: Config,
    *,
    source: str,
    code: str,
    run_live: bool,
) -> SourceCheckResult:
    health = daily_source_health_snapshot()
    if not run_live:
        return SourceCheckResult(status="skipped", sources=[source], health=health)
    try:
        df = fetch_daily_history(
            code,
            lookback_days=config.daily_lookback_days,
            source=source,
            retries=0,
            cache_dir=config.daily_history_cache_dir,
            cache_ttl_seconds=config.daily_history_cache_ttl_hours * 3600,
        )
    except Exception as exc:  # noqa: BLE001 - doctor must aggregate failures.
        return SourceCheckResult(
            status="failed",
            sources=[source],
            errors=[str(exc)],
            health=daily_source_health_snapshot(),
        )
    return SourceCheckResult(
        status="ok" if not bool(df.attrs.get("daily_stale")) else "degraded",
        sources=[source],
        source=str(df.attrs.get("daily_source", "")),
        rows=int(len(df)),
        fallback_used=bool(df.attrs.get("source_errors")),
        stale=bool(df.attrs.get("daily_stale")),
        errors=[str(item) for item in list(df.attrs.get("source_errors", []) or [])],
        health=daily_source_health_snapshot(),
    )


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
