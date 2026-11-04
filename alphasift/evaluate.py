# -*- coding: utf-8 -*-
"""T+N evaluation for saved screening runs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from alphasift.config import Config
from alphasift.daily import fetch_daily_history
from alphasift.markets import get_market
from alphasift.models import EvaluationResult, PickEvaluation, ScreenResult
from alphasift.normalize import normalize_code
from alphasift.snapshot import fetch_snapshot_with_fallback
from alphasift.snapshot_yahoo import fetch_yahoo_quotes
from alphasift.store import list_saved_runs, load_screen_result
from alphasift.timeutil import now_iso, parse_timestamp


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
    horizon_days: int | None = None,
    benchmark_paths: dict[str, pd.DataFrame] | None = None,
) -> EvaluationResult:
    """Evaluate saved picks.

    By default each pick's return is measured to the latest snapshot price.
    With ``horizon_days`` (T+N), the return is the close of the Nth trading
    bar after entry, compared with the market benchmark over the same bars.
    Picks whose window has not elapsed are reported as ``pending`` and kept
    out of averages. ``benchmark_paths`` caches benchmark history by market
    across runs.
    """
    if config is None:
        config = Config.from_env()

    run = load_screen_result(run_ref, data_dir=config.data_dir)
    if current_snapshot is None:
        # Must fetch the snapshot for the run's own market — a CN-default
        # snapshot can't resolve US tickers (or vice versa), which silently
        # marks every pick "missing" instead of evaluating it.
        current_snapshot = fetch_snapshot_with_fallback(
            config.snapshot_source_priority,
            fallback_snapshot_path=config.fallback_snapshot_path,
            fallback_max_age_hours=config.snapshot_fallback_max_age_hours,
            source_health_path=config.source_health_path,
            market=run.market,
        )
        current_snapshot = _fill_missing_quotes(
            current_snapshot, run.market, [pick.code for pick in run.picks]
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
    if horizon_days is not None:
        horizon_days = max(int(horizon_days), 1)
        with_price_path = True
        # Cover entry -> today; the window is cut from the post-entry bars.
        elapsed = _elapsed_days(run) or 0
        price_path_lookback_days = max(int(price_path_lookback_days), elapsed + 10)

    snapshot_source = str(current_snapshot.attrs.get("snapshot_source", ""))
    source_errors = [str(item) for item in current_snapshot.attrs.get("source_errors", [])]
    by_code = _snapshot_by_code(current_snapshot)
    evaluations: list[PickEvaluation] = []
    returns: list[float] = []
    missing_codes: list[str] = []
    path_errors: list[str] = []
    effective_price_paths = _normalize_price_path_mapping(price_paths)
    if with_price_path:
        # Same market-aware default as pipeline.py: config.daily_source's
        # "auto" chain is CN-only and cannot resolve Yahoo symbols.
        effective_daily_source = (
            "yfinance" if run.market != "cn" and config.daily_source in ("auto", "")
            else config.daily_source
        )
        fetched_paths, path_errors = _fetch_price_paths(
            run,
            existing=effective_price_paths,
            lookback_days=price_path_lookback_days,
            source=effective_daily_source,
            retries=config.daily_fetch_retries,
            max_workers=config.daily_fetch_max_workers,
            cache_dir=_daily_history_cache_dir(config),
            cache_ttl_seconds=_daily_history_cache_ttl_seconds(config),
        )
        effective_price_paths.update(fetched_paths)

    excess_returns: list[float] = []
    pending_count = 0
    benchmark_errors: list[str] = []
    benchmark_label = ""
    benchmark_return_pct: float | None = None
    benchmark_curve: pd.Series | None = None
    if horizon_days is not None:
        benchmark_return_pct, benchmark_label, benchmark_errors, benchmark_curve = _benchmark_return(
            run,
            horizon_days=horizon_days,
            lookback_days=int(price_path_lookback_days),
            cache=benchmark_paths,
        )

    for pick in run.picks:
        code = _normalize_code(pick.code)
        current_price = by_code.get(code)
        path_metrics = _price_path_metrics(
            effective_price_paths.get(code),
            entry_price=pick.price,
            created_at=run.created_at,
            cost_bps=float(cost_bps),
            market=run.market,
            horizon_days=horizon_days,
        )
        status = "ok"
        return_pct = None
        excess_return_pct = None
        pick_benchmark_pct = None
        if horizon_days is not None:
            # T+N: the return is the Nth post-entry close, not today's price.
            if pick.price <= 0:
                status = "bad_entry_price"
            elif path_metrics["path_status"] == "ok":
                return_pct = path_metrics["path_end_return_pct"]
                returns.append(float(return_pct))
                # Benchmark through this pick's own window end (same dates).
                pick_benchmark_pct = _benchmark_return_through(
                    benchmark_curve, path_metrics.get("path_end_date")
                )
                if pick_benchmark_pct is not None:
                    excess_return_pct = _safe_round(float(return_pct) - pick_benchmark_pct)
                    excess_returns.append(float(excess_return_pct))
            elif path_metrics["path_status"] == "pending":
                status = "pending"
                pending_count += 1
            else:
                status = "missing"
                missing_codes.append(pick.code)
        elif current_price is None:
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
            llm_catalysts=list(pick.llm_catalysts),
            llm_risks=list(pick.llm_risks),
            post_analysis_tags=list(pick.post_analysis_tags),
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
            horizon_days=horizon_days,
            benchmark_return_pct=pick_benchmark_pct,
            excess_return_pct=excess_return_pct,
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
            *[
                (f"Missing T+{horizon_days} price path for {code}" if horizon_days else f"Missing current quote for {code}")
                for code in missing_codes
            ],
            *path_errors,
            *benchmark_errors,
        ],
        horizon_days=horizon_days,
        benchmark=benchmark_label,
        benchmark_return_pct=benchmark_return_pct if horizon_days is not None else None,
        average_excess_return_pct=(
            _safe_round(sum(excess_returns) / len(excess_returns)) if excess_returns else None
        ),
        pending_count=pending_count,
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
            market=run.market,
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
            llm_catalysts=list(pick.llm_catalysts),
            llm_risks=list(pick.llm_risks),
            post_analysis_tags=list(pick.post_analysis_tags),
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
    market: str = "cn",
    cost_bps: float | None = None,
    follow_through_pct: float | None = None,
    failed_breakout_pct: float | None = None,
    with_price_path: bool | None = None,
    price_path_lookback_days: int | None = None,
    failure_sample_limit: int = 5,
    horizon_days: int | None = None,
    benchmark_paths: dict[str, pd.DataFrame] | None = None,
) -> dict[str, object]:
    """Evaluate multiple saved runs with one current snapshot and aggregate stats.

    A batch evaluates runs from a single market at a time: all runs share one
    freshly-fetched snapshot, and a CN snapshot can't resolve US tickers (or
    vice versa), so mixed-market batches would silently mark every pick from
    the other market "missing". Runs are filtered to `market` accordingly.
    """
    if config is None:
        config = Config.from_env()
    market = get_market(market).id  # saved runs store the lowercase id
    fetched_snapshot = current_snapshot is None
    if current_snapshot is None:
        current_snapshot = fetch_snapshot_with_fallback(
            config.snapshot_source_priority,
            fallback_snapshot_path=config.fallback_snapshot_path,
            fallback_max_age_hours=config.snapshot_fallback_max_age_hours,
            source_health_path=config.source_health_path,
            market=market,
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
        market=market,
    )
    if fetched_snapshot:
        current_snapshot = _fill_missing_quotes(
            current_snapshot, market, _saved_pick_codes(run_items, config)
        )

    shared_benchmark_paths = benchmark_paths if benchmark_paths is not None else {}
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
                    horizon_days=horizon_days,
                    benchmark_paths=shared_benchmark_paths,
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
        "by_llm_catalyst": _aggregate_by_pick_multi_label(evaluations, "llm_catalysts"),
        "by_llm_risk": _aggregate_by_pick_multi_label(evaluations, "llm_risks"),
        "by_post_analysis_tag": _aggregate_by_pick_multi_label(evaluations, "post_analysis_tags"),
        "by_risk_flag": _aggregate_by_pick_multi_label(evaluations, "risk_flags"),
        "by_portfolio_flag": _aggregate_by_pick_multi_label(evaluations, "portfolio_flags"),
        "by_holding_period": _aggregate_by_holding_period(evaluations),
        "by_shape_status": _aggregate_by_pick_label(evaluations, "shape_status"),
        "by_shape_tag": _aggregate_by_pick_multi_label(evaluations, "shape_tags"),
        "by_path_status": _aggregate_by_pick_label(evaluations, "path_status"),
    }
    return {
        "evaluated_at": now_iso(),
        "snapshot_source": str(current_snapshot.attrs.get("snapshot_source", "")),
        "source_errors": [str(item) for item in current_snapshot.attrs.get("source_errors", [])],
        "limit": limit,
        "strategy_filter": strategy or "",
        "cost_bps": float(cost_bps),
        "follow_through_pct": float(follow_through_pct),
        "failed_breakout_pct": float(failed_breakout_pct),
        "with_price_path": bool(with_price_path),
        "price_path_lookback_days": int(price_path_lookback_days),
        "horizon_days": horizon_days,
        "summary": summary,
        "portfolio_summary": portfolio_summary,
        "by_strategy": by_strategy,
        "portfolio_by_strategy": portfolio_by_strategy,
        "strategy_summaries": strategy_summaries,
        "dimensions": dimensions,
        "event_signal_review": _event_signal_review(evaluations),
        "failure_review": _failure_review(
            evaluations,
            sample_limit=failure_sample_limit,
        ),
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
    market: str = "cn",
    cost_bps: float | None = None,
    follow_through_pct: float | None = None,
    failed_breakout_pct: float | None = None,
    failure_sample_limit: int = 5,
) -> dict[str, Any]:
    """Evaluate saved runs at fixed T+N horizons (trading bars after entry).

    Each window measures every pick at the close of its Nth post-entry bar and
    compares it with the market benchmark over the same bars. Runs whose
    window has not elapsed yet count as pending rather than as returns.
    """
    normalized_windows = _normalize_price_windows(windows)
    if not normalized_windows:
        normalized_windows = [30]

    if config is None:
        config = Config.from_env()

    if current_snapshot is None:
        # One live snapshot for every window instead of one per window.
        current_snapshot = fetch_snapshot_with_fallback(
            config.snapshot_source_priority,
            fallback_snapshot_path=config.fallback_snapshot_path,
            fallback_max_age_hours=config.snapshot_fallback_max_age_hours,
            source_health_path=config.source_health_path,
            market=get_market(market).id,
        )
    window_results: list[dict[str, Any]] = []
    benchmark_paths: dict[str, pd.DataFrame] = {}
    for window_days in normalized_windows:
        window_results.append(
            evaluate_saved_runs(
                config=config,
                current_snapshot=current_snapshot,
                limit=limit,
                strategy=strategy,
                market=market,
                cost_bps=cost_bps,
                follow_through_pct=follow_through_pct,
                failed_breakout_pct=failed_breakout_pct,
                with_price_path=True,
                horizon_days=window_days,
                benchmark_paths=benchmark_paths,
                failure_sample_limit=failure_sample_limit,
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
                    "evaluated_pick_count": summary.get("evaluated_pick_count", 0),
                    "pending_count": summary.get("pending_count", 0),
                    "benchmark": summary.get("benchmark", ""),
                    "average_benchmark_return_pct": summary.get("average_benchmark_return_pct"),
                    "average_excess_return_pct": summary.get("average_excess_return_pct"),
                    "beat_benchmark_rate": summary.get("beat_benchmark_rate"),
                    "benchmark_errors": summary.get("benchmark_errors", []),
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

    # Failures and event signals differ by horizon: a pick that is fine at T+5
    # can be a loser at T+20. Each window keeps its own reviews.
    window_reviews = [
        {
            "window_days": window_days,
            "event_signal_review": window_results[index].get("event_signal_review", {}),
            "failure_review": window_results[index].get("failure_review", {}),
        }
        for index, window_days in enumerate(normalized_windows)
    ]
    base_payload = window_results[0]
    return {
        **{k: base_payload[k] for k in base_payload if k != "strategy_summaries"},
        "strategy_summaries": summary_by_strategy,
        "price_path_window_days": normalized_windows,
        # Top-level summary, dimensions and reviews are those of the shortest window.
        "review_window_days": normalized_windows[0],
        "window_reviews": window_reviews,
        "with_price_path": True,
    }


def _fill_missing_quotes(
    snapshot: pd.DataFrame,
    market: str,
    codes: list[str],
) -> pd.DataFrame:
    """Add prices for saved non-CN picks that fell out of the screener universe.

    The Yahoo screener only returns names above the market's universe floor,
    so a pick that dropped below it would be marked missing and silently
    left out of returns. CN snapshots cover the whole market already.
    """
    if get_market(market).cn_rules:
        return snapshot
    have = set(_snapshot_by_code(snapshot))
    missing = [
        code for code in dict.fromkeys(_normalize_code(item) for item in codes)
        if code and code not in have
    ]
    if not missing:
        return snapshot
    attrs = dict(snapshot.attrs)
    errors = [str(item) for item in attrs.get("source_errors", [])]
    try:
        quotes = fetch_yahoo_quotes(missing)
    except Exception as exc:  # noqa: BLE001 - leave the picks missing, but say why
        errors.append(f"yahoo_quotes for {len(missing)} saved picks: {exc}")
        quotes = pd.DataFrame(columns=["code", "price"])
    unresolved = sorted(set(missing) - set(quotes["code"]))
    if unresolved:
        errors.append(f"yahoo_quotes: no price for {','.join(unresolved[:10])}")
    combined = pd.concat([snapshot, quotes], ignore_index=True) if not quotes.empty else snapshot.copy()
    combined.attrs = {**attrs, "source_errors": errors}
    return combined


def _saved_pick_codes(run_items: list[dict[str, Any]], config: Config) -> list[str]:
    codes: list[str] = []
    for item in run_items:
        try:
            run = load_screen_result(str(item["path"]), data_dir=config.data_dir)
        except Exception:  # noqa: BLE001 - the per-run loop reports load errors
            continue
        codes.extend(pick.code for pick in run.picks)
    return codes


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
    market: str = "cn",
    horizon_days: int | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Return path metrics over bars strictly after the entry session.

    With ``horizon_days`` the window is the first N post-entry bars (a true
    T+N); fewer bars than N means the window has not elapsed yet ("pending").
    The T+N return is close-to-close from the entry session's close in the
    same history, so it shares the benchmark's start and the history's
    split/dividend adjustment; the saved (possibly intraday, unadjusted)
    pick price is only the fallback. Without a horizon, the window runs from
    the saved entry price to the latest bar.
    """
    empty = {
        "path_status": "",
        "path_days": None,
        "path_end_return_pct": None,
        "max_drawdown_pct": None,
        "max_runup_pct": None,
        "path_end_date": None,
    }
    if path is None:
        return empty
    if entry_price <= 0:
        return {**empty, "path_status": "bad_entry_price"}
    as_of = now or _history_fetched_at(path)
    df = _normalize_price_path(path)
    if df.empty:
        return {**empty, "path_status": "no_path"}
    cutoff = entry_cutoff_date(created_at, market)
    if horizon_days and cutoff is not None and "date" in df.columns:
        entry_bars = df[df["date"].dt.normalize() <= pd.Timestamp(cutoff)]
        if not entry_bars.empty and float(entry_bars["close"].iloc[-1]) > 0:
            entry_price = float(entry_bars["close"].iloc[-1])
    df = _filter_path_after_entry(df, cutoff)
    # Only sessions that had closed when the history was fetched count; a bar
    # cached mid-session is not a close even after the session ends.
    df = _completed_sessions(df, market, now=as_of)
    if horizon_days:
        if len(df) < horizon_days:
            return {**empty, "path_status": "pending", "path_days": int(len(df))}
        df = df.head(int(horizon_days))
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
        "path_end_date": df["date"].iloc[-1] if "date" in df.columns else None,
        "path_days": int(len(close)),
        "path_end_return_pct": _safe_round(end_return),
        "max_drawdown_pct": _safe_round(min(max_drawdown, 0.0)) if max_drawdown is not None else None,
        "max_runup_pct": _safe_round(max(max_runup, 0.0)) if max_runup is not None else None,
    }


