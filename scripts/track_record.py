#!/usr/bin/env python3
"""Daily track record: screen after the close, evaluate T+N, build the site data.

Used by ``.github/workflows/track-record.yml``. Every built-in strategy is
run with ``--no-llm --save-run`` for each market of a session. The saved runs
are the record. Evaluation and site data are derived from them and can be
rebuilt at any time.

    python scripts/track_record.py screen   --session asia --track track
    python scripts/track_record.py evaluate --markets cn,hk --track track
    python scripts/track_record.py build    --track track

``--track`` is a checkout of the ``track-record`` branch. Runs go to
``<track>/data/runs`` (``ALPHASIFT_DATA_DIR=<track>/data``), and the site to
``<track>/site``. Caches and source health are pointed at a separate state
directory by the workflow, so they never land in git.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SESSIONS = {"asia": ["cn", "hk", "jp", "kr", "tw", "in"], "us": ["us"]}
WINDOWS = [5, 10, 20]
SCREEN_TIMEOUT_SEC = 20 * 60
RECENT_DAYS_IN_SUMMARY = 30
PICK_FIELDS = ("rank", "code", "name", "industry", "price", "pe_ratio", "pb_ratio", "final_score")


# --------------------------------------------------------------------------- screen


def strategies_for(market: str) -> list[str]:
    from alphasift.strategy import list_strategies

    return sorted(info.name for info in list_strategies() if market in info.market_scope)


def run_session(session: str, track: Path, *, markets: list[str] | None = None) -> dict[str, Any]:
    """Screen every strategy of every market in the session; never stop on one failure."""
    runs_dir = track / "data" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "ALPHASIFT_DATA_DIR": str(track / "data")}
    entries = []
    for market in markets or SESSIONS[session]:
        for strategy in strategies_for(market):
            before = set(runs_dir.glob("*.json"))
            started = time.monotonic()
            entry: dict[str, Any] = {"market": market, "strategy": strategy}
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "alphasift.cli", "screen", strategy,
                     "--market", market, "--no-llm", "--save-run"],
                    env=env, capture_output=True, text=True, timeout=SCREEN_TIMEOUT_SEC,
                )
                created = sorted(set(runs_dir.glob("*.json")) - before)
                if proc.returncode == 0 and created:
                    run = json.loads(created[-1].read_text(encoding="utf-8"))
                    entry.update(status="ok", run_id=run.get("run_id"), picks=len(run.get("picks", [])),
                                 snapshot_source=run.get("snapshot_source", ""),
                                 degradation=len(run.get("degradation") or []))
                else:
                    entry.update(status="failed", error=_tail(proc.stderr or proc.stdout))
            except subprocess.TimeoutExpired:
                entry.update(status="timeout", error=f"exceeded {SCREEN_TIMEOUT_SEC}s")
            entry["seconds"] = round(time.monotonic() - started, 1)
            print(f"[{entry['status']:>7}] {market:<3} {strategy:<24} {entry['seconds']:>6}s "
                  f"{entry.get('error', '')}", flush=True)
            entries.append(entry)

    log = {"session": session, "finished_at": _now(), "entries": entries}
    log_path = track / "data" / "logs" / f"{_today_cst()}-{session}.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    return log


def _tail(text: str, lines: int = 3) -> str:
    return " | ".join(line.strip() for line in (text or "").strip().splitlines()[-lines:])[:600]


# --------------------------------------------------------------------------- evaluate


def evaluate_markets(track: Path, markets: list[str]) -> dict[str, Any]:
    """T+N evaluation of every saved run in ``markets``; other markets keep their last result.

    A run whose windows have all completed is final and is not fetched again.
    """
    import pandas as pd

    os.environ["ALPHASIFT_DATA_DIR"] = str(track / "data")
    from alphasift.config import Config
    from alphasift.evaluate import evaluate_saved_run

    config = Config.from_env()
    out_path = track / "site" / "evaluation.json"
    previous = _read_json(out_path) or {}
    runs_out: dict[str, Any] = dict(previous.get("runs", {}))
    no_snapshot = pd.DataFrame(columns=["code", "price"])  # T+N uses closes, not live quotes

    for run in load_runs(track):
        if run["market"] not in markets:
            continue
        prior = runs_out.get(run["run_id"])
        if prior and prior.get("final"):
            continue
        benchmark_paths: dict = {}
        windows: dict[str, Any] = {}
        for window in WINDOWS:
            try:
                result = evaluate_saved_run(
                    run["path"], config=config, current_snapshot=no_snapshot,
                    with_price_path=True, horizon_days=window, benchmark_paths=benchmark_paths,
                )
            except Exception as exc:  # one broken run must not stop the record
                windows[str(window)] = {"error": str(exc)[:300]}
                continue
            windows[str(window)] = {
                "benchmark": result.benchmark,
                "benchmark_return_pct": result.benchmark_return_pct,
                "pending": result.pending_count,
                "picks": {
                    pick.code: {
                        "status": pick.status,
                        "return_pct": _round(pick.return_pct),
                        "excess_return_pct": _round(pick.excess_return_pct),
                    }
                    for pick in result.picks
                },
            }
        final = all(
            "picks" in item and not any(p["status"] == "pending" for p in item["picks"].values())
            for item in windows.values()
        )
        runs_out[run["run_id"]] = {"evaluated_at": _now(), "final": final, "windows": windows}
        print(f"evaluated {run['market']:<3} {run['strategy']:<24} {run['run_id']} final={final}", flush=True)

    payload = {"evaluated_at": _now(), "windows": WINDOWS, "runs": runs_out}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return payload


# --------------------------------------------------------------------------- build


def load_runs(track: Path) -> list[dict[str, Any]]:
    """Saved runs, oldest first, each with its session date in exchange time."""
    runs = []
    for path in (track / "data" / "runs").glob("*.json"):
        data = _read_json(path)
        if not isinstance(data, dict) or not data.get("run_id"):
            continue
        market = data.get("market") or "cn"
        runs.append({
            "path": str(path),
            "run_id": data["run_id"],
            "market": market,
            "strategy": data.get("strategy", ""),
            "strategy_version": data.get("strategy_version", ""),
            "created_at": data.get("created_at", ""),
            "date": session_date(market, data.get("created_at", "")),
            "snapshot_count": data.get("snapshot_count"),
            "after_filter_count": data.get("after_filter_count"),
            "snapshot_source": data.get("snapshot_source", ""),
            "degradation": len(data.get("degradation") or []),
            "picks": [
                {key: _round(pick.get(key)) if isinstance(pick.get(key), float) else pick.get(key)
                 for key in PICK_FIELDS}
                for pick in data.get("picks", []) if isinstance(pick, dict)
            ],
        })
    return sorted(runs, key=lambda run: run["created_at"])


def session_date(market: str, created_at: str) -> str:
    """The exchange session a run belongs to (a US run saved at 06:30 CST is the prior US day)."""
    from alphasift.markets import get_market, latest_settled_close
    from alphasift.timeutil import parse_timestamp

    created = parse_timestamp(created_at)
    if created is None:
        return created_at[:10]
    settled = latest_settled_close(market, created)
    if settled is not None:
        return settled[0].isoformat()
    return created.astimezone(ZoneInfo(get_market(market).timezone)).date().isoformat()


def build_site(track: Path) -> dict[str, Any]:
    from alphasift.markets import get_market
    from alphasift.strategy import list_strategies

    site = track / "site"
    (site / "days").mkdir(parents=True, exist_ok=True)
    runs = load_runs(track)
    evaluation = (_read_json(site / "evaluation.json") or {}).get("runs", {})
    names = {info.name: info.display_name for info in list_strategies()}

    for run in runs:
        windows = (evaluation.get(run["run_id"]) or {}).get("windows", {})
        run["evaluation"] = {w: _run_window_summary(item) for w, item in windows.items()}
        for pick in run["picks"]:
            pick["evaluation"] = {
                w: item.get("picks", {}).get(pick["code"]) for w, item in windows.items() if "picks" in item
            }

    by_day: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        by_day.setdefault(run["date"], []).append(run)
    for day, day_runs in by_day.items():
        payload = {"date": day, "runs": [{k: v for k, v in run.items() if k != "path"} for run in day_runs]}
        (site / "days" / f"{day}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    markets = sorted({run["market"] for run in runs}, key=lambda m: list(SESSIONS["asia"] + SESSIONS["us"]).index(m))
    summary = {
        "generated_at": _now(),
        "windows": WINDOWS,
        "strategy_names": names,
        "markets": [
            {"id": m, "name": get_market(m).name, "benchmark": get_market(m).benchmark_name} for m in markets
        ],
        "sessions": _latest_logs(track),
        "scorecard": scorecard(runs, evaluation),
        "trend": trend(runs, evaluation),
        "latest": _latest_runs(runs),
        "days": [{"date": day, "runs": len(by_day[day])} for day in sorted(by_day, reverse=True)],
        "run_count": len(runs),
    }
    (site / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    (track / "README.md").write_text(render_readme(summary), encoding="utf-8")
    return summary


def _run_window_summary(item: dict[str, Any]) -> dict[str, Any]:
    picks = list(item.get("picks", {}).values())
    returns = [p["return_pct"] for p in picks if p["status"] == "ok" and p["return_pct"] is not None]
    excess = [p["excess_return_pct"] for p in picks if p["status"] == "ok" and p["excess_return_pct"] is not None]
    return {
        "average_return_pct": _round(statistics.fmean(returns)) if returns else None,
        "average_excess_return_pct": _round(statistics.fmean(excess)) if excess else None,
        "benchmark_return_pct": _round(item.get("benchmark_return_pct")),
        "evaluated": len(returns),
        "pending": item.get("pending", 0),
        "error": item.get("error"),
    }


def _pick_outcomes(runs: list[dict], evaluation: dict, window: int):
    """(run, pick outcome) for every pick of ``runs`` at ``window``."""
    for run in runs:
        item = ((evaluation.get(run["run_id"]) or {}).get("windows") or {}).get(str(window)) or {}
        for outcome in (item.get("picks") or {}).values():
            yield run, outcome


def scorecard(runs: list[dict], evaluation: dict) -> list[dict[str, Any]]:
    """Per market and strategy, per window: pick-level averages over completed windows.

    Excess return and beat rate use only picks whose benchmark matched, and
    ``matched_return_pct`` is the return over that same population, so
    matched return − benchmark = excess.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for run in runs:
        groups.setdefault((run["market"], run["strategy"]), []).append(run)
    rows = []
    for (market, strategy), group in sorted(groups.items()):
        windows = {}
        for window in WINDOWS:
            outcomes = [o for _, o in _pick_outcomes(group, evaluation, window)]
            done = [o for o in outcomes if o["status"] == "ok" and o["return_pct"] is not None]
            matched = [o for o in done if o["excess_return_pct"] is not None]
            windows[str(window)] = {
                "evaluated": len(done),
                "pending": sum(1 for o in outcomes if o["status"] == "pending"),
                "unavailable": sum(1 for o in outcomes if o["status"] not in {"ok", "pending"}),
                "average_return_pct": _mean(o["return_pct"] for o in done),
                "win_rate": _round(sum(o["return_pct"] > 0 for o in done) / len(done)) if done else None,
                "matched": len(matched),
                "matched_return_pct": _mean(o["return_pct"] for o in matched),
                "average_excess_return_pct": _mean(o["excess_return_pct"] for o in matched),
                "beat_rate": _round(sum(o["excess_return_pct"] > 0 for o in matched) / len(matched))
                if matched else None,
            }
        rows.append({"market": market, "strategy": strategy, "runs": len(group),
                     "first_date": group[0]["date"], "last_date": group[-1]["date"], "windows": windows})
    return rows


