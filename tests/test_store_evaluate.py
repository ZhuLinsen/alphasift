import os
import threading

import pandas as pd

from alphasift.config import Config
from alphasift.evaluate import (
    evaluate_result_against_snapshot,
    evaluate_saved_run,
    evaluate_saved_runs,
    evaluate_saved_runs_by_windows,
)
from alphasift.models import Pick, ScreenResult
from alphasift.store import (
    list_saved_runs,
    load_screen_result,
    save_screen_result,
    screen_result_to_jsonl,
)


def test_save_and_load_screen_result(tmp_path):
    result = ScreenResult(
        strategy="dual_low",
        market="cn",
        run_id="run123",
        picks=[Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80, price=10)],
    )

    path = save_screen_result(result, data_dir=tmp_path)
    loaded = load_screen_result("run123", data_dir=tmp_path)

    assert path.name == "run123.json"
    assert loaded.picks[0].code == "000001"
    assert loaded.saved_path == str(path)


def test_list_saved_runs_reads_only_metadata_until_limit(tmp_path):
    result = ScreenResult(
        strategy="dual_low",
        market="cn",
        run_id="run_metadata",
        strategy_version="1.2",
        strategy_category="value",
        snapshot_count=3000,
        after_filter_count=100,
        snapshot_source="sina",
        source_errors=["akshare: timeout"],
        degradation=["used fallback"],
        llm_ranked=True,
        llm_coverage=0.75,
        daily_enriched=True,
        daily_enrich_count=20,
        post_analyzers=["scorecard"],
        created_at="2026-04-01T09:30:00",
        picks=[Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80, price=10)],
    )
    path = save_screen_result(result, data_dir=tmp_path)
    path.write_text("{not-valid-json", encoding="utf-8")

    runs = list_saved_runs(data_dir=tmp_path, limit=1)

    assert runs == [{
        "schema_version": 3,
        "run_id": "run_metadata",
        "strategy": "dual_low",
        "market": "cn",
        "strategy_version": "1.2",
        "strategy_category": "value",
        "created_at": "2026-04-01T09:30:00",
        "picks": 1,
        "snapshot_count": 3000,
        "after_filter_count": 100,
        "snapshot_source": "sina",
        "source_error_count": 1,
        "source_errors": ["akshare: timeout"],
        "degradation_count": 1,
        "degradation": ["used fallback"],
        "llm_ranked": True,
        "llm_coverage": 0.75,
        "daily_enriched": True,
        "daily_enrich_count": 20,
        "post_analyzers": ["scorecard"],
        "path": str(path),
        "report_path": str(path.with_suffix(".md")),
    }]


def test_list_saved_runs_falls_back_to_payload_when_metadata_missing(tmp_path):
    path = save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="run_legacy",
            created_at="2026-04-01T09:30:00",
            source_errors=["akshare: disconnected"],
            degradation=["used stale fallback"],
            picks=[Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80, price=10)],
        ),
        data_dir=tmp_path,
    )
    path.with_suffix(path.suffix + ".meta").unlink(missing_ok=True)

    runs = list_saved_runs(data_dir=tmp_path, limit=1)

    assert runs[0]["run_id"] == "run_legacy"
    assert runs[0]["picks"] == 1
    assert runs[0]["schema_version"] == 1
    assert runs[0]["strategy_version"] == ""
    assert runs[0]["source_error_count"] == 1
    assert runs[0]["source_errors"] == ["akshare: disconnected"]
    assert runs[0]["degradation_count"] == 1
    assert runs[0]["degradation"] == ["used stale fallback"]
    assert runs[0]["report_path"].endswith("run_legacy.md")


def test_screen_result_jsonl_contains_run_and_pick_lines():
    result = ScreenResult(
        strategy="dual_low",
        market="cn",
        run_id="run123",
        picks=[Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80)],
    )

    lines = screen_result_to_jsonl(result)

    assert '"type": "run"' in lines[0]
    assert '"type": "pick"' in lines[1]


