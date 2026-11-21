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
_MAX_HEADER_LINES = 32
_MAX_HEADER_BYTES = 8192
_MAX_PATTERN_SELECTION = 32
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


def _require_str(args: dict[str, Any], key: str) -> str:
    raw = args.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"Missing or invalid required string parameter: {key!r}")
    return raw.strip()


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
            "alphasift_overview": self._handle_overview,
            "alphasift_doctor_data_sources": self._handle_doctor_data_sources,
            "alphasift_notify_status": self._handle_notify_status,
            "alphasift_list_runs": self._handle_list_runs,
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
            config=self.config,
        )
        return asdict(result)

    def _handle_list_patterns(self, args: dict[str, Any]) -> Any:
        include_exp = _optional_bool(args, "include_experimental", False)
        return {"patterns": [asdict(item) for item in list_patterns(include_experimental=include_exp)]}

    def _handle_scan_patterns(self, args: dict[str, Any]) -> Any:
        raw_patterns = args.get("patterns")
        patterns: list[str] | None = None
        if raw_patterns is not None:
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
            patterns = selected or None

        trade_date = _optional_str(args, "trade_date") or None
        include_exp = _optional_bool(args, "include_experimental", False)
        try:
            daily_pack = load_pack(pack_dir(self.config))
        except (OSError, PackError, ValueError) as exc:
            raise RuntimeError(
                f"CN DailyPack unavailable: {type(exc).__name__}. "
                "Build a pack with `alphasift pack build` first."
            ) from exc
        return scan_patterns(
            daily_pack,
            patterns=patterns,
            trade_date=trade_date,
            include_experimental=include_exp,
        ).to_dict()

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

    def _read_skill_markdown(self) -> str:
        candidates = [
            _PROJECT_ROOT / "SKILL.md",
            Path(__file__).resolve().parent / "SKILL.md",
            Path(sys.prefix) / "SKILL.md",
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
