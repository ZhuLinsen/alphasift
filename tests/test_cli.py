import json
import sys

import pandas as pd

from alphasift.cli import _append_industry_cache_history, _write_industry_cache_metadata, main
from alphasift.hotspot import (
    HotspotDetail,
    HotspotRouteItem,
    HotspotStock,
    HotspotSummary,
    TimelineEvent,
    save_hotspots_json,
)
from alphasift.models import EvaluationResult, Pick, PickEvaluation, ScreenResult
from alphasift.store import save_evaluation_result, save_screen_result


def test_write_industry_cache_metadata_supports_output_without_suffix(tmp_path):
    output = tmp_path / "industry_map"

    metadata_path = _write_industry_cache_metadata(
        output,
        provider="akshare",
        max_boards=3,
        rows=12,
        notes=["ok"],
        generated_at="2026-04-28T10:00:00",
        history_path=tmp_path / "industry_map.history.jsonl",
    )

    data = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata_path.name == "industry_map.meta.json"
    assert data["provider"] == "akshare"
    assert data["max_boards"] == 3
    assert data["rows"] == 12
    assert data["history_path"].endswith("industry_map.history.jsonl")


def test_append_industry_cache_history_groups_board_summaries(tmp_path):
    output = tmp_path / "industry_map.csv"

    history_path = _append_industry_cache_history(
        output,
        mapping={
            "000001": {"board_heat_summary": "银行:+1.20%:rank=3", "board_heat_score": 72.5},
            "600000": {"board_heat_summary": "银行:+1.20%:rank=3", "board_heat_score": 70.0},
            "000002": {"board_heat_summary": "地产:+0.50%:rank=8", "board_heat_score": 55.0},
        },
        generated_at="2026-04-28T10:00:00",
    )

    rows = [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_board = {row["board"]: row for row in rows}
    assert history_path.name == "industry_map.csv.history.jsonl"
    assert by_board["银行"]["code_count"] == 2
    assert by_board["银行"]["max_board_heat_score"] == 72.5
    assert by_board["地产"]["code_count"] == 1


def test_cli_hotspots_provider_none_explain_does_not_call_network(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["alphasift", "hotspots", "--provider", "none", "--explain"])

    main()

    out = capsys.readouterr().out
    assert "hotspots=0 provider=none" in out


def test_cli_strategies_json_exposes_catalog_metadata(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["alphasift", "strategies", "--json"])

    main()

    payload = json.loads(capsys.readouterr().out)
    by_name = {item["name"]: item for item in payload}
    low_volatility = by_name["low_volatility_quality"]
    assert low_volatility["requires_daily_features"] is True
    assert low_volatility["data_requirements"] == ["snapshot", "daily_k", "industry_context"]
    assert "pb_ratio" in low_volatility["required_snapshot_fields"]
    assert "volatility_20d_pct" in low_volatility["required_daily_fields"]
    assert low_volatility["factor_weights"]["stability"] == 0.30
    assert "volatility_20d_pct_max" in low_volatility["active_filters"]
    assert low_volatility["style"]["risk_profile"] == "defensive"
    assert low_volatility["style"]["holding_period"] == "swing"
    assert low_volatility["style"]["ui_badge"] == "质量"


def test_cli_strategies_explain_shows_data_requirements(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["alphasift", "strategies", "--explain"])

    main()

    out = capsys.readouterr().out
    assert "strategies=" in out
    assert "low_volatility_quality" in out
    assert "data=snapshot,daily_k,industry_context" in out
    assert "style=defensive/swing/quality_defensive" in out
    assert "required_fields=snapshot[" in out
    assert "daily_k[change_60d,signal_score" in out


def test_cli_strategies_json_matches_style_preferences(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [
        "alphasift",
        "strategies",
        "--risk-profile",
        "defensive",
        "--holding-period",
        "swing",
        "--market-regime",
        "risk_off",
        "--strict",
        "--json",
    ])

    main()

    payload = json.loads(capsys.readouterr().out)
    assert [item["name"] for item in payload] == ["low_volatility_quality"]
    assert payload[0]["score"] == 6.0
    assert payload[0]["missing"] == []
    assert payload[0]["style"]["ui_badge"] == "质量"


def test_cli_strategies_explain_matches_data_requirements(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [
        "alphasift",
        "strategies",
        "--risk-profile",
        "aggressive",
        "--data-requirement",
        "daily_k",
        "--limit",
        "2",
        "--explain",
    ])

    main()

    out = capsys.readouterr().out
    assert "strategy_matches=2" in out
    assert "criteria=risk_profile=aggressive;data_requirements=daily_k;limit=2" in out
    assert "volume_breakout" in out
    assert "matched=risk_profile:aggressive,data_requirement:daily_k" in out
    assert "capital_heat" in out
    assert "missing=data_requirement:daily_k" in out


def test_cli_strategies_compare_json_shows_parameter_diffs(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [
        "alphasift",
        "strategies",
        "--compare",
        "dual_low",
        "low_volatility_quality",
        "--json",
    ])

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["base"]["name"] == "dual_low"
    assert payload["target"]["name"] == "low_volatility_quality"
    assert "daily_k" in payload["differences"]["data_requirements"]["added"]
    assert "volatility_20d_pct" in payload["differences"]["required_daily_fields"]["added"]
    assert "daily_feature_requirement_changed" in payload["summary"]["compatibility_notes"]


def test_cli_strategies_compare_explain_shows_changed_sections(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [
        "alphasift",
        "strategies",
        "--compare",
        "dual_low",
        "low_volatility_quality",
        "--explain",
    ])

    main()

    out = capsys.readouterr().out
    assert "strategy_compare base=dual_low" in out
    assert "target=low_volatility_quality" in out
    assert "data_requirements:" in out
    assert "daily_k" in out
    assert "factor_weights:" in out


def test_cli_strategies_templates_json_returns_lightweight_catalog(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["alphasift", "strategies", "--templates", "--json"])

    main()

    payload = json.loads(capsys.readouterr().out)
    names = [item["name"] for item in payload]
    assert "defensive_value_quality" in names
    assert "momentum_breakout_daily" in names
    assert "yaml" not in payload[0]
    assert payload[1]["data_requirements"] == ["snapshot", "daily_k", "industry_context"]


def test_cli_strategies_template_json_returns_yaml(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["alphasift", "strategies", "--template", "momentum_breakout_daily", "--json"],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["name"] == "momentum_breakout_daily"
    assert payload["style"]["execution_style"] == "breakout"
    assert "require_price_above_ma20: true" in payload["yaml"]
    assert "daily_k" in payload["data_requirements"]


def test_cli_strategies_template_explain_includes_notes_and_yaml(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["alphasift", "strategies", "--template", "oversold_reversal_snapshot", "--explain"],
    )

    main()

    out = capsys.readouterr().out
    assert "strategy_template=oversold_reversal_snapshot" in out
    assert "note=适合数据源不稳定时的低依赖策略起点" in out
    assert "name: my_oversold_reversal" in out


def test_cli_runs_json_filters_strategy(monkeypatch, tmp_path, capsys):
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            strategy_version="1.2",
            strategy_category="value",
            run_id="run_dual",
            snapshot_source="sina",
            daily_enriched=True,
            post_analyzers=["scorecard"],
            picks=[Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80)],
        ),
        data_dir=tmp_path,
    )
    save_screen_result(
        ScreenResult(
            strategy="volume_breakout",
            market="cn",
            run_id="run_breakout",
            picks=[Pick(rank=1, code="000002", name="万科A", final_score=75, screen_score=75)],
        ),
        data_dir=tmp_path,
    )
    monkeypatch.setenv("ALPHASIFT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["alphasift", "runs", "--strategy", "dual_low", "--json"])

    main()

    payload = json.loads(capsys.readouterr().out)
    assert [item["run_id"] for item in payload] == ["run_dual"]
    assert payload[0]["strategy_version"] == "1.2"
    assert payload[0]["snapshot_source"] == "sina"
    assert payload[0]["daily_enriched"] is True
    assert payload[0]["post_analyzers"] == ["scorecard"]


def test_cli_evaluate_batch_explain_includes_failure_review(monkeypatch, tmp_path, capsys):
    save_screen_result(
        ScreenResult(
            strategy="volume_breakout",
            market="cn",
            run_id="run_fail",
            created_at="2026-04-01T09:30:00",
            picks=[
                Pick(
                    rank=1,
                    code="600000",
                    name="浦发银行",
                    final_score=70,
                    screen_score=70,
                    price=20,
                    llm_catalysts=["订单落地"],
                    llm_risks=["监管问询"],
                    breakout_20d_pct=0.2,
                )
            ],
        ),
        data_dir=tmp_path,
    )

    def fake_fetch_snapshot(*args, **kwargs):
        snapshot = pd.DataFrame([{"code": "600000", "price": 18}])
        snapshot.attrs["snapshot_source"] = "test"
        return snapshot

    monkeypatch.setenv("ALPHASIFT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("alphasift.evaluate.fetch_snapshot_with_fallback", fake_fetch_snapshot)
    monkeypatch.setattr(
        sys,
        "argv",
        ["alphasift", "evaluate-batch", "--limit", "1", "--cost-bps", "0", "--failure-samples", "1", "--explain"],
    )

    main()

    out = capsys.readouterr().out
    assert "failure_review failures=1 shown=1 negative=1" in out
    assert "event_signal_review signals=" in out
    assert "patches=1" in out
    assert "event_signals signal action picks avg_return win_rate failures codes" in out
    assert "event_signal_strategy_patches strategy prefer avoid evidence" in out
    assert "risk:监管问询" in out
    assert "风险:监管问询" in out
    assert "failure_samples run strategy rank code return status reasons" in out
    assert "run_fail" in out
    assert "negative_return" in out
    assert "failure_event_signals=" in out
    assert "failure_llm_risks=监管问询" in out
    assert "failure_next_actions=" in out


def test_cli_overview_json_combines_catalog_health_and_runs(monkeypatch, tmp_path, capsys):
    save_screen_result(
        ScreenResult(
            strategy="volume_breakout",
            market="cn",
            run_id="run_breakout",
            snapshot_source="sina",
            picks=[Pick(rank=1, code="000002", name="万科A", final_score=75, screen_score=75)],
        ),
        data_dir=tmp_path,
    )
    save_evaluation_result(
        EvaluationResult(
            run_id="run_breakout",
            strategy="volume_breakout",
            market="cn",
            created_at="2026-04-01T09:30:00",
            evaluated_at="2026-04-02T09:30:00",
            average_return_pct=7.0,
            win_rate=100.0,
            picks=[
                PickEvaluation(
                    code="000002",
                    name="万科A",
                    rank=1,
                    entry_price=10,
                    current_price=10.7,
                    return_pct=7.0,
                    status="ok",
                    final_score=75,
                )
            ],
        ),
        data_dir=tmp_path,
    )
    monkeypatch.setenv("ALPHASIFT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", [
        "alphasift",
        "overview",
        "--risk-profile",
        "aggressive",
        "--data-requirement",
        "daily_k",
        "--match-limit",
        "1",
        "--runs-limit",
        "1",
        "--json",
    ])

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["summary"]["strategy_match_count"] == 1
    assert payload["strategy_matches"][0]["name"] == "volume_breakout"
    assert payload["recent_runs"][0]["run_id"] == "run_breakout"
    assert payload["data_source_history"]["snapshot_sources"][0]["snapshot_source"] == "sina"
    assert payload["performance_summary"]["leaderboard"][0]["strategy"] == "volume_breakout"
    assert "health_summary" in payload["data_sources"]
    assert payload["data_sources"]["freshness_summary"]["snapshot"]["data_state"] == "not_checked"


def test_cli_overview_explain_formats_dashboard_summary(monkeypatch, tmp_path, capsys):
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="run_overview_explain",
            snapshot_source="sina",
            source_errors=["sina: timeout"],
            picks=[Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80)],
        ),
        data_dir=tmp_path,
    )
    monkeypatch.setenv("ALPHASIFT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", [
        "alphasift",
        "overview",
        "--risk-profile",
        "defensive",
        "--holding-period",
        "swing",
        "--market-regime",
        "risk_off",
        "--strict",
        "--match-limit",
        "1",
        "--explain",
    ])

    main()

    out = capsys.readouterr().out
    assert "overview generated_at=" in out
    assert "snapshot_health" in out
    assert "freshness fresh_enough=False" in out
    assert "source_history=" in out
    assert "status=degraded" in out
    assert "categories=" in out
    assert "strategy_matches:" in out
    assert "low_volatility_quality" in out
    assert "next_actions=" in out


