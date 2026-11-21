import json
import os
import subprocess
import sys
from pathlib import Path

from alphasift.config import Config
from alphasift.mcp import MCP_PROTOCOL_VERSION, MCPServer


def test_mcp_initialize_tools_and_resources(tmp_path):
    cfg = Config(data_dir=tmp_path)
    server = MCPServer(cfg)

    init_resp = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert init_resp is not None
    assert init_resp["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert init_resp["result"]["serverInfo"]["name"] == "alphasift"

    assert server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "ping"}) == {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {},
    }

    tools_resp = server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    tool_names = {item["name"] for item in tools_resp["result"]["tools"]}
    assert tool_names == {
        "alphasift_list_strategies",
        "alphasift_get_strategy",
        "alphasift_compare_strategies",
        "alphasift_screen",
        "alphasift_list_patterns",
        "alphasift_scan_patterns",
        "alphasift_overview",
        "alphasift_doctor_data_sources",
        "alphasift_notify_status",
        "alphasift_list_runs",
    }

    res_list = server.handle_request({"jsonrpc": "2.0", "id": 4, "method": "resources/list"})
    uris = {item["uri"] for item in res_list["result"]["resources"]}
    assert uris == {"alphasift://skill", "alphasift://strategies"}

    skill_res = server.handle_request(
        {"jsonrpc": "2.0", "id": 5, "method": "resources/read", "params": {"uri": "alphasift://skill"}}
    )
    assert "alphasift" in skill_res["result"]["contents"][0]["text"]

    strat_res = server.handle_request(
        {"jsonrpc": "2.0", "id": 6, "method": "resources/read", "params": {"uri": "alphasift://strategies"}}
    )
    strat_catalog = json.loads(strat_res["result"]["contents"][0]["text"])
    assert len(strat_catalog["strategies"]) >= 8


def test_mcp_tool_calls_and_safety_guards(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path)
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    server = MCPServer(cfg)

    # list strategies filtered to us
    us_strats = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": "alphasift_list_strategies", "arguments": {"market": "us"}},
        }
    )
    assert us_strats["result"]["isError"] is False
    us_names = {s["name"] for s in json.loads(us_strats["result"]["content"][0]["text"])["strategies"]}
    assert "us_momentum_quality" in us_names

    # path traversal blocked cleanly in get_strategy
    trav = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {"name": "alphasift_get_strategy", "arguments": {"name": "../secret"}},
        }
    )
    assert trav["result"]["isError"] is True
    assert "Unsafe strategy name" in trav["result"]["content"][0]["text"]

    # notify status never exposes secrets
    monkeypatch.setenv("WECOM_WEBHOOK_URL", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=TOP_SECRET")
    srv_secret = MCPServer(Config.from_env())
    nst = srv_secret.handle_request(
        {"jsonrpc": "2.0", "id": 12, "method": "tools/call", "params": {"name": "alphasift_notify_status"}}
    )
    txt = nst["result"]["content"][0]["text"]
    assert "TOP_SECRET" not in txt
    assert json.loads(txt)["wecom_configured"] is True

    # stdout prints inside tool handler are redirected away from JSON-RPC stream
    monkeypatch.setattr(
        "alphasift.mcp.screen",
        lambda strategy, **kw: print("NOISY_LIBRARY_STDOUT") or __import__(
            "alphasift.models", fromlist=["ScreenResult"]
        ).ScreenResult(strategy=strategy, market=kw["market"], strategy_version="1.0", snapshot_count=10, after_filter_count=2),
    )
    scr = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {"name": "alphasift_screen", "arguments": {"strategy": "balanced_alpha", "max_output": 200}},
        }
    )
    assert scr["result"]["isError"] is False
    assert "NOISY_LIBRARY_STDOUT" not in scr["result"]["content"][0]["text"]
    assert json.loads(scr["result"]["content"][0]["text"])["strategy"] == "balanced_alpha"

    # missing DailyPack produces clean isError instead of crashing
    scan = server.handle_request(
        {"jsonrpc": "2.0", "id": 14, "method": "tools/call", "params": {"name": "alphasift_scan_patterns"}}
    )
    assert scan["result"]["isError"] is True
    assert "DailyPack unavailable" in scan["result"]["content"][0]["text"]

    # unknown method & unknown tool error codes
    assert server.handle_request({"jsonrpc": "2.0", "id": 15, "method": "unknown/method"})["error"]["code"] == -32601
    assert (
        server.handle_request(
            {"jsonrpc": "2.0", "id": 16, "method": "tools/call", "params": {"name": "nope"}}
        )["error"]["code"]
        == -32602
    )