def trend(runs: list[dict], evaluation: dict) -> dict[str, Any]:
    """Expanding mean excess return by entry date: market -> window -> strategy -> [[date, mean, n]]."""
    out: dict[str, Any] = {}
    for window in WINDOWS:
        sums: dict[tuple[str, str], list[float]] = {}
        for run, outcome in _pick_outcomes(runs, evaluation, window):
            if outcome["status"] != "ok" or outcome["excess_return_pct"] is None:
                continue
            key = (run["market"], run["strategy"])
            sums.setdefault(key, [])
            series = out.setdefault(run["market"], {}).setdefault(str(window), {}).setdefault(run["strategy"], [])
            values = sums[key]
            values.append(outcome["excess_return_pct"])
            point = [run["date"], _round(statistics.fmean(values)), len(values)]
            if series and series[-1][0] == run["date"]:
                series[-1] = point
            else:
                series.append(point)
    return out


def _latest_runs(runs: list[dict]) -> dict[str, list[dict]]:
    latest: dict[tuple[str, str], dict] = {}
    for run in runs:  # oldest first, so the last one wins
        latest[(run["market"], run["strategy"])] = run
    out: dict[str, list[dict]] = {}
    for (market, _), run in sorted(latest.items()):
        out.setdefault(market, []).append({k: v for k, v in run.items() if k != "path"})
    return out


