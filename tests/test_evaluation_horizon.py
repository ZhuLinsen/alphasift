from datetime import date

import pandas as pd

from alphasift.config import Config
from alphasift.daily import _to_tencent_code
from alphasift.evaluate import entry_cutoff_date, evaluate_saved_run
from alphasift.models import Pick, ScreenResult
from alphasift.store import save_screen_result


def test_entry_cutoff_uses_exchange_session_open():
    # Shanghai: before 09:30 the bar of that day is entirely post-entry.
    assert entry_cutoff_date("2026-04-01T08:00:00+08:00", "cn") == date(2026, 3, 31)
    assert entry_cutoff_date("2026-04-01T09:30:00+08:00", "cn") == date(2026, 4, 1)
    assert entry_cutoff_date("2026-04-01T20:00:00+08:00", "cn") == date(2026, 4, 1)


def test_entry_cutoff_converts_to_the_market_timezone():
    # 20:00 Beijing = 08:00 New York (before the open) -> previous US session.
    assert entry_cutoff_date("2026-04-01T20:00:00+08:00", "us") == date(2026, 3, 31)
    # 22:00 Beijing = 10:00 New York (session open) -> same US session.
    assert entry_cutoff_date("2026-04-01T22:00:00+08:00", "us") == date(2026, 4, 1)
    # Tokyo opens at 09:00.
    assert entry_cutoff_date("2026-04-01T09:10:00+09:00", "jp") == date(2026, 4, 1)


def test_entry_cutoff_handles_bad_input():
    assert entry_cutoff_date("not-a-date", "cn") is None
    # Unknown markets fall back to CN rules rather than raising.
    assert entry_cutoff_date("2026-04-01T08:00:00+08:00", "zz") == date(2026, 3, 31)


def test_tencent_code_passes_prefixed_index_symbols_through():
    assert _to_tencent_code("sh000300") == "sh000300"
    assert _to_tencent_code("SZ399001") == "sz399001"
    assert _to_tencent_code("600519") == "sh600519"
    assert _to_tencent_code("000001") == "sz000001"


def _save_run(tmp_path, created_at="2026-03-31T20:00:00+08:00"):
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="run_h",
            created_at=created_at,
            picks=[
                Pick(rank=1, code="000001", name="a", final_score=80, screen_score=80, price=10.0),
                Pick(rank=2, code="600000", name="b", final_score=70, screen_score=70, price=20.0),
            ],
        ),
        data_dir=tmp_path,
    )


def _with_entry(entry_close, bars):
    """Prepend the entry session's bar (03-31), as a real history has it."""
    entry = pd.DataFrame([{"date": "2026-03-31", "close": entry_close, "high": entry_close, "low": entry_close}])
    return pd.concat([entry, bars], ignore_index=True)


def _bars(start_day, closes):
    return pd.DataFrame(
        [
            {"date": f"2026-04-{day:02d}", "close": close, "high": close, "low": close}
            for day, close in enumerate(closes, start=start_day)
        ]
    )


def test_horizon_marks_short_paths_pending_and_survives_benchmark_failure(tmp_path, monkeypatch):
    _save_run(tmp_path)

    def failing_benchmark(market, *, lookback_days):
        raise RuntimeError("index endpoint down")

    monkeypatch.setattr("alphasift.evaluate._fetch_benchmark_path", failing_benchmark)
    snapshot = pd.DataFrame([{"code": "000001", "price": 50.0}, {"code": "600000", "price": 50.0}])

    result = evaluate_saved_run(
        "run_h",
        config=Config(llm_api_key="", data_dir=tmp_path),
        current_snapshot=snapshot,
        cost_bps=0,
        horizon_days=2,
        price_paths={
            "000001": _with_entry(10.0, _bars(1, [10.5, 11.0, 12.0])),
            "600000": _with_entry(20.0, _bars(1, [19.0])),  # only one post-entry bar so far
        },
    )

    first, second = result.picks
    assert first.status == "ok"
    assert first.return_pct == 10.0  # T+2 close 11.0, not today's 50.0
    assert first.excess_return_pct is None
    assert second.status == "pending"
    assert second.return_pct is None
    assert result.pending_count == 1
    assert result.average_return_pct == 10.0
    assert result.missing_codes == []
    assert any("Benchmark CSI 300 fetch failed" in item for item in result.degradation)


def test_default_mode_still_measures_return_to_date(tmp_path):
    _save_run(tmp_path)
    snapshot = pd.DataFrame([{"code": "000001", "price": 12.0}, {"code": "600000", "price": 18.0}])

    result = evaluate_saved_run(
        "run_h",
        config=Config(llm_api_key="", data_dir=tmp_path),
        current_snapshot=snapshot,
        cost_bps=0,
        with_price_path=False,
    )

    assert [pick.return_pct for pick in result.picks] == [20.0, -10.0]
    assert result.horizon_days is None
    assert result.benchmark == ""


