from pathlib import Path

from alphasift.config import Config
from alphasift.models import EvaluationResult, Pick, PickEvaluation, ScreenResult
from alphasift.server import build_api_response
from alphasift.store import save_evaluation_result, save_screen_result


def _config(tmp_path):
    return Config(
        strategies_dir=Path("strategies"),
        data_dir=tmp_path,
        snapshot_source_priority=["sina"],
        daily_source="auto",
        fallback_snapshot_path=tmp_path / "snapshot.last_good.json",
        daily_history_cache_dir=tmp_path / "daily_history",
    )


def test_api_health_and_index(tmp_path):
    config = _config(tmp_path)

    status, index = build_api_response(config, "/")
    health_status, health = build_api_response(config, "/health")

    assert status == 200
    assert "/overview" in index["endpoints"]
    assert "/result-schema" in index["endpoints"]
    assert "/strategy" in index["endpoints"]
    assert "/strategy-compare" in index["endpoints"]
    assert "/strategy-facets" in index["endpoints"]
    assert "/strategy-cards" in index["endpoints"]
    assert "/strategy-readiness" in index["endpoints"]
    assert "/strategy-run-summary" in index["endpoints"]
    assert "/data-source-history" in index["endpoints"]
    assert "/strategy-performance" in index["endpoints"]
    assert "/strategy-templates" in index["endpoints"]
    assert health_status == 200
    assert health == {"status": "ok", "service": "alphasift", "schema_version": 1}


def test_api_overview_and_runs_are_ui_ready(tmp_path):
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="run_api",
            snapshot_source="sina",
            picks=[Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80)],
        ),
        data_dir=tmp_path,
    )
    config = _config(tmp_path)

    status, overview = build_api_response(
        config,
        "/overview",
        query="risk_profile=defensive&holding_period=swing&match_limit=1&runs_limit=1",
    )
    runs_status, runs = build_api_response(config, "/runs", query="strategy=dual_low&limit=1")

    assert status == 200
    assert overview["summary"]["strategy_match_count"] == 1
    assert overview["strategy_matches"][0]["name"] == "low_volatility_quality"
    assert overview["recent_runs"][0]["run_id"] == "run_api"
    assert overview["strategy_cards"]["cards"][0]["name"]
    assert runs_status == 200
    assert runs["runs"][0]["run_id"] == "run_api"
    assert overview["run_history_summary"]["strategies"][0]["strategy"] == "dual_low"


def test_api_strategy_run_summary_returns_saved_run_rollup(tmp_path):
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="run_a",
            created_at="2026-04-01T09:30:00",
            snapshot_source="sina",
            source_errors=["source: timeout"],
            picks=[Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80)],
        ),
        data_dir=tmp_path,
    )
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="run_b",
            created_at="2026-04-02T09:30:00",
            snapshot_source="efinance",
            picks=[Pick(rank=1, code="000002", name="万科A", final_score=85, screen_score=85)],
        ),
        data_dir=tmp_path,
    )

    status, payload = build_api_response(
        _config(tmp_path),
        "/strategy-run-summary",
        query="strategy=dual_low&limit=5",
    )

    assert status == 200
    assert payload["schema_version"] == 1
    assert payload["strategy_filter"] == "dual_low"
    assert payload["run_count"] == 2
    assert payload["strategies"][0]["strategy"] == "dual_low"
    assert payload["strategies"][0]["latest_run_id"] == "run_b"
    assert payload["strategies"][0]["runs_with_source_errors"] == 1


def test_api_data_source_history_returns_saved_run_source_rollup(tmp_path):
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="run_source_a",
            created_at="2026-04-01T09:30:00",
            snapshot_source="sina",
            source_errors=["source: timeout"],
            picks=[Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80)],
        ),
        data_dir=tmp_path,
    )
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="run_source_b",
            created_at="2026-04-02T09:30:00",
            snapshot_source="efinance",
            picks=[Pick(rank=1, code="000002", name="万科A", final_score=85, screen_score=85)],
        ),
        data_dir=tmp_path,
    )

    status, payload = build_api_response(
        _config(tmp_path),
        "/data-source-history",
        query="strategy=dual_low&limit=5",
    )

    assert status == 200
    assert payload["schema_version"] == 1
    assert payload["strategy_filter"] == "dual_low"
    assert payload["run_count"] == 2
    by_source = {item["snapshot_source"]: item for item in payload["snapshot_sources"]}
    assert by_source["sina"]["source_error_rate"] == 1.0
    assert by_source["sina"]["stability_status"] == "degraded"
    assert by_source["efinance"]["source_error_rate"] == 0.0
    assert by_source["efinance"]["stability_status"] == "ok"


