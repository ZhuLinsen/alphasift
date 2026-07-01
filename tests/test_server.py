from pathlib import Path

from alphasift.config import Config
from alphasift.models import Pick, ScreenResult
from alphasift.server import build_api_response
from alphasift.store import save_screen_result


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
    assert "/strategy-facets" in index["endpoints"]
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
    assert runs_status == 200
    assert runs["runs"][0]["run_id"] == "run_api"


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
