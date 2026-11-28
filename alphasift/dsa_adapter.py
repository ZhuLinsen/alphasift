# -*- coding: utf-8 -*-
"""Stable DSA integration adapter.

DSA should depend on this module instead of AlphaSift internal pipeline,
strategy, or model details. Keep this contract backward-compatible.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List

from alphasift import __version__
from alphasift.jsonutil import finite_float, json_safe, safe_int
from alphasift.normalize import safe_bool, safe_text
from alphasift.pipeline import screen as run_screen
from alphasift.strategy import list_strategies as load_strategies

CONTRACT_VERSION = "1"


def _safe_list(value: Any) -> List[Any]:
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return []


def _safe_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return {str(key): json_safe(val) for key, val in value.items()}
    return {}


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
        "run_id": safe_text(result.run_id),
        "strategy": safe_text(result.strategy),
        "strategy_version": safe_text(result.strategy_version),
        "strategy_category": safe_text(result.strategy_category),
        "market": safe_text(result.market),
        "snapshot_count": max(safe_int(result.snapshot_count, default=0), 0),
        "after_filter_count": max(safe_int(result.after_filter_count, default=0), 0),
        "llm_ranked": safe_bool(result.llm_ranked) is True,
        "llm_market_view": safe_text(result.llm_market_view),
        "llm_selection_logic": safe_text(result.llm_selection_logic),
        "llm_portfolio_risk": safe_text(result.llm_portfolio_risk),
        "llm_coverage": finite_float(result.llm_coverage),
        "llm_parse_errors": _safe_list(result.llm_parse_errors),
        "candidate_count": len(picks),
        "candidates": picks,
        "warnings": _safe_list(result.degradation),
        "source_errors": _safe_list(result.source_errors),
    }


def _normalize_pick(raw: Any, fallback_rank: int) -> Dict[str, Any]:
    item = _to_plain(raw)
    if not isinstance(item, dict):
        item = {"code": safe_text(item)}
    raw_rank = safe_int(item.get("rank"), default=0)
    rank = raw_rank if raw_rank > 0 else max(safe_int(fallback_rank, default=1), 1)
    screen_score = finite_float(item.get("screen_score"))
    score = finite_float(item.get("final_score"))
    if score is None:
        score = screen_score
    raw_factors = item.get("factor_scores")
    factor_scores = (
        {
            str(key): num
            for key, val in raw_factors.items()
            if (num := finite_float(val)) is not None
        }
        if isinstance(raw_factors, dict)
        else {}
    )
    llm_thesis = safe_text(item.get("llm_thesis"))
    reason = (
        llm_thesis
        or safe_text(item.get("ranking_reason"))
        or safe_text(item.get("risk_summary"))
        or _build_reason(item)
    )
    return {
        "rank": rank,
        "code": (
            safe_text(item.get("code"))
            or safe_text(item.get("symbol"))
            or safe_text(item.get("stock_code"))
        ),
        "name": safe_text(item.get("name")) or safe_text(item.get("stock_name")),
        "score": score,
        "screen_score": screen_score,
        "reason": reason,
        "risk_level": safe_text(item.get("risk_level")),
        "risk_flags": _safe_list(item.get("risk_flags")),
        "llm_score": finite_float(item.get("llm_score")),
        "llm_confidence": finite_float(item.get("llm_confidence")),
        "llm_sector": safe_text(item.get("llm_sector")),
        "llm_theme": safe_text(item.get("llm_theme")),
        "llm_tags": _safe_list(item.get("llm_tags")),
        "llm_thesis": llm_thesis,
        "llm_catalysts": _safe_list(item.get("llm_catalysts")),
        "llm_risks": _safe_list(item.get("llm_risks")),
        "llm_watch_items": _safe_list(item.get("llm_watch_items")),
        "llm_invalidators": _safe_list(item.get("llm_invalidators")),
        "llm_style_fit": safe_text(item.get("llm_style_fit")),
        "price": finite_float(item.get("price")),
        "change_pct": finite_float(item.get("change_pct")),
        "amount": finite_float(item.get("amount")),
        "industry": safe_text(item.get("industry")),
        "factor_scores": factor_scores,
        "dsa_context": _safe_dict(item.get("dsa_context")),
        "dsa_news": _safe_list(item.get("dsa_news")),
        "dsa_analysis_summary": safe_text(item.get("dsa_analysis_summary")),
        "post_analysis_summaries": _safe_dict(item.get("post_analysis_summaries")),
        "post_analysis_tags": _safe_list(item.get("post_analysis_tags")),
        "raw": json_safe(item),
    }


def _build_reason(item: Dict[str, Any]) -> str:
    summaries = item.get("post_analysis_summaries") or {}
    if isinstance(summaries, dict):
        summary = next((text for value in summaries.values() if (text := safe_text(value))), "")
        if summary:
            return summary

    parts: List[str] = []
    factors = item.get("factor_scores") or {}
    if isinstance(factors, dict):
        clean_factors = [
            (str(key), num)
            for key, value in factors.items()
            if (num := finite_float(value)) is not None
        ]
        top_factors = sorted(
            clean_factors,
            key=lambda pair: pair[1],
            reverse=True,
        )[:3]
        if top_factors:
            factor_text = ", ".join(f"{key} {value:.1f}" for key, value in top_factors)
            parts.append(f"Top factors: {factor_text}")
    industry = safe_text(item.get("industry"))
    if industry:
        parts.append(f"Industry: {industry}")
    risk_level = safe_text(item.get("risk_level"))
    if risk_level:
        parts.append(f"Risk level: {risk_level}")
    return "; ".join(parts)


def _to_plain(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict") and callable(value.dict):
        return value.dict()
    return value