def test_api_strategy_performance_returns_saved_evaluation_rollup(tmp_path):
    save_evaluation_result(
        EvaluationResult(
            run_id="run_perf_api",
            strategy="dual_low",
            market="cn",
            created_at="2026-04-01T09:30:00",
            evaluated_at="2026-04-02T09:30:00",
            average_return_pct=3.0,
            win_rate=100.0,
            picks=[
                PickEvaluation(
                    code="000001",
                    name="平安银行",
                    rank=1,
                    entry_price=10,
                    current_price=10.3,
                    return_pct=3.0,
                    status="ok",
                    final_score=80,
                )
            ],
        ),
        data_dir=tmp_path,
    )

    status, payload = build_api_response(
        _config(tmp_path),
        "/strategy-performance",
        query="strategy=dual_low&limit=5",
    )

    assert status == 200
    assert payload["schema_version"] == 1
    assert payload["strategy_filter"] == "dual_low"
    assert payload["evaluation_count"] == 1
    assert payload["leaderboard"][0]["strategy"] == "dual_low"
    assert payload["leaderboard"][0]["outcome"] == "strong"


def test_api_report_returns_run_report_payload(tmp_path):
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="run_report_api",
            snapshot_source="sina",
            picks=[
                Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80),
                Pick(rank=2, code="600000", name="浦发银行", final_score=70, screen_score=70),
            ],
        ),
        data_dir=tmp_path,
    )

    status, payload = build_api_response(
        _config(tmp_path),
        "/report",
        query="run=run_report_api&max_picks=1",
    )

    assert status == 200
    assert payload["object"] == "RunReport"
    assert payload["run"]["run_id"] == "run_report_api"
    assert len(payload["top_picks"]) == 1
    assert payload["top_picks"][0]["code"] == "000001"


def test_api_report_errors_are_json(tmp_path):
    missing_param_status, missing_param = build_api_response(_config(tmp_path), "/report")
    missing_run_status, missing_run = build_api_response(
        _config(tmp_path),
        "/report",
        query="run=missing",
    )

    assert missing_param_status == 400
    assert missing_param["error"] == "missing_run"
    assert missing_run_status == 404
    assert missing_run["error"] == "run_not_found"


def test_api_strategies_supports_matching_query(tmp_path):
    config = _config(tmp_path)

    status, payload = build_api_response(
        config,
        "/strategies",
        query="risk_profile=aggressive&data_requirement=daily_k&limit=1",
    )

    assert status == 200
    assert payload["schema_version"] == 1
    assert payload["strategies"][0]["name"] == "volume_breakout"
    assert "data_requirement:daily_k" in payload["strategies"][0]["matched"]


def test_api_strategy_facets_returns_filter_values(tmp_path):
    status, payload = build_api_response(_config(tmp_path), "/strategy-facets")

    assert status == 200
    assert payload["schema_version"] == 1
    facets = {
        item["name"]: item
        for item in payload["facets"]
    }
    data_values = {
        item["value"]: item
        for item in facets["data_requirement"]["values"]
    }
    assert facets["risk_profile"]["query_param"] == "risk_profile"
    assert facets["tag"]["multi"] is True
    assert "daily_k" in data_values
    assert "volume_breakout" in data_values["daily_k"]["strategies"]


def test_api_strategy_cards_returns_ui_cards(tmp_path):
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="run_card_api",
            snapshot_source="sina",
            picks=[Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80)],
        ),
        data_dir=tmp_path,
    )

    status, payload = build_api_response(
        _config(tmp_path),
        "/strategy-cards",
        query="strategy=dual_low&limit=5",
    )
    missing_status, missing = build_api_response(
        _config(tmp_path),
        "/strategy-cards",
        query="strategy=missing",
    )

    assert status == 200
    assert payload["schema_version"] == 1
    assert payload["strategy_filter"] == "dual_low"
    assert payload["cards"][0]["name"] == "dual_low"
    assert payload["cards"][0]["history"]["latest_run_id"] == "run_card_api"
    assert payload["cards"][0]["readiness"]["status"] == "skipped"
    assert missing_status == 404
    assert missing["error"] == "strategy_not_found"


def test_api_strategy_readiness_defaults_to_all_strategies_without_live(tmp_path):
    status, payload = build_api_response(_config(tmp_path), "/strategy-readiness")

    assert status == 200
    assert payload["schema_version"] == 1
    assert payload["config"]["live_checks"] is False
    assert payload["strategy_requirements"]["mode"] == "all"
    summary = payload["strategy_readiness_summary"]
    assert summary["strategy_count"] >= 9
    assert summary["unchecked_strategy_count"] >= 9
    assert summary["status_counts"]["skipped"] >= 9
    assert payload["strategy_coverage"][0]["status"] == "skipped"


