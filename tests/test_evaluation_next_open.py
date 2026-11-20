import json
import sys

import pandas as pd
import pytest

from alphasift.cli import main
from alphasift.config import Config
from alphasift.evaluate import evaluate_saved_run, evaluate_saved_runs_by_windows
from alphasift.models import Pick, ScreenResult
from alphasift.report import build_run_report_payload, render_run_report_markdown
from alphasift.store import evaluation_from_dict, save_screen_result


def _history(*rows):
    frame = pd.DataFrame(rows, columns=["date", "open", "close", "low", "high"])
    frame["date"] = frame["date"].map(lambda day: f"2025-03-{day:02d}")
    frame.attrs["fetched_at"] = "2025-03-10T17:00:00-04:00"
    return frame


@pytest.fixture
def next_open_run(tmp_path, monkeypatch):
    config = Config(llm_api_key="", data_dir=tmp_path)
    snapshot = pd.DataFrame(columns=["code", "price"])
    benchmark = _history(
        (3, 89, 90, 88, 91),
        (4, 100, 101, 99, 102),
        (5, 102, 103, 100, 104),
        (6, 105, 110, 104, 111),
        (7, 109, 120, 108, 121),
    )

    def setup(paths, *, names=None, market="cn", benchmark_path=benchmark):
        run = ScreenResult(
            run_id="next-open",
            strategy="dual_low",
            market=market,
            created_at="2025-03-03T23:00:00+00:00",
            picks=[
                Pick(
                    rank=rank, code=code, name=(names or {}).get(code, code),
                    price=99.0, screen_score=80, final_score=80,
                )
                for rank, code in enumerate(paths, start=1)
            ],
        )
        save_screen_result(run, data_dir=tmp_path)
        monkeypatch.setattr("alphasift.cli.Config.from_env", lambda: config)
        monkeypatch.setattr("alphasift.evaluate.fetch_snapshot_with_fallback", lambda *args, **kwargs: snapshot)
        monkeypatch.setattr("alphasift.evaluate._fill_missing_quotes", lambda *args: snapshot)
        monkeypatch.setattr("alphasift.evaluate.fetch_daily_history", lambda code, **kwargs: paths[code])
        monkeypatch.setattr(
            "alphasift.evaluate._fetch_benchmark_path", lambda market, *, lookback_days: benchmark_path
        )
        return run, config, snapshot

    return setup


def test_next_open_counts_entry_bar_and_matches_benchmark_open(next_open_run):
    stock = _history(
        (3, 9.8, 9.8, 9.0, 12.0),
        (4, "10", 10.4, 9.5, 10.8),
        (5, "10.5", 10.6, 10.0, 10.7),
        (6, "10.8", 11.5, 10.8, 11.7),
    ).rename(columns={"open": "开盘"})
    run, config, snapshot = next_open_run({"000001": stock})
    params = dict(config=config, current_snapshot=snapshot, horizon_days=2, cost_bps=25)

    result = evaluate_saved_run(run.run_id, entry_mode="next_open", **params)

    pick = result.picks[0]
    assert result.entry_mode == pick.entry_mode == "next_open"
    assert (pick.entry_date, pick.exit_date, pick.path_days) == ("2025-03-04", "2025-03-05", 2)
    assert pick.entry_open == 10.0
    assert pick.entry_price == 99.0
    assert pick.return_pct == 5.75
    assert pick.max_runup_pct == 8.0
    assert pick.max_drawdown_pct == -5.0
    assert result.benchmark_return_pct == pick.benchmark_return_pct == 3.0
    assert result.average_excess_return_pct == pick.excess_return_pct == 2.75

    default = evaluate_saved_run(run.run_id, **params)
    close = evaluate_saved_run(run.run_id, entry_mode="close", **params)
    assert default.picks == close.picks
    assert default.average_return_pct == close.average_return_pct == 7.9133
    assert default.benchmark_return_pct == close.benchmark_return_pct == 14.4444


