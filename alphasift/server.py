# -*- coding: utf-8 -*-
"""Read-only HTTP API surface for UI and agent integrations."""

from __future__ import annotations

import base64
import hashlib
import html
import math
from dataclasses import asdict
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import pandas as pd

from alphasift.config import Config
from alphasift.daily_report import build_daily_report, load_daily_report_runs
from alphasift.daily_report_html import _safe_detail_url, render_daily_report_html
from alphasift.doctor import doctor_data_sources, doctor_radar_readiness
from alphasift.market_digest import build_markets_digest, load_multi_market_runs
from alphasift.market_regime import compute_market_regime, compute_market_regime_series
from alphasift.jsonutil import dumps_strict_json
from alphasift.markets import MARKETS, get_market
from alphasift.overview import build_overview
from alphasift.pack import PackError, load_pack, pack_dir
from alphasift.pattern_replay import load_cn_benchmark, replay_patterns
from alphasift.patterns import extract_mini_kline_bars, list_patterns, scan_patterns
from alphasift.performance_history import build_strategy_performance_summary
from alphasift.report import build_run_report_payload
from alphasift.result_schema import daily_report_schema, screen_result_schema
from alphasift.run_history import build_strategy_run_summary
from alphasift.source_history import build_data_source_history
from alphasift.store import list_saved_runs, load_screen_result
from alphasift.strategy import compare_strategies, list_strategies, match_strategies, strategy_facets
from alphasift.strategy_cards import build_strategy_cards
from alphasift.strategy_templates import get_strategy_template, list_strategy_templates
from alphasift.workbench_ui import render_workbench_html


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
    if path == "/result-schema":
        return 200, screen_result_schema()
    if path == "/daily-report-schema":
        return 200, daily_report_schema()
    if path == "/markets":
        market_arg = (_single(params, "id") or _single(params, "market")).lower()
        if market_arg:
            try:
                spec = get_market(market_arg)
            except ValueError as exc:
                return 404, {
                    "error": "market_not_found",
                    "message": str(exc),
                    "market": market_arg,
                }
            return 200, {"schema_version": 1, "market": asdict(spec)}
        return 200, {
            "schema_version": 1,
            "markets": [asdict(item) for item in MARKETS.values()],
        }
    if path == "/overview":
        strategy_arg = _single(params, "strategy") or None
        if strategy_arg and _find_strategy(config, strategy_arg) is None:
            return 404, {
                "error": "strategy_not_found",
                "message": f"Strategy '{strategy_arg}' not found.",
                "strategy": strategy_arg,
            }
        try:
            return 200, build_overview(
                config,
                strategy_name=strategy_arg,
                runs_limit=_int_param(params, "runs_limit", 5, min_val=1, max_val=200),
                live_data_check=_bool_param(params, "live", False),
                strategy_match=_strategy_match_params(params),
                match_limit=_int_param(params, "match_limit", 5, min_val=1, max_val=100),
            )
        except ValueError as exc:
            return 400, {"error": "invalid_request", "message": str(exc)}
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
    if path == "/strategy":
        strategy_name = _single(params, "name")
        if not strategy_name:
            return 400, {
                "error": "missing_strategy_name",
                "message": "Query parameter `name` is required.",
            }
        strategy = _find_strategy(config, strategy_name)
        if strategy is None:
            return 404, {
                "error": "strategy_not_found",
                "message": f"Strategy '{strategy_name}' not found.",
                "name": strategy_name,
            }
        return 200, {"schema_version": 1, "strategy": asdict(strategy)}
    if path == "/strategy-compare":
        base_name = _single(params, "base")
        target_name = _single(params, "target")
        if not base_name or not target_name:
            return 400, {
                "error": "missing_strategy_compare_params",
                "message": "Query parameters `base` and `target` are required.",
            }
        try:
            comparison = compare_strategies(base_name, target_name, config.strategies_dir)
        except ValueError as exc:
            return 404, {
                "error": "strategy_not_found",
                "message": str(exc),
                "base": base_name,
                "target": target_name,
            }
        return 200, {"schema_version": 1, "comparison": comparison}
    if path == "/strategy-facets":
        return 200, strategy_facets(config.strategies_dir)
    if path == "/strategy-cards":
        try:
            return 200, build_strategy_cards(
                config,
                strategy_name=_single(params, "strategy") or None,
                runs_limit=_int_param(params, "limit", 100),
                live_data_check=_bool_param(params, "live", False),
            )
        except ValueError as exc:
            return 404, {
                "error": "strategy_not_found",
                "message": str(exc),
                "strategy": _single(params, "strategy"),
            }
    if path == "/strategy-readiness":
        strategy_name = _single(params, "strategy") or None
        try:
            result = doctor_data_sources(
                config,
                snapshot_sources=_multi(params, "snapshot_source") or None,
                daily_source=_single(params, "daily_source") or None,
                daily_code=_single(params, "daily_code") or "000001",
                run_live=_bool_param(params, "live", False),
                check_daily=not _bool_param(params, "no_daily", False),
                strategy_name=strategy_name,
                all_strategies=strategy_name is None,
            ).to_dict()
        except ValueError as exc:
            return 404, {
                "error": "strategy_not_found",
                "message": str(exc),
                "strategy": strategy_name or "",
            }
        return 200, {
            "schema_version": 1,
            "status": result.get("status"),
            "config": result.get("config", {}),
            "strategy_requirements": result.get("strategy_requirements", {}),
            "strategy_coverage": result.get("strategy_coverage", []),
            "strategy_readiness_summary": result.get("strategy_readiness_summary", {}),
            "health_summary": result.get("health_summary", {}),
            "freshness_summary": result.get("freshness_summary", {}),
            "recommendations": result.get("recommendations", []),
        }
    if path == "/strategy-templates":
        return 200, {"schema_version": 1, "templates": list_strategy_templates()}
    if path == "/strategy-template":
        template_name = _single(params, "name")
        if not template_name:
            return 400, {
                "error": "missing_template_name",
                "message": "Query parameter `name` is required.",
            }
        try:
            template = get_strategy_template(
                template_name,
                include_yaml=_bool_param(params, "include_yaml", True),
            )
        except ValueError as exc:
            return 404, {
                "error": "strategy_template_not_found",
                "message": str(exc),
                "name": template_name,
            }
        return 200, {"schema_version": 1, "template": template}
    if path == "/strategy-run-summary":
        return 200, build_strategy_run_summary(
            data_dir=config.data_dir,
            limit=_int_param(params, "limit", 100, min_val=1, max_val=200),
            strategy=_single(params, "strategy") or None,
        )
    if path == "/data-source-history":
        return 200, build_data_source_history(
            data_dir=config.data_dir,
            limit=_int_param(params, "limit", 100, min_val=1, max_val=200),
            strategy=_single(params, "strategy") or None,
        )
    if path == "/strategy-performance":
        return 200, build_strategy_performance_summary(
            data_dir=config.data_dir,
            limit=_int_param(params, "limit", 100, min_val=1, max_val=200),
            strategy=_single(params, "strategy") or None,
        )
    if path == "/runs":
        return 200, {
            "schema_version": 1,
            "runs": list_saved_runs(
                data_dir=config.data_dir,
                limit=_int_param(params, "limit", 20, min_val=1, max_val=200),
                strategy=_single(params, "strategy") or None,
            ),
        }
    if path == "/report":
        run_ref = _single(params, "run")
        if not run_ref:
            return 400, {"error": "missing_run", "message": "Query parameter `run` is required."}
        try:
            safe_run_path = _validate_safe_run_file(run_ref, data_dir=config.data_dir)
            run = load_screen_result(safe_run_path, data_dir=config.data_dir)
        except ValueError as exc:
            return 400, {"error": "invalid_run_id", "message": str(exc), "run": run_ref}
        except FileNotFoundError as exc:
            return 404, {"error": "run_not_found", "message": str(exc), "run": run_ref}
        return 200, build_run_report_payload(
            run,
            max_picks=_int_param(params, "max_picks", 10, min_val=1, max_val=200),
        )
    if path == "/doctor/data-sources":
        try:
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
        except ValueError as exc:
            return 400, {"error": "invalid_request", "message": str(exc)}
        return 200, result.to_dict()
    if path == "/doctor/radar":
        try:
            return 200, doctor_radar_readiness(
                config,
                trade_date=_single(params, "trade_date") or None,
            )
        except ValueError as exc:
            return 400, {"error": "invalid_request", "message": str(exc)}
    if path == "/patterns":
        include_exp = _bool_param(params, "include_experimental", True)
        return 200, {
            "schema_version": 1,
            "patterns": [asdict(item) for item in list_patterns(include_experimental=include_exp)],
        }
    if path == "/markets-digest":
        raw_markets = _multi(params, "markets") or _multi(params, "market")
        if raw_markets:
            markets = list(dict.fromkeys(m.lower() for m in raw_markets))
            if len(markets) > 7:
                return 400, {"error": "invalid_request", "message": "Too many markets requested (max 7)."}
        else:
            markets = ["us", "hk", "jp", "kr", "tw", "in"]
        try:
            for m in markets:
                get_market(m)
            trade_date = _single(params, "trade_date") or None
            if trade_date is not None:
                if len(trade_date) != 10:
                    raise ValueError(f"Invalid trade_date (expected YYYY-MM-DD): {trade_date!r}")
                try:
                    date.fromisoformat(trade_date)
                except ValueError as exc:
                    raise ValueError(f"Invalid trade_date (expected YYYY-MM-DD): {trade_date!r}") from exc
            raw_detail = _single(params, "detail_url")
            detail_url = (
                _safe_detail_url(raw_detail, fallback="")
                if raw_detail
                else _safe_detail_url(config.dashboard_url, fallback="")
            )
            runs_by_mkt = load_multi_market_runs(config, markets=markets, trade_date=trade_date)
            return 200, build_markets_digest(
                runs_by_mkt,
                markets=markets,
                trade_date=trade_date,
                detail_url=detail_url,
                include_news=False,
                config=config,
            )
        except ValueError as exc:
            return 400, {"error": "invalid_request", "message": str(exc)}
    if path in {"/market-stats", "/patterns/scan", "/patterns/replay", "/daily-report"}:
        safe_run_paths: list[str] = []
        if path == "/daily-report":
            requested_ai_brief = (_single(params, "ai_brief") or "off").lower()
            if requested_ai_brief == "on":
                return 403, {
                    "error": "llm_get_disabled",
                    "message": "HTTP GET /daily-report does not spend LLM credits; use CLI daily-report --ai-brief on.",
                }
            for raw_id in _multi(params, "run_id"):
                try:
                    safe_run_paths.append(str(_validate_safe_run_file(raw_id, data_dir=config.data_dir)))
                except ValueError as exc:
                    return 400, {"error": "invalid_run_id", "message": str(exc), "run_id": raw_id}
        try:
            daily_pack = load_pack(pack_dir(config))
        except (OSError, PackError, ValueError) as exc:
            return 503, {
                "error": "pack_unavailable",
                "message": f"CN DailyPack unavailable: {exc}",
            }
        trade_date = _single(params, "trade_date") or None
        try:
            if path == "/market-stats":
                days = max(1, min(250, _int_param(params, "days", 1)))
                if days <= 1:
                    return 200, compute_market_regime(daily_pack, trade_date=trade_date).to_dict()
                if trade_date is not None:
                    dates = [str(d) for d in daily_pack.dates]
                    if trade_date not in dates:
                        raise ValueError(f"trade_date {trade_date!r} not found in DailyPack")
                    end_idx = dates.index(trade_date)
                else:
                    end_idx = len(daily_pack.dates) - 1
                series = compute_market_regime_series(daily_pack, end_index=end_idx)[-days:]
                return 200, {"schema_version": 1, "days": [item.to_dict() for item in series]}
            if path == "/patterns/scan":
                include_exp = _bool_param(params, "include_experimental", False)
                selected_patterns, pat_err = _validate_pattern_selection(_multi(params, "pattern"))
                if pat_err is not None:
                    return pat_err
                payload = scan_patterns(
                    daily_pack,
                    patterns=selected_patterns,
                    trade_date=trade_date,
                    include_experimental=include_exp,
                ).to_dict()
                if _bool_param(params, "with_kline", False):
                    sig_codes: list[str] = []
                    for items in (payload.get("signals_by_pattern") or {}).values():
                        for item in list(items)[:12]:
                            code = str(item.get("code") or "")
                            if code:
                                sig_codes.append(code)
                    if sig_codes:
                        klines = extract_mini_kline_bars(
                            daily_pack,
                            sig_codes,
                            trade_date=payload.get("trade_date"),
                            bars=20,
                        )
                        for items in (payload.get("signals_by_pattern") or {}).values():
                            for item in items:
                                item["kline"] = klines.get(str(item.get("code") or ""), [])
                return 200, payload
            if path == "/patterns/replay":
                selected_patterns, pat_err = _validate_pattern_selection(_multi(params, "pattern"))
                if pat_err is not None:
                    return pat_err
                warmup_days = _int_param(params, "warmup_days", 60, min_val=10, max_val=200)
                cost_bps = _float_param(params, "cost_bps", default=25.0, min_val=0.0, max_val=200.0)
                assert cost_bps is not None
                allowed_regimes = _multi(params, "allowed_regime") or None
                excluded_regimes = _multi(params, "exclude_regime") or None
                max_overhead_pct = _float_param(
                    params,
                    "max_overhead_pct",
                    default=None,
                    min_val=0.0,
                    max_val=100.0,
                    exclusive_min=True,
                )
                benchmark_df = (
                    load_cn_benchmark(lookback_days=max(len(daily_pack.dates) + 40, 320))
                    if _bool_param(params, "live_benchmark", False)
                    else pd.DataFrame()
                )
                report = replay_patterns(
                    daily_pack,
                    patterns=selected_patterns,
                    benchmark_df=benchmark_df,
                    warmup_days=warmup_days,
                    cost_bps=cost_bps,
                    allowed_regimes=allowed_regimes,
                    excluded_regimes=excluded_regimes,
                    max_overhead_pct=max_overhead_pct,
                )
                return 200, {
                    "schema_version": 1,
                    "generated_at": report.get("generated_at"),
                    "entry_mode": report.get("entry_mode"),
                    "cost_bps": report.get("cost_bps"),
                    "walk_forward_boundary_policy": report.get("walk_forward_boundary_policy"),
                    "regime_filter": report.get("regime_filter"),
                    "overhead_filter": report.get("overhead_filter"),
                    "graduation_rule": report.get("graduation_rule"),
                    "pack_summary": report.get("pack_summary"),
                    "universe_baseline": report.get("universe_baseline"),
                    "patterns": [
                        {
                            "pattern": item.get("pattern"),
                            "display_name": item.get("display_name"),
                            "family": item.get("family"),
                            "mode": item.get("mode"),
                            "total_signals": item.get("total_signals"),
                            "untradable_share_pct": item.get("untradable_share_pct"),
                            "horizons": item.get("horizons"),
                            "graduation": item.get("graduation"),
                            "stability": item.get("stability"),
                            "walk_forward_regime_audit": item.get("walk_forward_regime_audit"),
                        }
                        for item in (report.get("patterns") or [])
                    ],
                }
            # /daily-report
            include_ann = _bool_param(params, "announcements", False)
            include_runs = _bool_param(params, "include_runs", True)
            run_ids = safe_run_paths or None
            expected_date = _single(params, "expected_trade_date") or None
            allow_stale = _bool_param(params, "allow_stale_pack", True)
            default_detail = _safe_detail_url(config.dashboard_url, fallback="../index.html")
            detail_url = _safe_detail_url(_single(params, "detail_url") or default_detail, fallback=default_detail)
            # Read-only HTTP GET never spends paid LLM credits by default.
            ai_brief = "off"
            ann_max = max(0, min(30, _int_param(params, "announcement_max_codes", 8)))
            strategy_runs = (
                load_daily_report_runs(
                    config,
                    run_refs=run_ids,
                    trade_date=trade_date or daily_pack.trade_date,
                )
                if include_runs
                else []
            )
            return 200, build_daily_report(
                daily_pack,
                trade_date=trade_date,
                expected_trade_date=expected_date,
                allow_stale_pack=allow_stale,
                detail_url=detail_url,
                strategy_runs=strategy_runs,
                include_announcements=include_ann,
                announcement_max_codes=ann_max,
                announcement_cache_dir=(
                    config.llm_candidate_context_cache_dir
                    or (config.data_dir / "candidate_context_cache")
                ),
                ai_brief_mode=ai_brief,
                config=config,
            )
        except (ValueError, IndexError, FileNotFoundError) as exc:
            return 400, {"error": "invalid_request", "message": str(exc)}
    return 404, {
        "error": "not_found",
        "path": path,
        "available_endpoints": _index_payload()["endpoints"],
    }