def test_api_strategy_readiness_supports_single_strategy_and_errors(tmp_path):
    status, payload = build_api_response(
        _config(tmp_path),
        "/strategy-readiness",
        query="strategy=low_volatility_quality",
    )
    missing_status, missing = build_api_response(
        _config(tmp_path),
        "/strategy-readiness",
        query="strategy=missing",
    )

    assert status == 200
    assert payload["strategy_requirements"]["strategy"] == "low_volatility_quality"
    assert payload["strategy_readiness_summary"]["strategy_count"] == 1
    assert (
        payload["strategy_readiness_summary"]["unchecked_strategies"][0]["strategy"]
        == "low_volatility_quality"
    )
    assert missing_status == 404
    assert missing["error"] == "strategy_not_found"


def test_api_strategy_detail_returns_one_strategy(tmp_path):
    status, payload = build_api_response(
        _config(tmp_path),
        "/strategy",
        query="name=low_volatility_quality",
    )

    assert status == 200
    assert payload["schema_version"] == 1
    assert payload["strategy"]["name"] == "low_volatility_quality"
    assert payload["strategy"]["style"]["risk_profile"] == "defensive"
    assert "daily_k" in payload["strategy"]["data_requirements"]
    assert "volatility_20d_pct" in payload["strategy"]["required_daily_fields"]


def test_api_strategy_detail_errors_are_json(tmp_path):
    missing_status, missing = build_api_response(_config(tmp_path), "/strategy")
    unknown_status, unknown = build_api_response(
        _config(tmp_path),
        "/strategy",
        query="name=missing",
    )

    assert missing_status == 400
    assert missing["error"] == "missing_strategy_name"
    assert unknown_status == 404
    assert unknown["error"] == "strategy_not_found"
    assert unknown["name"] == "missing"


def test_api_strategy_compare_returns_diff_payload(tmp_path):
    status, payload = build_api_response(
        _config(tmp_path),
        "/strategy-compare",
        query="base=dual_low&target=low_volatility_quality",
    )

    assert status == 200
    assert payload["schema_version"] == 1
    comparison = payload["comparison"]
    assert comparison["base"]["name"] == "dual_low"
    assert comparison["target"]["name"] == "low_volatility_quality"
    assert "daily_k" in comparison["differences"]["data_requirements"]["added"]
    assert "daily_feature_requirement_changed" in comparison["summary"]["compatibility_notes"]


def test_api_strategy_compare_errors_are_json(tmp_path):
    missing_status, missing = build_api_response(
        _config(tmp_path),
        "/strategy-compare",
        query="base=dual_low",
    )
    unknown_status, unknown = build_api_response(
        _config(tmp_path),
        "/strategy-compare",
        query="base=dual_low&target=missing",
    )

    assert missing_status == 400
    assert missing["error"] == "missing_strategy_compare_params"
    assert unknown_status == 404
    assert unknown["error"] == "strategy_not_found"
    assert unknown["target"] == "missing"


def test_api_result_schema_returns_machine_readable_contract(tmp_path):
    status, payload = build_api_response(_config(tmp_path), "/result-schema")

    assert status == 200
    assert payload["object"] == "ScreenResult"
    assert "picks" in payload["top_level_fields"]
    assert "final_score" in payload["pick_fields"]
    assert payload["ui_card_fields"]["identity"] == [
        "rank",
        "code",
        "name",
        "final_score",
        "screen_score",
    ]


def test_api_strategy_templates_and_template_detail(tmp_path):
    catalog_status, catalog = build_api_response(_config(tmp_path), "/strategy-templates")
    detail_status, detail = build_api_response(
        _config(tmp_path),
        "/strategy-template",
        query="name=momentum_breakout_daily",
    )
    no_yaml_status, no_yaml_detail = build_api_response(
        _config(tmp_path),
        "/strategy-template",
        query="name=momentum_breakout_daily&include_yaml=false",
    )

    assert catalog_status == 200
    assert catalog["schema_version"] == 1
    assert catalog["templates"][0]["name"] == "defensive_value_quality"
    assert "yaml" not in catalog["templates"][0]
    assert detail_status == 200
    assert detail["template"]["name"] == "momentum_breakout_daily"
    assert "yaml" in detail["template"]
    assert "daily_k" in detail["template"]["data_requirements"]
    assert no_yaml_status == 200
    assert "yaml" not in no_yaml_detail["template"]