def entry_cutoff_date(created_at: str, market: str = "cn") -> date | None:
    """Return the last session date whose bar is at least partly pre-entry.

    ``created_at`` carries its UTC offset (older runs hold a naive local
    time, read as this machine's local time). It is converted to the
    exchange's timezone: a run created before the session open was priced off
    the previous close, so that day's bar is entirely post-entry; a run
    created during or after the session saw part of that day's bar, which must
    not count toward post-entry run-up or drawdown.
    """
    try:
        created = datetime.fromisoformat(str(created_at))
    except (TypeError, ValueError):
        return None
    try:
        spec = get_market(market or "cn")
    except ValueError:
        spec = get_market("cn")
    local = created.astimezone(ZoneInfo(spec.timezone))
    hour, minute = (int(part) for part in spec.session_open.split(":"))
    if local.time() < time(hour, minute):
        return local.date() - timedelta(days=1)
    return local.date()


def _completed_sessions(
    df: pd.DataFrame,
    market: str,
    *,
    now: datetime | None = None,
) -> pd.DataFrame:
    """Keep bars whose session had closed at ``now`` (default: the current time).

    Pass the history's fetch time as ``now`` so a bar captured mid-session is
    never treated as that session's close.
    """
    if "date" not in df.columns or df["date"].dropna().empty:
        return df
    try:
        spec = get_market(market or "cn")
    except ValueError:
        spec = get_market("cn")
    tz = ZoneInfo(spec.timezone)
    local_now = (now or datetime.now(tz)).astimezone(tz)
    hour, minute = (int(part) for part in spec.session_close.split(":"))
    dates = df["date"].dt.normalize()
    last_closed = pd.Timestamp(local_now.date())
    if local_now.time() < time(hour, minute):
        last_closed -= pd.Timedelta(days=1)
    return df[dates <= last_closed].copy()


