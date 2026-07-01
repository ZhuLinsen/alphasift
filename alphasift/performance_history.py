# -*- coding: utf-8 -*-
"""Saved evaluation performance summaries for UI and agent integrations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from alphasift.models import EvaluationResult, PickEvaluation
from alphasift.store import evaluation_from_dict


def build_strategy_performance_summary(
    *,
    data_dir: Path,
    limit: int = 100,
    strategy: str | None = None,
) -> dict[str, object]:
    """Summarize saved T+N evaluation files without re-running live evaluation."""
    evaluations = _list_saved_evaluations(data_dir=data_dir, limit=limit, strategy=strategy)
    strategy_rows = [_strategy_summary(items) for items in _group_by_strategy(evaluations).values()]
    strategy_rows.sort(
        key=lambda item: (
            _score_value(item.get("performance_score")),
            str(item.get("latest_evaluated_at") or ""),
            str(item.get("strategy") or ""),
        ),
        reverse=True,
    )
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_count": len(evaluations),
        "strategy_count": len(strategy_rows),
        "limit": int(limit),
        "strategy_filter": strategy or "",
        "summary": _history_summary(evaluations),
        "strategies": strategy_rows,
        "leaderboard": strategy_rows[:10],
    }


def _list_saved_evaluations(
    *,
    data_dir: Path,
    limit: int,
    strategy: str | None,
) -> list[EvaluationResult]:
    evaluations_dir = data_dir / "evaluations"
    if not evaluations_dir.is_dir():
        return []
    limit = int(limit)
    if limit <= 0:
        return []
    rows: list[EvaluationResult] = []
    for path in sorted(evaluations_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        item = _load_evaluation(path)
        if item is None:
            continue
        if strategy and item.strategy != strategy:
            continue
        item.saved_path = str(path)
        rows.append(item)
        if len(rows) >= limit:
            break
    return rows


def _load_evaluation(path: Path) -> EvaluationResult | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    try:
        return evaluation_from_dict(data)
    except Exception:
        return None


def _group_by_strategy(evaluations: list[EvaluationResult]) -> dict[str, list[EvaluationResult]]:
    groups: dict[str, list[EvaluationResult]] = {}
    for item in evaluations:
        groups.setdefault(item.strategy or "unknown", []).append(item)
    return groups


def _strategy_summary(evaluations: list[EvaluationResult]) -> dict[str, object]:
    ordered = sorted(evaluations, key=_evaluation_sort_key, reverse=True)
    latest = ordered[0] if ordered else None
    pick_stats = _pick_stats(_all_picks(ordered))
    run_returns = _run_returns(ordered)
    missing_count = sum(len(item.missing_codes) for item in ordered)
    source_error_count = sum(len(item.source_errors) for item in ordered)
    degradation_count = sum(len(item.degradation) for item in ordered)
    performance_score = _performance_score(
        average_return_pct=pick_stats["average_return_pct"],
        win_rate=pick_stats["win_rate"],
        pick_count=pick_stats["pick_count"],
        missing_count=missing_count,
    )
    outcome = _performance_outcome(
        average_return_pct=pick_stats["average_return_pct"],
        win_rate=pick_stats["win_rate"],
    )
    return {
        "strategy": latest.strategy if latest else "unknown",
        "evaluation_count": len(ordered),
        "latest_run_id": latest.run_id if latest else "",
        "latest_evaluated_at": latest.evaluated_at if latest else "",
        "latest_elapsed_days": latest.elapsed_days if latest else None,
        "latest_snapshot_source": latest.snapshot_source if latest else "",
        "pick_count": pick_stats["pick_count"],
        "evaluated_pick_count": pick_stats["evaluated_pick_count"],
        "missing_count": missing_count,
        "missing_rate": _rate(missing_count, pick_stats["pick_count"]),
        "average_return_pct": pick_stats["average_return_pct"],
        "median_return_pct": pick_stats["median_return_pct"],
        "win_rate": pick_stats["win_rate"],
        "average_max_drawdown_pct": pick_stats["average_max_drawdown_pct"],
        "average_max_runup_pct": pick_stats["average_max_runup_pct"],
        "average_run_return_pct": _average(run_returns),
        "run_win_rate": _rate(sum(1 for value in run_returns if value > 0), len(run_returns), percent=True),
        "performance_score": performance_score,
        "outcome": outcome,
        "source_error_count": source_error_count,
        "degradation_count": degradation_count,
        "next_actions": _performance_actions(outcome),
        "recent_evaluations": [_compact_evaluation(item) for item in ordered[:5]],
    }


def _history_summary(evaluations: list[EvaluationResult]) -> dict[str, object]:
    ordered = sorted(evaluations, key=_evaluation_sort_key, reverse=True)
    pick_stats = _pick_stats(_all_picks(ordered))
    run_returns = _run_returns(ordered)
    missing_count = sum(len(item.missing_codes) for item in ordered)
    performance_score = _performance_score(
        average_return_pct=pick_stats["average_return_pct"],
        win_rate=pick_stats["win_rate"],
        pick_count=pick_stats["pick_count"],
        missing_count=missing_count,
    )
    outcome = _performance_outcome(
        average_return_pct=pick_stats["average_return_pct"],
        win_rate=pick_stats["win_rate"],
    )
    return {
        "evaluation_count": len(ordered),
        "pick_count": pick_stats["pick_count"],
        "evaluated_pick_count": pick_stats["evaluated_pick_count"],
        "missing_count": missing_count,
        "missing_rate": _rate(missing_count, pick_stats["pick_count"]),
        "average_return_pct": pick_stats["average_return_pct"],
        "median_return_pct": pick_stats["median_return_pct"],
        "win_rate": pick_stats["win_rate"],
        "average_run_return_pct": _average(run_returns),
        "run_win_rate": _rate(sum(1 for value in run_returns if value > 0), len(run_returns), percent=True),
        "performance_score": performance_score,
        "outcome": outcome,
        "latest_evaluation": _compact_evaluation(ordered[0]) if ordered else {},
        "next_actions": _performance_actions(outcome),
    }


def _pick_stats(picks: list[PickEvaluation]) -> dict[str, object]:
    returns = [float(item.return_pct) for item in picks if item.return_pct is not None]
    drawdowns = [float(item.max_drawdown_pct) for item in picks if item.max_drawdown_pct is not None]
    runups = [float(item.max_runup_pct) for item in picks if item.max_runup_pct is not None]
    return {
        "pick_count": len(picks),
        "evaluated_pick_count": len(returns),
        "average_return_pct": _average(returns),
        "median_return_pct": _median(returns),
        "win_rate": _rate(sum(1 for value in returns if value > 0), len(returns), percent=True),
        "average_max_drawdown_pct": _average(drawdowns),
        "average_max_runup_pct": _average(runups),
    }


def _all_picks(evaluations: list[EvaluationResult]) -> list[PickEvaluation]:
    picks: list[PickEvaluation] = []
    for item in evaluations:
        picks.extend(item.picks)
    return picks


def _run_returns(evaluations: list[EvaluationResult]) -> list[float]:
    values: list[float] = []
    for item in evaluations:
        if item.average_return_pct is not None:
            values.append(float(item.average_return_pct))
            continue
        returns = [float(pick.return_pct) for pick in item.picks if pick.return_pct is not None]
        if returns:
            values.append(sum(returns) / len(returns))
    return values


def _performance_score(
    *,
    average_return_pct: object,
    win_rate: object,
    pick_count: object,
    missing_count: int,
) -> float | None:
    if average_return_pct is None or win_rate is None or int(pick_count or 0) <= 0:
        return None
    missing_rate = float(missing_count) / float(pick_count or 1)
    score = 50.0 + (float(average_return_pct) * 2.0) + ((float(win_rate) - 50.0) * 0.5) - (missing_rate * 20.0)
    return round(max(0.0, min(100.0, score)), 1)


def _performance_outcome(*, average_return_pct: object, win_rate: object) -> str:
    if average_return_pct is None or win_rate is None:
        return "insufficient_data"
    avg = float(average_return_pct)
    wins = float(win_rate)
    if avg >= 2.0 and wins >= 60.0:
        return "strong"
    if avg > 0.0 and wins >= 50.0:
        return "positive"
    if avg < 0.0 and wins < 50.0:
        return "negative"
    return "mixed"


def _performance_actions(outcome: str) -> list[str]:
    if outcome == "insufficient_data":
        return ["Save more T+N evaluations before comparing strategy performance."]
    if outcome == "negative":
        return ["Review failure samples and tighten risk/event filters before reusing this strategy."]
    if outcome == "mixed":
        return ["Compare performance by event signals, shape status, and market regime before scaling usage."]
    if outcome == "positive":
        return ["Keep monitoring saved evaluations and compare against stronger strategy candidates."]
    if outcome == "strong":
        return ["Consider prioritizing this strategy while continuing T+N validation."]
    return []


def _compact_evaluation(item: EvaluationResult) -> dict[str, object]:
    return {
        "run_id": item.run_id,
        "strategy": item.strategy,
        "evaluated_at": item.evaluated_at,
        "elapsed_days": item.elapsed_days,
        "snapshot_source": item.snapshot_source,
        "pick_count": len(item.picks),
        "evaluated_pick_count": sum(1 for pick in item.picks if pick.return_pct is not None),
        "missing_count": len(item.missing_codes),
        "average_return_pct": item.average_return_pct,
        "win_rate": item.win_rate,
        "saved_path": item.saved_path,
    }


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(median(values)), 4)


def _rate(count: int, total: int, *, percent: bool = False) -> float | None:
    if total <= 0:
        return None
    value = float(count) / float(total)
    if percent:
        value *= 100.0
    return round(value, 4)


def _score_value(value: object) -> float:
    if value is None:
        return -1.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return -1.0


def _evaluation_sort_key(item: EvaluationResult) -> tuple[datetime, str]:
    return (_parse_datetime(item.evaluated_at), item.run_id)


def _parse_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.min
