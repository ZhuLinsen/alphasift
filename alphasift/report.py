# -*- coding: utf-8 -*-
"""Run report builders for human and UI surfaces."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alphasift.jsonutil import (
    atomic_write_strict_json,
    atomic_write_text,
    dumps_strict_json,
    finite_float,
    safe_int,
)
from alphasift.models import EvaluationResult, Pick, PickEvaluation, ScreenResult

RUN_REPORT_SCHEMA_VERSION = 1


def build_run_report_payload(
    result: ScreenResult,
    *,
    evaluation: EvaluationResult | None = None,
    max_picks: int = 10,
) -> dict[str, Any]:
    """Build a stable, UI-friendly report payload for a saved screen run."""
    max_picks = max(1, safe_int(max_picks, default=10))
    payload: dict[str, Any] = {
        "schema_version": RUN_REPORT_SCHEMA_VERSION,
        "object": "RunReport",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run": _run_summary(result),
        "summary_cards": _summary_cards(result, evaluation),
        "source_health": _source_health_summary(result),
        "top_picks": [_pick_card(pick) for pick in _sorted_picks(result.picks)[:max_picks]],
    }
    if evaluation is not None:
        payload["evaluation"] = _evaluation_summary(evaluation, max_picks=max_picks)
    return payload


def render_run_report_markdown(payload: dict[str, Any]) -> str:
    """Render a run report payload as Markdown."""
    run = payload.get("run", {}) or {}
    lines = [
        "# AlphaSift Run Report",
        "",
        f"- run_id: {_fmt(run.get('run_id'))}",
        f"- strategy: {_fmt(run.get('strategy'))} v{_fmt(run.get('strategy_version'))}",
        f"- market: {_fmt(run.get('market'))}",
        f"- created_at: {_fmt(run.get('created_at'))}",
        f"- generated_at: {_fmt(payload.get('generated_at'))}",
        "",
        "## Summary",
        "",
        "| Metric | Value | Status |",
        "|---|---:|---|",
    ]
    for card in payload.get("summary_cards", []) or []:
        lines.append(
            f"| {_md(card.get('label'))} | {_md(card.get('value'))} | {_md(card.get('status'))} |"
        )

    source = payload.get("source_health", {}) or {}
    lines.extend([
        "",
        "## Source Health",
        "",
        f"- snapshot_source: {_fmt(source.get('snapshot_source'))}",
        f"- daily_enriched: {_fmt(source.get('daily_enriched'))}",
        f"- daily_enrich_count: {_fmt(source.get('daily_enrich_count'))}",
    ])
    if source.get("source_errors"):
        lines.append("- source_errors: " + "; ".join(str(item) for item in source["source_errors"]))
    if source.get("degradation"):
        lines.append("- degradation: " + "; ".join(str(item) for item in source["degradation"]))

    lines.extend([
        "",
        "## Top Picks",
        "",
        "| # | Code | Name | Final | Screen | Risk | Industry | Notes |",
        "|---:|---|---|---:|---:|---|---|---|",
    ])
    for pick in payload.get("top_picks", []) or []:
        notes = _pick_notes(pick)
        lines.append(
            "| "
            f"{_md(pick.get('rank'))} | {_md(pick.get('code'))} | {_md(pick.get('name'))} | "
            f"{_md(pick.get('final_score'))} | {_md(pick.get('screen_score'))} | "
            f"{_md(pick.get('risk_level'))} | {_md(pick.get('industry'))} | {_md(notes)} |"
        )

    evaluation = payload.get("evaluation")
    if isinstance(evaluation, dict):
        lines.extend(_render_evaluation_markdown(evaluation))
    return "\n".join(lines).rstrip() + "\n"


def write_run_report(
    path: str | Path,
    payload: dict[str, Any],
    *,
    json_output: bool = False,
) -> Path:
    """Write a run report payload as Markdown or JSON."""
    if json_output:
        return atomic_write_strict_json(path, payload, indent=2)
    return atomic_write_text(path, render_run_report_markdown(payload))


def _run_summary(result: ScreenResult) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "strategy": result.strategy,
        "market": result.market,
        "strategy_version": result.strategy_version,
        "strategy_category": result.strategy_category,
        "created_at": result.created_at,
        "snapshot_count": _non_neg_int(result.snapshot_count),
        "after_filter_count": _non_neg_int(result.after_filter_count),
        "pick_count": len(result.picks),
        "llm_ranked": bool(result.llm_ranked),
        "llm_coverage": finite_float(result.llm_coverage),
        "post_analyzers": list(result.post_analyzers),
        "saved_path": result.saved_path,
    }


def _summary_cards(
    result: ScreenResult,
    evaluation: EvaluationResult | None,
) -> list[dict[str, Any]]:
    snapshot_count = _non_neg_int(result.snapshot_count)
    after_filter_count = _non_neg_int(result.after_filter_count)
    cards = [
        _card("Snapshot Rows", snapshot_count, _count_status(snapshot_count)),
        _card("After Filter", after_filter_count, _count_status(after_filter_count)),
        _card("Picks", len(result.picks), _count_status(len(result.picks))),
        _card("LLM Ranked", bool(result.llm_ranked), "ok" if result.llm_ranked else "skipped"),
        _card("Daily Enriched", bool(result.daily_enriched), "ok" if result.daily_enriched else "skipped"),
        _card(
            "Degradation",
            len(result.degradation),
            "degraded" if result.degradation else "ok",
        ),
    ]
    if evaluation is not None:
        avg_ret = _round_value(evaluation.average_return_pct)
        win_rate = _round_value(evaluation.win_rate)
        cards.extend([
            _card("Average Return %", avg_ret, _return_status(avg_ret)),
            _card("Win Rate %", win_rate, _win_rate_status(win_rate)),
            _card("Missing Quotes", len(evaluation.missing_codes), "degraded" if evaluation.missing_codes else "ok"),
        ])
    return cards


def _source_health_summary(result: ScreenResult) -> dict[str, Any]:
    return {
        "snapshot_source": result.snapshot_source,
        "source_errors": list(result.source_errors),
        "degradation": list(result.degradation),
        "daily_enriched": bool(result.daily_enriched),
        "daily_enrich_count": _non_neg_int(result.daily_enrich_count),
        "post_analyzers": list(result.post_analyzers),
        "portfolio_concentration_notes": list(result.portfolio_concentration_notes),
        "portfolio_topic_exposure": dict(result.portfolio_topic_exposure),
        "overconcentrated_topics": list(result.overconcentrated_topics),
        "replacement_candidates": list(result.replacement_candidates),
    }


def _sorted_picks(picks: list[Pick]) -> list[Pick]:
    return sorted(picks, key=lambda pick: (_rank_sort_value(pick.rank), -(finite_float(pick.final_score) or 0.0)))


def _pick_card(pick: Pick) -> dict[str, Any]:
    return {
        "rank": _opt_int(pick.rank),
        "code": pick.code,
        "name": pick.name,
        "final_score": _round_value(pick.final_score),
        "screen_score": _round_value(pick.screen_score),
        "price": _round_value(pick.price),
        "change_pct": _round_value(pick.change_pct),
        "industry": pick.industry,
        "concepts": pick.concepts,
        "topic_alignment_status": pick.topic_alignment_status,
        "topic_alignment_role": pick.topic_alignment_role,
        "topic_alignment_reason": pick.topic_alignment_reason,
        "matched_topics": list(pick.matched_topics),
        "unmatched_topics": list(pick.unmatched_topics),
        "board_heat_score": _round_value(pick.board_heat_score),
        "board_heat_state": pick.board_heat_state,
        "board_heat_summary": pick.board_heat_summary,
        "daily_quality_score": _round_value(pick.daily_quality_score),
        "daily_quality_flags": pick.daily_quality_flags,
        "daily_source": pick.daily_source,
        "signal_score": _round_value(pick.signal_score),
        "change_60d": _round_value(pick.change_60d),
        "volatility_20d_pct": _round_value(pick.volatility_20d_pct),
        "max_drawdown_20d_pct": _round_value(pick.max_drawdown_20d_pct),
        "atr_20_pct": _round_value(pick.atr_20_pct),
        "risk_score": _round_value(pick.risk_score),
        "risk_level": pick.risk_level,
        "risk_flags": list(pick.risk_flags),
        "portfolio_flags": list(pick.portfolio_flags),
        "ranking_reason": pick.ranking_reason,
        "llm_thesis": pick.llm_thesis,
        "llm_watch_items": list(pick.llm_watch_items),
        "llm_invalidators": list(pick.llm_invalidators),
        "post_analysis_status": dict(pick.post_analysis_status),
        "post_analysis_summaries": dict(pick.post_analysis_summaries),
        "post_analysis_tags": list(pick.post_analysis_tags),
    }


def _eval_pick_sort_key(item: PickEvaluation) -> tuple[bool, float, int]:
    ret = finite_float(item.return_pct)
    return (
        ret is None,
        -(ret if ret is not None else -999999.0),
        _rank_sort_value(item.rank),
    )


def _evaluation_summary(
    evaluation: EvaluationResult,
    *,
    max_picks: int,
) -> dict[str, Any]:
    horizon_days = _opt_int(evaluation.horizon_days)
    if horizon_days is not None and horizon_days <= 0:
        horizon_days = None
    return {
        "run_id": evaluation.run_id,
        "strategy": evaluation.strategy,
        "evaluated_at": evaluation.evaluated_at,
        "elapsed_days": _opt_int(evaluation.elapsed_days),
        "snapshot_source": evaluation.snapshot_source,
        "average_return_pct": _round_value(evaluation.average_return_pct),
        "median_return_pct": _round_value(evaluation.median_return_pct),
        "win_rate": _round_value(evaluation.win_rate),
        "entry_mode": evaluation.entry_mode,
        "horizon_days": horizon_days,
        "pending_count": _non_neg_int(evaluation.pending_count),
        "untradable_count": _non_neg_int(evaluation.untradable_count),
        "untradable_share_pct": _round_value(evaluation.untradable_share_pct),
        "missing_count": len(evaluation.missing_codes),
        "missing_codes": list(evaluation.missing_codes),
        "degradation": list(evaluation.degradation),
        "picks": [
            _evaluation_pick_card(pick)
            for pick in sorted(evaluation.picks, key=_eval_pick_sort_key)[:max_picks]
        ],
    }


def _evaluation_pick_card(pick: PickEvaluation) -> dict[str, Any]:
    return {
        "rank": _opt_int(pick.rank),
        "code": pick.code,
        "name": pick.name,
        "entry_price": _round_value(pick.entry_price),
        "entry_open": _round_value(pick.entry_open),
        "current_price": _round_value(pick.current_price),
        "return_pct": _round_value(pick.return_pct),
        "status": pick.status,
        "llm_tags": list(pick.llm_tags),
        "llm_catalysts": list(pick.llm_catalysts),
        "llm_risks": list(pick.llm_risks),
        "post_analysis_tags": list(pick.post_analysis_tags),
        "risk_level": pick.risk_level,
        "risk_flags": list(pick.risk_flags),
        "shape_status": pick.shape_status,
        "shape_tags": list(pick.shape_tags),
        "path_status": pick.path_status,
        "entry_date": pick.entry_date,
        "exit_date": pick.exit_date,
        "tradability_flags": list(pick.tradability_flags),
        "max_drawdown_pct": _round_value(pick.max_drawdown_pct),
        "max_runup_pct": _round_value(pick.max_runup_pct),
    }


def _render_evaluation_markdown(evaluation: dict[str, Any]) -> list[str]:
    lines = [
        "",
        "## Evaluation",
        "",
        f"- evaluated_at: {_fmt(evaluation.get('evaluated_at'))}",
        f"- elapsed_days: {_fmt(evaluation.get('elapsed_days'))}",
        f"- average_return_pct: {_fmt(evaluation.get('average_return_pct'))}",
        f"- median_return_pct: {_fmt(evaluation.get('median_return_pct'))}",
        f"- win_rate: {_fmt(evaluation.get('win_rate'))}",
        f"- missing_count: {_fmt(evaluation.get('missing_count'))}",
    ]
    next_open = evaluation.get("entry_mode") == "next_open"
    if evaluation.get("horizon_days") is not None:
        lines.extend([
            f"- window: T+{evaluation['horizon_days']}",
            f"- entry_mode: {_fmt(evaluation.get('entry_mode'))}",
            f"- pending_count: {_fmt(evaluation.get('pending_count'))}",
        ])
    if next_open:
        lines.extend([
            f"- untradable_count: {_fmt(evaluation.get('untradable_count'))}",
            f"- untradable_share_pct: {_fmt(evaluation.get('untradable_share_pct'))}",
        ])
        lines.extend(f"- {_md(note)}" for note in evaluation.get("degradation", []))
    lines.extend([
        "",
        "| # | Code | Name | Return % | Status | Shape | Max DD | Max Runup |"
        + (" Path status | Tradability flags |" if next_open else ""),
        "|---:|---|---|---:|---|---|---:|---:|" + ("---|---|" if next_open else ""),
    ])
    for pick in evaluation.get("picks", []) or []:
        lines.append(
            "| "
            f"{_md(pick.get('rank'))} | {_md(pick.get('code'))} | {_md(pick.get('name'))} | "
            f"{_md(pick.get('return_pct'))} | {_md(pick.get('status'))} | "
            f"{_md(pick.get('shape_status'))} | {_md(pick.get('max_drawdown_pct'))} | "
            f"{_md(pick.get('max_runup_pct'))} |"
            + (
                f" {_md(pick.get('path_status'))} | {_md(', '.join(pick.get('tradability_flags', [])))} |"
                if next_open else ""
            )
        )
    return lines


def _pick_notes(pick: dict[str, Any]) -> str:
    notes = []
    if pick.get("daily_quality_flags"):
        notes.append(f"daily={pick['daily_quality_flags']}")
    if pick.get("risk_flags"):
        notes.append("risk=" + ",".join(str(item) for item in pick["risk_flags"]))
    if pick.get("post_analysis_tags"):
        notes.append("post=" + ",".join(str(item) for item in pick["post_analysis_tags"]))
    if pick.get("ranking_reason"):
        notes.append(str(pick["ranking_reason"]))
    return "; ".join(notes)


def _card(label: str, value: Any, status: str) -> dict[str, Any]:
    return {"label": label, "value": value, "status": status}


def _count_status(value: int | float | None) -> str:
    num = finite_float(value)
    if num is None:
        return "unknown"
    return "ok" if num > 0 else "degraded"


def _return_status(value: float | None) -> str:
    num = finite_float(value)
    if num is None:
        return "unknown"
    return "ok" if num > 0 else "degraded"


def _win_rate_status(value: float | None) -> str:
    num = finite_float(value)
    if num is None:
        return "unknown"
    return "ok" if num >= 50 else "degraded"


def _round_value(value: Any) -> float | None:
    num = finite_float(value)
    return round(num, 4) if num is not None else None


def _non_neg_int(value: object) -> int:
    return max(safe_int(value, default=0), 0)


def _opt_int(value: object) -> int | None:
    num = finite_float(value)
    return int(num) if num is not None else None


def _rank_sort_value(value: object) -> int:
    parsed = _opt_int(value)
    return parsed if parsed is not None and parsed > 0 else 999999


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, (dict, list)):
        return dumps_strict_json(value, indent=None)
    return str(value)


def _md(value: Any) -> str:
    return _fmt(value).replace("|", "\\|").replace("\n", " ")


def report_payload_to_json(payload: dict[str, Any]) -> str:
    """Serialize report payload with stable JSON formatting."""
    return dumps_strict_json(payload, indent=2)
