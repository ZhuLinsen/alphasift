from pathlib import Path

from alphasift.config import Config
from alphasift.models import Pick, ScreenResult
from alphasift.overview import build_overview
from alphasift.store import save_screen_result


def test_build_overview_groups_strategies_and_recent_runs(tmp_path):
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            strategy_version="1.2",
            strategy_category="value",
            run_id="run_dual",
            snapshot_source="sina",
            picks=[Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80)],
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
    assert payload["data_sources"]["health_summary"]["snapshot"]["requested_sources"] == ["sina"]
    assert payload["data_sources"]["freshness_summary"]["snapshot"]["data_state"] == "not_checked"
    assert payload["data_sources"]["freshness_summary"]["fresh_enough"] is False
    by_risk = {
        item["name"]: item
        for item in payload["strategy_groups"]["by_risk_profile"]
    }
    assert "dual_low" in by_risk["defensive"]["strategies"]
    assert any("live-data-check" in item for item in payload["next_actions"])


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
