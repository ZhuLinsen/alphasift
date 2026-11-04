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
            "000001": _bars(1, [10.5, 11.0, 12.0]),
            "600000": _bars(1, [19.0]),  # only one post-entry bar so far
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

    ret, label, errors = _benchmark_return(old_run, horizon_days=5, lookback_days=160, cache=cache)

    assert fetched == [160]
    assert errors == [] and ret is not None
    assert cache["us"]["date"].min() == pd.Timestamp("2026-06-01")