def build_html_response(
    config: Config,
    path: str,
    *,
    query: str = "",
) -> tuple[int, str]:
    """Return HTTP status and HTML content for standalone UI and report endpoints."""
    if path in {"/ui", "/"}:
        return 200, render_workbench_html()
    if path != "/daily-report.html":
        return 404, (
            "<!doctype html><meta charset='utf-8'><h1>404 Not Found</h1>"
            f"<p>{html.escape(path)}</p>"
        )
    status, payload = build_api_response(config, "/daily-report", query=query)
    if status != 200:
        msg = html.escape(str(payload.get("message") or payload.get("error") or "Error"))
        return status, (
            f"<!doctype html><meta charset='utf-8'><h1>{status}</h1><p>{msg}</p>"
        )
    return 200, render_daily_report_html(payload)


def _parse_accept_q(params: list[str]) -> float:
    for p in params:
        if "=" in p:
            k, v = p.split("=", 1)
            if k.strip().lower() == "q":
                try:
                    return max(0.0, min(1.0, float(v.strip())))
                except ValueError:
                    return 0.0
    return 1.0


def _prefers_html(accept_header: str, query: str) -> bool:
    params = parse_qs(query, keep_blank_values=False)
    if (params.get("format") or [""])[-1].strip().lower() == "json":
        return False
    best_html_q = 0.0
    best_json_q = 0.0
    for raw_range in str(accept_header or "").split(","):
        tokens = [tok.strip() for tok in raw_range.split(";") if tok.strip()]
        if not tokens:
            continue
        media = tokens[0].lower()
        q = _parse_accept_q(tokens[1:])
        if q <= 0.0:
            continue
        if media in {"text/html", "application/xhtml+xml"}:
            best_html_q = max(best_html_q, q)
        elif media == "application/json":
            best_json_q = max(best_json_q, q)
    if best_html_q <= 0.0:
        return False
    return best_html_q >= best_json_q


