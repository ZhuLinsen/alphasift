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
        "alphasift_replay_patterns",
        "alphasift_markets_digest",
        "alphasift_daily_report",
    }

    res_list = server.handle_request({"jsonrpc": "2.0", "id": 4, "method": "resources/list"})
    uris = {item["uri"] for item in res_list["result"]["resources"]}
    assert uris == {"alphasift://skill", "alphasift://strategies", "alphasift://patterns", "alphasift://markets"}

    skill_res = server.handle_request(
        {"jsonrpc": "2.0", "id": 5, "method": "resources/read", "params": {"uri": "alphasift://skill"}}
    )
    assert "alphasift" in skill_res["result"]["contents"][0]["text"]

    strat_res = server.handle_request(
        {"jsonrpc": "2.0", "id": 6, "method": "resources/read", "params": {"uri": "alphasift://strategies"}}
    )
    strat_catalog = json.loads(strat_res["result"]["contents"][0]["text"])
    assert len(strat_catalog["strategies"]) >= 8

    pat_res = server.handle_request(
        {"jsonrpc": "2.0", "id": 61, "method": "resources/read", "params": {"uri": "alphasift://patterns"}}
    )
    pat_catalog = json.loads(pat_res["result"]["contents"][0]["text"])
    assert len(pat_catalog["patterns"]) >= 9

    mkt_res = server.handle_request(
        {"jsonrpc": "2.0", "id": 62, "method": "resources/read", "params": {"uri": "alphasift://markets"}}
    )
    mkt_catalog = json.loads(mkt_res["result"]["contents"][0]["text"])
    assert len(mkt_catalog["markets"]) == 7
    assert {item["id"] for item in mkt_catalog["markets"]} == {"cn", "us", "hk", "jp", "kr", "tw", "in"}
    assert all(isinstance(item.get("session_open"), str) and item.get("currency") for item in mkt_catalog["markets"])


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

    # stdout prints inside tool handler are redirected away from JSON-RPC stream,
    # and read-only MCP screen disables side-effectful downstream analyzers (post_analyzers=["scorecard"]).
    seen_post_analyzers = []

    def _mock_screen(strategy, **kw):
        seen_post_analyzers.append(kw.get("post_analyzers"))
        print("NOISY_LIBRARY_STDOUT")
        from alphasift.models import ScreenResult
        return ScreenResult(strategy=strategy, market=kw["market"], strategy_version="1.0", snapshot_count=10, after_filter_count=2)

    monkeypatch.setattr("alphasift.mcp.screen", _mock_screen)
    scr = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {"name": "alphasift_screen", "arguments": {"strategy": "balanced_alpha", "max_output": 200}},
        }
    )
    assert scr["result"]["isError"] is False
    assert seen_post_analyzers == [["scorecard"]]
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
    assert len(decoded_msgs[1]["result"]["tools"]) == 13


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


def test_mcp_reads_skill_markdown_from_user_base_fallback(monkeypatch, tmp_path):
    import site
    import alphasift.mcp as mcp_mod

    missing_root = tmp_path / "no_repo"
    missing_prefix = tmp_path / "no_prefix"
    user_base = tmp_path / "user_base"
    user_base.mkdir(parents=True)
    (user_base / "SKILL.md").write_text("# User Base Skill\n", encoding="utf-8")

    monkeypatch.setattr(mcp_mod, "_PROJECT_ROOT", missing_root)
    monkeypatch.setattr(mcp_mod.sys, "prefix", str(missing_prefix))
    monkeypatch.setattr(site, "USER_BASE", str(user_base))

    server = MCPServer(Config(data_dir=tmp_path))
    assert server._read_skill_markdown() == "# User Base Skill\n"



