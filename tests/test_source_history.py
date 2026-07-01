from alphasift.models import Pick, ScreenResult
from alphasift.source_history import build_data_source_history
from alphasift.store import save_screen_result


def test_build_data_source_history_groups_runs_by_snapshot_source(tmp_path):
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="run_sina_old",
            created_at="2026-04-01T09:30:00",
            snapshot_source="sina",
            source_errors=["akshare: timeout"],
            degradation=["fallback"],
            picks=[
                Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80),
                Pick(rank=2, code="600000", name="浦发银行", final_score=70, screen_score=70),
            ],
        ),
        data_dir=tmp_path,
    )
    save_screen_result(
        ScreenResult(
            strategy="volume_breakout",
            market="cn",
            run_id="run_sina_new",
            created_at="2026-04-02T09:30:00",
            snapshot_source="sina",
            daily_enriched=True,
            daily_enrich_count=3,
            picks=[Pick(rank=1, code="300001", name="特锐德", final_score=88, screen_score=88)],
        ),
        data_dir=tmp_path,
    )
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="run_cache",
            created_at="2026-04-03T09:30:00",
            snapshot_source="last_good_cache",
            degradation=["Snapshot source fallback: last_good_cache stale"],
            picks=[Pick(rank=1, code="000002", name="万科A", final_score=85, screen_score=85)],
        ),
        data_dir=tmp_path,
    )

    payload = build_data_source_history(data_dir=tmp_path, limit=10)
    by_source = {item["snapshot_source"]: item for item in payload["snapshot_sources"]}

    assert payload["schema_version"] == 1
    assert payload["run_count"] == 3
    assert payload["source_count"] == 2
    assert payload["summary"]["runs_with_source_errors"] == 1
    assert payload["summary"]["source_error_rate"] == 0.3333
    assert payload["summary"]["source_error_samples"] == ["akshare: timeout"]
    assert payload["summary"]["degradation_samples"] == [
        "Snapshot source fallback: last_good_cache stale",
        "fallback",
    ]
    assert payload["summary"]["fallback_run_count"] == 1
    assert payload["summary"]["fallback_rate"] == 0.3333
    assert payload["summary"]["stability_status"] == "fallback"
    assert payload["summary"]["stability_score"] == 51.7
    assert payload["summary"]["next_actions"] == [
        "Refresh live snapshot providers before relying on last-good cache runs."
    ]
    assert payload["summary"]["latest_run"]["run_id"] == "run_cache"

    assert by_source["sina"]["run_count"] == 2
    assert by_source["sina"]["strategies"] == ["volume_breakout", "dual_low"]
    assert by_source["sina"]["strategy_count"] == 2
    assert by_source["sina"]["total_picks"] == 3
    assert by_source["sina"]["average_picks"] == 1.5
    assert by_source["sina"]["runs_with_source_errors"] == 1
    assert by_source["sina"]["source_error_rate"] == 0.5
    assert by_source["sina"]["source_error_samples"] == ["akshare: timeout"]
    assert by_source["sina"]["runs_with_degradation"] == 1
    assert by_source["sina"]["degradation_rate"] == 0.5
    assert by_source["sina"]["degradation_samples"] == ["fallback"]
    assert by_source["sina"]["fallback_rate"] == 0.0
    assert by_source["sina"]["stability_status"] == "degraded"
    assert by_source["sina"]["stability_score"] == 60.0
    assert by_source["sina"]["next_actions"] == [
        "Compare `sina` with alternate snapshot providers and inspect issue samples."
    ]
    assert by_source["sina"]["daily_enriched_runs"] == 1
    assert by_source["sina"]["daily_enrich_count"] == 3
    assert by_source["sina"]["recent_runs"][1]["source_errors"] == ["akshare: timeout"]

    assert by_source["last_good_cache"]["fallback_run_count"] == 1
    assert by_source["last_good_cache"]["fallback_rate"] == 1.0
    assert by_source["last_good_cache"]["degradation_rate"] == 1.0
    assert by_source["last_good_cache"]["stability_status"] == "fallback"
    assert by_source["last_good_cache"]["stability_score"] == 35.0
    assert payload["watchlist"][0]["snapshot_source"] == "last_good_cache"
    assert payload["watchlist"][0]["stability_status"] == "fallback"
    assert payload["watchlist"][0]["stability_score"] == 35.0
    assert payload["watchlist"][0]["degradation_samples"] == [
        "Snapshot source fallback: last_good_cache stale"
    ]
    assert payload["watchlist"][0]["next_actions"] == [
        "Refresh live snapshot providers before relying on last-good cache runs."
    ]


def test_build_data_source_history_supports_strategy_filter(tmp_path):
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="run_dual",
            snapshot_source="sina",
            picks=[Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80)],
        ),
        data_dir=tmp_path,
    )
    save_screen_result(
        ScreenResult(
            strategy="volume_breakout",
            market="cn",
            run_id="run_breakout",
            snapshot_source="efinance",
            picks=[Pick(rank=1, code="300001", name="特锐德", final_score=88, screen_score=88)],
        ),
        data_dir=tmp_path,
    )

    payload = build_data_source_history(data_dir=tmp_path, limit=10, strategy="dual_low")

    assert payload["strategy_filter"] == "dual_low"
    assert payload["run_count"] == 1
    assert payload["summary"]["stability_status"] == "ok"
    assert payload["summary"]["stability_score"] == 100.0
    assert payload["snapshot_sources"][0]["snapshot_source"] == "sina"
    assert payload["snapshot_sources"][0]["stability_status"] == "ok"
    assert payload["snapshot_sources"][0]["next_actions"] == []