def test_api_strategy_template_errors_are_json(tmp_path):
    missing_status, missing = build_api_response(_config(tmp_path), "/strategy-template")
    unknown_status, unknown = build_api_response(
        _config(tmp_path),
        "/strategy-template",
        query="name=missing",
    )

    assert missing_status == 400
    assert missing["error"] == "missing_template_name"
    assert unknown_status == 404
    assert unknown["error"] == "strategy_template_not_found"
    assert unknown["name"] == "missing"


def test_api_doctor_defaults_to_no_live(tmp_path):
    config = _config(tmp_path)

    status, payload = build_api_response(
        config,
        "/doctor/data-sources",
        query="strategy=low_volatility_quality&no_daily=true",
    )

    assert status == 200
    assert payload["status"] == "skipped"
    assert payload["config"]["live_checks"] is False
    assert payload["strategy_requirements"]["strategy"] == "low_volatility_quality"
    assert payload["freshness_summary"]["snapshot"]["data_state"] == "not_checked"


def test_api_unknown_route_returns_endpoint_index(tmp_path):
    status, payload = build_api_response(_config(tmp_path), "/missing")

    assert status == 404
    assert payload["error"] == "not_found"
    assert "/doctor/data-sources" in payload["available_endpoints"]


def test_api_report_rejects_path_traversal_and_blocks_llm_on_get(tmp_path):
    outside = tmp_path / "secret.json"
    outside.write_text('{"secret": 1}', encoding="utf-8")
    cfg = _config(tmp_path)

    bad_status, bad_payload = build_api_response(cfg, "/report", query=f"run={outside}")
    assert bad_status == 400
    assert bad_payload["error"] == "invalid_run_id"

    trav_status, trav_payload = build_api_response(cfg, "/report", query="run=../secret")
    assert trav_status == 400
    assert trav_payload["error"] == "invalid_run_id"

    llm_status, llm_payload = build_api_response(cfg, "/daily-report", query="ai_brief=on")
    assert llm_status == 403
    assert llm_payload["error"] == "llm_get_disabled"


def test_api_report_rejects_cwd_shadow_and_symlinks(tmp_path, monkeypatch):
    import json

    cfg = _config(tmp_path)
    runs_dir = cfg.data_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    real_run = runs_dir / "2026-11-21_balanced_alpha.json"
    real_run.write_text(
        json.dumps({"strategy": "balanced_alpha", "run_id": "2026-11-21_balanced_alpha", "picks": []}),
        encoding="utf-8",
    )

    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    (cwd_dir / "shadow.json").write_text('{"strategy": "evil"}', encoding="utf-8")
    monkeypatch.chdir(cwd_dir)

    shadow_status, shadow_payload = build_api_response(cfg, "/report", query="run=shadow")
    assert shadow_status == 404
    assert shadow_payload["error"] == "run_not_found"

    outside_target = tmp_path / "outside.json"
    outside_target.write_text('{"strategy": "outside"}', encoding="utf-8")
    sym_run = runs_dir / "symrun.json"
    sym_run.symlink_to(outside_target)
    sym_status, sym_payload = build_api_response(cfg, "/report", query="run=symrun")
    assert sym_status == 400
    assert sym_payload["error"] == "invalid_run_id"

    dr_bad_status, dr_bad_payload = build_api_response(cfg, "/daily-report", query="run_id=../bad")
    assert dr_bad_status == 400
    assert dr_bad_payload["error"] == "invalid_run_id"