def test_evaluate_result_against_snapshot_computes_returns():
    run = ScreenResult(
        strategy="dual_low",
        market="cn",
        run_id="run123",
        picks=[
            Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80, price=10),
            Pick(rank=2, code="600000", name="浦发银行", final_score=70, screen_score=70, price=20),
        ],
    )
    snapshot = pd.DataFrame([
        {"code": "000001", "price": 11},
        {"code": "600000", "price": 18},
    ])
    snapshot.attrs["snapshot_source"] = "test"

    result = evaluate_result_against_snapshot(run, snapshot)

    assert result.average_return_pct == 0.0
    assert result.win_rate == 50.0
    assert result.picks[0].return_pct == 10.0
    assert result.picks[1].return_pct == -10.0


def test_evaluate_result_normalizes_snapshot_and_pick_codes():
    run = ScreenResult(
        strategy="dual_low",
        market="cn",
        run_id="run123",
        picks=[Pick(rank=1, code="SZ000001", name="平安银行", final_score=80, screen_score=80, price=10)],
    )
    snapshot = pd.DataFrame([{"code": 1.0, "price": 11}])

    result = evaluate_result_against_snapshot(run, snapshot)

    assert result.picks[0].status == "ok"
    assert result.picks[0].return_pct == 10.0


def test_evaluate_result_against_snapshot_subtracts_cost_bps():
    run = ScreenResult(
        strategy="dual_low",
        market="cn",
        run_id="run123",
        picks=[Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80, price=10)],
    )
    snapshot = pd.DataFrame([{"code": "000001", "price": 11}])

    result = evaluate_result_against_snapshot(run, snapshot, cost_bps=10)

    assert result.picks[0].return_pct == 9.9


def test_evaluate_result_marks_breakout_follow_through_and_failure():
    run = ScreenResult(
        strategy="volume_breakout",
        market="cn",
        run_id="run123",
        picks=[
            Pick(
                rank=1,
                code="000001",
                name="平安银行",
                final_score=80,
                screen_score=80,
                price=10,
                breakout_20d_pct=0.5,
                consolidation_days_20d=10,
            ),
            Pick(
                rank=2,
                code="600000",
                name="浦发银行",
                final_score=70,
                screen_score=70,
                price=20,
                breakout_20d_pct=0.2,
            ),
        ],
    )
    snapshot = pd.DataFrame([
        {"code": "000001", "price": 10.4},
        {"code": "600000", "price": 19.0},
    ])

    result = evaluate_result_against_snapshot(
        run,
        snapshot,
        follow_through_pct=3.0,
        failed_breakout_pct=-3.0,
    )

    assert result.picks[0].shape_status == "breakout_follow_through"
    assert "consolidation_setup" in result.picks[0].shape_tags
    assert result.picks[1].shape_status == "failed_breakout"


def test_evaluate_result_computes_price_path_metrics():
    run = ScreenResult(
        strategy="dual_low",
        market="cn",
        run_id="run123",
        created_at="2026-04-01T09:30:00",
        picks=[Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80, price=10)],
    )
    snapshot = pd.DataFrame([{"code": "000001", "price": 11}])
    path = pd.DataFrame([
        {"日期": "2026-03-31", "收盘": 9.5, "最高": 9.8, "最低": 9.2},
        {"日期": "2026-04-01", "收盘": 10.2, "最高": 10.5, "最低": 9.7},
        {"日期": "2026-04-02", "收盘": 11.0, "最高": 11.5, "最低": 10.1},
    ])

    result = evaluate_result_against_snapshot(
        run,
        snapshot,
        price_paths={"SZ000001": path},
    )

    pick = result.picks[0]
    assert pick.path_status == "ok"
    assert pick.path_days == 2
    assert pick.path_end_return_pct == 10.0
    assert pick.max_drawdown_pct == -3.0
    assert pick.max_runup_pct == 15.0