def _history_fetched_at(path: pd.DataFrame) -> datetime | None:
    raw = getattr(path, "attrs", {}).get("fetched_at")
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return None


def _filter_path_after_entry(df: pd.DataFrame, cutoff: date | None) -> pd.DataFrame:
    if cutoff is None or "date" not in df.columns or df["date"].dropna().empty:
        return df
    dates = df["date"]
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_localize(None)
    return df[dates.dt.normalize() > pd.Timestamp(cutoff)].copy()


def _benchmark_return(
    run: ScreenResult,
    *,
    horizon_days: int,
    lookback_days: int,
    cache: dict[str, pd.DataFrame] | None,
) -> tuple[float | None, str, list[str], pd.DataFrame | None]:
    """Return the benchmark's T+N return plus its post-entry closes.

    The closes (indexed by date, as returns from the entry close) let each
    pick be compared through its own window end, which differs from the
    benchmark's when the stock skipped a session (suspension, holiday gap).
    """
    try:
        spec = get_market(run.market or "cn")
    except ValueError:
        return None, "", [f"Benchmark skipped: unsupported market {run.market!r}"], None
    label = spec.benchmark_name or spec.benchmark
    if not spec.benchmark:
        return None, label, [], None
    cutoff = entry_cutoff_date(run.created_at, spec.id)
    path = cache.get(spec.id) if cache is not None else None
    if path is not None and not _path_reaches(path, cutoff):
        # Cached for a newer run with a shorter lookback; batches list runs
        # newest first, so older runs need a longer history.
        path = None
    if path is None:
        try:
            path = _fetch_benchmark_path(spec.id, lookback_days=lookback_days)
        except Exception as exc:
            return None, label, [f"Benchmark {label} fetch failed: {exc}"], None
        if cache is not None:
            cache[spec.id] = path
    # Entry level = the benchmark close on the entry cutoff session, so the
    # benchmark and the picks share the same start and the same N bars.
    df = _normalize_price_path(path)
    if df.empty or cutoff is None or "date" not in df.columns:
        return None, label, [f"Benchmark {label} has no usable history"], None
    dates = df["date"].dt.normalize()
    before = df[dates <= pd.Timestamp(cutoff)]
    if before.empty:
        return None, label, [f"Benchmark {label} history does not reach the entry date"], None
    entry_level = float(before["close"].iloc[-1])
    metrics = _price_path_metrics(
        path,
        entry_price=entry_level,
        created_at=run.created_at,
        cost_bps=0.0,
        market=spec.id,
        horizon_days=horizon_days,
    )
    after = _completed_sessions(
        _filter_path_after_entry(df, cutoff), spec.id, now=_history_fetched_at(path)
    )
    curve = pd.Series(
        (after["close"].to_numpy(dtype=float) / entry_level - 1.0) * 100,
        index=after["date"].dt.normalize(),
    )
    return metrics["path_end_return_pct"], label, [], curve