def test_http_workbench_ui_content_negotiation_security_headers_and_js_syntax(tmp_path):
    from http.server import ThreadingHTTPServer
    import json
    import subprocess
    import threading
    import urllib.request
    from alphasift.server import _handler_for_config
    from alphasift.workbench_ui import render_workbench_html

    cfg = _config(tmp_path)
    html_text = render_workbench_html()
    assert "http://" not in html_text and "https://" not in html_text
    assert "/strategy-compare?base=" in html_text
    assert "/strategy-compare?names=" not in html_text
    assert "noopener noreferrer" in html_text
    # Workbench aligns with actual backend JSON schema fields
    assert "s.market_scope" in html_text
    assert "radLlm.configured" in html_text
    assert 'p.status || "experimental"' in html_text
    assert "ov.summary" in html_text
    assert "snapshot_source_priority" in html_text
    assert "!ep.startsWith(\"//\")" in html_text

    # Regression checks for Audit #4 security fixes
    from alphasift.daily_report_html import render_daily_report_html

    xss_html = render_daily_report_html({
        "trade_date": "2026-11-21",
        "pack_trade_date": "2026-11-21",
        "detail_url": "</script><script>alert(1)</script>",
    })
    assert "</script><script>alert(1)" not in xss_html
    assert 'href="javascript:' not in render_daily_report_html({"detail_url": "javascript:alert(1)"})

    bad_pat_st, bad_pat = build_api_response(cfg, "/patterns/scan", query="pattern=/etc/passwd")
    assert bad_pat_st in {400, 503}
    if bad_pat_st == 400:
        assert bad_pat["error"] == "invalid_pattern"

    unknown_ov_st, unknown_ov = build_api_response(cfg, "/overview", query="strategy=missing_strat")
    assert unknown_ov_st == 404
    assert unknown_ov["error"] == "strategy_not_found"

    conflict_doc_st, _ = build_api_response(cfg, "/doctor/data-sources", query="strategy=dual_low&all_strategies=1")
    assert conflict_doc_st == 400

    script_body = html_text.split("<script>", 1)[1].rsplit("</script>", 1)[0]
    js_file = tmp_path / "wb.js"
    js_file.write_text(script_body, encoding="utf-8")
    subprocess.run(["node", "--check", str(js_file)], check=True)

    # Pure build_api_response("/") stays pure JSON
    idx_status, idx_payload = build_api_response(cfg, "/")
    assert idx_status == 200
    assert "/ui" in idx_payload["endpoints"]

    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for_config(cfg))
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # 1. GET /ui returns Workbench HTML + strict hashed script CSP (no unsafe-inline script-src)
        req_ui = urllib.request.Request(f"http://127.0.0.1:{port}/ui")
        with urllib.request.urlopen(req_ui, timeout=5) as resp:
            assert resp.status == 200
            assert "text/html" in resp.headers.get("Content-Type", "")
            assert resp.headers.get("X-Content-Type-Options") == "nosniff"
            assert resp.headers.get("X-Frame-Options") == "DENY"
            csp = resp.headers.get("Content-Security-Policy", "")
            assert "frame-ancestors 'none'" in csp
            assert "'sha256-" in csp
            assert "'unsafe-inline'" not in csp.split("style-src")[0]
            assert "AlphaSift" in resp.read().decode("utf-8")

        # 2. GET / with Accept: text/html serves Workbench UI + Vary: Accept
        req_html = urllib.request.Request(
            f"http://127.0.0.1:{port}/",
            headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
        )
        with urllib.request.urlopen(req_html, timeout=5) as resp:
            assert "text/html" in resp.headers.get("Content-Type", "")
            assert resp.headers.get("Vary") == "Accept"

        # 3. GET / with Accept: text/html;q=0, application/json OR ?format=json serves pure JSON without wildcard CORS
        req_qzero = urllib.request.Request(
            f"http://127.0.0.1:{port}/",
            headers={"Accept": "text/html;q=0, application/json;q=0.9"},
        )
        with urllib.request.urlopen(req_qzero, timeout=5) as resp:
            assert "application/json" in resp.headers.get("Content-Type", "")
            assert resp.headers.get("Vary") == "Accept"
            assert resp.headers.get("Access-Control-Allow-Origin") is None

        req_json = urllib.request.Request(
            f"http://127.0.0.1:{port}/",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req_json, timeout=5) as resp:
            assert "application/json" in resp.headers.get("Content-Type", "")
            assert resp.headers.get("X-Content-Type-Options") == "nosniff"
            assert resp.headers.get("Access-Control-Allow-Origin") is None
            data = json.loads(resp.read().decode("utf-8"))
            assert "/ui" in data["endpoints"]

        req_fmt = urllib.request.Request(
            f"http://127.0.0.1:{port}/?format=json",
            headers={"Accept": "text/html"},
        )
        with urllib.request.urlopen(req_fmt, timeout=5) as resp:
            assert "application/json" in resp.headers.get("Content-Type", "")

        # 4. Live /daily-report.html safely strips dangerous detail_url schemes & closes no script tags
        req_dr = urllib.request.Request(
            f"http://127.0.0.1:{port}/daily-report.html?detail_url=javascript:alert(1)",
        )
        try:
            with urllib.request.urlopen(req_dr, timeout=5) as resp:
                body_dr = resp.read().decode("utf-8")
                assert "javascript:alert(1)" not in body_dr
        except urllib.error.HTTPError as err_dr:
            assert err_dr.code in {400, 503}
    finally:
        server.shutdown()
        server.server_close()
