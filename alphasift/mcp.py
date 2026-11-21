# -*- coding: utf-8 -*-
"""Zero-dependency STDIO Model Context Protocol (MCP 2024-11-05) server for AlphaSift."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import redirect_stdout
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any, BinaryIO

from alphasift import __version__
from alphasift.config import Config
from alphasift.doctor import doctor_data_sources
from alphasift.markets import get_market
from alphasift.notify import notify_readiness
from alphasift.overview import build_overview
from alphasift.pack import PackError, load_pack, pack_dir
from alphasift.patterns import list_patterns, scan_patterns
from alphasift.pipeline import screen
from alphasift.store import list_saved_runs
from alphasift.strategy import compare_strategies, list_strategies, load_all_strategies

MCP_PROTOCOL_VERSION = "2024-11-05"
_MAX_CONTENT_LENGTH = 16 * 1024 * 1024
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    if value is None or isinstance(value, bool):
        return default
    parsed = int(value)
    return max(minimum, min(parsed, maximum))


def _require_str(args: dict[str, Any], key: str) -> str:
    raw = args.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"Missing or invalid required string parameter: {key!r}")
    return raw.strip()


class _RPCParamError(Exception):
    """Raised on JSON-RPC protocol/param errors (-32602 / -32601)."""

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
                        "description": "Optional list of pattern names.",
                    },
                    "trade_date": {"type": "string", "description": "Optional YYYY-MM-DD trade date."},
                    "include_experimental": {"type": "boolean", "default": False},
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
    ]


class MCPServer:
    """Stateless JSON-RPC 2.0 dispatcher implementing the AlphaSift MCP interface."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config.from_env()
        self._tools: list[dict[str, Any]] = _tool_definitions()
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            "alphasift_list_strategies": self._handle_list_strategies,
            "alphasift_get_strategy": self._handle_get_strategy,
            "alphasift_compare_strategies": self._handle_compare_strategies,
            "alphasift_screen": self._handle_screen,
            "alphasift_list_patterns": self._handle_list_patterns,
            "alphasift_scan_patterns": self._handle_scan_patterns,
            "alphasift_overview": self._handle_overview,
            "alphasift_doctor_data_sources": self._handle_doctor_data_sources,
            "alphasift_notify_status": self._handle_notify_status,
            "alphasift_list_runs": self._handle_list_runs,
        }

    def _handle_list_strategies(self, args: dict[str, Any]) -> Any:
        market = str(args.get("market") or "").strip().lower()
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
        return compare_strategies(base, target, self.config.strategies_dir)

    def _handle_screen(self, args: dict[str, Any]) -> Any:
        strategy = _require_str(args, "strategy")
        market = str(args.get("market") or "cn").strip().lower()
        get_market(market)
        raw_max_output = args.get("max_output")
        max_output = (
            _clamp_int(raw_max_output, default=10, minimum=1, maximum=50)
            if raw_max_output is not None
            else None
        )
        use_llm = bool(args.get("use_llm", False))
        explain_filters = bool(args.get("explain_filters", False))
        llm_context = args.get("llm_context")
        if llm_context is not None:
            llm_context = str(llm_context)[:4000]
        result = screen(
            strategy,
            market=market,
            max_output=max_output,
            use_llm=use_llm,
            llm_context=llm_context,
            explain_filters=explain_filters,
            config=self.config,
        )
        return asdict(result)

    def _handle_list_patterns(self, args: dict[str, Any]) -> Any:
        include_exp = bool(args.get("include_experimental", False))
        return {"patterns": [asdict(item) for item in list_patterns(include_experimental=include_exp)]}

    def _handle_scan_patterns(self, args: dict[str, Any]) -> Any:
        raw_patterns = args.get("patterns")
        if raw_patterns is not None:
            if not isinstance(raw_patterns, list) or not all(isinstance(p, str) for p in raw_patterns):
                raise ValueError("Parameter 'patterns' must be a list of strings.")
            patterns = [p.strip() for p in raw_patterns if p.strip()] or None
        else:
            patterns = None
        raw_date = args.get("trade_date")
        trade_date = str(raw_date).strip() if raw_date else None
        include_exp = bool(args.get("include_experimental", False))
        try:
            daily_pack = load_pack(pack_dir(self.config))
        except (OSError, PackError, ValueError) as exc:
            raise RuntimeError(
                f"CN DailyPack unavailable at {pack_dir(self.config)}: {exc}. "
                "Build a pack with `alphasift pack build` first."
            ) from exc
        return scan_patterns(
            daily_pack,
            patterns=patterns,
            trade_date=trade_date,
            include_experimental=include_exp,
        ).to_dict()

    def _handle_overview(self, args: dict[str, Any]) -> Any:
        strategy = str(args.get("strategy") or "").strip() or None
        runs_limit = _clamp_int(args.get("runs_limit"), default=5, minimum=1, maximum=50)
        live = bool(args.get("live_data_check", False))
        return build_overview(
            self.config,
            strategy_name=strategy,
            runs_limit=runs_limit,
            live_data_check=live,
        )

    def _handle_doctor_data_sources(self, args: dict[str, Any]) -> Any:
        strategy = str(args.get("strategy") or "").strip() or None
        market = str(args.get("market") or "").strip().lower() or None
        if market:
            get_market(market)
        run_live = bool(args.get("run_live", False))
        check_daily = bool(args.get("check_daily", True))
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
        strategy = str(args.get("strategy") or "").strip() or None
        market = str(args.get("market") or "").strip().lower() or None
        return {
            "runs": list_saved_runs(
                data_dir=self.config.data_dir,
                limit=limit,
                strategy=strategy,
                market=market,
            )
        }

    def _read_skill_markdown(self) -> str:
        candidates = [
            _PROJECT_ROOT / "SKILL.md",
            Path(__file__).resolve().parent / "SKILL.md",
        ]
        for path in candidates:
            if path.is_file():
                return path.read_text(encoding="utf-8")
        raise FileNotFoundError("SKILL.md not found")

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
            return {
                "jsonrpc": "2.0",
                "id": request.get("id") if isinstance(request, dict) else None,
                "error": {"code": -32600, "message": "Invalid JSON-RPC 2.0 request"},
            }

        method = request["method"]
        req_id = request.get("id")
        is_notification = "id" not in request
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
            try:
                payload = handler(arguments)
                return {
                    "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
                    "isError": False,
                }
            except Exception as exc:  # noqa: BLE001
                return {
                    "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
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
                            "text": json.dumps(payload, ensure_ascii=False, indent=2),
                        }
                    ]
                }
            raise _RPCParamError(-32602, f"Unknown resource URI: {uri}")
        raise _RPCParamError(-32601, f"Method not found: {method}")


