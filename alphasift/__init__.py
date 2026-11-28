# -*- coding: utf-8 -*-
"""alphasift — 自动选股 Skill"""

__version__ = "0.3.2"

from alphasift.pipeline import screen
from alphasift.evaluate import evaluate_saved_run, evaluate_saved_runs
from alphasift.daily_brief import (
    build_cross_strategy_synthesis,
    generate_ai_daily_brief,
    resolve_strategy_display_names,
)
from alphasift.daily_report import (
    build_daily_report,
    load_daily_report_runs,
    render_daily_im_card,
)
from alphasift.daily_report_html import render_daily_report_html, write_daily_report_html
from alphasift.doctor import doctor_radar_readiness
from alphasift.market_digest import (
    build_markets_digest,
    load_multi_market_runs,
    render_market_digest_im_card,
)
from alphasift.market_regime import compute_market_regime, compute_market_regime_series
from alphasift.mcp import MCPServer, serve_mcp
from alphasift.notify import push_daily_report
from alphasift.pattern_replay import load_cn_benchmark, render_replay_markdown, replay_patterns
from alphasift.patterns import list_patterns, scan_patterns
from alphasift.performance_history import build_strategy_performance_summary
from alphasift.strategy import compare_strategies, list_strategies, strategy_facets
from alphasift.audit import audit_project
from alphasift.overview import build_overview
from alphasift.run_history import build_strategy_run_summary
from alphasift.server import build_api_response, serve_api
from alphasift.source_history import build_data_source_history
from alphasift.strategy_cards import build_strategy_cards
from alphasift.strategy_templates import get_strategy_template, list_strategy_templates

__all__ = [
    "__version__",
    "screen",
    "evaluate_saved_run",
    "evaluate_saved_runs",
    "build_cross_strategy_synthesis",
    "build_daily_report",
    "generate_ai_daily_brief",
    "load_daily_report_runs",
    "render_daily_im_card",
    "render_daily_report_html",
    "resolve_strategy_display_names",
    "write_daily_report_html",
    "build_markets_digest",
    "load_multi_market_runs",
    "render_market_digest_im_card",
    "doctor_radar_readiness",
    "compute_market_regime",
    "compute_market_regime_series",
    "push_daily_report",
    "list_patterns",
    "scan_patterns",
    "load_cn_benchmark",
    "render_replay_markdown",
    "replay_patterns",
    "build_strategy_performance_summary",
    "list_strategies",
    "compare_strategies",
    "strategy_facets",
    "get_strategy_template",
    "list_strategy_templates",
    "audit_project",
    "build_overview",
    "build_strategy_run_summary",
    "build_data_source_history",
    "build_strategy_cards",
    "build_api_response",
    "serve_api",
    "MCPServer",
    "serve_mcp",
]