def test_mcp_replay_patterns_tool_and_validation_guards(tmp_path, monkeypatch):
    class _DummyPack:
        dates = ["2026-02-01", "2026-06-01", "2026-11-01"]

    captured: dict[str, object] = {}

    def _fake_load_pack(_path):
        return _DummyPack()

    def _fake_load_cn_benchmark(*, lookback_days):
        captured["lookback_days"] = lookback_days
        return "BENCH"

    def _fake_replay_patterns(daily_pack, **kwargs):
        captured["kwargs"] = kwargs
        return {
            "generated_at": "2026-11-24T15:00:00Z",
            "entry_mode": "next_open",
            "benchmark": "sh000300",
            "cost_bps": kwargs["cost_bps"],
            "regime_filter": {"active": True, "effective_regimes": ["startup", "main_up"]},
            "overhead_filter": {"active": True, "max_overhead_pct": kwargs["max_overhead_pct"]},
            "graduation_rule": {"min_samples": 200},
            "pack_summary": {"eval_sessions": 180},
            "universe_baseline": {"t5": {"equal_weight_excess_mean_pct": -0.3}},
            "patterns": [
                {
                    "pattern": "bottom_volume_yang",
                    "display_name": "底部倍量阳",
                    "family": "bottom_reversal",
                    "mode": "direct",
                    "total_signals": 82,
                    "untradable_share_pct": 1.2,
                    "horizons": {"t5": {"net_excess_mean_pct": 2.8}},
                    "graduation": {"recommended_status": "experimental"},
                    "stability": {"t_stat": 1.07},
                    "walk_forward_regime_audit": {
                        "h2_non_adverse_low_overhead": {"days": 16, "signals": 82, "daily_mean_pct": 2.848},
                    },
                }
            ],
        }

    monkeypatch.setattr("alphasift.mcp.load_pack", _fake_load_pack)
    monkeypatch.setattr("alphasift.mcp.load_cn_benchmark", _fake_load_cn_benchmark)
    monkeypatch.setattr("alphasift.mcp.replay_patterns", _fake_replay_patterns)

    server = MCPServer(Config(data_dir=tmp_path))
    ok = server.handle_request({
        "jsonrpc": "2.0",
        "id": 100,
        "method": "tools/call",
        "params": {
            "name": "alphasift_replay_patterns",
            "arguments": {
                "patterns": ["bottom_volume_yang"],
                "excluded_regimes": ["freezing"],
                "max_overhead_pct": 15.0,
                "cost_bps": 25.0,
            },
        },
    })
    assert ok["result"]["isError"] is False
    assert captured["lookback_days"] == 320
    assert captured["kwargs"] == {
        "patterns": ["bottom_volume_yang"],
        "benchmark_df": "BENCH",
        "warmup_days": 60,
        "cost_bps": 25.0,
        "allowed_regimes": None,
        "excluded_regimes": ["freezing"],
        "max_overhead_pct": 15.0,
    }
    body = json.loads(ok["result"]["content"][0]["text"])
    assert body["overhead_filter"] == {"active": True, "max_overhead_pct": 15.0}
    assert body["patterns"][0]["walk_forward_regime_audit"]["h2_non_adverse_low_overhead"]["daily_mean_pct"] == 2.848

    for idx, bad_args in enumerate(
        [
            {"max_overhead_pct": 0},
            {"max_overhead_pct": True},
            {"cost_bps": -1},
            {"patterns": ["../evil"]},
            {"excluded_regimes": "freezing"},
        ],
        start=101,
    ):
        err = server.handle_request({
            "jsonrpc": "2.0",
            "id": idx,
            "method": "tools/call",
            "params": {"name": "alphasift_replay_patterns", "arguments": bad_args},
        })
        assert err["result"]["isError"] is True, bad_args


def test_mcp_markets_digest_tool_and_validation_guards(tmp_path):
    from alphasift.models import Pick, ScreenResult
    from alphasift.store import save_screen_result

    cfg = Config(data_dir=tmp_path)
    save_screen_result(
        ScreenResult(
            strategy="us_momentum_quality",
            market="us",
            run_id="us_mom_1",
            track="rules",
            created_at="2026-11-20T22:00:00Z",
            snapshot_count=400,
            after_filter_count=12,
            picks=[
                Pick(rank=1, code="MSFT", name="Microsoft", final_score=94.0, screen_score=94.0),
                Pick(rank=2, code="AAPL", name="Apple", final_score=86.0, screen_score=86.0),
            ],
        ),
        data_dir=cfg.data_dir,
    )
    save_screen_result(
        ScreenResult(
            strategy="global_value",
            market="us",
            run_id="us_val_1",
            track="rules",
            created_at="2026-11-20T22:05:00Z",
            snapshot_count=400,
            after_filter_count=8,
            picks=[
                Pick(rank=1, code="AAPL", name="Apple", final_score=84.0, screen_score=84.0),
            ],
        ),
        data_dir=cfg.data_dir,
    )
    save_screen_result(
        ScreenResult(
            strategy="global_value",
            market="hk",
            run_id="hk_val_1",
            track="rules",
            created_at="2026-11-20T09:00:00Z",
            snapshot_count=300,
            after_filter_count=5,
            picks=[
                Pick(rank=1, code="00700", name="Tencent", final_score=88.5, screen_score=88.5),
            ],
        ),
        data_dir=cfg.data_dir,
    )

    server = MCPServer(cfg)
    ok = server.handle_request({
        "jsonrpc": "2.0",
        "id": 200,
        "method": "tools/call",
        "params": {
            "name": "alphasift_markets_digest",
            "arguments": {
                "markets": ["us", "US", "hk"],
                "include_news": False,
                "detail_url": "https://alphasift.zhulinsen.tech/",
            },
        },
    })
    assert ok is not None
    assert ok["result"]["isError"] is False
    body = json.loads(ok["result"]["content"][0]["text"])
    assert body["object"] == "MarketDigest"
    assert body["markets"] == ["us", "hk"]
    assert len(body["market_sections"]) == 2
    assert body["market_sections"][0]["market"] == "us"
    assert body["market_sections"][0]["top_picks"][0]["code"] == "AAPL"
    assert body["market_sections"][0]["top_picks"][0]["strategy_count"] == 2
    assert body["im_card_chars"] < 1200
    assert "https://alphasift.zhulinsen.tech/" in body["im_card_markdown"]

    for idx, bad_args in enumerate(
        [
            {"markets": []},
            {"markets": ["mars"]},
            {"trade_date": "2026/11/24"},
            {"trade_date": "2026-13-40"},
            {"include_news": "yes"},
            {"detail_url": "javascript:alert(1)"},
        ],
        start=201,
    ):
        err = server.handle_request({
            "jsonrpc": "2.0",
            "id": idx,
            "method": "tools/call",
            "params": {"name": "alphasift_markets_digest", "arguments": bad_args},
        })
        assert err is not None
        assert err["result"]["isError"] is True, bad_args

    proto_err = server.handle_request({
        "jsonrpc": "2.0",
        "id": 299,
        "method": "tools/call",
        "params": {"name": "alphasift_markets_digest", "arguments": {"bogus": 1}},
    })
    assert proto_err is not None
    assert proto_err["error"]["code"] == -32602