def test_cli_performance_explain_formats_saved_evaluations(monkeypatch, tmp_path, capsys):
    save_evaluation_result(
        EvaluationResult(
            run_id="run_perf_cli",
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
    monkeypatch.setenv("ALPHASIFT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", [
        "alphasift",
        "performance",
        "--strategy",
        "dual_low",
        "--explain",
    ])

    main()

    out = capsys.readouterr().out
    assert "performance=evaluations=1 strategies=1 outcome=strong" in out
    assert "performance_leaderboard strategy evals score outcome avg_return win_rate latest_run" in out
    assert "dual_low" in out


def test_cli_hotspots_explain_shows_fallback_and_source_errors(monkeypatch, tmp_path, capsys):
    cache = tmp_path / "hotspots.json"
    save_hotspots_json(
        cache,
        [HotspotSummary(topic="AI算力", source="concept", rank=1, heat_score=82, leaders=["算力龙头"])],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "alphasift",
            "hotspots",
            "--provider",
            "unknown,none",
            "--fallback-cache",
            str(cache),
            "--explain",
        ],
    )

    main()

    out = capsys.readouterr().out
    assert "fallback=True" in out
    assert "source_errors=" in out
    assert "unknown provider" in out


def test_cli_hotspot_explain_formats_detail(monkeypatch, capsys):
    def fake_detail(topic, **kwargs):
        assert topic == "AI算力"
        assert kwargs["top_stocks"] == 1
        return HotspotDetail(
            summary=HotspotSummary(
                topic=topic,
                source="concept",
                rank=1,
                heat_score=82,
                stage="加速主升",
                sample_stock_count=1,
                leaders=["算力龙头"],
                provider_used="last_good_cache",
                fallback_used=True,
                stale=True,
                source_errors=["akshare: disconnected"],
            ),
            stocks=[
                HotspotStock(
                    code="300001",
                    name="算力龙头",
                    role="核心龙头",
                    hot_stock_score=95,
                    change_pct=10,
                )
            ],
            timeline=[
                TimelineEvent(
                    date="2026-06-05",
                    source="公告",
                    title="订单落地",
                    event_type="order",
                    impact_score=8,
                    related_codes=["300001"],
                )
            ],
            route=[
                HotspotRouteItem(
                    date="2026-06-05",
                    source="notice",
                    title="Order catalyst",
                    description="short catalyst summary",
                    event_type="order",
                    impact_score=8,
                )
            ],
        )

    monkeypatch.setattr("alphasift.cli.get_hotspot_detail", fake_detail)
    monkeypatch.setattr(
        sys,
        "argv",
        ["alphasift", "hotspot", "AI算力", "--top-stocks", "1", "--timeline", "--explain"],
    )

    main()

    out = capsys.readouterr().out
    assert "topic=AI算力" in out
    assert "核心龙头" in out
    assert "订单落地" in out
    assert "Order catalyst" in out
    assert "short catalyst summary" in out
    assert "fallback=True" in out
    assert "source_errors=akshare: disconnected" in out


def test_cli_hotspot_cache_writes_json_history_and_metadata(monkeypatch, tmp_path, capsys):
    output = tmp_path / "hotspots.json"
    history = tmp_path / "hotspot.history.jsonl"

    def fake_discover(**kwargs):
        assert kwargs["provider"] == "none"
        return [
            HotspotSummary(
                topic="AI算力",
                source="concept",
                rank=1,
                heat_score=80,
                leaders=["算力龙头"],
            )
        ]

    monkeypatch.setattr("alphasift.cli.discover_hotspots", fake_discover)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "alphasift",
            "hotspot-cache",
            "--provider",
            "none",
            "--output",
            str(output),
            "--history-path",
            str(history),
            "--explain",
        ],
    )

    main()

    assert "rows=1" in capsys.readouterr().out
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert payload["hotspots"][0]["topic"] == "AI算力"
    history_rows = [
        json.loads(line)
        for line in history.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert history_rows[0]["board"] == "AI算力"
    assert history_rows[0]["max_board_heat_score"] == 80
    metadata = json.loads((tmp_path / "hotspots.json.meta.json").read_text(encoding="utf-8"))
    assert metadata["schema_version"] == 2
    assert metadata["history_path"] == str(history)


def test_cli_hotspot_cache_does_not_overwrite_non_empty_cache_with_empty_provider(
    monkeypatch,
    tmp_path,
    capsys,
):
    output = tmp_path / "hotspots.json"
    history = tmp_path / "hotspot.history.jsonl"
    save_hotspots_json(
        output,
        [HotspotSummary(topic="AI算力", source="concept", rank=1, heat_score=82, leaders=["算力龙头"])],
    )
    original_cache = output.read_text(encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "alphasift",
            "hotspot-cache",
            "--provider",
            "none",
            "--output",
            str(output),
            "--history-path",
            str(history),
            "--explain",
        ],
    )

    main()

    out = capsys.readouterr().out
    assert "fallback=True" in out
    assert output.read_text(encoding="utf-8") == original_cache
    assert not history.exists()
    metadata = json.loads((tmp_path / "hotspots.json.meta.json").read_text(encoding="utf-8"))
    assert metadata["fallback_used"] is True
    assert metadata["history_appended"] is False
    assert metadata["rows"] == 1


def test_cli_doctor_dsa_readiness_missing_url_writes_json(monkeypatch, tmp_path, capsys):
    output = tmp_path / "dsa-readiness.json"
    monkeypatch.delenv("DSA_API_URL", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["alphasift", "doctor", "dsa-readiness", "--json", "--output", str(output)],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    written = json.loads(output.read_text(encoding="utf-8"))
    assert payload["available"] is False
    assert payload["status"] == "missing_url"
    assert written == payload


def test_cli_doctor_dsa_readiness_explain_uses_configured_url(monkeypatch, capsys):
    def fake_get(url, timeout):
        class FakeResponse:
            status_code = 405
            text = ""

        assert url == "http://localhost:8000/api/v1/analysis/analyze"
        assert timeout == 1.0
        return FakeResponse()

    monkeypatch.setattr("alphasift.dsa.requests.get", fake_get)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "alphasift",
            "doctor",
            "dsa-readiness",
            "--api-url",
            "http://localhost:8000",
            "--timeout-sec",
            "1",
            "--explain",
        ],
    )

    main()

    out = capsys.readouterr().out
    assert "dsa status=route_present available=True" in out
    assert "http://localhost:8000/api/v1/analysis/analyze" in out