def test_t_plus_n_ignores_todays_bar_until_the_session_closes():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from alphasift.evaluate import _price_path_metrics

    path = pd.DataFrame(
        [
            {"date": "2026-11-03", "close": 10.0, "high": 10.0, "low": 10.0},
            {"date": "2026-11-04", "close": 10.5, "high": 10.6, "low": 10.4},
        ]
    )
    kwargs = dict(
        entry_price=10.0,
        created_at="2026-11-03T19:34:00+08:00",  # after the 11-03 close
        cost_bps=0.0,
        market="cn",
        horizon_days=1,
    )
    shanghai = ZoneInfo("Asia/Shanghai")

    intraday = _price_path_metrics(path, now=datetime(2026, 11, 4, 10, 45, tzinfo=shanghai), **kwargs)
    assert intraday["path_status"] == "pending"

    after_close = _price_path_metrics(path, now=datetime(2026, 11, 4, 15, 5, tzinfo=shanghai), **kwargs)
    assert after_close["path_status"] == "ok"
    assert after_close["path_end_return_pct"] == 5.0


def test_runs_without_market_load_as_cn(tmp_path):
    import json

    from alphasift.store import list_saved_runs, load_screen_result

    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "legacy.json").write_text(
        json.dumps({"strategy": "dual_low", "run_id": "legacy", "created_at": "2026-04-01T09:30:00", "picks": []}),
        encoding="utf-8",
    )

    assert load_screen_result("legacy", data_dir=tmp_path).market == "cn"
    assert [item["run_id"] for item in list_saved_runs(data_dir=tmp_path, market="cn")] == ["legacy"]


def test_benchmark_cache_refetches_for_older_runs(monkeypatch):
    from alphasift.evaluate import _benchmark_return

    def path(start, days):
        dates = pd.bdate_range(start, periods=days)
        return pd.DataFrame({"date": dates, "close": [100.0 + i for i in range(days)]})

    fetched = []

    def fake_fetch(market, *, lookback_days):
        fetched.append(lookback_days)
        return path("2026-06-01", 120)

    monkeypatch.setattr("alphasift.evaluate._fetch_benchmark_path", fake_fetch)
    cache = {"us": path("2026-10-01", 20)}  # left by a newer run
    old_run = ScreenResult(strategy="s", market="us", run_id="old", created_at="2026-06-10T22:00:00")

    ret, label, errors, curve = _benchmark_return(old_run, horizon_days=5, lookback_days=160, cache=cache)

    assert fetched == [160]
    assert errors == [] and ret is not None
    assert cache["us"]["date"].min() == pd.Timestamp("2026-06-01")


def test_pending_picks_are_not_failures_or_event_evidence():
    from alphasift.evaluate import _event_signal_review, _failure_reasons
    from alphasift.models import EvaluationResult, PickEvaluation

    pending = PickEvaluation(
        code="000001", name="a", rank=1, entry_price=10.0, current_price=None,
        return_pct=None, final_score=80, status="pending", path_status="pending",
        post_analysis_tags=["value_quality"],
    )
    evaluation = EvaluationResult(
        run_id="r", strategy="dual_low", market="cn", created_at="2026-04-01T10:00:00",
        snapshot_source="", picks=[pending],
    )

    assert _failure_reasons(pending) == []
    assert _event_signal_review([evaluation])["signals"] == []


def test_benchmark_average_is_pick_weighted_like_excess(tmp_path, monkeypatch):
    from alphasift.evaluate import _aggregate_evaluations
    from alphasift.models import EvaluationResult, PickEvaluation

    def run(n, ret, bench):
        picks = [
            PickEvaluation(
                code=f"{i:06d}", name="x", rank=i, entry_price=1.0, current_price=None,
                return_pct=ret, final_score=1, benchmark_return_pct=bench,
                excess_return_pct=ret - bench,
            )
            for i in range(n)
        ]
        return EvaluationResult(
            run_id=str(n), strategy="s", market="cn", created_at="", snapshot_source="",
            picks=picks, benchmark_return_pct=bench,
        )

    summary = _aggregate_evaluations([run(1, 10.0, 2.0), run(9, 0.0, 12.0)])

    assert summary["average_benchmark_return_pct"] == 11.0
    assert summary["average_excess_return_pct"] == -10.0


