from alphasift.models import EvaluationResult, PickEvaluation
from alphasift.performance_history import build_strategy_performance_summary
from alphasift.store import save_evaluation_result


def test_build_strategy_performance_summary_groups_saved_evaluations(tmp_path):
    save_evaluation_result(
        EvaluationResult(
            run_id="run_dual_old",
            strategy="dual_low",
            market="cn",
            created_at="2026-04-01T09:30:00",
            evaluated_at="2026-04-02T09:30:00",
            elapsed_days=1,
            snapshot_source="sina",
            average_return_pct=4.0,
            win_rate=50.0,
            picks=[
                PickEvaluation(
                    code="000001",
                    name="平安银行",
                    rank=1,
                    entry_price=10,
                    current_price=11,
                    return_pct=10.0,
                    status="ok",
                    final_score=80,
                ),
                PickEvaluation(
                    code="600000",
                    name="浦发银行",
                    rank=2,
                    entry_price=10,
                    current_price=9.8,
                    return_pct=-2.0,
                    status="ok",
                    final_score=70,
                ),
            ],
        ),
        data_dir=tmp_path,
    )
    save_evaluation_result(
        EvaluationResult(
            run_id="run_dual_new",
            strategy="dual_low",
            market="cn",
            created_at="2026-04-03T09:30:00",
            evaluated_at="2026-04-04T09:30:00",
            elapsed_days=1,
            snapshot_source="efinance",
            average_return_pct=6.0,
            win_rate=100.0,
            source_errors=["sina: timeout"],
            picks=[
                PickEvaluation(
                    code="000002",
                    name="万科A",
                    rank=1,
                    entry_price=10,
                    current_price=10.6,
                    return_pct=6.0,
                    status="ok",
                    final_score=82,
                    max_drawdown_pct=-1.5,
                    max_runup_pct=8.0,
                )
            ],
        ),
        data_dir=tmp_path,
    )
    save_evaluation_result(
        EvaluationResult(
            run_id="run_breakout",
            strategy="volume_breakout",
            market="cn",
            created_at="2026-04-05T09:30:00",
            evaluated_at="2026-04-06T09:30:00",
            elapsed_days=1,
            average_return_pct=-5.0,
            win_rate=0.0,
            degradation=["Missing current quote for 300001"],
            missing_codes=["300001"],
            picks=[
                PickEvaluation(
                    code="300001",
                    name="特锐德",
                    rank=1,
                    entry_price=10,
                    current_price=9.5,
                    return_pct=-5.0,
                    status="ok",
                    final_score=88,
                )
            ],
        ),
        data_dir=tmp_path,
    )

    payload = build_strategy_performance_summary(data_dir=tmp_path, limit=10)
    by_strategy = {item["strategy"]: item for item in payload["strategies"]}

    assert payload["schema_version"] == 1
    assert payload["evaluation_count"] == 3
    assert payload["strategy_count"] == 2
    assert payload["summary"]["average_return_pct"] == 2.25
    assert payload["summary"]["win_rate"] == 50.0
    assert payload["summary"]["outcome"] == "positive"
    assert payload["leaderboard"][0]["strategy"] == "dual_low"

    dual = by_strategy["dual_low"]
    assert dual["evaluation_count"] == 2
    assert dual["latest_run_id"] == "run_dual_new"
    assert dual["latest_snapshot_source"] == "efinance"
    assert dual["pick_count"] == 3
    assert dual["evaluated_pick_count"] == 3
    assert dual["average_return_pct"] == 4.6667
    assert dual["median_return_pct"] == 6.0
    assert dual["win_rate"] == 66.6667
    assert dual["average_run_return_pct"] == 5.0
    assert dual["run_win_rate"] == 100.0
    assert dual["performance_score"] == 67.7
    assert dual["outcome"] == "strong"
    assert dual["source_error_count"] == 1
    assert dual["next_actions"] == [
        "Consider prioritizing this strategy while continuing T+N validation."
    ]

    breakout = by_strategy["volume_breakout"]
    assert breakout["missing_count"] == 1
    assert breakout["missing_rate"] == 1.0
    assert breakout["outcome"] == "negative"
    assert breakout["next_actions"] == [
        "Review failure samples and tighten risk/event filters before reusing this strategy."
    ]


def test_build_strategy_performance_summary_supports_strategy_filter(tmp_path):
    save_evaluation_result(
        EvaluationResult(
            run_id="run_dual",
            strategy="dual_low",
            market="cn",
            created_at="2026-04-01T09:30:00",
            picks=[],
        ),
        data_dir=tmp_path,
    )
    save_evaluation_result(
        EvaluationResult(
            run_id="run_breakout",
            strategy="volume_breakout",
            market="cn",
            created_at="2026-04-01T09:30:00",
            picks=[],
        ),
        data_dir=tmp_path,
    )

    payload = build_strategy_performance_summary(data_dir=tmp_path, limit=10, strategy="dual_low")

    assert payload["strategy_filter"] == "dual_low"
    assert payload["evaluation_count"] == 1
    assert payload["strategies"][0]["strategy"] == "dual_low"


