# -*- coding: utf-8 -*-
"""Zero-dependency STDIO Model Context Protocol (MCP 2024-11-05) server for AlphaSift."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import redirect_stdout
from dataclasses import asdict
from datetime import date, datetime
import json
import math
import os
from pathlib import Path
import site
import sys
from typing import Any, BinaryIO

from alphasift import __version__
from alphasift.config import Config
from alphasift.daily_report import build_daily_report, load_daily_report_runs
from alphasift.doctor import doctor_data_sources
from alphasift.market_digest import build_markets_digest, load_multi_market_runs
from alphasift.markets import get_market
from alphasift.notify import notify_readiness
from alphasift.overview import build_overview
from alphasift.pack import PackError, load_pack, pack_dir
from alphasift.pattern_replay import load_cn_benchmark, replay_patterns
from alphasift.patterns import list_patterns, scan_patterns
from alphasift.pipeline import screen
from alphasift.store import list_saved_runs
from alphasift.strategy import compare_strategies, list_strategies, load_all_strategies

MCP_PROTOCOL_VERSION = "2024-11-05"
_MAX_CONTENT_LENGTH = 16 * 1024 * 1024
_MAX_HEADER_LINES = 32
_MAX_HEADER_BYTES = 8192
_MAX_PATTERN_SELECTION = 32
_DEFAULT_DIGEST_MARKETS = ("us", "hk", "jp", "kr", "tw", "in")
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Expected integer parameter, got {type(value).__name__}")
    return max(minimum, min(value, maximum))


def _optional_bool(args: dict[str, Any], key: str, default: bool) -> bool:
    if key not in args or args[key] is None:
        return default
    val = args[key]
    if not isinstance(val, bool):
        raise ValueError(f"Parameter {key!r} must be a boolean")
    return val


def _optional_str(args: dict[str, Any], key: str) -> str:
    if key not in args or args[key] is None:
        return ""
    val = args[key]
    if not isinstance(val, str):
        raise ValueError(f"Parameter {key!r} must be a string")
    return val.strip()


def _optional_float(
    args: dict[str, Any],
    key: str,
    *,
    default: float | None,
    minimum: float,
    maximum: float,
    exclusive_min: bool = False,
) -> float | None:
    if key not in args or args[key] is None:
        return default
    raw = args[key]
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f'Parameter {key!r} must be a number, got {type(raw).__name__}')
    val = float(raw)
    if not math.isfinite(val):
        raise ValueError(f'Parameter {key!r} must be finite')
    if (val <= minimum if exclusive_min else val < minimum) or val > maximum:
        op = '>' if exclusive_min else '>='
        raise ValueError(f'Parameter {key!r} must satisfy {op} {minimum} and <= {maximum}')
    return val


def _optional_str_list(args: dict[str, Any], key: str, *, max_items: int = 16) -> list[str] | None:
    if key not in args or args[key] is None:
        return None
    raw = args[key]
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise ValueError(f'Parameter {key!r} must be a list of strings')
    items = [x.strip() for x in raw if x.strip()]
    if len(items) > max_items:
        raise ValueError(f'Too many entries in {key!r} (max {max_items})')
    return items or None


def _require_str(args: dict[str, Any], key: str) -> str:
    raw = args.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"Missing or invalid required string parameter: {key!r}")
    return raw.strip()


def _optional_iso_date(args: dict[str, Any], key: str) -> str | None:
    value = _optional_str(args, key) or None
    if value is not None:
        if len(value) != 10:
            raise ValueError(f"Invalid {key} (expected YYYY-MM-DD): {value!r}")
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Invalid {key} (expected YYYY-MM-DD): {value!r}") from exc
    return value


def _optional_http_url(args: dict[str, Any], key: str, *, default: str = "") -> str:
    if key in args and args[key] is not None:
        url = _optional_str(args, key)
    else:
        url = str(default or "").strip()
    if url and (len(url) > 500 or not url.startswith(("http://", "https://"))):
        raise ValueError(f"Parameter {key!r} must be an http:// or https:// URL (<= 500 chars)")
    return url


def _json_safe(obj: Any) -> Any:
    """Normalize NaN/Inf floats, NumPy scalars/arrays, and dates before strict JSON serialization."""
    if obj is None or isinstance(obj, (bool, int)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, str):
        return obj
    if type(obj).__name__ == "NaTType":
        return None
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    ndim = getattr(obj, "ndim", None)
    if isinstance(ndim, int) and ndim > 0 and hasattr(obj, "tolist") and callable(getattr(obj, "tolist")):
        try:
            return _json_safe(obj.tolist())
        except Exception:
            pass
    if hasattr(obj, "item") and callable(getattr(obj, "item")):
        try:
            return _json_safe(obj.item())
        except Exception:
            pass
    if hasattr(obj, "tolist") and callable(getattr(obj, "tolist")):
        try:
            return _json_safe(obj.tolist())
        except Exception:
            pass
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_safe(v) for v in obj]
    return str(obj)


class _RPCParamError(Exception):
    """Raised on JSON-RPC protocol/param errors (-32602 / -32601 / -32600)."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "alphasift_list_strategies",
            "description": "List available quantitative stock screening strategies and metadata.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "market": {
                        "type": "string",
                        "description": "Optional market filter: cn, us, hk, jp, kr, tw, in.",
                    },
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "alphasift_get_strategy",
            "description": "Get full YAML-derived configuration and factor weights for a named strategy.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Strategy identifier (e.g. balanced_alpha)."},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
        {
            "name": "alphasift_compare_strategies",
            "description": "Compare two strategies across style, data requirements, hard filters, and factor weights.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "base": {"type": "string", "description": "Base strategy name."},
                    "target": {"type": "string", "description": "Target strategy name."},
                },
                "required": ["base", "target"],
                "additionalProperties": False,
            },
        },
        {
            "name": "alphasift_screen",
            "description": (
                "Run stock screening for a strategy and return structured ScreenResult JSON. "
                "Defaults to use_llm=false unless explicitly enabled."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "strategy": {"type": "string", "description": "Strategy identifier."},
                    "market": {"type": "string", "default": "cn", "description": "Target market (cn/us/hk/jp/kr/tw/in)."},
                    "max_output": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Max picks (1-50)."},
                    "use_llm": {"type": "boolean", "default": False, "description": "Enable L2 LLM ranking."},
                    "explain_filters": {"type": "boolean", "default": False, "description": "Include L1 waterfall diagnostics."},
                    "llm_context": {"type": "string", "description": "Optional market/theme context for L2 LLM ranking."},
                },
                "required": ["strategy"],
                "additionalProperties": False,
            },
        },
        {
            "name": "alphasift_list_patterns",
            "description": "List declarative CN daily-matrix technical pattern definitions.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "include_experimental": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "alphasift_scan_patterns",
            "description": "Scan the local CN DailyPack for matching chart/volume patterns.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of built-in pattern names.",
                    },
                    "trade_date": {"type": "string", "description": "Optional YYYY-MM-DD trade date."},
                    "include_experimental": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "alphasift_replay_patterns",
            "description": (
                "Replay CN chart patterns point-in-time on the local CN DailyPack with next_open fills "
                "and zero-snooping H1->H2 Walk-Forward (Regime x Overhead) audit."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of built-in pattern names.",
                    },
                    "warmup_days": {
                        "type": "integer",
                        "minimum": 10,
                        "maximum": 200,
                        "default": 60,
                        "description": "Warmup sessions before evaluating signals (10-200).",
                    },
                    "cost_bps": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 200,
                        "default": 25.0,
                        "description": "Round-trip trading cost in bps (0-200).",
                    },
                    "allowed_regimes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional permitted regime stages (e.g. startup, main_up).",
                    },
                    "excluded_regimes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional excluded regime stages (e.g. freezing, ebb).",
                    },
                    "max_overhead_pct": {
                        "type": "number",
                        "minimum": 0.1,
                        "maximum": 100.0,
                        "description": "Keep only signals with top-10% overhead supply strictly below this % (e.g. 15).",
                    },
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "alphasift_overview",
            "description": "Build the AlphaSift operational overview (strategies, source health, history, performance).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "strategy": {"type": "string", "description": "Optional strategy focus."},
                    "runs_limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 5},
                    "live_data_check": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "alphasift_doctor_data_sources",
            "description": "Inspect snapshot & daily K data source health and strategy field readiness.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "strategy": {"type": "string"},
                    "market": {"type": "string"},
                    "run_live": {"type": "boolean", "default": False},
                    "check_daily": {"type": "boolean", "default": True},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "alphasift_notify_status",
            "description": "Inspect configured notification channels and ledger path (never exposes secrets).",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": "alphasift_list_runs",
            "description": "List saved screening runs stored under ALPHASIFT_DATA_DIR/runs.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    "strategy": {"type": "string"},
                    "market": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "alphasift_markets_digest",
            "description": (
                "Build a structured multi-market post-close screening digest (MarketDigest JSON + IM card) "
                "from saved runs under ALPHASIFT_DATA_DIR/runs."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "markets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Markets to aggregate (default: us, hk, jp, kr, tw, in; also supports cn).",
                    },
                    "trade_date": {
                        "type": "string",
                        "description": "Optional YYYY-MM-DD market session date filter.",
                    },
                    "include_news": {
                        "type": "boolean",
                        "default": False,
                        "description": "Fetch live regional market news headlines (defaults to false for offline speed).",
                    },
                    "detail_url": {
                        "type": "string",
                        "description": "Optional http(s) dashboard URL included in the IM card.",
                    },
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "alphasift_daily_report",
            "description": (
                "Build the offline-safe CN post-close DailyReport JSON + <1200-char IM card "
                "(market regime, multi-strategy consensus, AI rebalance diff, and pattern radar) "
                "from the local CN DailyPack and saved runs (never spends LLM credits)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "trade_date": {
                        "type": "string",
                        "description": "Optional YYYY-MM-DD trade date (defaults to latest session in DailyPack).",
                    },
                    "include_runs": {
                        "type": "boolean",
                        "default": True,
                        "description": "Include saved CN strategy runs for the trade date.",
                    },
                    "include_experimental_patterns": {
                        "type": "boolean",
                        "default": True,
                        "description": "Include observation/experimental CN chart patterns.",
                    },
                    "detail_url": {
                        "type": "string",
                        "description": "Optional http(s) dashboard URL included in the IM card (empty string omits link).",
                    },
                },
                "additionalProperties": False,
            },
        },
    ]