def test_windows_share_one_live_snapshot(tmp_path, monkeypatch):
    from alphasift.evaluate import evaluate_saved_runs_by_windows

    _save_run(tmp_path)
    calls = []

    def fake_snapshot(*args, **kwargs):
        calls.append(kwargs.get("market"))
        return pd.DataFrame([{"code": "000001", "price": 11.0}, {"code": "600000", "price": 21.0}])

    monkeypatch.setattr("alphasift.evaluate.fetch_snapshot_with_fallback", fake_snapshot)
    monkeypatch.setattr(
        "alphasift.evaluate._fetch_price_paths", lambda run, **kwargs: ({}, [])
    )
    monkeypatch.setattr(
        "alphasift.evaluate._fetch_benchmark_path",
        lambda market, *, lookback_days: _bars(1, [100.0, 101.0]),
    )

    evaluate_saved_runs_by_windows(
        windows=[5, 10, 20], config=Config(llm_api_key="", data_dir=tmp_path), cost_bps=0
    )

    assert calls == ["cn"]


def test_yfinance_daily_history_requests_through_tomorrow(monkeypatch):
    import sys
    import types

    from alphasift.snapshot_us import fetch_daily_history_yfinance

    seen = {}

    def fake_download(ticker, start, end, **kwargs):
        seen["end"] = end
        idx = pd.date_range("2026-11-02", periods=2)
        return pd.DataFrame(
            {"Open": [1.0, 1.0], "High": [1.0, 1.0], "Low": [1.0, 1.0], "Close": [1.0, 1.0], "Volume": [1, 1]},
            index=idx,
        )

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(download=fake_download))

    fetch_daily_history_yfinance("0700.HK", lookback_days=10)

    today_utc = pd.Timestamp.now(tz="UTC").normalize().tz_localize(None)
    assert pd.Timestamp(seen["end"]) > today_utc


def test_bar_cached_mid_session_is_not_a_close_after_the_session_ends():
    from alphasift.evaluate import _price_path_metrics

    path = pd.DataFrame(
        [
            {"date": "2026-11-03", "close": 10.0, "high": 10.0, "low": 10.0},
            {"date": "2026-11-04", "close": 10.5, "high": 10.6, "low": 10.4},  # 10:00 snapshot
        ]
    )
    path.attrs["fetched_at"] = "2026-11-04T10:00:00+08:00"

    result = _price_path_metrics(
        path, entry_price=10.0, created_at="2026-11-03T19:34:00+08:00",
        cost_bps=0.0, market="cn", horizon_days=1,
    )

    assert result["path_status"] == "pending"