def test_evaluate_saved_runs_aggregates_by_strategy(tmp_path, monkeypatch):
    def fake_fetch_daily_history(code, **kwargs):
        if code == "600000":
            return pd.DataFrame([
                {"日期": "2026-04-01", "收盘": 20.0, "最高": 20.5, "最低": 18.0},
                {"日期": "2026-04-02", "收盘": 18.0, "最高": 21.0, "最低": 19.0},
            ])
        return pd.DataFrame([
            {"日期": "2026-04-01", "收盘": 10.0, "最高": 10.5, "最低": 9.5},
            {"日期": "2026-04-02", "收盘": 11.0, "最高": 11.5, "最低": 10.0},
        ])

    monkeypatch.setattr("alphasift.evaluate.fetch_daily_history", fake_fetch_daily_history)
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="run_a",
            created_at="2026-04-01T09:30:00",
            picks=[
                Pick(
                    rank=1,
                    code="000001",
                    name="平安银行",
                    final_score=80,
                    screen_score=80,
                    price=10,
                    llm_sector="银行",
                    llm_theme="低估值修复",
                    llm_tags=["价值"],
                    risk_flags=["低波动"],
                    breakout_20d_pct=0.3,
                )
            ],
        ),
        data_dir=tmp_path,
    )
    save_screen_result(
        ScreenResult(
            strategy="volume_breakout",
            market="cn",
            run_id="run_b",
            created_at="2026-04-01T09:30:00",
            picks=[
                Pick(
                    rank=1,
                    code="600000",
                    name="浦发银行",
                    final_score=70,
                    screen_score=70,
                    price=20,
                    llm_tags=["订单催化"],
                    llm_catalysts=["订单落地"],
                    llm_risks=["监管问询"],
                    risk_flags=["高换手"],
                    portfolio_flags=["题材集中"],
                    post_analysis_tags=["volume_spike"],
                    breakout_20d_pct=0.2,
                )
            ],
        ),
        data_dir=tmp_path,
    )
    snapshot = pd.DataFrame([
        {"code": "000001", "price": 11},
        {"code": "600000", "price": 18},
    ])
    snapshot.attrs["snapshot_source"] = "test"

    result = evaluate_saved_runs(
        config=Config(llm_api_key="", data_dir=tmp_path),
        current_snapshot=snapshot,
        limit=10,
        cost_bps=0,
        with_price_path=True,
    )

    assert result["summary"]["run_count"] == 2
    assert result["summary"]["win_rate"] == 50.0
    assert result["summary"]["average_return_pct"] == 0.0
    assert result["by_strategy"]["dual_low"]["average_return_pct"] == 10.0
    assert result["by_strategy"]["volume_breakout"]["average_return_pct"] == -10.0
    strategy_summaries = result["strategy_summaries"]
    assert isinstance(strategy_summaries, list)
    assert isinstance(strategy_summaries[0], dict)
    assert isinstance(strategy_summaries[1], dict)
    assert strategy_summaries[0]["strategy"] == "dual_low"
    assert strategy_summaries[0]["outcome"] == "positive"
    assert strategy_summaries[0]["shape_status_counts"] == {"breakout_follow_through": 1}
    assert strategy_summaries[1]["strategy"] == "volume_breakout"
    assert strategy_summaries[1]["outcome"] == "negative"
    assert result["portfolio_summary"]["evaluated_run_count"] == 2
    assert result["portfolio_summary"]["average_portfolio_return_pct"] == 0.0
    assert result["portfolio_summary"]["portfolio_win_rate"] == 50.0
    assert result["portfolio_summary"]["average_portfolio_max_drawdown_pct"] == -7.5
    assert result["portfolio_by_strategy"]["dual_low"]["average_portfolio_return_pct"] == 10.0
    assert result["dimensions"]["by_sector"]["银行"]["average_return_pct"] == 10.0
    assert result["dimensions"]["by_theme"]["低估值修复"]["win_rate"] == 100.0
    assert result["dimensions"]["by_tag"]["价值"]["pick_count"] == 1
    assert result["dimensions"]["by_llm_catalyst"]["订单落地"]["pick_count"] == 1
    assert result["dimensions"]["by_llm_risk"]["监管问询"]["average_return_pct"] == -10.0
    assert result["dimensions"]["by_post_analysis_tag"]["volume_spike"]["pick_count"] == 1
    assert result["dimensions"]["by_risk_flag"]["低波动"]["average_return_pct"] == 10.0
    assert result["dimensions"]["by_holding_period"]["T+20_plus"]["pick_count"] == 2
    assert result["dimensions"]["by_shape_status"]["breakout_follow_through"]["pick_count"] == 1
    assert result["dimensions"]["by_shape_tag"]["breakout_setup"]["pick_count"] == 2
    assert result["dimensions"]["by_path_status"]["ok"]["pick_count"] == 2
    event_review = result["event_signal_review"]
    by_signal = {item["signal"]: item for item in event_review["signals"]}
    assert event_review["summary"]["signal_count"] >= 5
    assert by_signal["tag:价值"]["action"] == "prefer"
    assert by_signal["tag:价值"]["average_return_pct"] == 10.0
    assert by_signal["risk:监管问询"]["action"] == "avoid"
    assert by_signal["risk:监管问询"]["failure_count"] == 1
    assert any("Review avoided-event candidates" in item for item in event_review["recommendations"])
    patch_by_strategy = {
        item["strategy"]: item
        for item in event_review["strategy_patch_suggestions"]
    }
    assert event_review["summary"]["patch_suggestion_count"] == 2
    assert patch_by_strategy["dual_low"]["preferred_event_tags"] == ["价值"]
    assert "preferred_event_tags" in patch_by_strategy["dual_low"]["yaml_patch"]
    assert "风险:监管问询" in patch_by_strategy["volume_breakout"]["avoided_event_tags"]
    assert {
        "path": "screening.event_profile.avoided_event_tags",
        "operation": "append_unique",
        "add": patch_by_strategy["volume_breakout"]["avoided_event_tags"],
    } in patch_by_strategy["volume_breakout"]["field_changes"]
    review = result["failure_review"]
    assert review["summary"]["failure_count"] == 1
    assert review["summary"]["negative_pick_count"] == 1
    assert review["summary"]["failed_breakout_count"] == 1
    assert review["summary"]["severe_drawdown_count"] == 1
    assert review["failure_samples"][0]["code"] == "600000"
    assert "negative_return" in review["failure_samples"][0]["failure_reasons"]
    assert "shape_status:failed_breakout" in review["failure_samples"][0]["failure_reasons"]
    assert "risk:监管问询" in review["failure_samples"][0]["event_signals"]
    assert review["dimensions"]["by_event_signal"]["risk:监管问询"]["failure_count"] == 1
    assert review["dimensions"]["by_llm_risk"]["监管问询"]["failure_count"] == 1
    assert review["dimensions"]["by_post_analysis_tag"]["volume_spike"]["failure_count"] == 1
    assert review["dimensions"]["by_risk_flag"]["高换手"]["failure_count"] == 1
    assert review["dimensions"]["by_portfolio_flag"]["题材集中"]["failure_count"] == 1
    assert any("Failed breakout samples" in item for item in review["recommendations"])
    assert any("LLM risk `监管问询`" in item for item in review["recommendations"])
    assert result["summary"]["path_pick_count"] == 2
    assert result["summary"]["average_max_drawdown_pct"] == -7.5
    assert result["cost_bps"] == 0.0


