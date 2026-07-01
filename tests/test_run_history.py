from alphasift.models import Pick, ScreenResult
from alphasift.run_history import build_strategy_run_summary
from alphasift.store import save_screen_result


def test_build_strategy_run_summary_groups_saved_run_metadata(tmp_path):
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="run_old",
            strategy_category="value",
            created_at="2026-04-01T09:30:00",
            snapshot_source="sina",
            source_errors=["akshare: timeout"],
            degradation=["fallback"],
            llm_ranked=True,
            llm_coverage=0.5,
            daily_enriched=False,
            post_analyzers=["scorecard"],
            picks=[
                Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80),
                Pick(rank=2, code="600000", name="浦发银行", final_score=70, screen_score=70),
            ],
        ),
        data_dir=tmp_path,
    )
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="run_new",
            strategy_category="value",
            created_at="2026-04-02T09:30:00",
            snapshot_source="efinance",
            llm_ranked=True,
            llm_coverage=1.0,
            daily_enriched=True,
            daily_enrich_count=2,
            post_analyzers=["scorecard", "dsa"],
            picks=[Pick(rank=1, code="000002", name="万科A", final_score=85, screen_score=85)],
        ),
        data_dir=tmp_path,
    )
    save_screen_result(
        ScreenResult(
            strategy="volume_breakout",
            market="cn",
            run_id="run_breakout",
            strategy_category="momentum",
            created_at="2026-04-03T09:30:00",
            snapshot_source="sina",
            picks=[Pick(rank=1, code="300001", name="特锐德", final_score=88, screen_score=88)],
        ),
        data_dir=tmp_path,
    )

    payload = build_strategy_run_summary(data_dir=tmp_path, limit=10)
    by_strategy = {item["strategy"]: item for item in payload["strategies"]}

    assert payload["schema_version"] == 1
    assert payload["run_count"] == 3
    assert payload["strategy_count"] == 2
    assert payload["summary"]["total_picks"] == 4
    assert payload["summary"]["latest_run"]["run_id"] == "run_breakout"
    assert payload["summary"]["source_error_samples"] == ["akshare: timeout"]
    assert payload["summary"]["degradation_samples"] == ["fallback"]
    assert by_strategy["dual_low"]["run_count"] == 2
    assert by_strategy["dual_low"]["latest_run_id"] == "run_new"
    assert by_strategy["dual_low"]["total_picks"] == 3
    assert by_strategy["dual_low"]["average_picks"] == 1.5
    assert by_strategy["dual_low"]["runs_with_source_errors"] == 1
    assert by_strategy["dual_low"]["source_error_samples"] == ["akshare: timeout"]
    assert by_strategy["dual_low"]["runs_with_degradation"] == 1
    assert by_strategy["dual_low"]["degradation_samples"] == ["fallback"]
    assert by_strategy["dual_low"]["average_llm_coverage"] == 0.75
    assert by_strategy["dual_low"]["daily_enriched_runs"] == 1
    assert by_strategy["dual_low"]["post_analyzers"] == ["scorecard", "dsa"]
    assert by_strategy["dual_low"]["recent_runs"][1]["source_errors"] == ["akshare: timeout"]
    assert by_strategy["dual_low"]["recent_runs"][1]["degradation"] == ["fallback"]


def test_build_strategy_run_summary_supports_strategy_filter(tmp_path):
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="run_dual",
            picks=[Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80)],
        ),
        data_dir=tmp_path,
    )
    save_screen_result(
        ScreenResult(
            strategy="volume_breakout",
            market="cn",
            run_id="run_breakout",
            picks=[Pick(rank=1, code="300001", name="特锐德", final_score=88, screen_score=88)],
        ),
        data_dir=tmp_path,
    )

    payload = build_strategy_run_summary(data_dir=tmp_path, limit=10, strategy="dual_low")

    assert payload["strategy_filter"] == "dual_low"
    assert payload["run_count"] == 1
    assert payload["strategies"][0]["strategy"] == "dual_low"