def test_mcp_daily_report_tool_and_validation_guards(tmp_path):
    import numpy as np
    import pandas as pd

    from alphasift.models import Pick, ScreenResult
    from alphasift.pack import DailyPack, FIELDS, pack_dir, save_pack
    from alphasift.store import save_screen_result

    cfg = Config(data_dir=tmp_path)
    server = MCPServer(cfg)

    missing_pack = server.handle_request({
        "jsonrpc": "2.0",
        "id": 300,
        "method": "tools/call",
        "params": {"name": "alphasift_daily_report", "arguments": {}},
    })
    assert missing_pack is not None
    assert missing_pack["result"]["isError"] is True
    assert "CN DailyPack unavailable" in missing_pack["result"]["content"][0]["text"]

    n_d = 25
    mat = {f: np.full((n_d, 1), 10.0, dtype=np.float32) for f in FIELDS}
    mat["open"][:, 0] = 10.0
    mat["high"][:, 0] = 10.2
    mat["low"][:, 0] = 9.9
    mat["close"][:, 0] = 10.1
    mat["volume"][:, 0] = 5_000_000.0
    mat["amount"][:, 0] = 50_000_000.0
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-10-01", periods=n_d)]
    last_date = dates[-1]
    save_pack(
        pack_dir(cfg),
        DailyPack(
            dates=np.asarray(dates, dtype=str),
            codes=np.asarray(["000001"], dtype=str),
            matrices=mat,
            meta=pd.DataFrame([{"code": "000001", "name": "平安", "industry": "银行", "pe_ratio": 5.0, "pb_ratio": 0.6, "total_mv": 1e11, "circ_mv": 9e10, "list_date": "1991-04-03", "is_st": False}]),
            sources=("test",),
        ),
    )
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="cn_dr_1",
            track="rules",
            created_at=f"{last_date}T08:00:00Z",
            snapshot_count=100,
            after_filter_count=5,
            picks=[Pick(rank=1, code="000001", name="平安", final_score=85.0, screen_score=85.0)],
        ),
        data_dir=cfg.data_dir,
    )
    replay_dir = tmp_path / "patterns"
    replay_dir.mkdir(parents=True, exist_ok=True)
    (replay_dir / "replay.json").write_text(
        json.dumps({
            "cost_bps": 25.0,
            "patterns": [
                {
                    "pattern": "double_bottom_breakout",
                    "horizons": {"t5": {"net_excess_mean_pct": 0.24, "excess_win_rate_pct": 54.0, "excess_scored": 40}},
                    "graduation": {"recommended_status": "experimental", "t5_net_excess_mean_pct": 0.24},
                    "walk_forward_regime_audit": {
                        "h2_non_adverse_low_overhead": {"days": 16, "signals": 28, "daily_mean_pct": 0.31},
                    },
                }
            ],
        }),
        encoding="utf-8",
    )

    ok = server.handle_request({
        "jsonrpc": "2.0",
        "id": 301,
        "method": "tools/call",
        "params": {
            "name": "alphasift_daily_report",
            "arguments": {"include_runs": True, "detail_url": "https://alphasift.zhulinsen.tech/"},
        },
    })
    assert ok is not None
    assert ok["result"]["isError"] is False
    body = json.loads(ok["result"]["content"][0]["text"])
    assert body["object"] == "DailyReport"
    assert body["ai_brief"]["mode"] == "rule_fallback"
    assert body["im_card_chars"] < 1200
    assert len(body["strategies"]) == 1
    assert "https://alphasift.zhulinsen.tech/" in body["im_card_markdown"]

    for idx, bad_args in enumerate(
        [
            {"trade_date": "2026/11/24"},
            {"trade_date": "2026-99-99"},
            {"include_runs": "yes"},
            {"include_experimental_patterns": "no"},
            {"detail_url": "javascript:alert(1)"},
        ],
        start=302,
    ):
        err = server.handle_request({
            "jsonrpc": "2.0",
            "id": idx,
            "method": "tools/call",
            "params": {"name": "alphasift_daily_report", "arguments": bad_args},
        })
        assert err is not None
        assert err["result"]["isError"] is True, bad_args

    proto_dr_err = server.handle_request({
        "jsonrpc": "2.0",
        "id": 399,
        "method": "tools/call",
        "params": {"name": "alphasift_daily_report", "arguments": {"bogus": 1}},
    })
    assert proto_dr_err is not None
    assert proto_dr_err["error"]["code"] == -32602


