# -*- coding: utf-8 -*-
"""Stable DSA integration adapter.

DSA should depend on this module instead of AlphaSift internal pipeline,
strategy, or model details. Keep this contract backward-compatible.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List

from alphasift import __version__
from alphasift.pipeline import screen as run_screen
from alphasift.strategy import list_strategies as load_strategies

CONTRACT_VERSION = "1"


def get_contract_version() -> str:
    """Return the stable adapter contract version."""
    return CONTRACT_VERSION


def get_status(context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Return non-sensitive adapter status for DSA health checks."""
    try:
        strategies = list_strategies(context=context)
        strategy_count = len(strategies)
        available = True
        error = ""
    except Exception as exc:  # pragma: no cover - defensive integration boundary
        strategy_count = 0
        available = False
        error = str(exc)

    payload: Dict[str, Any] = {
        "available": available,
        "version": __version__,
        "contract_version": CONTRACT_VERSION,
        "strategy_count": strategy_count,
    }
    if error:
        payload["error"] = error
    return payload


def list_strategies(context: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    """List enabled AlphaSift strategies using a DSA-stable shape."""
    return [
        {
            "id": item.name,
            "name": item.display_name,
            "description": item.description,
            "version": item.version,
            "category": item.category,
            "tags": list(item.tags),
            "market_scope": list(item.market_scope),
        }
        for item in load_strategies()
    ]


def screen(
    strategy: str,
    *,
    market: str = "cn",
    max_results: int = 20,
    use_llm: bool = True,
    context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Run one screening request and return a stable DSA response."""
    result = run_screen(
        strategy,
        market=market,
        max_output=max_results,
        use_llm=use_llm,
        context=context,
    )
    picks = [_normalize_pick(item, index + 1) for index, item in enumerate(result.picks)]
    return {
        "source": "alphasift",
        "contract_version": CONTRACT_VERSION,
        "run_id": result.run_id,
        "strategy": result.strategy,
        "strategy_version": result.strategy_version,
        "strategy_category": result.strategy_category,
        "market": result.market,
        "snapshot_count": result.snapshot_count,
        "after_filter_count": result.after_filter_count,
        "llm_ranked": result.llm_ranked,
        "llm_market_view": result.llm_market_view,
        "llm_selection_logic": result.llm_selection_logic,
        "llm_portfolio_risk": result.llm_portfolio_risk,
        "llm_coverage": result.llm_coverage,
        "llm_parse_errors": list(result.llm_parse_errors),
        "candidate_count": len(picks),
        "candidates": picks,
        "warnings": list(result.degradation),
        "source_errors": list(result.source_errors),
        "snapshot_source": result.snapshot_source,
        "daily_enriched": result.daily_enriched,
        "daily_enrich_count": result.daily_enrich_count,
        "risk_enabled": result.risk_enabled,
        "portfolio_diversity_enabled": result.portfolio_diversity_enabled,
        "portfolio_concentration_notes": list(result.portfolio_concentration_notes),
        "universe_audit": dict(result.universe_audit),
    }


def _normalize_pick(raw: Any, fallback_rank: int) -> Dict[str, Any]:
    item = _to_plain(raw)
    if not isinstance(item, dict):
        item = {"code": str(item)}
    score = item.get("final_score")
    if score is None:
        score = item.get("screen_score")
    reason = item.get("llm_thesis") or item.get("ranking_reason") or item.get("risk_summary") or _build_reason(item)
    return {
        "rank": item.get("rank") or fallback_rank,
        "code": item.get("code") or item.get("symbol") or item.get("stock_code") or "",
        "name": item.get("name") or item.get("stock_name") or "",
        "score": score,
        "screen_score": item.get("screen_score"),
        "reason": reason,
        "risk_level": item.get("risk_level") or "",
        "risk_flags": list(item.get("risk_flags") or []),
        "llm_score": item.get("llm_score"),
        "llm_confidence": item.get("llm_confidence"),
        "llm_sector": item.get("llm_sector") or "",
        "llm_theme": item.get("llm_theme") or "",
        "llm_tags": list(item.get("llm_tags") or []),
        "llm_thesis": item.get("llm_thesis") or "",
        "llm_catalysts": list(item.get("llm_catalysts") or []),
        "llm_risks": list(item.get("llm_risks") or []),
        "llm_watch_items": list(item.get("llm_watch_items") or []),
        "llm_invalidators": list(item.get("llm_invalidators") or []),
        "llm_style_fit": item.get("llm_style_fit") or "",
        "price": item.get("price"),
        "change_pct": item.get("change_pct"),
        "amount": item.get("amount"),
        "industry": item.get("industry") or "",
        "factor_scores": dict(item.get("factor_scores") or {}),
        "daily_source": item.get("daily_source") or "",
        "daily_adjustment": item.get("daily_adjustment") or "unknown",
        "daily_as_of": item.get("daily_as_of") or "",
        "daily_fetched_at": item.get("daily_fetched_at") or "",
        "daily_quality_score": item.get("daily_quality_score"),
        "daily_quality_flags": item.get("daily_quality_flags") or "",
        "main_wave_eligible": bool(item.get("main_wave_eligible")),
        "main_wave_ineligible_reasons": item.get("main_wave_ineligible_reasons") or "",
        "main_wave_raw_score": item.get("main_wave_raw_score"),
        "main_wave_raw_max_score": item.get("main_wave_raw_max_score", 50.0),
        "main_wave_score": item.get("main_wave_score"),
        "main_wave_max_score": item.get("main_wave_max_score", 100.0),
        "main_wave_hit_count": item.get("main_wave_hit_count", 0),
        "main_wave_rules": list(item.get("main_wave_rules") or []),
        "sentiment_available": bool(item.get("sentiment_available")),
        "sentiment_score": item.get("sentiment_score"),
        "sentiment_label": item.get("sentiment_label") or "unavailable",
        "sentiment_confidence": item.get("sentiment_confidence", 0.0),
        "sentiment_source_count": item.get("sentiment_source_count", 0),
        "sentiment_positive_events": list(item.get("sentiment_positive_events") or []),
        "sentiment_negative_events": list(item.get("sentiment_negative_events") or []),
        "sentiment_evidence": list(item.get("sentiment_evidence") or []),
        "sentiment_as_of": item.get("sentiment_as_of") or "",
        "sentiment_score_delta": item.get("sentiment_score_delta", 0.0),
        "dsa_context": dict(item.get("dsa_context") or {}),
        "dsa_news": list(item.get("dsa_news") or []),
        "dsa_analysis_summary": item.get("dsa_analysis_summary") or "",
        "post_analysis_summaries": dict(item.get("post_analysis_summaries") or {}),
        "post_analysis_tags": list(item.get("post_analysis_tags") or []),
        "raw": item,
    }


def _build_reason(item: Dict[str, Any]) -> str:
    summaries = item.get("post_analysis_summaries") or {}
    if isinstance(summaries, dict):
        summary = next((str(value) for value in summaries.values() if value), "")
        if summary:
            return summary

    parts: List[str] = []
    factors = item.get("factor_scores") or {}
    if isinstance(factors, dict):
        top_factors = sorted(
            ((key, value) for key, value in factors.items() if isinstance(value, (int, float))),
            key=lambda pair: pair[1],
            reverse=True,
        )[:3]
        if top_factors:
            factor_text = ", ".join(f"{key} {value:.1f}" for key, value in top_factors)
            parts.append(f"Top factors: {factor_text}")
    if item.get("industry"):
        parts.append(f"Industry: {item['industry']}")
    if item.get("risk_level"):
        parts.append(f"Risk level: {item['risk_level']}")
    return "; ".join(parts)


def _to_plain(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict") and callable(value.dict):
        return value.dict()
    return value
