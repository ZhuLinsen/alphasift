# -*- coding: utf-8 -*-
"""alphasift — 自动选股 Skill"""

__version__ = "0.2.0"

from alphasift.pipeline import screen
from alphasift.evaluate import evaluate_saved_run, evaluate_saved_runs
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
]