def test_t_plus_n_is_close_to_close_on_the_history_basis():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from alphasift.evaluate import _price_path_metrics

    # Run at 10:00 on 11-03 at an intraday 100; the history was later
    # restated for a 2-for-1 split, so 11-03 closes at 55 and 11-04 at 60.5.
    path = pd.DataFrame(
        [
            {"date": "2026-11-03", "close": 55.0, "high": 56.0, "low": 50.0},
            {"date": "2026-11-04", "close": 60.5, "high": 61.0, "low": 54.0},
        ]
    )

    result = _price_path_metrics(
        path, entry_price=100.0, created_at="2026-11-03T10:00:00+08:00", cost_bps=0.0,
        market="cn", horizon_days=1, now=datetime(2026, 11, 5, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert result["path_end_return_pct"] == 10.0  # 55 -> 60.5, not 100 -> 60.5
    assert result["max_drawdown_pct"] == -1.8182  # low 54 vs entry close 55


def test_excess_uses_benchmark_through_the_picks_own_end_date(tmp_path, monkeypatch):
    save_screen_result(
        ScreenResult(
            strategy="dual_low", market="cn", run_id="run_g",
            created_at="2026-03-31T20:00:00+08:00",
            picks=[Pick(rank=1, code="000001", name="a", final_score=80, screen_score=80, price=10.0)],
        ),
        data_dir=tmp_path,
    )
    bench = pd.DataFrame(
        [
            {"date": "2026-03-31", "close": 100.0, "high": 100.0, "low": 100.0},
            {"date": "2026-04-01", "close": 105.0, "high": 105.0, "low": 105.0},
            {"date": "2026-04-02", "close": 110.0, "high": 110.0, "low": 110.0},
        ]
    )
    monkeypatch.setattr("alphasift.evaluate._fetch_benchmark_path", lambda market, *, lookback_days: bench)
    stock = pd.DataFrame(
        [
            {"date": "2026-03-31", "close": 10.0, "high": 10.0, "low": 10.0},
            # suspended on 04-01; its first post-entry bar is 04-02
            {"date": "2026-04-02", "close": 11.0, "high": 11.0, "low": 11.0},
        ]
    )

    result = evaluate_saved_run(
        "run_g",
        config=Config(llm_api_key="", data_dir=tmp_path),
        current_snapshot=pd.DataFrame([{"code": "000001", "price": 11.0}]),
        cost_bps=0,
        horizon_days=1,
        price_paths={"000001": stock},
    )

    pick = result.picks[0]
    assert result.benchmark_return_pct == 5.0  # the index's own T+1 (04-01)
    assert pick.return_pct == 10.0
    assert pick.benchmark_return_pct == 10.0  # through 04-02, the pick's T+1
    assert pick.excess_return_pct == 0.0


def test_window_summaries_report_benchmark_failures(tmp_path, monkeypatch):
    from alphasift.evaluate import evaluate_saved_runs_by_windows

    _save_run(tmp_path)

    def failing_benchmark(market, *, lookback_days):
        raise RuntimeError("index endpoint down")

    monkeypatch.setattr("alphasift.evaluate._fetch_benchmark_path", failing_benchmark)
    monkeypatch.setattr(
        "alphasift.evaluate._fetch_price_paths",
        lambda run, **kwargs: ({"000001": _bars(1, [10.5, 11.0])}, []),
    )

    result = evaluate_saved_runs_by_windows(
        windows=[1],
        config=Config(llm_api_key="", data_dir=tmp_path),
        current_snapshot=pd.DataFrame([{"code": "000001", "price": 11.0}]),
        cost_bps=0,
    )

    window = result["strategy_summaries"][0]["window_summaries"][0]
    assert window["average_excess_return_pct"] is None
    assert any("index endpoint down" in item for item in window["benchmark_errors"])


def test_horizon_without_the_entry_close_is_not_measured_from_the_saved_price(tmp_path, monkeypatch):
    # History starts after entry: the saved pick price (intraday, unadjusted)
    # must not be compared with adjusted closes. A 2:1 split would read -50%.
    _save_run(tmp_path)
    monkeypatch.setattr("alphasift.evaluate._fetch_benchmark_path", lambda market, *, lookback_days: pd.DataFrame())

    result = evaluate_saved_run(
        "run_h",
        config=Config(llm_api_key="", data_dir=tmp_path),
        current_snapshot=pd.DataFrame([{"code": "000001", "price": 5.0}]),
        cost_bps=0,
        horizon_days=2,
        price_paths={"000001": _bars(1, [5.0, 5.0, 5.0]), "600000": _bars(1, [10.0, 10.0])},
    )

    assert [pick.path_status for pick in result.picks] == ["no_entry_close", "no_entry_close"]
    assert all(pick.return_pct is None for pick in result.picks)
    assert result.average_return_pct is None


def test_partial_benchmark_coverage_reports_the_matched_population():
    from alphasift.cli import _format_partial_benchmark
    from alphasift.evaluate import _aggregate_evaluations
    from alphasift.models import EvaluationResult, PickEvaluation

    def pick(code, ret, bench):
        return PickEvaluation(
            code=code, name=code, rank=1, entry_price=10.0, current_price=None, return_pct=ret,
            final_score=80, status="ok", benchmark_return_pct=bench,
            excess_return_pct=None if bench is None else ret - bench,
        )

    evaluation = EvaluationResult(
        run_id="r", strategy="dual_low", market="cn", created_at="",
        picks=[pick("a", 10.0, 5.0), pick("b", -20.0, None)],
    )

    aggregate = _aggregate_evaluations([evaluation])

    # All priced picks: (10 - 20) / 2 = -5. Only "a" has a benchmark.
    assert aggregate["average_return_pct"] == -5.0
    assert aggregate["benchmark_pick_count"] == 1
    assert aggregate["average_matched_return_pct"] == 10.0
    assert aggregate["average_matched_return_pct"] - aggregate["average_benchmark_return_pct"] == (
        aggregate["average_excess_return_pct"]
    )
    window = {**aggregate, "evaluated_pick_count": aggregate["evaluated_pick_count"]}
    assert _format_partial_benchmark(window) == "bench_n=1/2 matched_ret=10.0 "


def test_window_evaluation_survives_a_snapshot_outage(tmp_path, monkeypatch):
    from alphasift.evaluate import evaluate_saved_runs_by_windows

    _save_run(tmp_path)

    def snapshot_down(*args, **kwargs):
        raise RuntimeError("All snapshot sources failed")

    paths = {
        "000001": _with_entry(10.0, _bars(1, [10.5, 11.0, 12.0])),
        "600000": _with_entry(20.0, _bars(1, [19.0, 18.0, 17.0])),
    }
    monkeypatch.setattr("alphasift.evaluate.fetch_snapshot_with_fallback", snapshot_down)
    monkeypatch.setattr("alphasift.evaluate.fetch_daily_history", lambda code, **kwargs: paths[code])
    monkeypatch.setattr("alphasift.evaluate._fetch_benchmark_path", lambda market, *, lookback_days: pd.DataFrame())

    payload = evaluate_saved_runs_by_windows(
        windows=[2], config=Config(llm_api_key="", data_dir=tmp_path), cost_bps=0
    )

    window = payload["strategy_summaries"][0]["window_summaries"][0]
    assert window["average_return_pct"] == 0.0  # +10% and -10% at T+2
    assert any("current snapshot unavailable" in item for item in payload["source_errors"])