def test_build_strategy_performance_summary_scrubs_non_finite_metrics(tmp_path):
    save_evaluation_result(
        EvaluationResult(
            run_id="run_mixed_nonfinite",
            strategy="momentum_5d",
            market="cn",
            created_at="2026-04-07T09:30:00",
            evaluated_at="2026-04-08T09:30:00",
            elapsed_days=1,
            average_return_pct=float("nan"),
            win_rate=float("inf"),
            picks=[
                PickEvaluation(
                    code="000001",
                    name="平安银行",
                    rank=1,
                    entry_price=10.0,
                    current_price=10.5,
                    return_pct=5.0,
                    max_drawdown_pct=float("-inf"),
                    max_runup_pct=float("nan"),
                    status="ok",
                    final_score=80,
                ),
                PickEvaluation(
                    code="000002",
                    name="万科A",
                    rank=2,
                    entry_price=10.0,
                    current_price=10.0,
                    return_pct=float("nan"),
                    status="missing",
                    final_score=70,
                ),
            ],
        ),
        data_dir=tmp_path,
    )

    payload = build_strategy_performance_summary(data_dir=tmp_path, limit=10)
    assert payload["strategy_count"] == 1
    row = payload["strategies"][0]
    assert row["pick_count"] == 2
    assert row["evaluated_pick_count"] == 1
    assert row["average_return_pct"] == 5.0
    assert row["median_return_pct"] == 5.0
    assert row["win_rate"] == 100.0
    assert row["average_max_drawdown_pct"] is None
    assert row["average_max_runup_pct"] is None
    assert row["average_run_return_pct"] == 5.0
    assert row["performance_score"] == 85.0
    assert row["outcome"] == "strong"
    assert row["recent_evaluations"][0]["evaluated_pick_count"] == 1
    assert row["recent_evaluations"][0]["average_return_pct"] is None
    assert row["recent_evaluations"][0]["win_rate"] is None


def test_performance_history_helpers_scrub_nonfinite_and_bool(tmp_path):
    import json
    from alphasift.performance_history import _average, _median, _performance_score, _rate

    for bad_limit in (True, float("nan"), float("inf"), -5):
        payload = build_strategy_performance_summary(data_dir=tmp_path, limit=bad_limit)  # type: ignore[arg-type]
        assert payload["limit"] == 0
        assert payload["evaluation_count"] == 0
        json.dumps(payload, allow_nan=False)

    assert _performance_score(average_return_pct=5.0, win_rate=60.0, pick_count=True, missing_count=0) is None
    assert _performance_score(average_return_pct=float("nan"), win_rate=60.0, pick_count=4, missing_count=0) is None
    assert _performance_score(average_return_pct=5.0, win_rate=60.0, pick_count=4, missing_count=10) == 45.0

    assert _average([float("nan"), float("inf"), True, False, 2.0, 6.0]) == 4.0  # type: ignore[list-item]
    assert _average([float("nan"), True]) is None  # type: ignore[list-item]
    assert _median([float("nan"), float("-inf"), True, 1.0, 5.0]) == 3.0  # type: ignore[list-item]
    assert _median([float("inf"), False]) is None  # type: ignore[list-item]

    assert _rate(True, 4) is None  # type: ignore[arg-type]
    assert _rate(1, float("nan")) is None  # type: ignore[arg-type]
    assert _rate(1, 4, percent=True) == 25.0


def test_build_strategy_performance_summary_scrubs_na_fields_bad_elapsed_and_nones(
    monkeypatch,
    tmp_path,
):
    import json

    corrupt_eval = EvaluationResult(
        run_id=float("nan"),  # type: ignore[arg-type]
        strategy="NA",
        market="cn",
        created_at="2026-04-07T09:30:00",
        evaluated_at=float("nan"),  # type: ignore[arg-type]
        elapsed_days=True,  # type: ignore[arg-type]
        snapshot_source="null",
        picks=None,  # type: ignore[arg-type]
        missing_codes=None,  # type: ignore[arg-type]
        source_errors=None,  # type: ignore[arg-type]
        degradation=None,  # type: ignore[arg-type]
    )
    negative_elapsed = EvaluationResult(
        run_id="run_neg",
        strategy="nan",
        market="cn",
        created_at="2026-04-08T09:30:00",
        evaluated_at="2026-04-08T09:30:00",
        elapsed_days=-3,
        snapshot_source=None,  # type: ignore[arg-type]
        picks=[],
    )
    monkeypatch.setattr(
        "alphasift.performance_history._list_saved_evaluations",
        lambda **_kwargs: [corrupt_eval, negative_elapsed],
    )

    payload = build_strategy_performance_summary(data_dir=tmp_path, limit=10, strategy="  NA  ")

    json.dumps(payload, allow_nan=False)
    assert payload["strategy_filter"] == ""
    assert payload["evaluation_count"] == 2
    assert payload["strategy_count"] == 1
    row = payload["strategies"][0]
    assert row["strategy"] == "unknown"
    assert row["latest_elapsed_days"] is None
    assert row["latest_snapshot_source"] == ""
    assert row["source_error_count"] == 0
    assert row["degradation_count"] == 0
    assert all(entry["elapsed_days"] is None for entry in row["recent_evaluations"])
    assert all(entry["run_id"] != "nan" for entry in row["recent_evaluations"])