def _benchmark_return_through(curve: pd.Series | None, end_date) -> float | None:
    """Benchmark return from the entry close to the last close on or before ``end_date``."""
    if curve is None or curve.empty or end_date is None:
        return None
    upto = curve[curve.index <= pd.Timestamp(end_date).normalize()]
    return _safe_round(float(upto.iloc[-1])) if not upto.empty else None


def _path_reaches(path: pd.DataFrame, cutoff: date | None) -> bool:
    """True when the history has a bar on or before the entry cutoff session."""
    if cutoff is None:
        return True
    df = _normalize_price_path(path)
    if df.empty or "date" not in df.columns:
        return False
    return bool((df["date"].dt.normalize() <= pd.Timestamp(cutoff)).any())


def _fetch_benchmark_path(market: str, *, lookback_days: int) -> pd.DataFrame:
    spec = get_market(market or "cn")
    if not spec.benchmark:
        raise RuntimeError(f"no benchmark configured for market {spec.id}")
    fetched_at = datetime.now().astimezone()
    if spec.id == "cn":
        from alphasift.daily import _fetch_daily_tencent

        path = _fetch_daily_tencent(spec.benchmark, lookback_days=lookback_days)
    else:
        from alphasift.snapshot_us import fetch_daily_history_yfinance

        path = fetch_daily_history_yfinance(spec.benchmark, lookback_days=lookback_days)
    path.attrs["fetched_at"] = fetched_at.isoformat()
    return path


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
        if getattr(df["date"].dt, "tz", None) is not None:
            df["date"] = df["date"].dt.tz_localize(None)
        df = df.sort_values("date")
    return df.dropna(subset=["close"]).copy()


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
    excess = [
        float(pick.excess_return_pct)
        for evaluation in evaluations
        for pick in evaluation.picks
        if pick.excess_return_pct is not None
    ]
    # Pick-weighted like the return and excess averages, so ret - bench == excess.
    benchmark_returns = [
        float(pick.benchmark_return_pct)
        for evaluation in evaluations
        for pick in evaluation.picks
        if pick.excess_return_pct is not None and pick.benchmark_return_pct is not None
    ]
    benchmarks = sorted({evaluation.benchmark for evaluation in evaluations if evaluation.benchmark})
    benchmark_errors = _dedupe_strings(
        item
        for evaluation in evaluations
        for item in evaluation.degradation
        if str(item).startswith("Benchmark ")
    )
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
        "pending_count": sum(evaluation.pending_count for evaluation in evaluations),
        "benchmark": ",".join(benchmarks),
        # Why bench/excess are empty when they are: fetch failures, short history.
        "benchmark_errors": benchmark_errors,
        "average_benchmark_return_pct": (
            _safe_round(sum(benchmark_returns) / len(benchmark_returns)) if benchmark_returns else None
        ),
        "average_excess_return_pct": _safe_round(sum(excess) / len(excess)) if excess else None,
        "beat_benchmark_rate": (
            _safe_round(sum(1 for value in excess if value > 0) / len(excess) * 100) if excess else None
        ),
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
            "pending_count": aggregate["pending_count"],
            "benchmark": aggregate["benchmark"],
            "average_benchmark_return_pct": aggregate["average_benchmark_return_pct"],
            "average_excess_return_pct": aggregate["average_excess_return_pct"],
            "benchmark_errors": aggregate["benchmark_errors"],
            "beat_benchmark_rate": aggregate["beat_benchmark_rate"],
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