def test_cn_limit_up_boards_are_excluded_and_counted_separately(next_open_run):
    limits = {
        "000001": (10.03, 11.03),
        "300001": (10, 12), "301001": (10, 12),
        "688001": (10, 12), "689001": (10, 12),
        "430001": (10, 13), "830001": (10, 13), "920001": (10, 13),
        "600001": (10, 10.5), "600002": (10, 10.5),
    }
    paths = {
        code: _history((3, previous, previous, previous, previous), (4, limit, limit, limit, limit))
        for code, (previous, limit) in limits.items()
    }
    paths["600003"] = _history((3, 10, 10, 10, 10), (4, 10, 11, 10, 11))
    paths["600004"] = _history((3, 10, 10, 10, 10), (4, 11, 11, 10.9, 11))
    run, config, snapshot = next_open_run(paths, names={"600001": "ST样例", "600002": "*ST样例"})

    result = evaluate_saved_run(
        run.run_id, config=config, current_snapshot=snapshot, entry_mode="next_open", horizon_days=1, cost_bps=0
    )

    assert {
        pick.code for pick in result.picks
        if pick.status == pick.path_status == "untradable_limit_up" and pick.return_pct is None
    } == set(limits)
    assert [pick.return_pct for pick in result.picks[-2:]] == [10.0, 0.0]
    assert result.untradable_count == 10
    assert result.untradable_share_pct == 83.3333
    assert result.missing_codes == []
    assert result.average_return_pct == 5.0
    assert result.win_rate == 50.0

    payload = evaluate_saved_runs_by_windows(
        config=config, current_snapshot=snapshot, entry_mode="next_open", windows=[1], cost_bps=0
    )
    summary = payload["strategy_summaries"][0]["window_summaries"][0]
    assert summary["pick_status_counts"] == {"ok": 2, "untradable_limit_up": 10}
    assert summary["untradable_count"] == 10
    assert summary["untradable_share_pct"] == 83.3333
    assert summary["evaluated_pick_count"] == 2
    assert summary["average_return_pct"] == 5.0
    assert summary["win_rate"] == 50.0

    report = render_run_report_markdown(build_run_report_payload(run, evaluation=result))
    assert "entry_mode: next_open" in report
    assert "untradable_count: 10" in report
    assert "untradable_limit_up" in report


def test_st_name_on_20pct_board_keeps_board_limit(next_open_run):
    # A flat +5% bar is a one-price limit-up only for main-board ST.
    paths = {"300002": _history((3, 10, 10, 10, 10), (4, 10.5, 10.5, 10.5, 10.5))}
    run, config, snapshot = next_open_run(paths, names={"300002": "ST创业"})

    result = evaluate_saved_run(
        run.run_id, config=config, current_snapshot=snapshot, entry_mode="next_open", horizon_days=1, cost_bps=0
    )

    assert [pick.status for pick in result.picks] == ["ok"]
    assert result.untradable_count == 0


def test_cn_open_one_tick_below_rounded_limit_is_tradable(next_open_run):
    stock = _history((3, 10.05, 10.05, 10.05, 10.05), (4, 11.05, 11.06, 11.05, 11.06))
    run, config, snapshot = next_open_run({"000001": stock})

    result = evaluate_saved_run(
        run.run_id, config=config, current_snapshot=snapshot, entry_mode="next_open", horizon_days=1, cost_bps=0
    )

    assert result.picks[0].status == "ok"
    assert result.picks[0].return_pct == 0.0905


@pytest.mark.parametrize("can_exit", [True, False])
def test_cn_limit_down_rolls_until_first_unlocked_bar(next_open_run, can_exit):
    rows = [
        (3, 10, 10, 10, 10),
        (4, 10, 10, 9.8, 10.5),
        (5, 9, 9, 9, 9),
        (6, 8.1, 8.1, 8.1, 8.1),
    ]
    if can_exit:
        rows.append((7, 7.4, 7.8, 7.32, 8.0))
    run, config, snapshot = next_open_run({"000001": _history(*rows)})

    result = evaluate_saved_run(
        run.run_id, config=config, current_snapshot=snapshot, entry_mode="next_open", horizon_days=2, cost_bps=0
    )

    pick = result.picks[0]
    assert pick.tradability_flags == ["exit_delayed_limit_down"]
    if can_exit:
        assert pick.status == "ok"
        assert pick.exit_date == "2025-03-07"
        assert pick.path_days == 4
        assert pick.return_pct == -22.0
        assert pick.max_drawdown_pct == -26.8
        assert pick.benchmark_return_pct == 20.0
        assert pick.excess_return_pct == -42.0
    else:
        assert pick.status == pick.path_status == "pending"
        assert pick.path_days == 3
        assert pick.exit_date is pick.return_pct is pick.excess_return_pct is None
        assert result.pending_count == 1


@pytest.mark.parametrize("has_suspended_bar", [False, True])
def test_suspended_entry_uses_first_available_stock_bar_and_benchmark_date(next_open_run, has_suspended_bar):
    rows = [
        (3, 10, 10, 10, 10),
        (5, 10, 10.5, 9.8, 10.5),
        (6, 10.5, 11, 10.2, 11),
    ]
    if has_suspended_bar:
        rows.insert(1, (4, 10, 10, 10, 10))
    stock = _history(*rows)
    if has_suspended_bar:
        stock["成交量"] = [1000, 0, 1000, 1000]
    run, config, snapshot = next_open_run({"000001": stock})

    result = evaluate_saved_run(
        run.run_id, config=config, current_snapshot=snapshot, entry_mode="next_open", horizon_days=2, cost_bps=0
    )

    pick = result.picks[0]
    assert pick.tradability_flags == ["entry_delayed_missing_bar"]
    assert (pick.entry_date, pick.exit_date) == ("2025-03-05", "2025-03-06")
    assert result.benchmark_return_pct == 3.0
    assert pick.return_pct == 10.0
    assert pick.benchmark_return_pct == 7.8431
    assert pick.excess_return_pct == 2.1569