def _script_src_csp(html_content: str) -> str:
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html_content)
    if not scripts:
        return "'none'"
    hashes = []
    for body in scripts:
        digest = hashlib.sha256(body.encode("utf-8")).digest()
        hashes.append(f"'sha256-{base64.b64encode(digest).decode('ascii')}'")
    return " ".join(hashes)


_WORKBENCH_SCRIPT_CSP = _script_src_csp(render_workbench_html())


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
            self._serve_request(send_body=True)

        def do_HEAD(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler.
            self._serve_request(send_body=False)

        def _serve_request(self, *, send_body: bool) -> None:
            parsed = urlparse(self.path)
            vary_accept = parsed.path == "/"
            try:
                if parsed.path in {"/ui", "/daily-report.html"} or (
                    parsed.path == "/" and _prefers_html(self.headers.get("Accept", ""), parsed.query)
                ):
                    status, html_body = build_html_response(config, parsed.path, query=parsed.query)
                    is_workbench = parsed.path in {"/ui", "/"} and status == 200
                    self._send_html(
                        status,
                        html_body,
                        vary_accept=vary_accept,
                        script_csp=_WORKBENCH_SCRIPT_CSP if is_workbench else "'none'",
                        send_body=send_body,
                    )
                    return
                status, payload = build_api_response(config, parsed.path, query=parsed.query)
                self._send_json(status, payload, vary_accept=vary_accept, send_body=send_body)
            except Exception:  # noqa: BLE001 - avoid leaking tracebacks in HTTP responses.
                self._send_json(
                    500,
                    {"error": "internal_error", "message": "Internal server error"},
                    vary_accept=vary_accept,
                    send_body=send_body,
                )

        def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature.
            return

        def _send_html(
            self,
            status: int,
            content: str,
            *,
            vary_accept: bool = False,
            script_csp: str = "'none'",
            send_body: bool = True,
        ) -> None:
            body = content.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            if vary_accept:
                self.send_header("Vary", "Accept")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                f"default-src 'self'; script-src {script_csp}; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if send_body:
                self.wfile.write(body)

        def _send_json(
            self,
            status: int,
            payload: dict[str, Any],
            *,
            vary_accept: bool = False,
            send_body: bool = True,
        ) -> None:
            body = dumps_strict_json(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            if vary_accept:
                self.send_header("Vary", "Accept")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if send_body:
                self.wfile.write(body)

    return AlphaSiftApiHandler


def _index_payload() -> dict[str, Any]:
    return {
        "service": "alphasift",
        "schema_version": 1,
        "endpoints": [
            "/health",
            "/ui",
            "/result-schema",
            "/daily-report-schema",
            "/overview",
            "/markets",
            "/strategies",
            "/strategy",
            "/strategy-compare",
            "/strategy-facets",
            "/strategy-cards",
            "/strategy-readiness",
            "/strategy-run-summary",
            "/data-source-history",
            "/strategy-performance",
            "/strategy-templates",
            "/strategy-template",
            "/runs",
            "/report",
            "/doctor/data-sources",
            "/doctor/radar",
            "/market-stats",
            "/patterns",
            "/patterns/scan",
            "/patterns/replay",
            "/daily-report",
            "/daily-report.html",
            "/markets-digest",
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


_SAFE_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _validate_safe_run_file(run_ref: str, *, data_dir: Path) -> Path:
    cleaned = str(run_ref or "").strip()
    if (
        not cleaned
        or "/" in cleaned
        or "\\" in cleaned
        or ".." in cleaned
        or not _SAFE_RUN_ID_RE.fullmatch(cleaned)
    ):
        raise ValueError(f"Unsafe run identifier: {cleaned!r}")
    runs_root = (data_dir / "runs").resolve()
    raw_path = runs_root / f"{cleaned}.json"
    if raw_path.is_symlink():
        raise ValueError(f"Symlink run file is not allowed: {cleaned!r}")
    candidate = raw_path.resolve()
    if not candidate.is_relative_to(runs_root):
        raise ValueError(f"Run path escapes runs directory: {cleaned!r}")
    return candidate


def _find_strategy(config: Config, strategy_name: str) -> Any | None:
    for item in list_strategies(config.strategies_dir):
        if item.name == strategy_name:
            return item
    return None


def _single(params: dict[str, list[str]], key: str) -> str:
    values = params.get(key) or []
    return str(values[-1]).strip() if values else ""


def _multi(params: dict[str, list[str]], key: str) -> list[str]:
    values: list[str] = []
    for raw in params.get(key, []) or []:
        values.extend(str(item).strip() for item in str(raw).split(","))
    return [item for item in dict.fromkeys(values) if item]


def _int_param(
    params: dict[str, list[str]],
    key: str,
    default: int,
    *,
    min_val: int | None = None,
    max_val: int | None = None,
) -> int:
    try:
        val = int(_single(params, key) or default)
    except ValueError:
        val = default
    if min_val is not None:
        val = max(min_val, val)
    if max_val is not None:
        val = min(max_val, val)
    return val


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


def _validate_pattern_selection(
    raw_patterns: list[str],
) -> tuple[list[str] | None, tuple[int, dict[str, Any]] | None]:
    if not raw_patterns:
        return None, None
    known = {spec.name for spec in list_patterns(include_experimental=True)}
    deduped: list[str] = []
    for item in raw_patterns:
        if "/" in item or "\\" in item or ".." in item or item not in known:
            return None, (
                400,
                {
                    "error": "invalid_pattern",
                    "message": f"Unknown or unsafe pattern name: {item!r}",
                    "pattern": item,
                },
            )
        if item not in deduped:
            deduped.append(item)
    if len(deduped) > 32:
        return None, (
            400,
            {
                "error": "too_many_patterns",
                "message": "Too many patterns requested (max 32).",
            },
        )
    return deduped, None


def _float_param(
    params: dict[str, list[str]],
    key: str,
    *,
    default: float | None,
    min_val: float,
    max_val: float,
    exclusive_min: bool = False,
) -> float | None:
    raw = _single(params, key)
    if not raw:
        return default
    try:
        val = float(raw)
    except ValueError as exc:
        raise ValueError(f"Parameter `{key}` must be a finite number, got {raw!r}") from exc
    if not math.isfinite(val):
        raise ValueError(f"Parameter `{key}` must be finite")
    if (val <= min_val if exclusive_min else val < min_val) or val > max_val:
        op = ">" if exclusive_min else ">="
        raise ValueError(f"Parameter `{key}` must satisfy {op} {min_val} and <= {max_val}")
    return val
