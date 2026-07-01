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
