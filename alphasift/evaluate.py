# -*- coding: utf-8 -*-
"""T+N evaluation for saved screening runs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from alphasift.config import Config
from alphasift.daily import fetch_daily_history
from alphasift.models import EvaluationResult, PickEvaluation, ScreenResult
from alphasift.normalize import normalize_code
from alphasift.snapshot import fetch_snapshot_with_fallback
from alphasift.store import list_saved_runs, load_screen_result


def _normalize_code(value: object) -> str:
    # Stored picks and snapshot code columns are structured fields, so
    # US tickers may pass through (see normalize_code docstring).
    return normalize_code(value, allow_ticker=True)


def evaluate_saved_run(
    run_ref: str | Path,
    *,
    config: Config | None = None,
    current_snapshot: pd.DataFrame | None = None,
    cost_bps: float | None = None,
    follow_through_pct: float | None = None,
    failed_breakout_pct: float | None = None,
    price_paths: dict[str, pd.DataFrame] | None = None,
    with_price_path: bool | None = None,
    price_path_lookback_days: int | None = None,
) -> EvaluationResult:
    """Evaluate saved picks against the latest snapshot price."""
    if config is None:
        config = Config.from_env()

    run = load_screen_result(run_ref, data_dir=config.data_dir)
    if current_snapshot is None:
        current_snapshot = fetch_snapshot_with_fallback(
            config.snapshot_source_priority,
            fallback_snapshot_path=config.fallback_snapshot_path,
            fallback_max_age_hours=config.snapshot_fallback_max_age_hours,
        )
    if cost_bps is None:
        cost_bps = config.evaluation_cost_bps
    if follow_through_pct is None:
        follow_through_pct = config.evaluation_follow_through_pct
    if failed_breakout_pct is None:
        failed_breakout_pct = config.evaluation_failed_breakout_pct
    if with_price_path is None:
        with_price_path = config.evaluation_price_path_enabled
    if price_path_lookback_days is None:
        price_path_lookback_days = config.evaluation_price_path_lookback_days

    snapshot_source = str(current_snapshot.attrs.get("snapshot_source", ""))
    source_errors = [str(item) for item in current_snapshot.attrs.get("source_errors", [])]
    by_code = _snapshot_by_code(current_snapshot)
    evaluations: list[PickEvaluation] = []
    returns: list[float] = []
    missing_codes: list[str] = []
    path_errors: list[str] = []
    effective_price_paths = _normalize_price_path_mapping(price_paths)
    if with_price_path:
        fetched_paths, path_errors = _fetch_price_paths(
            run,
            existing=effective_price_paths,
            lookback_days=price_path_lookback_days,
            source=config.daily_source,
            retries=config.daily_fetch_retries,
            max_workers=config.daily_fetch_max_workers,
            cache_dir=_daily_history_cache_dir(config),
            cache_ttl_seconds=_daily_history_cache_ttl_seconds(config),
        )
        effective_price_paths.update(fetched_paths)

    for pick in run.picks:
        code = _normalize_code(pick.code)
        current_price = by_code.get(code)
        status = "ok"
        return_pct = None
        if current_price is None:
            status = "missing"
            missing_codes.append(pick.code)
        elif pick.price <= 0:
            status = "bad_entry_price"
        else:
            return_pct = (current_price / pick.price - 1.0) * 100
            return_pct -= float(cost_bps) / 100.0
            returns.append(return_pct)
        shape_status, shape_tags = _classify_shape_status(
            pick,
            return_pct,
            follow_through_pct=float(follow_through_pct),
            failed_breakout_pct=float(failed_breakout_pct),
        )
        path_metrics = _price_path_metrics(
            effective_price_paths.get(code),
            entry_price=pick.price,
            created_at=run.created_at,
            cost_bps=float(cost_bps),
        )
        evaluations.append(PickEvaluation(
            code=pick.code,
            name=pick.name,
            rank=pick.rank,
            entry_price=pick.price,
            current_price=current_price,
            return_pct=None if return_pct is None else round(return_pct, 4),
            final_score=pick.final_score,
            status=status,
            llm_sector=pick.llm_sector or pick.industry,
            llm_theme=pick.llm_theme,
            llm_tags=list(pick.llm_tags),
            risk_level=pick.risk_level,
            risk_flags=list(pick.risk_flags),
            portfolio_flags=list(pick.portfolio_flags),
            shape_status=shape_status,
            shape_tags=shape_tags,
            path_status=path_metrics["path_status"],
            path_days=path_metrics["path_days"],
            path_end_return_pct=path_metrics["path_end_return_pct"],
            max_drawdown_pct=path_metrics["max_drawdown_pct"],
            max_runup_pct=path_metrics["max_runup_pct"],
        ))

    return EvaluationResult(
        run_id=run.run_id,
        strategy=run.strategy,
        market=run.market,
        created_at=run.created_at,
        elapsed_days=_elapsed_days(run),
        snapshot_source=snapshot_source,
        source_errors=source_errors,
        picks=evaluations,
        average_return_pct=_safe_round(sum(returns) / len(returns)) if returns else None,
        median_return_pct=_safe_round(float(pd.Series(returns).median())) if returns else None,
        win_rate=_safe_round(sum(1 for item in returns if item > 0) / len(returns) * 100) if returns else None,
        missing_codes=missing_codes,
        degradation=[
            *[f"Missing current quote for {code}" for code in missing_codes],
            *path_errors,
        ],
    )


def evaluate_result_against_snapshot(
    run: ScreenResult,
    snapshot: pd.DataFrame,
    *,
    cost_bps: float = 0.0,
    follow_through_pct: float = 3.0,
    failed_breakout_pct: float = -3.0,
    price_paths: dict[str, pd.DataFrame] | None = None,
) -> EvaluationResult:
    """Convenience helper for tests and custom integrations."""
    by_code = _snapshot_by_code(snapshot)
    picks = []
    returns = []
    missing = []
    effective_price_paths = _normalize_price_path_mapping(price_paths)
    for pick in run.picks:
        code = _normalize_code(pick.code)
        current_price = by_code.get(code)
        return_pct = None
        status = "missing"
        if current_price is not None and pick.price > 0:
            return_pct = (current_price / pick.price - 1.0) * 100
            return_pct -= float(cost_bps) / 100.0
            returns.append(return_pct)
            status = "ok"
        elif current_price is not None:
            status = "bad_entry_price"
        else:
            missing.append(pick.code)
        shape_status, shape_tags = _classify_shape_status(
            pick,
            return_pct,
            follow_through_pct=follow_through_pct,
            failed_breakout_pct=failed_breakout_pct,
        )
        path_metrics = _price_path_metrics(
            effective_price_paths.get(code),
            entry_price=pick.price,
            created_at=run.created_at,
            cost_bps=float(cost_bps),
        )
        picks.append(PickEvaluation(
            code=pick.code,
            name=pick.name,
            rank=pick.rank,
            entry_price=pick.price,
            current_price=current_price,
            return_pct=None if return_pct is None else round(return_pct, 4),
            final_score=pick.final_score,
            status=status,
            llm_sector=pick.llm_sector or pick.industry,
            llm_theme=pick.llm_theme,
            llm_tags=list(pick.llm_tags),
            risk_level=pick.risk_level,
            risk_flags=list(pick.risk_flags),
            portfolio_flags=list(pick.portfolio_flags),
            shape_status=shape_status,
            shape_tags=shape_tags,
            path_status=path_metrics["path_status"],
            path_days=path_metrics["path_days"],
            path_end_return_pct=path_metrics["path_end_return_pct"],
            max_drawdown_pct=path_metrics["max_drawdown_pct"],
            max_runup_pct=path_metrics["max_runup_pct"],
        ))
    return EvaluationResult(
        run_id=run.run_id,
        strategy=run.strategy,
        market=run.market,
        created_at=run.created_at,
        elapsed_days=_elapsed_days(run),
        snapshot_source=str(snapshot.attrs.get("snapshot_source", "")),
        source_errors=[str(item) for item in snapshot.attrs.get("source_errors", [])],
        picks=picks,
        average_return_pct=_safe_round(sum(returns) / len(returns)) if returns else None,
        median_return_pct=_safe_round(float(pd.Series(returns).median())) if returns else None,
        win_rate=_safe_round(sum(1 for item in returns if item > 0) / len(returns) * 100) if returns else None,
        missing_codes=missing,
        degradation=[f"Missing current quote for {code}" for code in missing],
    )


def evaluate_saved_runs(
    *,
    config: Config | None = None,
    current_snapshot: pd.DataFrame | None = None,
    limit: int = 20,
    strategy: str | None = None,
    cost_bps: float | None = None,
    follow_through_pct: float | None = None,
    failed_breakout_pct: float | None = None,
    with_price_path: bool | None = None,
    price_path_lookback_days: int | None = None,
) -> dict[str, object]:
    """Evaluate multiple saved runs with one current snapshot and aggregate stats."""
    if config is None:
        config = Config.from_env()
    if current_snapshot is None:
        current_snapshot = fetch_snapshot_with_fallback(
            config.snapshot_source_priority,
            fallback_snapshot_path=config.fallback_snapshot_path,
            fallback_max_age_hours=config.snapshot_fallback_max_age_hours,
        )
    if cost_bps is None:
        cost_bps = config.evaluation_cost_bps
    if follow_through_pct is None:
        follow_through_pct = config.evaluation_follow_through_pct
    if failed_breakout_pct is None:
        failed_breakout_pct = config.evaluation_failed_breakout_pct
    if with_price_path is None:
        with_price_path = config.evaluation_price_path_enabled
    if price_path_lookback_days is None:
        price_path_lookback_days = config.evaluation_price_path_lookback_days

    run_items = list_saved_runs(
        data_dir=config.data_dir,
        limit=max(int(limit), 1),
        strategy=strategy,
    )

    evaluations: list[EvaluationResult] = []
    for item in run_items:
        try:
            evaluations.append(
                evaluate_saved_run(
                    str(item["path"]),
                    config=config,
                    current_snapshot=current_snapshot,
                    cost_bps=cost_bps,
                    follow_through_pct=follow_through_pct,
                    failed_breakout_pct=failed_breakout_pct,
                    with_price_path=with_price_path,
                    price_path_lookback_days=price_path_lookback_days,
                )
            )
        except Exception as exc:
            evaluations.append(EvaluationResult(
                run_id=str(item.get("run_id", "")),
                strategy=str(item.get("strategy", "")),
                market=str(item.get("market", "")),
                created_at=str(item.get("created_at", "")),
                snapshot_source=str(current_snapshot.attrs.get("snapshot_source", "")),
                source_errors=[str(err) for err in current_snapshot.attrs.get("source_errors", [])],
                degradation=[f"Failed to evaluate run: {exc}"],
            ))

    summary = _aggregate_evaluations(evaluations)
    portfolio_summary = _aggregate_portfolios(evaluations)
    by_strategy = {
        name: _aggregate_evaluations(items)
        for name, items in _group_by_strategy(evaluations).items()
    }
    portfolio_by_strategy = {
        name: _aggregate_portfolios(items)
        for name, items in _group_by_strategy(evaluations).items()
    }
    strategy_summaries = _strategy_summaries(evaluations)
    dimensions = {
        "by_sector": _aggregate_by_pick_label(evaluations, "llm_sector"),
        "by_theme": _aggregate_by_pick_label(evaluations, "llm_theme"),
        "by_tag": _aggregate_by_pick_multi_label(evaluations, "llm_tags"),
        "by_risk_flag": _aggregate_by_pick_multi_label(evaluations, "risk_flags"),
        "by_portfolio_flag": _aggregate_by_pick_multi_label(evaluations, "portfolio_flags"),
        "by_holding_period": _aggregate_by_holding_period(evaluations),
        "by_shape_status": _aggregate_by_pick_label(evaluations, "shape_status"),
        "by_shape_tag": _aggregate_by_pick_multi_label(evaluations, "shape_tags"),
        "by_path_status": _aggregate_by_pick_label(evaluations, "path_status"),
    }
    return {
        "evaluated_at": datetime.now().isoformat(),
        "snapshot_source": str(current_snapshot.attrs.get("snapshot_source", "")),
        "source_errors": [str(item) for item in current_snapshot.attrs.get("source_errors", [])],
        "limit": limit,
        "strategy_filter": strategy or "",
        "cost_bps": float(cost_bps),
        "follow_through_pct": float(follow_through_pct),
        "failed_breakout_pct": float(failed_breakout_pct),
        "with_price_path": bool(with_price_path),
        "price_path_lookback_days": int(price_path_lookback_days),
        "summary": summary,
        "portfolio_summary": portfolio_summary,
        "by_strategy": by_strategy,
        "portfolio_by_strategy": portfolio_by_strategy,
        "strategy_summaries": strategy_summaries,
        "dimensions": dimensions,
        "runs": [_evaluation_brief(item) for item in evaluations],
    }



def _normalize_price_windows(windows: list[int]) -> list[int]:
    unique: list[int] = []
    seen: set[int] = set()
    for window in windows:
        value = int(window)
        if value <= 0:
            continue
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return sorted(unique)


def evaluate_saved_runs_by_windows(
    *,
    windows: list[int],
    config: Config | None = None,
    current_snapshot: pd.DataFrame | None = None,
    limit: int = 20,
    strategy: str | None = None,
    cost_bps: float | None = None,
    follow_through_pct: float | None = None,
    failed_breakout_pct: float | None = None,
) -> dict[str, Any]:
    """Evaluate saved runs for multiple price-path windows."""
    normalized_windows = _normalize_price_windows(windows)
    if not normalized_windows:
        normalized_windows = [30]

    if config is None:
        config = Config.from_env()

    window_results: list[dict[str, Any]] = []
    for window_days in normalized_windows:
        window_results.append(
            evaluate_saved_runs(
                config=config,
                current_snapshot=current_snapshot,
                limit=limit,
                strategy=strategy,
                cost_bps=cost_bps,
                follow_through_pct=follow_through_pct,
                failed_breakout_pct=failed_breakout_pct,
                with_price_path=True,
                price_path_lookback_days=window_days,
            )
        )

    merged: dict[str, list[dict[str, Any]]] = {}
    for index, window_days in enumerate(normalized_windows):
        for summary in window_results[index].get("strategy_summaries", []):
            if not isinstance(summary, dict):
                continue
            strategy_name = str(summary.get("strategy", "unknown")) or "unknown"
            merged.setdefault(strategy_name, []).append(
                {
                    "window_days": window_days,
                    "average_return_pct": summary.get("average_return_pct"),
                    "win_rate": summary.get("win_rate"),
                    "average_max_drawdown_pct": summary.get("average_max_drawdown_pct"),
                    "average_max_runup_pct": summary.get("average_max_runup_pct"),
                    "failed_breakout_count": (summary.get("shape_status_counts", {}) or {}).get("failed_breakout", 0),
                    "breakout_follow_through_count": (summary.get("shape_status_counts", {}) or {}).get("breakout_follow_through", 0),
                    "missing_count": summary.get("missing_count", 0),
                    "shape_status_counts": summary.get("shape_status_counts", {}),
                    "pick_status_counts": summary.get("pick_status_counts", {}),
                }
            )

    summary_by_strategy: list[dict[str, Any]] = []
    for strategy_name, window_summaries in sorted(merged.items(), key=lambda item: item[0]):
        window_summaries.sort(key=lambda item: int(item.get("window_days", 0)))
        summary_by_strategy.append(
            {
                "strategy": strategy_name,
                "window_count": len(window_summaries),
                "window_summaries": window_summaries,
            }
        )

    base_payload = window_results[0]
    return {
        **{k: base_payload[k] for k in base_payload if k != "strategy_summaries"},
        "strategy_summaries": summary_by_strategy,
        "price_path_window_days": normalized_windows,
        "with_price_path": True,
    }


def _snapshot_by_code(snapshot: pd.DataFrame) -> dict[str, float]:
    if snapshot.empty or "code" not in snapshot.columns or "price" not in snapshot.columns:
        return {}
    result = {}
    for _, row in snapshot.iterrows():
        price = pd.to_numeric(row.get("price"), errors="coerce")
        if pd.notna(price):
            code = _normalize_code(row.get("code", ""))
            if code:
                result[code] = float(price)
    return result


def _normalize_price_path_mapping(
    price_paths: dict[str, pd.DataFrame] | None,
) -> dict[str, pd.DataFrame]:
    if not price_paths:
        return {}
    return {
        _normalize_code(code): path
        for code, path in price_paths.items()
        if _normalize_code(code) and isinstance(path, pd.DataFrame)
    }


def _fetch_price_paths(
    run: ScreenResult,
    *,
    existing: dict[str, pd.DataFrame],
    lookback_days: int,
    source: str,
    retries: int,
    max_workers: int = 1,
    cache_dir: str | Path | None = None,
    cache_ttl_seconds: float | None = None,
) -> tuple[dict[str, pd.DataFrame], list[str]]:
    paths: dict[str, pd.DataFrame] = {}
    errors: list[str] = []
    fetch_codes: list[str] = []
    seen_codes = set(existing)
    for pick in run.picks:
        code = _normalize_code(pick.code)
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        fetch_codes.append(code)

    def fetch_one(code: str) -> tuple[str, pd.DataFrame | None, str | None]:
        try:
            return code, fetch_daily_history(
                code,
                lookback_days=lookback_days,
                source=source,
                retries=retries,
                cache_dir=cache_dir,
                cache_ttl_seconds=cache_ttl_seconds,
            ), None
        except Exception as exc:
            return code, None, f"Price path fetch failed for {code}: {exc}"

    if len(fetch_codes) <= 1:
        fetched_rows = [fetch_one(code) for code in fetch_codes]
    else:
        worker_limit = min(max(1, int(max_workers)), len(fetch_codes))
        with ThreadPoolExecutor(max_workers=worker_limit) as executor:
            fetched_rows = list(executor.map(fetch_one, fetch_codes))

    for code, path, error in fetched_rows:
        if error:
            errors.append(error)
        elif path is not None:
            paths[code] = path
    return paths, errors


def _daily_history_cache_dir(config: Config) -> Path | None:
    configured = getattr(config, "daily_history_cache_dir", None)
    if configured is not None:
        return Path(configured)
    return Path(config.data_dir) / "daily_history"


def _daily_history_cache_ttl_seconds(config: Config) -> float:
    hours = getattr(config, "daily_history_cache_ttl_hours", 24)
    return max(0.0, float(hours)) * 60 * 60


def _price_path_metrics(
    path: pd.DataFrame | None,
    *,
    entry_price: float,
    created_at: str,
    cost_bps: float,
) -> dict[str, object]:
    empty = {
        "path_status": "",
        "path_days": None,
        "path_end_return_pct": None,
        "max_drawdown_pct": None,
        "max_runup_pct": None,
    }
    if path is None:
        return empty
    if entry_price <= 0:
        return {**empty, "path_status": "bad_entry_price"}
    df = _normalize_price_path(path)
    if df.empty:
        return {**empty, "path_status": "no_path"}
    df = _filter_path_after_created_at(df, created_at)
    if df.empty:
        return {**empty, "path_status": "no_path_after_entry"}

    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    high = pd.to_numeric(df["high"], errors="coerce").dropna()
    low = pd.to_numeric(df["low"], errors="coerce").dropna()
    if close.empty:
        return {**empty, "path_status": "no_close"}

    end_return = (float(close.iloc[-1]) / entry_price - 1.0) * 100 - cost_bps / 100.0
    max_runup = (float(high.max()) / entry_price - 1.0) * 100 if not high.empty else None
    max_drawdown = (float(low.min()) / entry_price - 1.0) * 100 if not low.empty else None
    return {
        "path_status": "ok",
        "path_days": int(len(close)),
        "path_end_return_pct": _safe_round(end_return),
        "max_drawdown_pct": _safe_round(min(max_drawdown, 0.0)) if max_drawdown is not None else None,
        "max_runup_pct": _safe_round(max(max_runup, 0.0)) if max_runup is not None else None,
    }


def _normalize_price_path(path: pd.DataFrame) -> pd.DataFrame:
    rename_map = {
        "日期": "date",
        "收盘": "close",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
    }
    df = path.rename(columns=rename_map).copy()
    if "close" not in df.columns:
        return pd.DataFrame()
    for column in ("close", "high", "low"):
        if column not in df.columns:
            df[column] = df["close"]
        df[column] = pd.to_numeric(df[column], errors="coerce")
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.sort_values("date")
    return df.dropna(subset=["close"]).copy()


def _filter_path_after_created_at(df: pd.DataFrame, created_at: str) -> pd.DataFrame:
    if "date" not in df.columns or df["date"].dropna().empty:
        return df
    try:
        created = pd.to_datetime(datetime.fromisoformat(created_at).date())
    except ValueError:
        return df
    return df[df["date"] >= created].copy()


def _classify_shape_status(
    pick,
    return_pct: float | None,
    *,
    follow_through_pct: float,
    failed_breakout_pct: float,
) -> tuple[str, list[str]]:
    tags: list[str] = []
    status = ""

    if pick.breakout_20d_pct is not None and pick.breakout_20d_pct >= -1.5:
        tags.append("breakout_setup")
        if return_pct is None:
            status = "breakout_pending"
        elif return_pct >= follow_through_pct:
            status = "breakout_follow_through"
        elif return_pct <= failed_breakout_pct:
            status = "failed_breakout"
        else:
            status = "breakout_unconfirmed"

    if pick.pullback_to_ma20_pct is not None and -3.0 <= pick.pullback_to_ma20_pct <= 6.0:
        tags.append("ma20_pullback_setup")
        if not status:
            if return_pct is None:
                status = "pullback_pending"
            elif return_pct > 0:
                status = "pullback_rebound"
            else:
                status = "pullback_failed"

    if pick.consolidation_days_20d is not None and pick.consolidation_days_20d >= 8:
        tags.append("consolidation_setup")

    return status, tags


def _aggregate_evaluations(evaluations: list[EvaluationResult]) -> dict[str, object]:
    returns = [
        float(pick.return_pct)
        for evaluation in evaluations
        for pick in evaluation.picks
        if pick.return_pct is not None
    ]
    drawdowns = [
        float(pick.max_drawdown_pct)
        for evaluation in evaluations
        for pick in evaluation.picks
        if pick.max_drawdown_pct is not None
    ]
    runups = [
        float(pick.max_runup_pct)
        for evaluation in evaluations
        for pick in evaluation.picks
        if pick.max_runup_pct is not None
    ]
    pick_count = sum(len(evaluation.picks) for evaluation in evaluations)
    missing_count = sum(len(evaluation.missing_codes) for evaluation in evaluations)
    return {
        "run_count": len(evaluations),
        "pick_count": pick_count,
        "evaluated_pick_count": len(returns),
        "missing_count": missing_count,
        "average_return_pct": _safe_round(sum(returns) / len(returns)) if returns else None,
        "median_return_pct": _safe_round(float(pd.Series(returns).median())) if returns else None,
        "win_rate": _safe_round(sum(1 for value in returns if value > 0) / len(returns) * 100)
        if returns else None,
        "path_pick_count": len(drawdowns),
        "average_max_drawdown_pct": _safe_round(sum(drawdowns) / len(drawdowns)) if drawdowns else None,
        "median_max_drawdown_pct": _safe_round(float(pd.Series(drawdowns).median())) if drawdowns else None,
        "average_max_runup_pct": _safe_round(sum(runups) / len(runups)) if runups else None,
        "median_max_runup_pct": _safe_round(float(pd.Series(runups).median())) if runups else None,
    }


def _aggregate_portfolios(evaluations: list[EvaluationResult]) -> dict[str, object]:
    returns: list[float] = []
    drawdowns: list[float] = []
    runups: list[float] = []
    evaluated_runs = 0
    for evaluation in evaluations:
        pick_returns = [
            float(pick.return_pct)
            for pick in evaluation.picks
            if pick.return_pct is not None
        ]
        if pick_returns:
            evaluated_runs += 1
            returns.append(sum(pick_returns) / len(pick_returns))
        pick_drawdowns = [
            float(pick.max_drawdown_pct)
            for pick in evaluation.picks
            if pick.max_drawdown_pct is not None
        ]
        if pick_drawdowns:
            drawdowns.append(sum(pick_drawdowns) / len(pick_drawdowns))
        pick_runups = [
            float(pick.max_runup_pct)
            for pick in evaluation.picks
            if pick.max_runup_pct is not None
        ]
        if pick_runups:
            runups.append(sum(pick_runups) / len(pick_runups))
    return {
        "run_count": len(evaluations),
        "evaluated_run_count": evaluated_runs,
        "average_portfolio_return_pct": _safe_round(sum(returns) / len(returns)) if returns else None,
        "median_portfolio_return_pct": _safe_round(float(pd.Series(returns).median())) if returns else None,
        "portfolio_win_rate": _safe_round(sum(1 for value in returns if value > 0) / len(returns) * 100)
        if returns else None,
        "path_run_count": len(drawdowns),
        "average_portfolio_max_drawdown_pct": _safe_round(sum(drawdowns) / len(drawdowns)) if drawdowns else None,
        "median_portfolio_max_drawdown_pct": _safe_round(float(pd.Series(drawdowns).median()))
        if drawdowns else None,
        "average_portfolio_max_runup_pct": _safe_round(sum(runups) / len(runups)) if runups else None,
        "median_portfolio_max_runup_pct": _safe_round(float(pd.Series(runups).median()))
        if runups else None,
    }


def _group_by_strategy(evaluations: list[EvaluationResult]) -> dict[str, list[EvaluationResult]]:
    result: dict[str, list[EvaluationResult]] = {}
    for item in evaluations:
        result.setdefault(item.strategy or "unknown", []).append(item)
    return result


def _strategy_summaries(evaluations: list[EvaluationResult]) -> list[dict[str, object]]:
    """Return stable per-strategy evaluation summaries for reports/UI."""
    summaries: list[dict[str, object]] = []
    for strategy, items in _group_by_strategy(evaluations).items():
        aggregate = _aggregate_evaluations(items)
        portfolio = _aggregate_portfolios(items)
        shape_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        for evaluation in items:
            for pick in evaluation.picks:
                shape = str(pick.shape_status or "unknown")
                shape_counts[shape] = shape_counts.get(shape, 0) + 1
                status = str(pick.status or "unknown")
                status_counts[status] = status_counts.get(status, 0) + 1
        summaries.append({
            "strategy": strategy,
            "run_count": aggregate["run_count"],
            "pick_count": aggregate["pick_count"],
            "evaluated_pick_count": aggregate["evaluated_pick_count"],
            "missing_count": aggregate["missing_count"],
            "average_return_pct": aggregate["average_return_pct"],
            "median_return_pct": aggregate["median_return_pct"],
            "win_rate": aggregate["win_rate"],
            "average_max_drawdown_pct": aggregate["average_max_drawdown_pct"],
            "average_max_runup_pct": aggregate["average_max_runup_pct"],
            "average_portfolio_return_pct": portfolio["average_portfolio_return_pct"],
            "portfolio_win_rate": portfolio["portfolio_win_rate"],
            "shape_status_counts": dict(sorted(shape_counts.items())),
            "pick_status_counts": dict(sorted(status_counts.items())),
            "outcome": _strategy_outcome(aggregate),
        })
    return sorted(
        summaries,
        key=lambda item: (
            item["average_return_pct"] is None,
            -(float(item["average_return_pct"]) if item["average_return_pct"] is not None else -999999.0),
            str(item["strategy"]),
        ),
    )


def _strategy_outcome(summary: dict[str, object]) -> str:
    avg = summary.get("average_return_pct")
    win_rate = summary.get("win_rate")
    if avg is None or win_rate is None:
        return "insufficient_data"
    avg_f = float(avg)
    win_f = float(win_rate)
    if avg_f > 0 and win_f >= 50:
        return "positive"
    if avg_f < 0 and win_f < 50:
        return "negative"
    return "mixed"


def _aggregate_by_pick_label(
    evaluations: list[EvaluationResult],
    field: str,
) -> dict[str, dict[str, object]]:
    groups: dict[str, list[float]] = {}
    for evaluation in evaluations:
        for pick in evaluation.picks:
            value = str(getattr(pick, field, "") or "unknown").strip() or "unknown"
            if pick.return_pct is not None:
                groups.setdefault(value, []).append(float(pick.return_pct))
            else:
                groups.setdefault(value, [])
    return {
        label: _return_stats(values)
        for label, values in sorted(groups.items())
    }


def _aggregate_by_pick_multi_label(
    evaluations: list[EvaluationResult],
    field: str,
) -> dict[str, dict[str, object]]:
    groups: dict[str, list[float]] = {}
    for evaluation in evaluations:
        for pick in evaluation.picks:
            labels = _normalize_labels(getattr(pick, field, []) or ["none"])
            for label in labels:
                key = str(label or "none").strip() or "none"
                if pick.return_pct is not None:
                    groups.setdefault(key, []).append(float(pick.return_pct))
                else:
                    groups.setdefault(key, [])
    return {
        label: _return_stats(values)
        for label, values in sorted(groups.items())
    }


def _normalize_labels(value: object) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()] or ["none"]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()] or ["none"]
    return ["none"]


def _aggregate_by_holding_period(evaluations: list[EvaluationResult]) -> dict[str, dict[str, object]]:
    groups: dict[str, list[float]] = {}
    for evaluation in evaluations:
        bucket = _holding_period_bucket(evaluation.elapsed_days)
        for pick in evaluation.picks:
            if pick.return_pct is not None:
                groups.setdefault(bucket, []).append(float(pick.return_pct))
            else:
                groups.setdefault(bucket, [])
    return {
        label: _return_stats(values)
        for label, values in sorted(groups.items())
    }


def _return_stats(values: list[float]) -> dict[str, object]:
    return {
        "pick_count": len(values),
        "average_return_pct": _safe_round(sum(values) / len(values)) if values else None,
        "median_return_pct": _safe_round(float(pd.Series(values).median())) if values else None,
        "win_rate": _safe_round(sum(1 for value in values if value > 0) / len(values) * 100)
        if values else None,
    }


def _holding_period_bucket(days: int | None) -> str:
    if days is None:
        return "unknown"
    if days <= 1:
        return "T+0_1"
    if days <= 5:
        return "T+2_5"
    if days <= 20:
        return "T+6_20"
    return "T+20_plus"


def _evaluation_brief(evaluation: EvaluationResult) -> dict[str, object]:
    return {
        "run_id": evaluation.run_id,
        "strategy": evaluation.strategy,
        "created_at": evaluation.created_at,
        "elapsed_days": evaluation.elapsed_days,
        "pick_count": len(evaluation.picks),
        "average_return_pct": evaluation.average_return_pct,
        "median_return_pct": evaluation.median_return_pct,
        "win_rate": evaluation.win_rate,
        "portfolio_return_pct": evaluation.average_return_pct,
        "path_pick_count": sum(1 for pick in evaluation.picks if pick.path_status == "ok"),
        "average_max_drawdown_pct": _safe_round(
            sum(float(pick.max_drawdown_pct) for pick in evaluation.picks if pick.max_drawdown_pct is not None)
            / sum(1 for pick in evaluation.picks if pick.max_drawdown_pct is not None)
        ) if any(pick.max_drawdown_pct is not None for pick in evaluation.picks) else None,
        "missing_count": len(evaluation.missing_codes),
        "degradation": evaluation.degradation,
    }


def _elapsed_days(run: ScreenResult) -> int | None:
    try:
        created = datetime.fromisoformat(run.created_at)
    except ValueError:
        return None
    return (datetime.now() - created).days


def _safe_round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)
