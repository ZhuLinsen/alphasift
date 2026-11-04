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