def read_stdio_message(stream: BinaryIO) -> tuple[str, bytes] | None:
    """Read either a Content-Length framed body or a newline-delimited JSON line."""
    while True:
        first_line = stream.readline()
        if not first_line:
            return None
        if first_line in (b"\r\n", b"\n"):
            continue
        break

    stripped = first_line.lstrip()
    if stripped.startswith((b"{", b"[")):
        return "line", first_line

    headers: dict[str, str] = {}
    line = first_line
    while True:
        if line in (b"\r\n", b"\n", b""):
            break
        decoded = line.decode("ascii", errors="replace").rstrip("\r\n")
        if ":" in decoded:
            k, v = decoded.split(":", 1)
            headers[k.strip().lower()] = v.strip()
        line = stream.readline()
        if not line:
            return None

    raw_len = headers.get("content-length")
    if raw_len is None:
        raise ValueError("Missing Content-Length header")
    length = int(raw_len)
    if length < 0 or length > _MAX_CONTENT_LENGTH:
        raise ValueError(f"Invalid Content-Length: {length}")
    body = stream.read(length)
    if len(body) < length:
        return None
    return "headers", body


def write_stdio_message(stream: BinaryIO, payload: dict[str, Any], *, framing: str = "line") -> None:
    """Serialize one JSON-RPC response in either header-framed or line-delimited mode."""
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
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
    writer = out_stream or sys.stdout.buffer

    while True:
        try:
            frame = read_stdio_message(reader)
        except ValueError as exc:
            write_stdio_message(
                writer,
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}},
                framing="line",
            )
            continue
        if frame is None:
            break
        framing, body = frame
        try:
            request = json.loads(body.decode("utf-8"))
        except ValueError:
            write_stdio_message(
                writer,
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                framing=framing,
            )
            continue
        response = server.handle_request(request)
        if response is not None:
            write_stdio_message(writer, response, framing=framing)