def test_mcp_stdio_subprocess_supports_line_and_content_length_framing(tmp_path):
    repo_root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env.pop("TICKPLUS_API_KEY", None)
    env["PYTHONPATH"] = str(repo_root)
    env["ALPHASIFT_DATA_DIR"] = str(tmp_path)

    # 1. Newline-delimited JSON framing
    line_input = (
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "alphasift_notify_status"}})
        + "\n"
    ).encode("utf-8")
    proc_line = subprocess.run(
        [sys.executable, "-m", "alphasift", "mcp"],
        input=line_input,
        capture_output=True,
        cwd=repo_root,
        env=env,
        timeout=20,
        check=True,
    )
    lines = [json.loads(line) for line in proc_line.stdout.decode("utf-8").splitlines() if line.strip()]
    assert [msg["id"] for msg in lines] == [1, 2]
    assert lines[0]["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert json.loads(lines[1]["result"]["content"][0]["text"])["any_configured"] is False

    # 2. Content-Length LSP/MCP header framing
    req1 = json.dumps({"jsonrpc": "2.0", "id": 10, "method": "ping"}).encode("utf-8")
    req2 = json.dumps({"jsonrpc": "2.0", "id": 11, "method": "tools/list"}).encode("utf-8")
    hdr_input = (
        f"Content-Length: {len(req1)}\r\n\r\n".encode("ascii")
        + req1
        + f"Content-Length: {len(req2)}\r\n\r\n".encode("ascii")
        + req2
    )
    proc_hdr = subprocess.run(
        [sys.executable, "-m", "alphasift", "mcp"],
        input=hdr_input,
        capture_output=True,
        cwd=repo_root,
        env=env,
        timeout=20,
        check=True,
    )
    raw = proc_hdr.stdout
    decoded_msgs = []
    pos = 0
    while pos < len(raw):
        sep = raw.index(b"\r\n\r\n", pos)
        hdr = raw[pos:sep].decode("ascii")
        length = int(hdr.split(":", 1)[1].strip())
        body_start = sep + 4
        decoded_msgs.append(json.loads(raw[body_start : body_start + length].decode("utf-8")))
        pos = body_start + length
    assert [m["id"] for m in decoded_msgs] == [10, 11]
    assert len(decoded_msgs[1]["result"]["tools"]) == 10


def test_mcp_round9_security_and_strict_schema_validation(tmp_path):
    cfg = Config(data_dir=tmp_path)
    server = MCPServer(cfg)

    # 1. String "false" must NOT be coerced to bool(True) and turn on billable LLM calls
    res_bad_bool = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 20,
            "method": "tools/call",
            "params": {"name": "alphasift_screen", "arguments": {"strategy": "dual_low", "use_llm": "false"}},
        }
    )
    assert res_bad_bool["result"]["isError"] is True
    assert "boolean" in res_bad_bool["result"]["content"][0]["text"]

    # 2. Arbitrary file paths in patterns[] are rejected BEFORE touching load_pattern
    secret_yaml = tmp_path / "secret.yaml"
    secret_yaml.write_text("api_key: super-secret\n", encoding="utf-8")
    res_path = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 21,
            "method": "tools/call",
            "params": {"name": "alphasift_scan_patterns", "arguments": {"patterns": [str(secret_yaml)]}},
        }
    )
    assert res_path["result"]["isError"] is True
    assert "Unknown or unsafe pattern name" in res_path["result"]["content"][0]["text"]
    assert "super-secret" not in res_path["result"]["content"][0]["text"]

    # 3. Non-finite NaN values in tool outputs serialize cleanly as null without crashing
    from alphasift.mcp import _json_safe

    cleaned = _json_safe({"score": float("nan"), "inf": float("inf"), "ok": 1.5})
    assert cleaned == {"score": None, "inf": None, "ok": 1.5}
    dumped = json.dumps(cleaned, allow_nan=False)
    assert "null" in dumped

    # 4. Invalid request ID types (float / bool / dict) are rejected with -32600
    bad_id = server.handle_request({"jsonrpc": "2.0", "id": True, "method": "ping"})
    assert bad_id["error"]["code"] == -32600

    # 5. Conflicting Content-Length headers are rejected cleanly
    import io
    from alphasift.mcp import read_stdio_message

    bad_hdr = io.BytesIO(b"Content-Length: 2\r\nContent-Length: 5\r\n\r\n{}")
    try:
        read_stdio_message(bad_hdr)
        raise AssertionError("Expected ValueError for conflicting Content-Length")
    except ValueError as exc:
        assert "Conflicting Content-Length" in str(exc)

    # 6. Unknown tool arguments rejected via additionalProperties check
    extra_arg = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 22,
            "method": "tools/call",
            "params": {"name": "alphasift_notify_status", "arguments": {"unexpected": True}},
        }
    )
    assert extra_arg["error"]["code"] == -32602

    # 7. Invalid request without "id" still returns -32600 instead of None
    invalid_no_id = server.handle_request({})
    assert invalid_no_id is not None and invalid_no_id["error"]["code"] == -32600

    # 8. Whitespace lines before JSON-RPC message are skipped cleanly
    ws_stream = io.BytesIO(b'   \n\t\r\n{"jsonrpc":"2.0","id":1,"method":"ping"}\n')
    framing, payload = read_stdio_message(ws_stream)
    assert framing == "line"
    assert json.loads(payload)["method"] == "ping"

    # 9. Single-element NumPy arrays retain shape & NaT serializes as None
    import numpy as np
    import pandas as pd

    arr_out = _json_safe({"a1": np.array([4]), "a2": np.array([[4]]), "s": np.float64(2.5), "t": pd.NaT})
    assert arr_out == {"a1": [4], "a2": [[4]], "s": 2.5, "t": None}

    # 10. Truncated Content-Length frame returns Content-Length-framed error
    from alphasift.mcp import serve_mcp

    trunc_in = io.BytesIO(b"Content-Length: 50\r\n\r\n{\"jsonrpc\":\"2.0\"")
    trunc_out = io.BytesIO()
    serve_mcp(cfg, in_stream=trunc_in, out_stream=trunc_out)
    raw_err = trunc_out.getvalue()
    assert raw_err.startswith(b"Content-Length: ")
    _, err_body = raw_err.split(b"\r\n\r\n", 1)
    assert json.loads(err_body.decode("utf-8"))["error"]["code"] == -32700