def _failure_review(
    evaluations: list[EvaluationResult],
    *,
    sample_limit: int = 5,
) -> dict[str, object]:
    samples = _failure_samples(evaluations)
    shown_samples = samples[:max(0, int(sample_limit))]
    dimensions = {
        "by_strategy": _aggregate_failure_dimension(samples, "strategy"),
        "by_sector": _aggregate_failure_dimension(samples, "llm_sector"),
        "by_theme": _aggregate_failure_dimension(samples, "llm_theme"),
        "by_risk_flag": _aggregate_failure_dimension(samples, "risk_flags", multi=True),
        "by_portfolio_flag": _aggregate_failure_dimension(samples, "portfolio_flags", multi=True),
        "by_shape_status": _aggregate_failure_dimension(samples, "shape_status"),
        "by_shape_tag": _aggregate_failure_dimension(samples, "shape_tags", multi=True),
        "by_llm_tag": _aggregate_failure_dimension(samples, "llm_tags", multi=True),
        "by_llm_catalyst": _aggregate_failure_dimension(samples, "llm_catalysts", multi=True),
        "by_llm_risk": _aggregate_failure_dimension(samples, "llm_risks", multi=True),
        "by_post_analysis_tag": _aggregate_failure_dimension(samples, "post_analysis_tags", multi=True),
        "by_event_signal": _aggregate_failure_dimension(samples, "event_signals", multi=True),
        "by_failure_reason": _aggregate_failure_dimension(samples, "failure_reasons", multi=True),
    }
    returns = [
        float(item["return_pct"])
        for item in samples
        if item.get("return_pct") is not None
    ]
    negative_returns = [value for value in returns if value < 0]
    summary = {
        "failure_count": len(samples),
        "shown_failure_count": len(shown_samples),
        "negative_pick_count": sum(1 for item in samples if _is_negative_sample(item)),
        "missing_count": sum(1 for item in samples if item.get("status") != "ok"),
        "failed_breakout_count": sum(
            1 for item in samples if item.get("shape_status") == "failed_breakout"
        ),
        "severe_drawdown_count": sum(
            1
            for item in samples
            if item.get("max_drawdown_pct") is not None
            and float(item["max_drawdown_pct"]) <= -8.0
        ),
        "average_negative_return_pct": (
            _safe_round(sum(negative_returns) / len(negative_returns)) if negative_returns else None
        ),
        "worst_return_pct": _safe_round(min(returns)) if returns else None,
    }
    return {
        "summary": summary,
        "failure_samples": shown_samples,
        "dimensions": dimensions,
        "recommendations": _failure_recommendations(summary, dimensions),
    }


def _event_signal_review(evaluations: list[EvaluationResult]) -> dict[str, object]:
    groups: dict[str, list[tuple[EvaluationResult, PickEvaluation]]] = {}
    signal_occurrences = 0
    for evaluation in evaluations:
        for pick in evaluation.picks:
            if pick.status == "pending":
                # Unelapsed T+N windows would dilute win and failure rates.
                continue
            signals = [signal for signal in _event_signals(pick) if signal != "none"]
            for signal in signals:
                signal_occurrences += 1
                groups.setdefault(signal, []).append((evaluation, pick))

    signals = [
        _event_signal_stats(signal, items)
        for signal, items in groups.items()
    ]
    signals.sort(
        key=lambda item: (
            _event_signal_action_rank(str(item.get("action", ""))),
            item.get("average_return_pct") is None,
            -(
                float(item["average_return_pct"])
                if item.get("average_return_pct") is not None
                else -999999.0
            ),
            -int(item.get("pick_count", 0) or 0),
            str(item.get("signal", "")),
        )
    )
    summary = {
        "signal_count": len(signals),
        "signal_occurrence_count": signal_occurrences,
        "positive_signal_count": sum(1 for item in signals if item.get("action") == "prefer"),
        "negative_signal_count": sum(1 for item in signals if item.get("action") == "avoid"),
        "mixed_signal_count": sum(1 for item in signals if item.get("action") == "watch"),
    }
    patch_suggestions = _event_signal_strategy_patch_suggestions(evaluations)
    summary["patch_suggestion_count"] = len(patch_suggestions)
    return {
        "summary": summary,
        "signals": signals,
        "strategy_patch_suggestions": patch_suggestions,
        "recommendations": _event_signal_recommendations(signals),
    }