def test_evaluate_saved_runs_uses_parallel_price_path_fetch_without_order_drift(tmp_path, monkeypatch):
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="run_parallel",
            created_at="2026-04-01T09:30:00",
            picks=[
                Pick(rank=1, code="000003", name="招商银行", final_score=90, screen_score=90, price=30),
                Pick(rank=2, code="000001", name="平安银行", final_score=80, screen_score=80, price=10),
                Pick(rank=3, code="600000", name="浦发银行", final_score=70, screen_score=70, price=20),
            ],
        ),
        data_dir=tmp_path,
    )
    snapshot = pd.DataFrame([
        {"code": "000001", "price": 11},
        {"code": "600000", "price": 18},
        {"code": "000003", "price": 33},
    ])
    snapshot.attrs["snapshot_source"] = "test"
    paths = {
        "000003": [
            {"日期": "2026-04-01", "收盘": 30.0, "最高": 31.5, "最低": 28.5},
            {"日期": "2026-04-02", "收盘": 33.0, "最高": 36.0, "最低": 27.0},
        ],
        "000001": [
            {"日期": "2026-04-01", "收盘": 10.0, "最高": 10.5, "最低": 9.5},
            {"日期": "2026-04-02", "收盘": 11.0, "最高": 11.5, "最低": 9.0},
        ],
        "600000": [
            {"日期": "2026-04-01", "收盘": 20.0, "最高": 20.5, "最低": 18.0},
            {"日期": "2026-04-02", "收盘": 18.0, "最高": 21.0, "最低": 17.0},
        ],
    }
    active = 0
    max_active = 0
    lock = threading.Lock()
    overlap_seen = threading.Event()

    def fake_fetch_daily_history(code, **kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            if active >= 2:
                overlap_seen.set()
        try:
            overlap_seen.wait(timeout=0.25)
            return pd.DataFrame(paths[code])
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr("alphasift.evaluate.fetch_daily_history", fake_fetch_daily_history)

    aggregate = evaluate_saved_runs(
        config=Config(llm_api_key="", data_dir=tmp_path, daily_fetch_max_workers=2),
        current_snapshot=snapshot,
        limit=10,
        cost_bps=0,
        with_price_path=True,
    )
    evaluation = evaluate_saved_run(
        "run_parallel",
        config=Config(llm_api_key="", data_dir=tmp_path, daily_fetch_max_workers=2),
        current_snapshot=snapshot,
        cost_bps=0,
        with_price_path=True,
    )

    assert max_active >= 2
    assert aggregate["summary"]["path_pick_count"] == 3
    assert [pick.code for pick in evaluation.picks] == ["000003", "000001", "600000"]
    assert [pick.path_end_return_pct for pick in evaluation.picks] == [10.0, 10.0, -10.0]
    assert [pick.max_drawdown_pct for pick in evaluation.picks] == [-10.0, -10.0, -15.0]


def test_evaluate_saved_runs_uses_cached_price_paths(tmp_path, monkeypatch):
    for run_id in ("run_cache_a", "run_cache_b"):
        save_screen_result(
            ScreenResult(
                strategy="dual_low",
                market="cn",
                run_id=run_id,
                created_at="2026-04-01T09:30:00",
                picks=[
                    Pick(
                        rank=1,
                        code="SZ000001",
                        name="平安银行",
                        final_score=80,
                        screen_score=80,
                        price=10,
                    )
                ],
            ),
            data_dir=tmp_path,
        )
    snapshot = pd.DataFrame([{"code": "000001", "price": 11}])
    snapshot.attrs["snapshot_source"] = "test"
    calls = {"count": 0}

    def fake_fetch_daily_akshare(code, *, lookback_days):
        calls["count"] += 1
        return pd.DataFrame([
            {"日期": "2026-04-01", "收盘": 10.0, "最高": 10.5, "最低": 9.5},
            {"日期": "2026-04-02", "收盘": 11.0, "最高": 11.5, "最低": 9.0},
        ])

    monkeypatch.setattr("alphasift.daily._fetch_daily_akshare", fake_fetch_daily_akshare)

    result = evaluate_saved_runs(
        config=Config(
            llm_api_key="",
            data_dir=tmp_path,
            daily_source="akshare",
            daily_fetch_retries=0,
            daily_history_cache_ttl_hours=24,
        ),
        current_snapshot=snapshot,
        limit=10,
        cost_bps=0,
        with_price_path=True,
        price_path_lookback_days=45,
    )

    assert calls["count"] == 1
    assert result["summary"]["run_count"] == 2
    assert result["summary"]["path_pick_count"] == 2
    assert len(list((tmp_path / "daily_history").glob("*.json"))) == 1


def test_evaluate_saved_runs_by_windows_aggregates_strategy_window_summaries(tmp_path, monkeypatch):
    def fake_fetch_daily_history(code, **kwargs):
        lookback = int(kwargs.get("lookback_days", 0) or 0)
        if lookback >= 10:
            path = pd.DataFrame(
                [
                    {"日期": "2026-04-01", "收盘": 10.0, "最高": 11.0, "最低": 9.0},
                    {"日期": "2026-04-02", "收盘": 11.0, "最高": 13.0, "最低": 9.5},
                    {"日期": "2026-04-03", "收盘": 11.5, "最高": 11.6, "最低": 10.5},
                    {"日期": "2026-04-04", "收盘": 10.2, "最高": 11.0, "最低": 10.1},
                    {"日期": "2026-04-05", "收盘": 11.2, "最高": 11.8, "最低": 9.8},
                ]
            )
        else:
            path = pd.DataFrame(
                [
                    {"日期": "2026-04-01", "收盘": 10.0, "最高": 11.0, "最低": 9.0},
                    {"日期": "2026-04-02", "收盘": 11.0, "最高": 13.0, "最低": 9.5},
                    {"日期": "2026-04-03", "收盘": 11.5, "最高": 11.6, "最低": 10.5},
                ]
            )
        return path

    monkeypatch.setattr("alphasift.evaluate.fetch_daily_history", fake_fetch_daily_history)
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="run_a",
            created_at="2026-04-01T09:30:00",
            picks=[
                Pick(
                    rank=1,
                    code="000001",
                    name="平安银行",
                    final_score=80,
                    screen_score=80,
                    price=10,
                    breakout_20d_pct=0.4,
                )
            ],
        ),
        data_dir=tmp_path,
    )
    save_screen_result(
        ScreenResult(
            strategy="volume_breakout",
            market="cn",
            run_id="run_b",
            created_at="2026-04-01T09:30:00",
            picks=[
                Pick(
                    rank=1,
                    code="600000",
                    name="浦发银行",
                    final_score=70,
                    screen_score=70,
                    price=20,
                    breakout_20d_pct=-0.5,
                )
            ],
        ),
        data_dir=tmp_path,
    )
    snapshot = pd.DataFrame(
        [
            {"code": "000001", "price": 11},
            {"code": "600000", "price": 18},
        ]
    )
    snapshot.attrs["snapshot_source"] = "test"

    payload = evaluate_saved_runs_by_windows(
        windows=[5, 10],
        config=Config(llm_api_key="", data_dir=tmp_path),
        current_snapshot=snapshot,
        limit=10,
        cost_bps=0,
    )
    window5 = evaluate_saved_runs(
        config=Config(llm_api_key="", data_dir=tmp_path),
        current_snapshot=snapshot,
        limit=10,
        cost_bps=0,
        with_price_path=True,
        price_path_lookback_days=5,
    )
    window10 = evaluate_saved_runs(
        config=Config(llm_api_key="", data_dir=tmp_path),
        current_snapshot=snapshot,
        limit=10,
        cost_bps=0,
        with_price_path=True,
        price_path_lookback_days=10,
    )

    assert payload["price_path_window_days"] == [5, 10]
    assert payload["with_price_path"] is True
    assert len(payload["strategy_summaries"]) == 2

    strategy = next(item for item in payload["strategy_summaries"] if item["strategy"] == "dual_low")
    assert strategy["window_count"] == 2
    assert [window.get("window_days") for window in strategy["window_summaries"]] == [5, 10]
    window5_summary = next(
        item for item in window5["strategy_summaries"] if item.get("strategy") == "dual_low"
    )
    window10_summary = next(
        item for item in window10["strategy_summaries"] if item.get("strategy") == "dual_low"
    )
    assert strategy["window_summaries"][0]["average_return_pct"] == window5_summary["average_return_pct"]
    assert strategy["window_summaries"][1]["average_return_pct"] == window10_summary["average_return_pct"]