def _latest_logs(track: Path) -> dict[str, Any]:
    out = {}
    for session in SESSIONS:
        logs = sorted((track / "data" / "logs").glob(f"*-{session}.json"))
        if logs:
            log = _read_json(logs[-1]) or {}
            entries = log.get("entries", [])
            out[session] = {
                "finished_at": log.get("finished_at"),
                "ok": sum(1 for e in entries if e.get("status") == "ok"),
                "total": len(entries),
                "failures": [e for e in entries if e.get("status") != "ok"],
            }
    return out


def render_readme(summary: dict[str, Any]) -> str:
    names = summary["strategy_names"]
    lines = [
        "# AlphaSift track record",
        "",
        "Every trading day after the close, a GitHub Action runs each built-in strategy with "
        "`--no-llm --save-run` and commits the saved run here. Picks are never edited afterwards; "
        "the git history is the timestamped record. Each pick is then measured at T+5 / T+10 / T+20 "
        "trading days against its market benchmark.",
        "",
        "**Dashboard:** https://zhulinsen.github.io/alphasift/ · Code: "
        "[ZhuLinsen/alphasift](https://github.com/ZhuLinsen/alphasift) · "
        f"Updated {summary['generated_at']} · {summary['run_count']} saved runs",
        "",
        "> For research only, not investment advice. Returns are close-to-close after a round-trip "
        "cost, ignore dividends, and small samples are noisy.",
        "",
        "## Scorecard (T+5 / T+20)",
        "",
        "| Market | Strategy | Runs | T+5 n | T+5 excess | T+5 beat | T+20 n | T+20 excess | T+20 beat |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["scorecard"]:
        w5, w20 = row["windows"]["5"], row["windows"]["20"]
        lines.append(
            f"| {row['market']} | {names.get(row['strategy'], row['strategy'])} | {row['runs']} "
            f"| {w5['matched']} | {_pct(w5['average_excess_return_pct'])} | {_rate(w5['beat_rate'])} "
            f"| {w20['matched']} | {_pct(w20['average_excess_return_pct'])} | {_rate(w20['beat_rate'])} |"
        )
    lines += ["", "## Latest session", ""]
    for session, info in summary["sessions"].items():
        lines.append(f"- **{session}** finished {info['finished_at']}: {info['ok']}/{info['total']} strategies ok")
        for failure in info["failures"]:
            lines.append(f"  - {failure['market']} {failure['strategy']}: {failure['status']} {failure.get('error', '')}")
    lines += ["", "Raw runs: [`data/runs/`](data/runs) · derived site data: [`site/`](site)", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- helpers


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _round(value: Any, digits: int = 4) -> Any:
    if isinstance(value, float):
        return round(value, digits) if value == value else None
    return value


def _mean(values) -> float | None:
    values = list(values)
    return _round(statistics.fmean(values)) if values else None


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value:+.2f}%"


def _rate(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:.0f}%"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _today_cst() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["screen", "evaluate", "build"])
    parser.add_argument("--track", type=Path, required=True, help="checkout of the track-record branch")
    parser.add_argument("--session", choices=sorted(SESSIONS), default="asia")
    parser.add_argument("--markets", default="", help="comma-separated; defaults to the session's markets")
    args = parser.parse_args(argv)
    markets = [m.strip() for m in args.markets.split(",") if m.strip()] or SESSIONS[args.session]

    if args.command == "screen":
        log = run_session(args.session, args.track, markets=markets)
        ok = sum(1 for e in log["entries"] if e["status"] == "ok")
        print(f"{ok}/{len(log['entries'])} strategies saved a run")
        return 0 if ok else 1
    if args.command == "evaluate":
        evaluate_markets(args.track, markets)
        return 0
    build_site(args.track)
    return 0


if __name__ == "__main__":
    sys.exit(main())