def _event_signal_stats(
    signal: str,
    items: list[tuple[EvaluationResult, PickEvaluation]],
) -> dict[str, object]:
    returns = [
        float(pick.return_pct)
        for _, pick in items
        if pick.return_pct is not None
    ]
    failures = [
        pick
        for _, pick in items
        if _failure_reasons(pick)
    ]
    strategies = _dedupe_strings(evaluation.strategy for evaluation, _ in items)
    sample_codes = _dedupe_strings(
        pick.code
        for _, pick in sorted(
            items,
            key=lambda item: (
                item[1].return_pct is None,
                float(item[1].return_pct or 0),
                item[0].strategy,
                item[1].rank,
            ),
        )
    )[:5]
    win_rate = (
        _safe_round(sum(1 for value in returns if value > 0) / len(returns) * 100)
        if returns
        else None
    )
    average = _safe_round(sum(returns) / len(returns)) if returns else None
    action = _event_signal_action(average, win_rate, len(failures), len(items))
    return {
        "signal": signal,
        "pick_count": len(items),
        "evaluated_pick_count": len(returns),
        "failure_count": len(failures),
        "failure_rate": _safe_round(len(failures) / len(items) * 100) if items else None,
        "average_return_pct": average,
        "median_return_pct": _safe_round(float(pd.Series(returns).median())) if returns else None,
        "win_rate": win_rate,
        "best_return_pct": _safe_round(max(returns)) if returns else None,
        "worst_return_pct": _safe_round(min(returns)) if returns else None,
        "strategies": strategies,
        "sample_codes": sample_codes,
        "action": action,
        "recommendation": _event_signal_action_text(signal, action),
    }


def _event_signal_action(
    average_return_pct: float | None,
    win_rate: float | None,
    failure_count: int,
    pick_count: int,
) -> str:
    if average_return_pct is None or win_rate is None:
        return "insufficient_data"
    failure_rate = failure_count / pick_count * 100 if pick_count else 0.0
    if average_return_pct > 0 and win_rate >= 50 and failure_rate < 50:
        return "prefer"
    if average_return_pct < 0 or win_rate < 50 or failure_rate >= 50:
        return "avoid"
    return "watch"


def _event_signal_action_text(signal: str, action: str) -> str:
    if action == "prefer":
        return f"Signal `{signal}` has positive follow-through; consider using it as a preferred event tag."
    if action == "avoid":
        return f"Signal `{signal}` has weak or negative follow-through; consider adding it to avoided_event_tags or risk penalties."
    if action == "watch":
        return f"Signal `{signal}` is mixed; keep collecting samples before changing strategy weights."
    return f"Signal `{signal}` has insufficient evaluated samples."


def _event_signal_action_rank(action: str) -> int:
    return {
        "avoid": 0,
        "prefer": 1,
        "watch": 2,
        "insufficient_data": 3,
    }.get(action, 4)


def _event_signal_recommendations(signals: list[dict[str, object]]) -> list[str]:
    recommendations: list[str] = []
    avoid = [item for item in signals if item.get("action") == "avoid"]
    prefer = [item for item in signals if item.get("action") == "prefer"]
    if avoid:
        labels = ", ".join(str(item.get("signal")) for item in avoid[:3])
        recommendations.append(f"Review avoided-event candidates first: {labels}.")
    if prefer:
        labels = ", ".join(str(item.get("signal")) for item in prefer[:3])
        recommendations.append(f"Preferred-event candidates with positive follow-through: {labels}.")
    if not recommendations:
        recommendations.append("No strong event-signal lessons yet; keep collecting saved runs and evaluations.")
    return recommendations


def _event_signal_strategy_patch_suggestions(
    evaluations: list[EvaluationResult],
) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[tuple[EvaluationResult, PickEvaluation]]] = {}
    for evaluation in evaluations:
        strategy = evaluation.strategy or "unknown"
        for pick in evaluation.picks:
            for signal in _event_signals(pick):
                if signal == "none":
                    continue
                groups.setdefault((strategy, signal), []).append((evaluation, pick))

    by_strategy: dict[str, list[dict[str, object]]] = {}
    for (strategy, signal), items in groups.items():
        stats = _event_signal_stats(signal, items)
        if stats.get("action") not in {"prefer", "avoid"}:
            continue
        if not stats.get("evaluated_pick_count"):
            continue
        by_strategy.setdefault(strategy, []).append(stats)

    suggestions: list[dict[str, object]] = []
    for strategy, signals in by_strategy.items():
        signals.sort(
            key=lambda item: (
                _event_signal_action_rank(str(item.get("action", ""))),
                item.get("average_return_pct") is None,
                -(
                    float(item["average_return_pct"])
                    if item.get("average_return_pct") is not None
                    else -999999.0
                ),
                str(item.get("signal", "")),
            )
        )
        preferred = _event_signal_patch_values(
            [item for item in signals if item.get("action") == "prefer"]
        )
        avoided = _event_signal_patch_values(
            [item for item in signals if item.get("action") == "avoid"]
        )
        if not preferred and not avoided:
            continue
        field_changes = _event_signal_field_changes(preferred=preferred, avoided=avoided)
        suggestions.append({
            "strategy": strategy,
            "preferred_event_tags": preferred,
            "avoided_event_tags": avoided,
            "field_changes": field_changes,
            "evidence": [_event_signal_patch_evidence(item) for item in signals],
            "yaml_patch": _event_signal_yaml_patch(preferred=preferred, avoided=avoided),
            "recommendation": _event_signal_patch_recommendation(
                strategy,
                preferred=preferred,
                avoided=avoided,
            ),
        })

    suggestions.sort(
        key=lambda item: (
            -len(item.get("avoided_event_tags", []) or []),
            -len(item.get("preferred_event_tags", []) or []),
            str(item.get("strategy", "")),
        )
    )
    return suggestions


