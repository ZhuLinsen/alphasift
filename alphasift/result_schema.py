# -*- coding: utf-8 -*-
"""Stable machine-readable result schema metadata."""

from __future__ import annotations

SCREEN_RESULT_SCHEMA_VERSION = 1

SCREEN_RESULT_SCHEMA: dict[str, object] = {
    "schema_version": SCREEN_RESULT_SCHEMA_VERSION,
    "object": "ScreenResult",
    "top_level_fields": [
        "strategy",
        "market",
        "strategy_version",
        "strategy_category",
        "snapshot_count",
        "after_filter_count",
        "picks",
        "run_id",
        "llm_ranked",
        "llm_coverage",
        "llm_parse_errors",
        "degradation",
        "snapshot_source",
        "source_errors",
        "deep_analysis_requested",
        "post_analyzers",
        "daily_enriched",
        "daily_enrich_count",
        "risk_enabled",
        "portfolio_diversity_enabled",
        "portfolio_concentration_notes",
        "created_at",
    ],
    "pick_fields": [
        "rank",
        "code",
        "name",
        "final_score",
        "screen_score",
        "factor_scores",
        "ranking_reason",
        "risk_summary",
        "risk_score",
        "risk_level",
        "risk_flags",
        "portfolio_penalty",
        "portfolio_flags",
        "industry",
        "concepts",
        "board_heat_score",
        "board_heat_summary",
        "daily_quality_score",
        "daily_quality_flags",
        "daily_source",
        "post_analysis_status",
        "post_analysis_summaries",
        "post_analysis_score_deltas",
        "post_analysis_tags",
        "dsa_context",
        "dsa_news",
        "dsa_analysis_summary",
        "deep_analysis_status",
        "deep_analysis_query_id",
        "deep_analysis_summary",
        "deep_analysis_error",
        "deep_analysis_signal_score",
        "deep_analysis_sentiment_score",
        "deep_analysis_operation_advice",
        "deep_analysis_trend_prediction",
        "deep_analysis_risk_flags",
    ],
    "ui_card_fields": {
        "identity": ["rank", "code", "name", "final_score", "screen_score"],
        "source_health": [
            "snapshot_source",
            "source_errors",
            "daily_source",
            "daily_quality_flags",
        ],
        "risk": ["risk_level", "risk_flags", "portfolio_flags", "risk_summary"],
        "watch": [
            "llm_watch_items",
            "llm_invalidators",
            "deep_analysis_operation_advice",
        ],
        "post_analysis": [
            "post_analysis_status",
            "post_analysis_summaries",
            "post_analysis_tags",
        ],
    },
    "non_goals": [
        "AlphaSift does not execute trades.",
        "AlphaSift does not provide full portfolio accounting.",
        "DSA is optional and must not be required for core screening.",
    ],
}


def screen_result_schema() -> dict[str, object]:
    """Return a copy of the stable ScreenResult schema metadata."""
    return {
        key: value.copy()
        if isinstance(value, dict)
        else list(value)
        if isinstance(value, list)
        else value
        for key, value in SCREEN_RESULT_SCHEMA.items()
    }
