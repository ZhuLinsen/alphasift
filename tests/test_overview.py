from pathlib import Path

from alphasift.config import Config
from alphasift.models import EvaluationResult, Pick, PickEvaluation, ScreenResult
from alphasift.overview import build_overview
from alphasift.store import save_evaluation_result, save_screen_result


def test_build_overview_groups_strategies_and_recent_runs(tmp_path):
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            strategy_version="1.2",
            strategy_category="value",
            run_id="run_dual",
            snapshot_source="sina",
            source_errors=["sina: timeout"],
            degradation=["Snapshot source fallback: stale provider"],
            picks=[Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80)],
        ),
        data_dir=tmp_path,
    )
    save_evaluation_result(
        EvaluationResult(
            run_id="run_dual",
            strategy="dual_low",
            market="cn",
            created_at="2026-04-01T09:30:00",
            evaluated_at="2026-04-02T09:30:00",
            average_return_pct=4.0,
            win_rate=100.0,
            picks=[
                PickEvaluation(
                    code="000001",
                    name="平安银行",
                    rank=1,
                    entry_price=10,
                    current_price=10.4,
                    return_pct=4.0,
                    status="ok",
                    final_score=80,
                )
            ],
        ),
        data_dir=tmp_path,
    )
    config = Config(
        strategies_dir=Path("strategies"),
        data_dir=tmp_path,
        snapshot_source_priority=["sina"],
        daily_source="auto",
        fallback_snapshot_path=tmp_path / "snapshot.last_good.json",
        daily_history_cache_dir=tmp_path / "daily_history",
    )

    payload = build_overview(config, runs_limit=3)

    assert payload["schema_version"] == 1
    assert payload["summary"]["strategy_count"] >= 9
    assert payload["summary"]["daily_strategy_count"] >= 3
    assert payload["summary"]["recent_run_count"] == 1
    assert payload["recent_runs"][0]["run_id"] == "run_dual"
    assert payload["run_history_summary"]["run_count"] == 1
    assert payload["run_history_summary"]["strategies"][0]["strategy"] == "dual_low"
    assert payload["data_source_history"]["run_count"] == 1
    assert payload["data_source_history"]["snapshot_sources"][0]["snapshot_source"] == "sina"
    assert payload["data_source_history"]["summary"]["stability_status"] == "degraded"
    assert payload["performance_summary"]["evaluation_count"] == 1
    assert payload["performance_summary"]["leaderboard"][0]["strategy"] == "dual_low"
    assert payload["strategy_cards"]["summary"]["strategy_count"] >= 10
    cards = {
        item["name"]: item
        for item in payload["strategy_cards"]["cards"]
    }
    assert cards["dual_low"]["history"]["run_count"] == 1
    assert cards["dual_low"]["performance"]["evaluation_count"] == 1
    assert cards["dual_low"]["readiness"]["status"] == "skipped"
    assert payload["data_sources"]["health_summary"]["snapshot"]["requested_sources"] == ["sina"]
    assert payload["data_sources"]["freshness_summary"]["snapshot"]["data_state"] == "not_checked"
    assert payload["data_sources"]["freshness_summary"]["fresh_enough"] is False
    readiness = payload["data_sources"]["strategy_readiness_summary"]
    assert readiness["strategy_count"] >= 9
    assert readiness["unchecked_strategy_count"] >= 9
    by_risk = {
        item["name"]: item
        for item in payload["strategy_groups"]["by_risk_profile"]
    }
    facets = {
        item["name"]: item
        for item in payload["strategy_facets"]["facets"]
    }
    daily_requirements = {
        item["value"]: item
        for item in facets["data_requirement"]["values"]
    }
    assert "dual_low" in by_risk["defensive"]["strategies"]
    assert "volume_breakout" in daily_requirements["daily_k"]["strategies"]
    assert any("live-data-check" in item for item in payload["next_actions"])
    assert any("Compare `sina` with alternate snapshot providers" in item for item in payload["next_actions"])
    assert any("prioritizing this strategy" in item for item in payload["next_actions"])


def test_build_overview_includes_strategy_matches(tmp_path):
    config = Config(
        strategies_dir=Path("strategies"),
        data_dir=tmp_path,
        snapshot_source_priority=["sina"],
        daily_source="auto",
        fallback_snapshot_path=tmp_path / "snapshot.last_good.json",
        daily_history_cache_dir=tmp_path / "daily_history",
    )

    payload = build_overview(
        config,
        strategy_match={
            "risk_profile": "aggressive",
            "data_requirements": ["daily_k"],
        },
        match_limit=1,
    )

    assert payload["summary"]["strategy_match_count"] == 1
    assert payload["strategy_matches"][0]["name"] == "volume_breakout"
    assert "data_requirement:daily_k" in payload["strategy_matches"][0]["matched"]
    assert any("volume_breakout" in item for item in payload["next_actions"])


def test_build_overview_strategy_cards_follow_strategy_filter(tmp_path):
    config = Config(
        strategies_dir=Path("strategies"),
        data_dir=tmp_path,
        snapshot_source_priority=["sina"],
        daily_source="auto",
        fallback_snapshot_path=tmp_path / "snapshot.last_good.json",
        daily_history_cache_dir=tmp_path / "daily_history",
    )

    payload = build_overview(config, strategy_name="blue_chip_income")

    assert payload["strategy_cards"]["strategy_filter"] == "blue_chip_income"
    assert payload["strategy_cards"]["summary"]["strategy_count"] == 1
    assert [item["name"] for item in payload["strategy_cards"]["cards"]] == ["blue_chip_income"]