def _event_signal_patch_values(signals: list[dict[str, object]]) -> list[str]:
    return _dedupe_strings(
        _event_signal_patch_value(str(item.get("signal", "")))
        for item in signals
    )


def _event_signal_patch_value(signal: str) -> str:
    prefix, separator, label = signal.partition(":")
    if not separator:
        return signal
    label = label.strip()
    if prefix == "risk":
        return f"风险:{label}"
    if prefix == "catalyst":
        return f"催化:{label}"
    if prefix == "post":
        return f"后验:{label}"
    return label


def _event_signal_field_changes(
    *,
    preferred: list[str],
    avoided: list[str],
) -> list[dict[str, object]]:
    changes: list[dict[str, object]] = []
    if preferred:
        changes.append({
            "path": "screening.event_profile.preferred_event_tags",
            "operation": "append_unique",
            "add": preferred,
        })
    if avoided:
        changes.append({
            "path": "screening.event_profile.avoided_event_tags",
            "operation": "append_unique",
            "add": avoided,
        })
    return changes


def _event_signal_patch_evidence(item: dict[str, object]) -> dict[str, object]:
    return {
        "signal": item.get("signal"),
        "action": item.get("action"),
        "pick_count": item.get("pick_count"),
        "evaluated_pick_count": item.get("evaluated_pick_count"),
        "average_return_pct": item.get("average_return_pct"),
        "win_rate": item.get("win_rate"),
        "failure_count": item.get("failure_count"),
        "failure_rate": item.get("failure_rate"),
        "sample_codes": item.get("sample_codes", []),
    }


def _event_signal_yaml_patch(
    *,
    preferred: list[str],
    avoided: list[str],
) -> str:
    lines = [
        "screening:",
        "  event_profile:",
    ]
    if preferred:
        lines.append("    preferred_event_tags:")
        lines.extend(f"      - {value}" for value in preferred)
    if avoided:
        lines.append("    avoided_event_tags:")
        lines.extend(f"      - {value}" for value in avoided)
    return "\n".join(lines)


def _event_signal_patch_recommendation(
    strategy: str,
    *,
    preferred: list[str],
    avoided: list[str],
) -> str:
    parts: list[str] = []
    if preferred:
        parts.append("prefer " + ", ".join(preferred[:3]))
    if avoided:
        parts.append("avoid " + ", ".join(avoided[:3]))
    return f"Review strategy `{strategy}` event_profile patch: {'; '.join(parts)}."


def _failure_samples(evaluations: list[EvaluationResult]) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for evaluation in evaluations:
        for pick in evaluation.picks:
            reasons = _failure_reasons(pick)
            if not reasons:
                continue
            samples.append({
                "run_id": evaluation.run_id,
                "strategy": evaluation.strategy,
                "created_at": evaluation.created_at,
                "elapsed_days": evaluation.elapsed_days,
                "code": pick.code,
                "name": pick.name,
                "rank": pick.rank,
                "entry_price": pick.entry_price,
                "current_price": pick.current_price,
                "return_pct": pick.return_pct,
                "final_score": pick.final_score,
                "status": pick.status,
                "llm_sector": pick.llm_sector,
                "llm_theme": pick.llm_theme,
                "llm_tags": list(pick.llm_tags),
                "llm_catalysts": list(pick.llm_catalysts),
                "llm_risks": list(pick.llm_risks),
                "post_analysis_tags": list(pick.post_analysis_tags),
                "event_signals": _event_signals(pick),
                "risk_level": pick.risk_level,
                "risk_flags": list(pick.risk_flags),
                "portfolio_flags": list(pick.portfolio_flags),
                "shape_status": pick.shape_status,
                "shape_tags": list(pick.shape_tags),
                "path_status": pick.path_status,
                "max_drawdown_pct": pick.max_drawdown_pct,
                "max_runup_pct": pick.max_runup_pct,
                "failure_reasons": reasons,
            })
    return sorted(samples, key=_failure_sample_sort_key)


def _failure_reasons(pick: PickEvaluation) -> list[str]:
    if pick.status == "pending":
        # The T+N window has not elapsed: no evidence either way yet.
        return []
    reasons: list[str] = []
    if pick.status != "ok":
        reasons.append(f"quote_status:{pick.status}")
    if pick.return_pct is not None and pick.return_pct < 0:
        reasons.append("negative_return")
        if pick.return_pct <= -5:
            reasons.append("large_loss")
    if pick.shape_status in {"failed_breakout", "pullback_failed"}:
        reasons.append(f"shape_status:{pick.shape_status}")
    elif pick.shape_status in {"breakout_unconfirmed"}:
        reasons.append("shape_status:breakout_unconfirmed")
    if pick.max_drawdown_pct is not None and pick.max_drawdown_pct <= -8:
        reasons.append("path_drawdown_breach")
    if pick.path_status and pick.path_status != "ok":
        reasons.append(f"path_status:{pick.path_status}")
    if not reasons:
        return []
    for flag in pick.risk_flags:
        reasons.append(f"risk_flag:{flag}")
    for flag in pick.portfolio_flags:
        reasons.append(f"portfolio_flag:{flag}")
    for risk in pick.llm_risks:
        reasons.append(f"llm_risk:{risk}")
    return _dedupe_strings(reasons)