def test_evaluate_saved_runs_filters_strategy_before_loading_runs(tmp_path):
    matching_path = save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="run_matching",
            created_at="2026-04-01T09:30:00",
            picks=[Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80, price=10)],
        ),
        data_dir=tmp_path,
    )
    newer_nonmatching_path = save_screen_result(
        ScreenResult(
            strategy="volume_breakout",
            market="cn",
            run_id="run_newer_nonmatching",
            created_at="2026-04-02T09:30:00",
            picks=[Pick(rank=1, code="600000", name="浦发银行", final_score=70, screen_score=70, price=20)],
        ),
        data_dir=tmp_path,
    )
    old_time = 1_800_000_000
    os.utime(matching_path, (old_time, old_time))
    os.utime(newer_nonmatching_path, (old_time + 10, old_time + 10))
    snapshot = pd.DataFrame([{"code": "000001", "price": 11}])
    snapshot.attrs["snapshot_source"] = "test"

    result = evaluate_saved_runs(
        config=Config(llm_api_key="", data_dir=tmp_path),
        current_snapshot=snapshot,
        limit=1,
        strategy="dual_low",
        cost_bps=0,
        with_price_path=False,
    )

    assert result["summary"]["run_count"] == 1
    assert result["runs"][0]["run_id"] == "run_matching"