class MCPServer:
    """Stateless JSON-RPC 2.0 dispatcher implementing the AlphaSift MCP interface."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config.from_env()
        self._tools: list[dict[str, Any]] = _tool_definitions()
        self._tool_props: dict[str, set[str]] = {
            t["name"]: set((t.get("inputSchema") or {}).get("properties", {}).keys())
            for t in self._tools
        }
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            "alphasift_list_strategies": self._handle_list_strategies,
            "alphasift_get_strategy": self._handle_get_strategy,
            "alphasift_compare_strategies": self._handle_compare_strategies,
            "alphasift_screen": self._handle_screen,
            "alphasift_list_patterns": self._handle_list_patterns,
            "alphasift_scan_patterns": self._handle_scan_patterns,
            "alphasift_replay_patterns": self._handle_replay_patterns,
            "alphasift_overview": self._handle_overview,
            "alphasift_doctor_data_sources": self._handle_doctor_data_sources,
            "alphasift_notify_status": self._handle_notify_status,
            "alphasift_list_runs": self._handle_list_runs,
            "alphasift_markets_digest": self._handle_markets_digest,
            "alphasift_daily_report": self._handle_daily_report,
        }

    def _handle_list_strategies(self, args: dict[str, Any]) -> Any:
        market = _optional_str(args, "market").lower()
        if market:
            get_market(market)
        items = [asdict(item) for item in list_strategies(self.config.strategies_dir)]
        if market:
            items = [item for item in items if market in (item.get("market_scope") or [])]
        return {"strategies": items}

    def _handle_get_strategy(self, args: dict[str, Any]) -> Any:
        name = _require_str(args, "name")
        if "/" in name or "\\" in name or ".." in name:
            raise ValueError(f"Unsafe strategy name: {name!r}")
        catalog = load_all_strategies(self.config.strategies_dir)
        strategy = catalog.get(name)
        if strategy is None:
            raise KeyError(f"Strategy not found: {name!r}")
        return asdict(strategy)

    def _handle_compare_strategies(self, args: dict[str, Any]) -> Any:
        base = _require_str(args, "base")
        target = _require_str(args, "target")
        if "/" in base or "\\" in base or ".." in base or "/" in target or "\\" in target or ".." in target:
            raise ValueError("Unsafe strategy name")
        return compare_strategies(base, target, self.config.strategies_dir)

    def _handle_screen(self, args: dict[str, Any]) -> Any:
        strategy = _require_str(args, "strategy")
        if "/" in strategy or "\\" in strategy or ".." in strategy:
            raise ValueError(f"Unsafe strategy name: {strategy!r}")
        market = (_optional_str(args, "market") or "cn").lower()
        get_market(market)
        raw_max_output = args.get("max_output")
        max_output = (
            _clamp_int(raw_max_output, default=10, minimum=1, maximum=50)
            if raw_max_output is not None
            else None
        )
        use_llm = _optional_bool(args, "use_llm", False)
        explain_filters = _optional_bool(args, "explain_filters", False)
        raw_ctx = args.get("llm_context")
        if raw_ctx is not None and not isinstance(raw_ctx, str):
            raise ValueError("Parameter 'llm_context' must be a string")
        llm_context = raw_ctx[:4000] if raw_ctx is not None else None
        result = screen(
            strategy,
            market=market,
            max_output=max_output,
            use_llm=use_llm,
            llm_context=llm_context,
            explain_filters=explain_filters,
            post_analyzers=["scorecard"],
            config=self.config,
        )
        return asdict(result)

    def _handle_list_patterns(self, args: dict[str, Any]) -> Any:
        include_exp = _optional_bool(args, "include_experimental", False)
        return {"patterns": [asdict(item) for item in list_patterns(include_experimental=include_exp)]}

    def _validate_pattern_names(self, raw_patterns: Any) -> list[str] | None:
        if raw_patterns is None:
            return None
        if not isinstance(raw_patterns, list) or not all(isinstance(p, str) for p in raw_patterns):
            raise ValueError("Parameter 'patterns' must be a list of strings.")
        known = {spec.name for spec in list_patterns(include_experimental=True)}
        selected: list[str] = []
        seen: set[str] = set()
        for raw_item in raw_patterns:
            cleaned = raw_item.strip()
            if not cleaned:
                continue
            if "/" in cleaned or "\\" in cleaned or ".." in cleaned or cleaned not in known:
                raise ValueError(f"Unknown or unsafe pattern name: {cleaned!r}")
            if cleaned not in seen:
                seen.add(cleaned)
                selected.append(cleaned)
        if len(selected) > _MAX_PATTERN_SELECTION:
            raise ValueError(f"Too many patterns requested (max {_MAX_PATTERN_SELECTION})")
        return selected or None

    def _load_cn_pack(self) -> Any:
        try:
            return load_pack(pack_dir(self.config))
        except (OSError, PackError, ValueError) as exc:
            raise RuntimeError(
                f"CN DailyPack unavailable: {type(exc).__name__}. "
                "Build a pack with `alphasift pack build` first."
            ) from exc

    def _handle_scan_patterns(self, args: dict[str, Any]) -> Any:
        patterns = self._validate_pattern_names(args.get("patterns"))
        trade_date = _optional_str(args, "trade_date") or None
        include_exp = _optional_bool(args, "include_experimental", False)
        daily_pack = self._load_cn_pack()
        return scan_patterns(
            daily_pack,
            patterns=patterns,
            trade_date=trade_date,
            include_experimental=include_exp,
        ).to_dict()

    def _handle_replay_patterns(self, args: dict[str, Any]) -> Any:
        patterns = self._validate_pattern_names(args.get("patterns"))
        warmup_days = _clamp_int(args.get("warmup_days"), default=60, minimum=10, maximum=200)
        cost_bps = _optional_float(args, "cost_bps", default=25.0, minimum=0.0, maximum=200.0)
        assert cost_bps is not None
        allowed_regimes = _optional_str_list(args, "allowed_regimes", max_items=16)
        excluded_regimes = _optional_str_list(args, "excluded_regimes", max_items=16)
        max_overhead_pct = _optional_float(
            args,
            "max_overhead_pct",
            default=None,
            minimum=0.0,
            maximum=100.0,
            exclusive_min=True,
        )
        daily_pack = self._load_cn_pack()
        bench = load_cn_benchmark(lookback_days=max(len(daily_pack.dates) + 40, 320))
        report = replay_patterns(
            daily_pack,
            patterns=patterns,
            benchmark_df=bench,
            warmup_days=warmup_days,
            cost_bps=cost_bps,
            allowed_regimes=allowed_regimes,
            excluded_regimes=excluded_regimes,
            max_overhead_pct=max_overhead_pct,
        )
        return {
            "generated_at": report.get("generated_at"),
            "entry_mode": report.get("entry_mode"),
            "benchmark": report.get("benchmark"),
            "cost_bps": report.get("cost_bps"),
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

    def _handle_overview(self, args: dict[str, Any]) -> Any:
        strategy = _optional_str(args, "strategy") or None
        runs_limit = _clamp_int(args.get("runs_limit"), default=5, minimum=1, maximum=50)
        live = _optional_bool(args, "live_data_check", False)
        return build_overview(
            self.config,
            strategy_name=strategy,
            runs_limit=runs_limit,
            live_data_check=live,
        )

    def _handle_doctor_data_sources(self, args: dict[str, Any]) -> Any:
        strategy = _optional_str(args, "strategy") or None
        market = _optional_str(args, "market").lower() or None
        if market:
            get_market(market)
        run_live = _optional_bool(args, "run_live", False)
        check_daily = _optional_bool(args, "check_daily", True)
        return doctor_data_sources(
            self.config,
            strategy_name=strategy,
            market=market,
            run_live=run_live,
            check_daily=check_daily,
        ).to_dict()

    def _handle_notify_status(self, args: dict[str, Any]) -> Any:
        return notify_readiness(self.config)

    def _handle_list_runs(self, args: dict[str, Any]) -> Any:
        limit = _clamp_int(args.get("limit"), default=20, minimum=1, maximum=100)
        strategy = _optional_str(args, "strategy") or None
        market = _optional_str(args, "market").lower() or None
        return {
            "runs": list_saved_runs(
                data_dir=self.config.data_dir,
                limit=limit,
                strategy=strategy,
                market=market,
            )
        }

    def _handle_markets_digest(self, args: dict[str, Any]) -> Any:
        if "markets" in args and args["markets"] is not None:
            parsed_markets = _optional_str_list(args, "markets", max_items=7)
            if parsed_markets is None:
                raise ValueError("Parameter 'markets' must contain at least one market code")
            markets = list(dict.fromkeys(m.lower() for m in parsed_markets))
        else:
            markets = list(_DEFAULT_DIGEST_MARKETS)
        for m in markets:
            get_market(m)

        trade_date = _optional_iso_date(args, "trade_date")
        include_news = _optional_bool(args, "include_news", False)
        detail_url = _optional_http_url(args, "detail_url", default=self.config.dashboard_url)

        runs_by_mkt = load_multi_market_runs(
            self.config,
            markets=markets,
            trade_date=trade_date,
        )
        return build_markets_digest(
            runs_by_mkt,
            markets=markets,
            trade_date=trade_date,
            detail_url=detail_url,
            include_news=include_news,
            config=self.config,
        )

    def _handle_daily_report(self, args: dict[str, Any]) -> Any:
        trade_date = _optional_iso_date(args, "trade_date")
        include_runs = _optional_bool(args, "include_runs", True)
        include_exp = _optional_bool(args, "include_experimental_patterns", True)
        detail_url = _optional_http_url(args, "detail_url", default=self.config.dashboard_url)

        daily_pack = self._load_cn_pack()
        strategy_runs = (
            load_daily_report_runs(
                self.config,
                trade_date=trade_date or daily_pack.trade_date,
            )
            if include_runs
            else []
        )
        pattern_replay: dict[str, Any] | None = None
        replay_path = self.config.data_dir / "patterns" / "replay.json"
        if replay_path.is_file():
            try:
                loaded = json.loads(replay_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    pattern_replay = loaded
            except (OSError, ValueError):
                pattern_replay = None

        return build_daily_report(
            daily_pack,
            trade_date=trade_date,
            detail_url=detail_url,
            strategy_runs=strategy_runs,
            include_experimental_patterns=include_exp,
            include_announcements=False,
            include_news=False,
            ai_brief_mode="off",
            config=self.config,
            pattern_replay=pattern_replay,
        )

    def _read_skill_markdown(self) -> str:
        candidates = [
            _PROJECT_ROOT / "SKILL.md",
            Path(__file__).resolve().parent / "SKILL.md",
            Path(sys.prefix) / "SKILL.md",
            Path(site.USER_BASE) / "SKILL.md",
            Path.cwd() / "SKILL.md",
        ]
        for path in candidates:
            if path.is_file():
                return path.read_text(encoding="utf-8")
        raise FileNotFoundError("SKILL.md not found")

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(request, dict):
            return {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Invalid JSON-RPC 2.0 request"},
            }
        raw_id = request.get("id")
        valid_id = raw_id is None or (isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool))
        req_id = raw_id if valid_id else None

        if request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str) or not valid_id:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32600, "message": "Invalid JSON-RPC 2.0 request"},
            }

        is_notification = "id" not in request
        method = request["method"]
        params = request.get("params")
        if params is None:
            params = {}
        elif not isinstance(params, dict):
            if is_notification:
                return None
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": "Invalid params: expected JSON object"},
            }

        if method.startswith("notifications/"):
            return None

        try:
            with redirect_stdout(sys.stderr):
                result = self._dispatch_method(method, params)
        except _RPCParamError as exc:
            if is_notification:
                return None
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": exc.code, "message": exc.message},
            }
        except Exception as exc:  # noqa: BLE001
            if is_notification:
                return None
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": f"Internal error: {type(exc).__name__}"},
            }

        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _dispatch_method(self, method: str, params: dict[str, Any]) -> Any:
        if method == "initialize":
            return {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                },
                "serverInfo": {"name": "alphasift", "version": __version__},
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": self._tools}
        if method == "tools/call":
            tool_name = params.get("name")
            if not isinstance(tool_name, str) or not tool_name.strip():
                raise _RPCParamError(-32602, "Invalid params: missing tool name")
            handler = self._handlers.get(tool_name)
            if handler is None:
                raise _RPCParamError(-32602, f"Unknown tool: {tool_name}")
            arguments = params.get("arguments")
            if arguments is None:
                arguments = {}
            elif not isinstance(arguments, dict):
                raise _RPCParamError(-32602, "Invalid params: tool arguments must be an object")
            allowed_props = self._tool_props.get(tool_name, set())
            unknown_props = sorted(set(arguments.keys()) - allowed_props)
            if unknown_props:
                raise _RPCParamError(
                    -32602,
                    f"Unknown arguments for {tool_name}: {', '.join(unknown_props)}",
                )
            try:
                payload = handler(arguments)
                safe_text = json.dumps(
                    _json_safe(payload),
                    ensure_ascii=False,
                    indent=2,
                    allow_nan=False,
                )
                return {
                    "content": [{"type": "text", "text": safe_text}],
                    "isError": False,
                }
            except Exception as exc:  # noqa: BLE001
                return {
                    "content": [{"type": "text", "text": f"{type(exc).__name__}: {str(exc)[:300]}"}],
                    "isError": True,
                }
        if method == "resources/list":
            return {
                "resources": [
                    {
                        "uri": "alphasift://skill",
                        "name": "AlphaSift SKILL.md",
                        "description": "Agent workflow and CLI specification for AlphaSift.",
                        "mimeType": "text/markdown",
                    },
                    {
                        "uri": "alphasift://strategies",
                        "name": "AlphaSift Strategy Catalog",
                        "description": "Complete catalog of built-in screening strategies.",
                        "mimeType": "application/json",
                    },
                    {
                        "uri": "alphasift://patterns",
                        "name": "AlphaSift Pattern Catalog",
                        "description": "Complete catalog of stateless empirical K-line & trend pattern specs.",
                        "mimeType": "application/json",
                    },
                ]
            }
        if method == "resources/read":
            uri = params.get("uri")
            if not isinstance(uri, str) or not uri.strip():
                raise _RPCParamError(-32602, "Invalid params: missing resource uri")
            if uri == "alphasift://skill":
                text = self._read_skill_markdown()
                return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": text}]}
            if uri == "alphasift://strategies":
                payload = {"strategies": [asdict(item) for item in list_strategies(self.config.strategies_dir)]}
                return {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "application/json",
                            "text": json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False),
                        }
                    ]
                }
            if uri == "alphasift://patterns":
                payload = {"patterns": [asdict(item) for item in list_patterns(include_experimental=True)]}
                return {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "application/json",
                            "text": json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False),
                        }
                    ]
                }
            raise _RPCParamError(-32602, f"Unknown resource URI: {uri}")
        raise _RPCParamError(-32601, f"Method not found: {method}")


def _read_bounded_line(stream: BinaryIO, limit: int = _MAX_CONTENT_LENGTH) -> bytes:
    line = stream.readline(limit + 1)
    if len(line) > limit:
        raise ValueError("MCP frame line exceeds maximum length")
    return line


class _FramingError(ValueError):
    """Raised when reading a framed STDIO message fails after framing mode is known."""

    def __init__(self, message: str, *, framing: str = "line") -> None:
        super().__init__(message)
        self.framing = framing


def _read_exact_bytes(stream: BinaryIO, length: int, *, framing: str = "headers") -> bytes:
    chunks: list[bytes] = []
    remaining = length
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            raise _FramingError("Truncated Content-Length body", framing=framing)
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_stdio_message(stream: BinaryIO) -> tuple[str, bytes] | None:
    """Read either a Content-Length framed body or a newline-delimited JSON line."""
    while True:
        first_line = _read_bounded_line(stream)
        if not first_line:
            return None
        if not first_line.strip():
            continue
        break

    stripped = first_line.lstrip()
    if stripped.startswith((b"{", b"[")):
        return "line", first_line

    headers: dict[str, str] = {}
    line = first_line
    header_bytes = 0
    header_lines = 0
    while True:
        if line in (b"\r\n", b"\n", b""):
            break
        header_lines += 1
        header_bytes += len(line)
        if header_lines > _MAX_HEADER_LINES or header_bytes > _MAX_HEADER_BYTES:
            raise _FramingError("MCP headers exceed maximum limits", framing="headers")
        decoded = line.decode("ascii", errors="replace").rstrip("\r\n")
        if ":" in decoded:
            k, v = decoded.split(":", 1)
            key_lower = k.strip().lower()
            val_clean = v.strip()
            if key_lower == "content-length" and key_lower in headers and headers[key_lower] != val_clean:
                raise _FramingError("Conflicting Content-Length headers", framing="headers")
            headers[key_lower] = val_clean
        line = _read_bounded_line(stream, limit=_MAX_HEADER_BYTES)
        if not line:
            return None

    raw_len = headers.get("content-length")
    if raw_len is None or not raw_len.isdigit():
        raise _FramingError("Missing or invalid Content-Length header", framing="headers")
    length = int(raw_len)
    if length < 0 or length > _MAX_CONTENT_LENGTH:
        raise _FramingError(f"Invalid Content-Length: {length}", framing="headers")
    body = _read_exact_bytes(stream, length, framing="headers")
    return "headers", body


def write_stdio_message(stream: BinaryIO, payload: dict[str, Any], *, framing: str = "line") -> None:
    """Serialize one JSON-RPC response in either header-framed or line-delimited mode."""
    encoded = json.dumps(_json_safe(payload), ensure_ascii=False, allow_nan=False).encode(
        "utf-8", errors="replace"
    )
    if framing == "headers":
        header = f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii")
        stream.write(header + encoded)
    else:
        stream.write(encoded + b"\n")
    stream.flush()


def serve_mcp(
    config: Config | None = None,
    *,
    in_stream: BinaryIO | None = None,
    out_stream: BinaryIO | None = None,
) -> None:
    """Run blocking STDIO JSON-RPC loop for MCP clients."""
    server = MCPServer(config or Config.from_env())
    reader = in_stream or sys.stdin.buffer
    owned_writer: BinaryIO | None = None

    if out_stream is not None:
        writer = out_stream
    else:
        try:
            protocol_fd = os.dup(sys.stdout.fileno())
            os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
            owned_writer = os.fdopen(protocol_fd, "wb")
            writer = owned_writer
        except (OSError, ValueError, AttributeError):
            writer = sys.stdout.buffer

    try:
        while True:
            try:
                frame = read_stdio_message(reader)
            except ValueError as exc:
                err_framing = exc.framing if isinstance(exc, _FramingError) else "line"
                write_stdio_message(
                    writer,
                    {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}},
                    framing=err_framing,
                )
                break
            if frame is None:
                break
            framing, body = frame
            try:
                request = json.loads(body.decode("utf-8"))
            except (ValueError, RecursionError):
                write_stdio_message(
                    writer,
                    {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                    framing=framing,
                )
                continue
            response = server.handle_request(request)
            if response is not None:
                write_stdio_message(writer, response, framing=framing)
    finally:
        if owned_writer is not None:
            owned_writer.close()