def test_next_open_ignores_an_incomplete_session(next_open_run):
    stock = _history((3, 10, 10, 10, 10), (4, 10, 10.5, 10, 10.5), (5, 10.5, 11, 10.5, 11))
    stock.attrs["fetched_at"] = "2025-03-05T10:00:00+08:00"
    run, config, snapshot = next_open_run({"000001": stock})

    result = evaluate_saved_run(
        run.run_id, config=config, current_snapshot=snapshot, entry_mode="next_open", horizon_days=2, cost_bps=0
    )

    assert result.pending_count == 1
    pick = result.picks[0]
    assert pick.status == "pending"
    assert pick.path_days == 1
    assert pick.tradability_flags == []
    assert pick.return_pct is None


def test_non_cn_ignores_both_limits(next_open_run):
    stock = _history((3, 10, 10, 10, 10), (4, 11, 11, 11, 11), (5, 9.9, 9.9, 9.9, 9.9))
    run, config, snapshot = next_open_run({"ACME": stock}, market="us")

    result = evaluate_saved_run(
        run.run_id, config=config, current_snapshot=snapshot, entry_mode="next_open", horizon_days=2, cost_bps=0
    )

    pick = result.picks[0]
    assert pick.status == "ok"
    assert pick.tradability_flags == []
    assert pick.entry_open == 11.0
    assert pick.exit_date == "2025-03-05"
    assert pick.return_pct == -10.0
    assert pick.excess_return_pct == -13.0


def test_missing_stock_open_or_benchmark_open_never_uses_close_as_substitute(next_open_run):
    stock = _history((3, 10, 10, 10, 10), (4, 10, 10.5, 9.9, 10.5))
    benchmark = _history((3, 90, 90, 90, 90), (4, 100, 101, 99, 102)).drop(columns="open")
    run, config, snapshot = next_open_run(
        {"000001": stock, "000002": stock.drop(columns="open")}, benchmark_path=benchmark
    )

    result = evaluate_saved_run(
        run.run_id, config=config, current_snapshot=snapshot, entry_mode="next_open", horizon_days=1, cost_bps=0
    )

    first, second = result.picks
    assert first.return_pct == 5.0
    assert result.benchmark_return_pct is first.benchmark_return_pct is first.excess_return_pct is None
    assert "Benchmark CSI 300 history has no open column" in result.degradation
    assert second.status == "missing"
    assert second.path_status == "no_entry_open"
    assert second.entry_open is second.return_pct is None


def test_missing_benchmark_exit_date_does_not_use_previous_close(next_open_run):
    stock = _history((3, 10, 10, 10, 10), (4, 10, 10.5, 10, 10.5), (5, 10.5, 11, 10.5, 11))
    benchmark = _history((3, 90, 90, 90, 90), (4, 100, 101, 99, 102), (6, 100, 102, 99, 102))
    run, config, snapshot = next_open_run({"000001": stock}, benchmark_path=benchmark)

    result = evaluate_saved_run(
        run.run_id, config=config, current_snapshot=snapshot, entry_mode="next_open", horizon_days=2, cost_bps=0
    )

    pick = result.picks[0]
    assert result.benchmark_return_pct == 2.0
    assert pick.return_pct == 10.0
    assert pick.benchmark_return_pct is pick.excess_return_pct is None
    assert "Benchmark CSI 300 history lacks a matching entry or exit session" in result.degradation


def test_window_entry_mode_is_exposed_in_cli_json_and_text(next_open_run, monkeypatch, capsys):
    stock = _history((3, 10, 10, 10, 10), (4, 11, 11, 11, 11))
    run, _, _ = next_open_run({"000001": stock})

    monkeypatch.setattr(sys, "argv", ["alphasift", "evaluate", run.run_id, "--window", "1", "--entry-mode", "next_open"])
    main()
    result = evaluation_from_dict(json.loads(capsys.readouterr().out))
    assert result.entry_mode == "next_open"
    assert result.picks[0].status == "untradable_limit_up"

    args = ["alphasift", "evaluate-strategies", "--window", "1,2", "--entry-mode", "next_open"]
    monkeypatch.setattr(sys, "argv", [*args, "--json"])
    main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["entry_mode"] == "next_open"
    for window in payload["strategy_summaries"][0]["window_summaries"]:
        assert window["untradable_count"] == 1
        assert window["untradable_share_pct"] == 100.0

    monkeypatch.setattr(sys, "argv", [*args, "--explain"])
    main()
    summary = capsys.readouterr().out
    assert "entry_mode=next_open" in summary
    assert "untradable=1 untradable_share=100.00%" in summary