def _failure_sample_sort_key(item: dict[str, object]) -> tuple[object, ...]:
    return_pct = item.get("return_pct")
    if return_pct is not None:
        return (0, float(return_pct), str(item.get("strategy", "")), int(item.get("rank", 0) or 0))
    return (1, str(item.get("status", "")), str(item.get("strategy", "")), int(item.get("rank", 0) or 0))


def _aggregate_failure_dimension(
    samples: list[dict[str, object]],
    field: str,
    *,
    multi: bool = False,
) -> dict[str, dict[str, object]]:
    groups: dict[str, list[dict[str, object]]] = {}
    for sample in samples:
        labels = _sample_labels(sample.get(field), multi=multi)
        for label in labels:
            groups.setdefault(label, []).append(sample)
    result: dict[str, dict[str, object]] = {}
    for label, items in groups.items():
        returns = [
            float(item["return_pct"])
            for item in items
            if item.get("return_pct") is not None
        ]
        result[label] = {
            "failure_count": len(items),
            "evaluated_failure_count": len(returns),
            "average_return_pct": _safe_round(sum(returns) / len(returns)) if returns else None,
            "worst_return_pct": _safe_round(min(returns)) if returns else None,
            "sample_codes": _dedupe_strings(
                str(item.get("code", ""))
                for item in sorted(items, key=_failure_sample_sort_key)
                if item.get("code")
            )[:3],
        }
    return dict(
        sorted(
            result.items(),
            key=lambda item: (
                -int(item[1]["failure_count"]),
                item[1]["worst_return_pct"] is None,
                float(item[1]["worst_return_pct"] or 0),
                item[0],
            ),
        )
    )


def _sample_labels(value: object, *, multi: bool) -> list[str]:
    if multi:
        return _normalize_labels(value or ["none"])
    text = str(value or "unknown").strip()
    return [text or "unknown"]


def _failure_recommendations(
    summary: dict[str, object],
    dimensions: dict[str, dict[str, dict[str, object]]],
) -> list[str]:
    if int(summary.get("failure_count", 0) or 0) == 0:
        return ["No evaluated failure samples yet; keep collecting saved runs before tuning strategy thresholds."]
    recommendations: list[str] = []
    if int(summary.get("missing_count", 0) or 0) > 0:
        recommendations.append(
            "Missing or bad current quotes appeared in failure samples; check snapshot source coverage before tuning strategy logic."
        )
    if int(summary.get("failed_breakout_count", 0) or 0) > 0:
        recommendations.append(
            "Failed breakout samples appeared; review breakout filters such as volume confirmation, MA20 position, and consolidation quality."
        )
    if int(summary.get("severe_drawdown_count", 0) or 0) > 0:
        recommendations.append(
            "Price-path drawdown breaches appeared; review stop-loss assumptions or tighten volatility and drawdown filters."
        )
    risk_item = _top_dimension_label(dimensions.get("by_risk_flag", {}), exclude={"none"})
    if risk_item:
        recommendations.append(
            f"Risk flag `{risk_item}` repeats in failure samples; consider adjusting risk_profile thresholds or penalties."
        )
    portfolio_item = _top_dimension_label(dimensions.get("by_portfolio_flag", {}), exclude={"none"})
    if portfolio_item:
        recommendations.append(
            f"Portfolio flag `{portfolio_item}` repeats in failure samples; review portfolio_profile concentration rules."
        )
    llm_risk_item = _top_dimension_label(dimensions.get("by_llm_risk", {}), exclude={"none"})
    if llm_risk_item:
        recommendations.append(
            f"LLM risk `{llm_risk_item}` repeats in failure samples; consider adding it to avoided_event_tags or risk_profile penalties."
        )
    event_item = _top_dimension_label(dimensions.get("by_event_signal", {}), exclude={"none"})
    if event_item:
        recommendations.append(
            f"Event signal `{event_item}` repeats in failure samples; compare its win/loss history before using it as a positive catalyst."
        )
    shape_item = _top_dimension_label(dimensions.get("by_shape_status", {}), exclude={"unknown", ""})
    if shape_item:
        recommendations.append(
            f"Shape outcome `{shape_item}` is a recurring failure bucket; compare it against strategy intent before raising exposure."
        )
    return _dedupe_strings(recommendations)


def _top_dimension_label(
    items: dict[str, dict[str, object]],
    *,
    exclude: set[str],
) -> str:
    for label, stats in items.items():
        if label in exclude:
            continue
        if int(stats.get("failure_count", 0) or 0) <= 0:
            continue
        return label
    return ""


def _is_negative_sample(item: dict[str, object]) -> bool:
    return item.get("return_pct") is not None and float(item["return_pct"]) < 0


def _event_signals(pick: PickEvaluation) -> list[str]:
    return _dedupe_strings([
        *[f"tag:{item}" for item in pick.llm_tags],
        *[f"catalyst:{item}" for item in pick.llm_catalysts],
        *[f"risk:{item}" for item in pick.llm_risks],
        *[f"post:{item}" for item in pick.post_analysis_tags],
    ]) or ["none"]


def _dedupe_strings(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


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
        "horizon_days": evaluation.horizon_days,
        "pending_count": evaluation.pending_count,
        "benchmark": evaluation.benchmark,
        "benchmark_return_pct": evaluation.benchmark_return_pct,
        "average_excess_return_pct": evaluation.average_excess_return_pct,
        "degradation": evaluation.degradation,
    }


def _elapsed_days(run: ScreenResult) -> int | None:
    created = parse_timestamp(run.created_at)
    if created is None:
        return None
    return (datetime.now(timezone.utc) - created).days


def _safe_round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)
