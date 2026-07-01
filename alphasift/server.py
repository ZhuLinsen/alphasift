# -*- coding: utf-8 -*-
"""Read-only HTTP API surface for UI and agent integrations."""

from __future__ import annotations

import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from alphasift.config import Config
from alphasift.doctor import doctor_data_sources
from alphasift.overview import build_overview
from alphasift.report import build_run_report_payload
from alphasift.store import list_saved_runs, load_screen_result
from alphasift.strategy import list_strategies, match_strategies


def build_api_response(
    config: Config,
    path: str,
    *,
    query: str = "",
) -> tuple[int, dict[str, Any]]:
    """Return an HTTP-ish status and JSON payload for a read-only API route."""
    params = parse_qs(query, keep_blank_values=False)
    if path in {"", "/"}:
        return 200, _index_payload()
    if path == "/health":
        return 200, {"status": "ok", "service": "alphasift", "schema_version": 1}
    if path == "/overview":
        return 200, build_overview(
            config,
            strategy_name=_single(params, "strategy") or None,
            runs_limit=_int_param(params, "runs_limit", 5),
            live_data_check=_bool_param(params, "live", False),
            strategy_match=_strategy_match_params(params),
            match_limit=_int_param(params, "match_limit", 5),
        )
    if path == "/strategies":
        criteria = _strategy_match_params(params)
        if _has_match_criteria(criteria):
            return 200, {
                "schema_version": 1,
                "strategies": match_strategies(
                    config.strategies_dir,
                    **criteria,
                    limit=_int_param(params, "limit", 20),
                ),
            }
        return 200, {
            "schema_version": 1,
            "strategies": [asdict(item) for item in list_strategies(config.strategies_dir)],
        }
    if path == "/runs":
        return 200, {
            "schema_version": 1,
            "runs": list_saved_runs(
                data_dir=config.data_dir,
                limit=_int_param(params, "limit", 20),
                strategy=_single(params, "strategy") or None,
            ),
        }
    if path == "/report":
        run_ref = _single(params, "run")
        if not run_ref:
            return 400, {"error": "missing_run", "message": "Query parameter `run` is required."}
        try:
            run = load_screen_result(run_ref, data_dir=config.data_dir)
        except FileNotFoundError as exc:
            return 404, {"error": "run_not_found", "message": str(exc), "run": run_ref}
        return 200, build_run_report_payload(
            run,
            max_picks=_int_param(params, "max_picks", 10),
        )
    if path == "/doctor/data-sources":
        result = doctor_data_sources(
            config,
            snapshot_sources=_multi(params, "snapshot_source") or None,
            daily_source=_single(params, "daily_source") or None,
            daily_code=_single(params, "daily_code") or "000001",
            run_live=_bool_param(params, "live", False),
            check_daily=not _bool_param(params, "no_daily", False),
            strategy_name=_single(params, "strategy") or None,
            all_strategies=_bool_param(params, "all_strategies", False),
            compare_snapshot_sources=_bool_param(params, "compare_snapshot_sources", False),
        )
        return 200, result.to_dict()
    return 404, {
        "error": "not_found",
        "path": path,
        "available_endpoints": _index_payload()["endpoints"],
    }


def serve_api(
    config: Config,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Start the local read-only AlphaSift HTTP API."""
    handler = _handler_for_config(config)
    server = ThreadingHTTPServer((host, int(port)), handler)
    try:
        print(f"AlphaSift API listening on http://{host}:{int(port)}")
        server.serve_forever()
    finally:
        server.server_close()


def _handler_for_config(config: Config):
    class AlphaSiftApiHandler(BaseHTTPRequestHandler):
        server_version = "AlphaSiftAPI/1"

        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler.
            parsed = urlparse(self.path)
            status, payload = build_api_response(config, parsed.path, query=parsed.query)
            self._send_json(status, payload)

        def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature.
            return

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return AlphaSiftApiHandler


def _index_payload() -> dict[str, Any]:
    return {
        "service": "alphasift",
        "schema_version": 1,
        "endpoints": [
            "/health",
            "/overview",
            "/strategies",
            "/runs",
            "/report",
            "/doctor/data-sources",
        ],
    }


def _strategy_match_params(params: dict[str, list[str]]) -> dict[str, Any]:
    return {
        "risk_profile": _single(params, "risk_profile"),
        "holding_period": _single(params, "holding_period"),
        "execution_style": _single(params, "execution_style"),
        "market_regime": _multi(params, "market_regime"),
        "capital_profile": _single(params, "capital_profile"),
        "data_requirements": _multi(params, "data_requirement"),
        "tags": _multi(params, "tag"),
        "category": _single(params, "category"),
        "daily_required": _optional_bool_param(params, "daily_required"),
        "strict": _bool_param(params, "strict", False),
    }


def _has_match_criteria(criteria: dict[str, Any]) -> bool:
    return any(
        bool(criteria.get(key))
        for key in (
            "risk_profile",
            "holding_period",
            "execution_style",
            "market_regime",
            "capital_profile",
            "data_requirements",
            "tags",
            "category",
        )
    ) or criteria.get("daily_required") is not None or bool(criteria.get("strict"))


def _single(params: dict[str, list[str]], key: str) -> str:
    values = params.get(key) or []
    return str(values[-1]).strip() if values else ""


def _multi(params: dict[str, list[str]], key: str) -> list[str]:
    values: list[str] = []
    for raw in params.get(key, []) or []:
        values.extend(str(item).strip() for item in str(raw).split(","))
    return [item for item in dict.fromkeys(values) if item]


def _int_param(params: dict[str, list[str]], key: str, default: int) -> int:
    try:
        return int(_single(params, key) or default)
    except ValueError:
        return default


def _optional_bool_param(params: dict[str, list[str]], key: str) -> bool | None:
    value = _single(params, key).lower()
    if value in {"", "any"}:
        return None
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _bool_param(params: dict[str, list[str]], key: str, default: bool) -> bool:
    value = _optional_bool_param(params, key)
    return default if value is None else value
