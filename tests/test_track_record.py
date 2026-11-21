import importlib.util
import json
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "track_record", Path(__file__).resolve().parents[1] / "scripts" / "track_record.py"
)
track_record = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(track_record)


def _write_run(track: Path, run_id: str, *, market: str, strategy: str, created_at: str, codes: list[str]):
    runs = track / "data" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    picks = [{"rank": i + 1, "code": code, "name": code, "price": 10.0, "final_score": 80.0} for i, code in enumerate(codes)]
    payload = {"run_id": run_id, "market": market, "strategy": strategy, "created_at": created_at, "picks": picks}
    (runs / f"{run_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def _outcome(status, ret=None, excess=None):
    return {"status": status, "return_pct": ret, "excess_return_pct": excess}


@pytest.mark.parametrize(
    "market, created_at, expected",
    [
        ("cn", "2026-11-04T18:30:00+08:00", "2026-11-04"),
        # Saved at 06:30 Beijing on Tuesday: the US session it belongs to is Monday.
        ("us", "2026-11-03T06:30:00+08:00", "2026-11-02"),
    ],
)
def test_session_date_is_the_exchange_day(market, created_at, expected):
    assert track_record.session_date(market, created_at) == expected


def test_scorecard_uses_one_population_for_return_and_excess(tmp_path):
    _write_run(tmp_path, "r1", market="cn", strategy="dual_low", created_at="2026-10-08T18:30:00+08:00", codes=["A", "B", "C"])
    _write_run(tmp_path, "r2", market="cn", strategy="dual_low", created_at="2026-10-09T18:30:00+08:00", codes=["D"])
    runs = track_record.load_runs(tmp_path)
    evaluation = {
        "r1": {"windows": {"5": {"picks": {
            "A": _outcome("ok", 4.0, 3.0),
            "B": _outcome("ok", -2.0, None),  # no benchmark match
            "C": _outcome("no_entry_close"),
        }}}},
        "r2": {"windows": {"5": {"picks": {"D": _outcome("pending")}}}},
    }

    [row] = track_record.scorecard(runs, evaluation)
    five = row["windows"]["5"]

    assert (five["evaluated"], five["pending"], five["unavailable"], five["matched"]) == (2, 1, 1, 1)
    assert five["untradable"] is None
    assert five["untradable_share_pct"] is None
    assert five["untradable_assessed"] is False
    assert row["entry_modes"] == ["close"]
    assert five["average_return_pct"] == 1.0
    assert five["win_rate"] == 0.5
    assert five["matched_return_pct"] == 4.0 and five["average_excess_return_pct"] == 3.0
    assert five["beat_rate"] == 1.0
    assert row["windows"]["20"]["evaluated"] == 0


def test_trend_is_an_expanding_mean_by_entry_date(tmp_path):
    _write_run(tmp_path, "r1", market="hk", strategy="global_value", created_at="2026-10-08T18:30:00+08:00", codes=["A"])
    _write_run(tmp_path, "r2", market="hk", strategy="global_value", created_at="2026-10-09T18:30:00+08:00", codes=["B"])
    runs = track_record.load_runs(tmp_path)
    evaluation = {
        "r1": {"windows": {"5": {"picks": {"A": _outcome("ok", 3.0, 2.0)}}}},
        "r2": {"windows": {"5": {"picks": {"B": _outcome("ok", -1.0, -4.0)}}}},
    }

    series = track_record.trend(runs, evaluation)["hk"]["5"]["global_value"]

    assert series == [["2026-10-08", 2.0, 1], ["2026-10-09", -1.0, 2]]


def test_build_writes_summary_days_and_readme(tmp_path, monkeypatch):
    _write_run(tmp_path, "r1", market="cn", strategy="dual_low", created_at="2026-10-08T18:30:00+08:00", codes=["A"])
    site = tmp_path / "site"
    site.mkdir()
    (site / "evaluation.json").write_text(json.dumps({"runs": {
        "r1": {"final": True, "windows": {"5": {"benchmark_return_pct": 1.0, "pending": 0,
                                                 "picks": {"A": _outcome("ok", 3.0, 2.0)}}}},
    }}), encoding="utf-8")

    summary = track_record.build_site(tmp_path)

    day = json.loads((site / "days" / "2026-10-08.json").read_text(encoding="utf-8"))
    assert day["runs"][0]["picks"][0]["evaluation"]["5"]["excess_return_pct"] == 2.0
    assert day["runs"][0]["evaluation"]["5"]["average_excess_return_pct"] == 2.0
    assert summary["days"] == [{"date": "2026-10-08", "runs": 1}]
    assert "+2.00%" in (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "path" not in summary["latest"]["cn"][0]


def test_evaluate_markets_reuses_benchmark_paths_and_self_heals_missing_benchmark(tmp_path, monkeypatch):
    import pandas as pd
    import alphasift.evaluate as eval_mod
    from alphasift.models import EvaluationResult, PickEvaluation

    _write_run(tmp_path, "r1", market="cn", strategy="dual_low", created_at="2026-10-08T18:30:00+08:00", codes=["A"])
    _write_run(tmp_path, "r2", market="cn", strategy="balanced_alpha", created_at="2026-10-09T18:30:00+08:00", codes=["B"])
    _write_run(tmp_path, "r_healed", market="cn", strategy="capital_heat", created_at="2026-10-07T18:30:00+08:00", codes=["C"])

    # Simulate an older broken evaluation.json where benchmark failed yet final=True was saved.
    site = tmp_path / "site"
    site.mkdir(parents=True, exist_ok=True)
    broken_windows = {
        str(w): {
            "benchmark": "CSI 300",
            "benchmark_return_pct": None,
            "pending": 0,
            "picks": {"C": _outcome("ok", 2.0, None)},
        }
        for w in track_record.WINDOWS
    }
    (site / "evaluation.json").write_text(
        json.dumps({"runs": {"r_healed": {"evaluated_at": "2026-10-20T00:00:00+00:00", "final": True, "windows": broken_windows}}}),
        encoding="utf-8",
    )

    seen_cache_ids = []
    bench_ok = {"value": False}

    def fake_evaluate(run_path, *, benchmark_paths=None, horizon_days=None, **kwargs):
        seen_cache_ids.append(id(benchmark_paths))
        benchmark_paths.setdefault("cn", pd.DataFrame([{"date": "2026-10-01", "close": 4000.0}]))
        run_id = Path(run_path).stem
        code = "C" if run_id == "r_healed" else ("A" if run_id == "r1" else "B")
        if bench_ok["value"]:
            pick = PickEvaluation(
                code=code, name=code, rank=1, entry_price=10.0, current_price=10.5,
                return_pct=5.0, benchmark_return_pct=1.0, excess_return_pct=4.0, status="ok",
            )
            return EvaluationResult(
                run_id=run_id, strategy="s", market="cn", created_at="",
                benchmark="CSI 300", benchmark_return_pct=1.0, picks=[pick], pending_count=0,
            )
        pick = PickEvaluation(
            code=code, name=code, rank=1, entry_price=10.0, current_price=10.5,
            return_pct=5.0, benchmark_return_pct=None, excess_return_pct=None, status="ok",
        )
        return EvaluationResult(
            run_id=run_id, strategy="s", market="cn", created_at="",
            benchmark="CSI 300", benchmark_return_pct=None,
            degradation=["Benchmark CSI 300 fetch failed: down"], picks=[pick], pending_count=0,
        )

    monkeypatch.setattr(eval_mod, "evaluate_saved_run", fake_evaluate)

    first = track_record.evaluate_markets(tmp_path, ["cn"])
    assert len(set(seen_cache_ids)) == 1  # shared across all runs and windows in the batch
    assert first["runs"]["r1"]["final"] is False
    assert first["runs"]["r2"]["final"] is False
    assert first["runs"]["r_healed"]["final"] is False  # broken prior final=True was re-evaluated
    assert first["runs"]["r1"]["windows"]["5"]["benchmark_errors"] == ["Benchmark CSI 300 fetch failed: down"]

    summary_before = track_record.build_site(tmp_path)
    day_data = json.loads((site / "days" / "2026-10-08.json").read_text(encoding="utf-8"))
    assert day_data["runs"][0]["evaluation"]["5"]["benchmark_errors"] == ["Benchmark CSI 300 fetch failed: down"]
    assert summary_before["run_count"] == 3

    seen_cache_ids.clear()
    bench_ok["value"] = True
    second = track_record.evaluate_markets(tmp_path, ["cn"])
    assert len(seen_cache_ids) == 9  # all 3 incomplete runs re-evaluated
    assert all(second["runs"][rid]["final"] is True for rid in ("r1", "r2", "r_healed"))

    seen_cache_ids.clear()
    track_record.evaluate_markets(tmp_path, ["cn"])
    assert seen_cache_ids == []  # finalized runs with matched benchmark are skipped


def test_run_session_shares_snapshot_isolates_failures_and_uses_exchange_log_date(tmp_path, monkeypatch):
    import pandas as pd
    import alphasift.pipeline as pipeline_mod
    from alphasift.models import Pick, ScreenResult

    # US screen runs at 06:30 Beijing on Friday 2026-11-13 -> US session is Thursday 2026-11-12.
    monkeypatch.setattr(track_record, "_now", lambda: "2026-11-12T22:30:00+00:00")
    monkeypatch.setattr(track_record, "strategies_for", lambda m: ["global_value", "us_momentum_quality"])

    snapshot = pd.DataFrame([{"code": "AAPL", "name": "Apple", "price": 220.0, "amount": 1e9, "total_mv": 3e12}])
    snapshot.attrs["snapshot_source"] = "yahoo_screener"
    snapshot.attrs["quote_date"] = "2026-11-12"
    fetch_calls = []

    def fake_fetch(market, strats, config):
        fetch_calls.append((market, list(strats)))
        return snapshot

    monkeypatch.setattr(track_record, "_fetch_market_snapshot", fake_fetch)

    seen_snapshots = []

    def fake_screen(strategy, *, market, use_llm, config, snapshot_df=None, **kwargs):
        seen_snapshots.append((strategy, snapshot_df))
        if strategy == "global_value":
            raise RuntimeError("boom in strategy")
        return ScreenResult(
            strategy=strategy,
            market=market,
            run_id="usrun1",
            created_at="2026-11-12T22:30:00+00:00",
            snapshot_source="yahoo_screener",
            picks=[Pick(rank=1, code="AAPL", name="Apple", final_score=85.0, screen_score=85.0, price=220.0)],
        )

    monkeypatch.setattr(pipeline_mod, "screen", fake_screen)

    log = track_record.run_session("us", tmp_path, markets=["us"])

    assert len(fetch_calls) == 1
    assert [name for name, _ in seen_snapshots] == ["global_value", "us_momentum_quality"]
    assert all(df is snapshot for _, df in seen_snapshots)
    assert log["date"] == "2026-11-12"
    assert (tmp_path / "data" / "logs" / "2026-11-12-us.json").is_file()
    statuses = {entry["strategy"]: entry["status"] for entry in log["entries"]}
    assert statuses == {"global_value": "failed", "us_momentum_quality": "ok"}

    # Re-running the same session skips us_momentum_quality (already recorded 2026-11-12)
    # and retries only global_value.
    seen_snapshots.clear()
    log2 = track_record.run_session("us", tmp_path, markets=["us"])
    assert [name for name, _ in seen_snapshots] == ["global_value"]
    statuses2 = {entry["strategy"]: entry["status"] for entry in log2["entries"]}
    assert statuses2 == {"global_value": "failed", "us_momentum_quality": "skipped_duplicate"}


def test_run_session_skips_holiday_and_already_recorded_without_failure(tmp_path, monkeypatch):
    import pandas as pd

    monkeypatch.setattr(track_record, "_now", lambda: "2026-11-12T22:30:00+00:00")
    monkeypatch.setattr(track_record, "strategies_for", lambda m: ["global_value", "us_momentum_quality"])

    # Live snapshot carries 2026-11-11 quotes on an exchange holiday (2026-11-12),
    # corroborated by the benchmark latest trading date also stopping at 2026-11-11.
    holiday_snap = pd.DataFrame([{"code": "AAPL", "price": 220.0}])
    holiday_snap.attrs["quote_date"] = "2026-11-11"
    monkeypatch.setattr(track_record, "_fetch_market_snapshot", lambda m, s, c: holiday_snap)
    monkeypatch.setattr(track_record, "_latest_benchmark_date", lambda market, **kw: "2026-11-11")

    rc = track_record.main(["screen", "--track", str(tmp_path), "--session", "us", "--markets", "us"])
    assert rc == 0
    assert list((tmp_path / "data" / "runs").glob("*.json")) == []

    summary = track_record.build_site(tmp_path)
    assert summary["sessions"]["us"]["failures"] == []
    assert summary["sessions"]["us"]["skipped"] == 2
    assert summary["sessions"]["us"]["total"] == 0
    assert "2 skipped" in (tmp_path / "README.md").read_text(encoding="utf-8")

    # If the benchmark actually traded on 2026-11-12 (or cannot corroborate the holiday),
    # a 2026-11-11 quote_date is stale vendor data and must be recorded as failed, not skipped.
    monkeypatch.setattr(track_record, "_latest_benchmark_date", lambda market, **kw: "2026-11-12")
    log_stale = track_record.run_session("us", tmp_path, markets=["us"])
    assert [e["status"] for e in log_stale["entries"]] == ["failed", "failed"]
    assert all(e["error"] for e in log_stale["entries"])

    monkeypatch.setattr(track_record, "_latest_benchmark_date", lambda market, **kw: None)
    log_unconfirmed = track_record.run_session("us", tmp_path, markets=["us"])
    assert [e["status"] for e in log_unconfirmed["entries"]] == ["failed", "failed"]
    assert list((tmp_path / "data" / "runs").glob("*.json")) == []

    # Undated or malformed-quote_date snapshots reject unverifiable freshness even if the benchmark stopped yesterday.
    monkeypatch.setattr(track_record, "_latest_benchmark_date", lambda market, **kw: "2026-11-11")
    undated_snap = pd.DataFrame([{"code": "AAPL", "price": 220.0}])
    monkeypatch.setattr(track_record, "_fetch_market_snapshot", lambda m, s, c: undated_snap)
    log_undated = track_record.run_session("us", tmp_path, markets=["us"])
    assert [e["status"] for e in log_undated["entries"]] == ["failed", "failed"]

    invalid_snap = pd.DataFrame([{"code": "AAPL", "price": 220.0}])
    invalid_snap.attrs["quote_date"] = "unknown"
    monkeypatch.setattr(track_record, "_fetch_market_snapshot", lambda m, s, c: invalid_snap)
    log_invalid = track_record.run_session("us", tmp_path, markets=["us"])
    assert [e["status"] for e in log_invalid["entries"]] == ["failed", "failed"]
    assert list((tmp_path / "data" / "runs").glob("*.json")) == []

    # Already-recorded date short-circuits before even fetching a snapshot.
    _write_run(tmp_path, "r_done1", market="us", strategy="global_value", created_at="2026-11-12T22:30:00+00:00", codes=["AAPL"])
    _write_run(tmp_path, "r_done2", market="us", strategy="us_momentum_quality", created_at="2026-11-12T22:30:00+00:00", codes=["MSFT"])
    monkeypatch.setattr(
        track_record,
        "_fetch_market_snapshot",
        lambda *a, **kw: pytest.fail("must not fetch snapshot when all strategies already recorded"),
    )
    log_dup = track_record.run_session("us", tmp_path, markets=["us"])
    assert [e["status"] for e in log_dup["entries"]] == ["skipped_duplicate", "skipped_duplicate"]


def test_evaluate_markets_keeps_transient_missing_non_final_until_resolved_or_expired(tmp_path, monkeypatch):
    import alphasift.evaluate as eval_mod
    from alphasift.models import EvaluationResult, PickEvaluation

    _write_run(tmp_path, "r_all_missing", market="cn", strategy="dual_low", created_at="2026-01-01T18:30:00+08:00", codes=["A", "B"])
    _write_run(tmp_path, "r_old_mixed", market="cn", strategy="balanced_alpha", created_at="2026-01-02T18:30:00+08:00", codes=["A", "B"])
    _write_run(tmp_path, "r_recent_mixed", market="cn", strategy="capital_heat", created_at="2026-10-01T18:30:00+08:00", codes=["A", "B"])

    monkeypatch.setattr(track_record, "_now", lambda: "2026-11-12T12:00:00+00:00")

    # Pre-populate a prior broken evaluation where r_recent_mixed was marked final despite a missing pick.
    site = tmp_path / "site"
    site.mkdir(parents=True, exist_ok=True)
    broken_windows = {
        str(w): {
            "benchmark": "CSI 300",
            "benchmark_return_pct": 1.0,
            "pending": 0,
            "picks": {"A": _outcome("ok", 5.0, 4.0), "B": _outcome("missing", None, None)},
        }
        for w in track_record.WINDOWS
    }
    (site / "evaluation.json").write_text(
        json.dumps({"runs": {"r_recent_mixed": {"evaluated_at": "2026-10-20T00:00:00+00:00", "final": True, "windows": broken_windows}}}),
        encoding="utf-8",
    )

    resolved = {"value": False}
    evaluated_runs = []

    def _ok_pick(code: str) -> PickEvaluation:
        return PickEvaluation(
            code=code, name=code, rank=1, entry_price=10.0, current_price=10.5,
            return_pct=5.0, benchmark_return_pct=1.0, excess_return_pct=4.0, status="ok",
        )

    def _missing_pick(code: str) -> PickEvaluation:
        return PickEvaluation(
            code=code, name=code, rank=2, entry_price=10.0, current_price=None,
            return_pct=None, benchmark_return_pct=None, excess_return_pct=None, status="missing",
        )

    def fake_evaluate(run_path, *, benchmark_paths=None, horizon_days=None, **kwargs):
        run_id = Path(run_path).stem
        evaluated_runs.append(run_id)
        if run_id == "r_all_missing":
            picks = [_missing_pick("A"), _missing_pick("B")]
        elif run_id == "r_recent_mixed" and resolved["value"]:
            picks = [_ok_pick("A"), _ok_pick("B")]
        else:
            picks = [_ok_pick("A"), _missing_pick("B")]
        return EvaluationResult(
            run_id=run_id, strategy="s", market="cn", created_at="",
            benchmark="CSI 300", benchmark_return_pct=1.0, picks=picks, pending_count=0,
        )

    monkeypatch.setattr(eval_mod, "evaluate_saved_run", fake_evaluate)

    first = track_record.evaluate_markets(tmp_path, ["cn"])
    assert first["runs"]["r_all_missing"]["final"] is False
    assert first["runs"]["r_old_mixed"]["final"] is True
    assert first["runs"]["r_recent_mixed"]["final"] is False

    evaluated_runs.clear()
    resolved["value"] = True
    second = track_record.evaluate_markets(tmp_path, ["cn"])
    assert "r_old_mixed" not in evaluated_runs
    assert "r_recent_mixed" in evaluated_runs
    assert "r_all_missing" in evaluated_runs
    assert second["runs"]["r_recent_mixed"]["final"] is True
    assert second["runs"]["r_all_missing"]["final"] is False


def test_run_session_rejects_fallback_snapshot_and_isolates_timeout(tmp_path, monkeypatch):
    import time
    import pandas as pd
    import alphasift.pipeline as pipeline_mod
    from alphasift.models import Pick, ScreenResult

    monkeypatch.setattr(track_record, "_now", lambda: "2026-11-12T14:00:00+00:00")
    monkeypatch.setattr(track_record, "strategies_for", lambda m: ["global_value"] if m == "us" else ["dual_low"])

    fallback_snap = pd.DataFrame([{"code": "AAPL", "name": "Apple", "price": 220.0}])
    fallback_snap.attrs["snapshot_source"] = "file_fallback"
    fallback_snap.attrs["fallback_used"] = True
    fallback_snap.attrs["quote_date"] = "2026-11-12"

    monkeypatch.setattr(track_record, "_fetch_market_snapshot", lambda m, s, c: fallback_snap)
    monkeypatch.setattr(
        pipeline_mod,
        "screen",
        lambda *a, **kw: pytest.fail("must not screen with fallback_used=True snapshot"),
    )

    log_fb = track_record.run_session("us", tmp_path, markets=["us"])
    assert [e["status"] for e in log_fb["entries"]] == ["failed"]
    assert list((tmp_path / "data" / "runs").glob("*.json")) == []

    # Timeout on US snapshot does not block CN market from completing, and failed US can be retried later.
    monkeypatch.setattr(track_record, "SNAPSHOT_TIMEOUT_SEC", 0.05)

    def slow_us_fast_cn(market, strats, config):
        if market == "us":
            time.sleep(0.25)
        snap = pd.DataFrame([{"code": "600519", "name": "Moutai", "price": 1500.0}])
        snap.attrs["snapshot_source"] = "baostock"
        snap.attrs["quote_date"] = "2026-11-12"
        snap.attrs["market"] = "cn"
        return snap

    def fake_screen(strategy, *, market, use_llm, config, snapshot_df=None, **kwargs):
        return ScreenResult(
            strategy=strategy,
            market=market,
            run_id=f"{market}run1",
            created_at="2026-11-12T14:00:00+00:00",
            snapshot_source="baostock" if market == "cn" else "yahoo_screener",
            picks=[Pick(rank=1, code="600519", name="Moutai", final_score=90.0, screen_score=90.0, price=1500.0)],
        )

    monkeypatch.setattr(track_record, "_fetch_market_snapshot", slow_us_fast_cn)
    monkeypatch.setattr(pipeline_mod, "screen", fake_screen)

    log_to = track_record.run_session("us", tmp_path, markets=["us", "cn"])
    by_market = {e["market"]: e["status"] for e in log_to["entries"]}
    assert by_market == {"us": "timeout", "cn": "ok"}
    assert len(list((tmp_path / "data" / "runs").glob("*.json"))) == 1

    # Retrying US with a healthy live snapshot now succeeds rather than being skipped.
    us_live = pd.DataFrame([{"code": "AAPL", "name": "Apple", "price": 220.0}])
    us_live.attrs["snapshot_source"] = "yahoo_screener"
    us_live.attrs["quote_date"] = "2026-11-12"
    us_live.attrs["market"] = "us"
    monkeypatch.setattr(track_record, "_fetch_market_snapshot", lambda m, s, c: us_live)
    log_retry = track_record.run_session("us", tmp_path, markets=["us"])
    assert [e["status"] for e in log_retry["entries"]] == ["ok"]
    assert len(list((tmp_path / "data" / "runs").glob("*.json"))) == 2


def test_run_session_does_not_refetch_incomplete_shared_snapshot(tmp_path, monkeypatch):
    import dataclasses
    import pandas as pd
    import alphasift.config as config_mod
    import alphasift.pipeline as pipeline_mod

    monkeypatch.setattr(track_record, "_now", lambda: "2026-11-12T22:30:00+00:00")
    monkeypatch.setattr(track_record, "strategies_for", lambda m: ["global_value", "us_momentum_quality"])
    monkeypatch.setenv("INDUSTRY_AUTO_BACKFILL", "false")

    orig_from_env = config_mod.Config.from_env
    monkeypatch.setattr(
        config_mod.Config,
        "from_env",
        staticmethod(
            lambda: dataclasses.replace(
                orig_from_env(),
                llm_api_key="",
                daily_enrich_enabled=False,
                post_analyzers=[],
                risk_enabled=False,
                source_health_path="off",
            )
        ),
    )

    # Fresh US snapshot missing global_value's pe_ratio/pb_ratio columns,
    # while still containing everything us_momentum_quality requires.
    fresh_incomplete = pd.DataFrame([{
        "code": "AAPL",
        "name": "Apple",
        "price": 220.0,
        "change_pct": 1.5,
        "amount": 1e9,
        "avg_amount": 1e9,
        "avg_amount_usd": 1e9,
        "total_mv": 3e12,
        "volume_ratio": 1.6,
        "turnover_rate": 1.2,
        "industry": "Technology",
    }])
    fresh_incomplete.attrs.update(
        market="us",
        quote_date="2026-11-12",
        snapshot_source="yfinance_tickers",
    )

    monkeypatch.setattr(track_record, "_fetch_market_snapshot", lambda m, s, c: fresh_incomplete)
    monkeypatch.setattr(
        pipeline_mod,
        "fetch_snapshot_with_fallback",
        lambda *a, **kw: pytest.fail("must not implicitly refetch replacement snapshot during track_record session"),
    )

    log = track_record.run_session("us", tmp_path, markets=["us"])
    by_strat = {e["strategy"]: e["status"] for e in log["entries"]}
    assert by_strat == {"global_value": "failed", "us_momentum_quality": "ok"}
    saved_runs = list((tmp_path / "data" / "runs").glob("*.json"))
    assert len(saved_runs) == 1
    assert json.loads(saved_runs[0].read_text(encoding="utf-8"))["strategy"] == "us_momentum_quality"


def test_cn_session_validates_snapshot_quote_date_and_clears_tushare_override(tmp_path, monkeypatch):
    import os
    import pandas as pd
    import alphasift.pipeline as pipeline_mod

    # 1. Explicit stale CN quote_date must not be accepted even when benchmark traded on expected_date.
    stale_cn = pd.DataFrame([{"code": "600519", "price": 1500.0}])
    stale_cn.attrs.update(market="cn", snapshot_source="tushare", quote_date="2026-11-11")
    monkeypatch.setattr(track_record, "_latest_benchmark_date", lambda market, **kw: "2026-11-12")
    status, reason = track_record._check_market_session("cn", stale_cn, "2026-11-12")
    assert status == "stale"
    assert "2026-11-11" in reason

    # 2. Undated tushare snapshot must be rejected as stale.
    undated_tushare = pd.DataFrame([{"code": "600519", "price": 1500.0}])
    undated_tushare.attrs.update(market="cn", snapshot_source="tushare")
    status_undated, _ = track_record._check_market_session("cn", undated_tushare, "2026-11-12")
    assert status_undated == "stale"

    # 3. Stale CN quote_date corroborated by BOTH Tencent and Sina stopping prior to expected_date => closed.
    monkeypatch.setattr(track_record, "_latest_benchmark_date", lambda market, **kw: "2026-11-11")
    status_closed, _ = track_record._check_market_session("cn", stale_cn, "2026-11-12")
    assert status_closed == "closed"

    # 4. run_session clears any ambient TUSHARE_TRADE_DATE during screening and restores it on exit.
    monkeypatch.setattr(track_record, "_now", lambda: "2026-11-12T10:30:00+00:00")  # 18:30 Shanghai
    monkeypatch.setattr(track_record, "strategies_for", lambda m: ["dual_low"] if m == "cn" else [])
    monkeypatch.setenv("TUSHARE_TRADE_DATE", "20261111")

    seen_env: list[str | None] = []

    def fake_fetch(market, strats, config):
        seen_env.append(os.environ.get("TUSHARE_TRADE_DATE"))
        return stale_cn

    monkeypatch.setattr(track_record, "_fetch_market_snapshot", fake_fetch)
    monkeypatch.setattr(track_record, "_latest_benchmark_date", lambda market, **kw: "2026-11-12")
    monkeypatch.setattr(pipeline_mod, "screen", lambda *a, **kw: pytest.fail("must not screen stale CN snapshot"))

    log = track_record.run_session("asia", tmp_path, markets=["cn"])
    assert seen_env == [None]
    assert os.environ.get("TUSHARE_TRADE_DATE") == "20261111"
    assert [e["status"] for e in log["entries"]] == ["failed"]
    assert list((tmp_path / "data" / "runs").glob("*.json")) == []
