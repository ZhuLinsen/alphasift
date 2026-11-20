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
import dataclasses
import json
import os
import statistics
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# Ensure direct script execution (`python scripts/track_record.py`) can import
# the local `alphasift` package when the repo root is not on sys.path.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

SESSIONS = {"asia": ["cn", "hk", "jp", "kr", "tw", "in"], "us": ["us"]}
WINDOWS = [5, 10, 20]
SNAPSHOT_TIMEOUT_SEC = 5 * 60
SCREEN_TIMEOUT_SEC = 20 * 60
AI_SCREEN_TIMEOUT_SEC = 120
AI_TRACK_MARKETS = frozenset({"cn"})
MAX_MISSING_RETRY_DAYS = 90
SKIPPED_STATUSES = frozenset({"skipped_holiday", "skipped_duplicate"})
RECENT_DAYS_IN_SUMMARY = 30
PICK_FIELDS = ("rank", "code", "name", "industry", "price", "pe_ratio", "pb_ratio", "final_score")


# --------------------------------------------------------------------------- screen


def strategies_for(market: str) -> list[str]:
    from alphasift.strategy import list_strategies

    return sorted(info.name for info in list_strategies() if market in info.market_scope)


def _required_columns_for_market(strategies: list[str], config: Any) -> list[str]:
    from alphasift.filter import requires_daily_features, without_daily_filters
    from alphasift.pipeline import _required_snapshot_columns
    from alphasift.strategy import load_all_strategies

    loaded = load_all_strategies(config.strategies_dir)
    cols: list[str] = []
    for name in strategies:
        strat = loaded.get(name)
        if strat is None:
            continue
        filters = strat.screening.hard_filters
        if requires_daily_features(filters):
            filters = without_daily_filters(filters)
        cols.extend(_required_snapshot_columns(filters))
    return list(dict.fromkeys(cols))


def _fetch_market_snapshot(market: str, strategies: list[str], config: Any):
    from alphasift.snapshot import fetch_snapshot_with_fallback

    required = _required_columns_for_market(strategies, config)
    try:
        return fetch_snapshot_with_fallback(
            config.snapshot_source_priority,
            required_columns=required,
            fallback_snapshot_path=config.fallback_snapshot_path,
            fallback_max_age_hours=config.snapshot_fallback_max_age_hours,
            market=market,
            source_health_path=config.source_health_path,
        )
    except Exception as exc:
        if "missing required columns" in str(exc) and len(strategies) > 1:
            return fetch_snapshot_with_fallback(
                config.snapshot_source_priority,
                required_columns=[],
                fallback_snapshot_path=config.fallback_snapshot_path,
                fallback_max_age_hours=config.snapshot_fallback_max_age_hours,
                market=market,
                source_health_path=config.source_health_path,
            )
        raise


def _latest_benchmark_date(market: str, *, source: str | None = None) -> str | None:
    from alphasift.evaluate import _normalize_price_path

    if market == "cn" and source in {"tencent", "sina"}:
        from alphasift.daily import _fetch_daily_sina, _fetch_daily_tencent

        fetcher = _fetch_daily_tencent if source == "tencent" else _fetch_daily_sina
        path = fetcher("sh000300", lookback_days=15)
    else:
        from alphasift.evaluate import _fetch_benchmark_path

        path = _fetch_benchmark_path(market, lookback_days=15)
    norm = _normalize_price_path(path)
    if norm.empty or "date" not in norm.columns or norm["date"].dropna().empty:
        return None
    return norm["date"].dropna().iloc[-1].date().isoformat()


def _check_market_session(market: str, snapshot_df: Any, expected_date: str) -> tuple[str, str]:
    """Verify whether the fetched live snapshot represents ``expected_date``.

    Returns ``("open", effective_date)``, ``("closed", reason)`` when two
    independent signals corroborate an exchange holiday, or ``("stale", reason)``
    when the session date looks outdated or cannot be verified.
    """
    if market == "cn":
        try:
            parsed_expected = date.fromisoformat(expected_date[:10])
        except ValueError:
            return ("stale", f"invalid expected_date {expected_date!r}")

        attrs = getattr(snapshot_df, "attrs", {})
        raw_quote_date = str(attrs.get("quote_date") or "").strip()
        snap_source = str(attrs.get("snapshot_source") or "").strip().lower()
        if not raw_quote_date and hasattr(snapshot_df, "columns"):
            from alphasift.snapshot import _extract_cn_quote_date

            raw_quote_date = _extract_cn_quote_date(snapshot_df) or ""

        parsed_quote: date | None = None
        if raw_quote_date:
            try:
                parsed_quote = date.fromisoformat(raw_quote_date[:10])
            except ValueError:
                return (
                    "stale",
                    f"invalid CN snapshot quote_date {raw_quote_date!r} for {expected_date}",
                )
        elif snap_source == "tushare":
            return ("stale", f"tushare snapshot missing quote_date for {expected_date}")

        if parsed_quote is not None and parsed_quote >= parsed_expected:
            return ("open", parsed_quote.isoformat())

        t_date: date | None = None
        try:
            t_raw = _latest_benchmark_date("cn", source="tencent")
            t_date = date.fromisoformat(t_raw[:10]) if t_raw else None
        except Exception:  # noqa: BLE001
            t_date = None

        if parsed_quote is None and t_date is not None and t_date >= parsed_expected:
            return ("open", t_date.isoformat())
        if parsed_quote is not None and t_date is not None and t_date >= parsed_expected:
            return (
                "stale",
                f"stale CN snapshot quote_date {parsed_quote.isoformat()} < {expected_date}",
            )

        s_date: date | None = None
        try:
            s_raw = _latest_benchmark_date("cn", source="sina")
            s_date = date.fromisoformat(s_raw[:10]) if s_raw else None
        except Exception:  # noqa: BLE001
            s_date = None

        if parsed_quote is not None:
            if (
                t_date is not None
                and s_date is not None
                and max(t_date, s_date) < parsed_expected
            ):
                latest = max(t_date, s_date).isoformat()
                return (
                    "closed",
                    f"market closed (quotes {parsed_quote.isoformat()}, CSI 300 latest {latest} < {expected_date})",
                )
            return (
                "stale",
                f"stale CN snapshot quote_date {parsed_quote.isoformat()} < {expected_date}",
            )

        if s_date is not None and s_date >= parsed_expected:
            return ("open", s_date.isoformat())
        if t_date is not None and s_date is not None:
            latest = max(t_date, s_date).isoformat()
            return ("closed", f"market closed (CSI 300 latest {latest} < {expected_date})")
        observed = t_date or s_date
        if observed is not None:
            return (
                "stale",
                f"unconfirmed stale CN index date {observed.isoformat()} < {expected_date}",
            )
        return ("stale", f"unable to verify CN trading session for {expected_date}")

    raw_quote_date = str(getattr(snapshot_df, "attrs", {}).get("quote_date") or "")[:10]
    try:
        parsed_quote = date.fromisoformat(raw_quote_date)
        parsed_expected = date.fromisoformat(expected_date[:10])
    except ValueError:
        return (
            "stale",
            f"missing or invalid snapshot quote_date {raw_quote_date!r} for {expected_date}",
        )

    quote_date = parsed_quote.isoformat()
    if parsed_quote >= parsed_expected:
        return ("open", quote_date)

    try:
        bench_raw = _latest_benchmark_date(market)
        parsed_bench = date.fromisoformat(bench_raw[:10]) if bench_raw else None
    except Exception:  # noqa: BLE001
        parsed_bench = None
    if parsed_bench is not None and parsed_bench < parsed_expected:
        return (
            "closed",
            f"market closed (quotes {quote_date}, benchmark {parsed_bench.isoformat()} < {expected_date})",
        )
    return ("stale", f"unconfirmed stale quote_date {quote_date} < {expected_date}")


def _print_entry(entry: dict[str, Any]) -> None:
    print(
        f"[{entry['status']:>17}] {entry['market']:<3} {entry['strategy']:<24} "
        f"{entry['seconds']:>6}s {entry.get('error', '')}",
        flush=True,
    )


def _should_run_ai_track(market: str, ai_track: str, config: Any) -> bool:
    mode = (ai_track or "auto").strip().lower()
    if mode == "off" or market not in AI_TRACK_MARKETS:
        return False
    return bool(config.has_llm_config())


def _ai_run_id(result: Any, expected_date: str) -> str:
    base = str(getattr(result, "run_id", "") or "").strip()
    if not base:
        base = f"{result.strategy}_{expected_date}"
    return base if base.endswith("-ai") else f"{base}-ai"


def record_cn_patterns(
    track: Path,
    *,
    pack_dir: Path | None = None,
    trade_date: str | None = None,
    require_exact_date: bool = False,
    mini_kline_bars: int = 20,
    max_signals_per_pattern: int = 10,
    include_replay: bool = False,
    replay_json_path: Path | None = None,
) -> dict[str, Any] | None:
    """Scan the CN DailyPack (all patterns) and persist daily pattern board snapshot."""
    from alphasift.config import Config
    from alphasift.pack import load_pack, pack_dir as resolve_pack_dir
    from alphasift.patterns import extract_mini_kline_bars, scan_patterns

    config = Config.from_env()
    directory = Path(pack_dir).expanduser() if pack_dir is not None else resolve_pack_dir(config)
    if not (directory / "manifest.json").is_file():
        return None
    daily_pack = load_pack(directory)
    dates_set = {str(d) for d in daily_pack.dates}
    if require_exact_date and trade_date and trade_date not in dates_set:
        return None
    target_date = trade_date if (trade_date and trade_date in dates_set) else None
    scan = scan_patterns(daily_pack, trade_date=target_date, include_experimental=True)
    payload = scan.to_dict()

    sig_codes: list[str] = []
    cap = max(1, int(max_signals_per_pattern))
    for pat_name, items in payload.get("signals_by_pattern", {}).items():
        trimmed = list(items)[:cap]
        payload["signals_by_pattern"][pat_name] = trimmed
        for item in trimmed:
            sig_codes.append(str(item["code"]))

    if sig_codes and mini_kline_bars > 0:
        klines = extract_mini_kline_bars(
            daily_pack,
            sig_codes,
            trade_date=scan.trade_date,
            bars=mini_kline_bars,
        )
        for items in payload.get("signals_by_pattern", {}).values():
            for item in items:
                item["kline"] = klines.get(str(item["code"]), [])

    out_dir = track / "data" / "patterns"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{scan.trade_date}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if replay_json_path is not None and Path(replay_json_path).is_file():
        replay_data = _read_json(Path(replay_json_path))
        if isinstance(replay_data, dict):
            (out_dir / "replay.json").write_text(
                json.dumps(replay_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    elif include_replay:
        from alphasift.pattern_replay import load_cn_benchmark, replay_patterns

        bench = load_cn_benchmark(lookback_days=max(len(daily_pack.dates) + 40, 320))
        replay_data = replay_patterns(daily_pack, benchmark_df=bench)
        (out_dir / "replay.json").write_text(
            json.dumps(replay_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return payload


def run_session(
    session: str,
    track: Path,
    *,
    markets: list[str] | None = None,
    ai_track: str = "auto",
    pack_dir: Path | None = None,
) -> dict[str, Any]:
    """Screen every strategy of every market in the session; never stop on one failure."""
    runs_dir = track / "data" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    old_data_dir = os.environ.get("ALPHASIFT_DATA_DIR")
    old_tushare_date = os.environ.pop("TUSHARE_TRADE_DATE", None)
    os.environ["ALPHASIFT_DATA_DIR"] = str(track / "data")
    now_iso = _now()
    target_markets = list(markets or SESSIONS[session])
    entries: list[dict[str, Any]] = []
    ai_entries: list[dict[str, Any]] = []
    try:
        from alphasift.config import Config
        from alphasift.pipeline import screen
        from alphasift.source_guard import call_with_timeout
        from alphasift.store import save_screen_result

        # Track record is an immutable daily ledger of live picks: never fall back
        # to stale last-good snapshot caches from earlier trading days.
        config = dataclasses.replace(Config.from_env(), fallback_snapshot_path=None)
        recorded_dates: dict[tuple[str, str, str], set[str]] = {}
        for existing in load_runs(track):
            recorded_dates.setdefault(
                (existing["market"], existing["strategy"], existing.get("track", "rules")),
                set(),
            ).add(existing["date"])

        for market in target_markets:
            strats = strategies_for(market)
            if not strats:
                continue
            expected_date = session_date(market, now_iso)
            run_ai = _should_run_ai_track(market, ai_track, config)
            rules_done = all(
                expected_date in recorded_dates.get((market, s, "rules"), set())
                for s in strats
            )
            ai_done = (not run_ai) or all(
                expected_date in recorded_dates.get((market, s, "ai"), set())
                for s in strats
            )
            if rules_done and ai_done:
                for strategy in strats:
                    entry: dict[str, Any] = {
                        "market": market,
                        "strategy": strategy,
                        "track": "rules",
                        "status": "skipped_duplicate",
                        "error": f"already recorded {expected_date}",
                        "seconds": 0.0,
                    }
                    _print_entry(entry)
                    entries.append(entry)
                continue

            started_snapshot = time.monotonic()
            try:
                market_snapshot = call_with_timeout(
                    _fetch_market_snapshot,
                    market,
                    strats,
                    config,
                    timeout_sec=SNAPSHOT_TIMEOUT_SEC,
                    label=f"snapshot {market}",
                )
                if getattr(market_snapshot, "attrs", {}).get("fallback_used"):
                    raise RuntimeError("refusing stale fallback snapshot for track record")
            except TimeoutError:
                elapsed = round(time.monotonic() - started_snapshot, 1)
                msg = f"snapshot exceeded {SNAPSHOT_TIMEOUT_SEC}s"
                for strategy in strats:
                    entry = {
                        "market": market,
                        "strategy": strategy,
                        "track": "rules",
                        "status": "timeout",
                        "error": msg,
                        "seconds": elapsed,
                    }
                    _print_entry(entry)
                    entries.append(entry)
                continue
            except Exception as exc:  # noqa: BLE001 - one market failing must not stop others
                elapsed = round(time.monotonic() - started_snapshot, 1)
                msg = _tail(str(exc))
                for strategy in strats:
                    entry = {
                        "market": market,
                        "strategy": strategy,
                        "track": "rules",
                        "status": "failed",
                        "error": msg,
                        "seconds": elapsed,
                    }
                    _print_entry(entry)
                    entries.append(entry)
                continue

            session_state, detail = _check_market_session(market, market_snapshot, expected_date)
            if session_state in {"closed", "stale"}:
                status = "skipped_holiday" if session_state == "closed" else "failed"
                for strategy in strats:
                    entry = {
                        "market": market,
                        "strategy": strategy,
                        "track": "rules",
                        "status": status,
                        "error": detail,
                        "seconds": 0.0,
                    }
                    _print_entry(entry)
                    entries.append(entry)
                continue

            effective_date = detail or expected_date
            for strategy in strats:
                if effective_date in recorded_dates.get((market, strategy, "rules"), set()):
                    entry = {
                        "market": market,
                        "strategy": strategy,
                        "track": "rules",
                        "status": "skipped_duplicate",
                        "error": f"already recorded {effective_date}",
                        "seconds": 0.0,
                    }
                    _print_entry(entry)
                    entries.append(entry)
                    continue

                started = time.monotonic()
                entry = {"market": market, "strategy": strategy, "track": "rules"}
                try:
                    result = call_with_timeout(
                        screen,
                        strategy,
                        market=market,
                        use_llm=False,
                        config=config,
                        snapshot_df=market_snapshot,
                        allow_snapshot_refetch=False,
                        timeout_sec=SCREEN_TIMEOUT_SEC,
                        label=f"screen {market} {strategy}",
                    )
                    result.track = "rules"
                    save_screen_result(result, data_dir=config.data_dir)
                    recorded_dates.setdefault((market, strategy, "rules"), set()).add(effective_date)
                    entry.update(
                        status="ok",
                        run_id=result.run_id,
                        picks=len(result.picks),
                        snapshot_source=result.snapshot_source,
                        degradation=len(result.degradation or []),
                    )
                except TimeoutError:
                    entry.update(status="timeout", error=f"exceeded {SCREEN_TIMEOUT_SEC}s")
                except Exception as exc:  # noqa: BLE001 - one broken strategy must not stop the rest
                    entry.update(status="failed", error=_tail(str(exc)))
                entry["seconds"] = round(time.monotonic() - started, 1)
                _print_entry(entry)
                entries.append(entry)

            # Optional AI track (runs strictly after rules pass; timeout/degradation never breaks rules).
            if run_ai:
                for strategy in strats:
                    if effective_date in recorded_dates.get((market, strategy, "ai"), set()):
                        entry = {
                            "market": market,
                            "strategy": strategy,
                            "track": "ai",
                            "status": "skipped_duplicate",
                            "error": f"already recorded ai {effective_date}",
                            "seconds": 0.0,
                        }
                        _print_entry(entry)
                        ai_entries.append(entry)
                        continue
                    started_ai = time.monotonic()
                    ai_entry: dict[str, Any] = {"market": market, "strategy": strategy, "track": "ai"}
                    try:
                        ai_result = call_with_timeout(
                            screen,
                            strategy,
                            market=market,
                            use_llm=True,
                            config=config,
                            snapshot_df=market_snapshot,
                            allow_snapshot_refetch=False,
                            timeout_sec=AI_SCREEN_TIMEOUT_SEC,
                            label=f"ai screen {market} {strategy}",
                        )
                        if not ai_result.llm_ranked:
                            ai_entry.update(
                                status="skipped_llm_degraded",
                                error="; ".join(ai_result.degradation[:2]) or "llm_ranked=False",
                            )
                        else:
                            ai_result.track = "ai"
                            ai_result.run_id = _ai_run_id(ai_result, effective_date)
                            save_screen_result(ai_result, data_dir=config.data_dir)
                            recorded_dates.setdefault((market, strategy, "ai"), set()).add(effective_date)
                            ai_entry.update(
                                status="ok",
                                run_id=ai_result.run_id,
                                picks=len(ai_result.picks),
                                snapshot_source=ai_result.snapshot_source,
                                degradation=len(ai_result.degradation or []),
                            )
                    except TimeoutError:
                        ai_entry.update(
                            status="skipped_llm_timeout",
                            error=f"ai exceeded {AI_SCREEN_TIMEOUT_SEC}s",
                        )
                    except Exception as exc:  # noqa: BLE001
                        ai_entry.update(status="failed", error=_tail(str(exc)))
                    ai_entry["seconds"] = round(time.monotonic() - started_ai, 1)
                    _print_entry(ai_entry)
                    ai_entries.append(ai_entry)

            if market == "cn":
                try:
                    record_cn_patterns(
                        track,
                        pack_dir=pack_dir,
                        trade_date=effective_date,
                        require_exact_date=True,
                    )
                except Exception:  # noqa: BLE001
                    pass
    finally:
        if old_data_dir is None:
            os.environ.pop("ALPHASIFT_DATA_DIR", None)
        else:
            os.environ["ALPHASIFT_DATA_DIR"] = old_data_dir
        if old_tushare_date is None:
            os.environ.pop("TUSHARE_TRADE_DATE", None)
        else:
            os.environ["TUSHARE_TRADE_DATE"] = old_tushare_date

    log_date = session_date(target_markets[0], now_iso) if target_markets else _today_cst()
    log: dict[str, Any] = {
        "session": session,
        "date": log_date,
        "finished_at": _now(),
        "entries": entries,
    }
    if ai_entries:
        log["ai_entries"] = ai_entries
    log_path = track / "data" / "logs" / f"{log_date}-{session}.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    return log


def _tail(text: str, lines: int = 3) -> str:
    return " | ".join(line.strip() for line in (text or "").strip().splitlines()[-lines:])[:600]


# --------------------------------------------------------------------------- evaluate


def _allow_missing_picks(created_at: str, now_iso: str) -> bool:
    from alphasift.timeutil import parse_timestamp

    created_dt = parse_timestamp(created_at)
    now_dt = parse_timestamp(now_iso)
    if created_dt is None or now_dt is None:
        return False
    return (now_dt - created_dt).total_seconds() >= MAX_MISSING_RETRY_DAYS * 86400


def _is_window_complete(
    item: dict[str, Any],
    *,
    has_benchmark: bool,
    allow_missing: bool = False,
) -> bool:
    picks = item.get("picks")
    if not isinstance(picks, dict):
        return False
    values = list(picks.values())
    if any(p.get("status") == "pending" for p in values):
        return False
    missing_picks = [p for p in values if p.get("status") == "missing"]
    if missing_picks:
        if not allow_missing or len(missing_picks) == len(values):
            return False
    if has_benchmark:
        ok_picks = [
            p for p in values
            if p.get("status") == "ok" and p.get("return_pct") is not None
        ]
        if ok_picks and (
            item.get("benchmark_return_pct") is None
            or any(p.get("excess_return_pct") is None for p in ok_picks)
        ):
            return False
    return True


def _is_run_final(
    entry: dict[str, Any],
    *,
    has_benchmark: bool,
    allow_missing: bool = False,
) -> bool:
    windows = entry.get("windows")
    if not isinstance(windows, dict):
        return False
    return all(
        str(window) in windows
        and _is_window_complete(
            windows[str(window)],
            has_benchmark=has_benchmark,
            allow_missing=allow_missing,
        )
        for window in WINDOWS
    )


def evaluate_markets(track: Path, markets: list[str]) -> dict[str, Any]:
    """T+N evaluation of every saved run in ``markets``; other markets keep their last result.

    A run whose windows have all completed is final and is not fetched again.
    """
    import pandas as pd

    old_data_dir = os.environ.get("ALPHASIFT_DATA_DIR")
    old_tushare_date = os.environ.pop("TUSHARE_TRADE_DATE", None)
    os.environ["ALPHASIFT_DATA_DIR"] = str(track / "data")
    out_path = track / "site" / "evaluation.json"
    previous = _read_json(out_path) or {}
    runs_out: dict[str, Any] = dict(previous.get("runs", {}))
    eval_now = _now()
    try:
        from alphasift.config import Config
        from alphasift.evaluate import evaluate_saved_run
        from alphasift.markets import get_market

        config = Config.from_env()
        no_snapshot = pd.DataFrame(columns=["code", "price"])  # T+N uses closes, not live quotes
        benchmark_paths: dict[str, pd.DataFrame] = {}

        for run in load_runs(track):
            if run["market"] not in markets:
                continue
            has_benchmark = bool(get_market(run["market"]).benchmark)
            allow_missing = _allow_missing_picks(run["created_at"], eval_now)
            prior = runs_out.get(run["run_id"])
            if (
                prior
                and prior.get("final")
                and _is_run_final(prior, has_benchmark=has_benchmark, allow_missing=allow_missing)
            ):
                continue
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
                window_payload: dict[str, Any] = {
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
                benchmark_errors = [
                    str(item) for item in (result.degradation or []) if str(item).startswith("Benchmark ")
                ]
                if benchmark_errors:
                    window_payload["benchmark_errors"] = benchmark_errors
                windows[str(window)] = window_payload
            final = all(
                _is_window_complete(item, has_benchmark=has_benchmark, allow_missing=allow_missing)
                for item in windows.values()
            )
            runs_out[run["run_id"]] = {"evaluated_at": eval_now, "final": final, "windows": windows}
            print(f"evaluated {run['market']:<3} {run['strategy']:<24} {run['run_id']} final={final}", flush=True)
    finally:
        if old_data_dir is None:
            os.environ.pop("ALPHASIFT_DATA_DIR", None)
        else:
            os.environ["ALPHASIFT_DATA_DIR"] = old_data_dir
        if old_tushare_date is None:
            os.environ.pop("TUSHARE_TRADE_DATE", None)
        else:
            os.environ["TUSHARE_TRADE_DATE"] = old_tushare_date

    payload = {"evaluated_at": eval_now, "windows": WINDOWS, "runs": runs_out}
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
            "track": str(data.get("track") or ("ai" if data.get("llm_ranked") else "rules")),
            "llm_ranked": bool(data.get("llm_ranked", False)),
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
    sc = scorecard(runs, evaluation)
    tc = track_comparison(sc)
    pb = _build_pattern_board(track)
    if pb is not None:
        (site / "patterns.json").write_text(json.dumps(pb, ensure_ascii=False), encoding="utf-8")
        pb_summary: dict[str, Any] | None = {
            "latest": {
                "trade_date": pb["latest"].get("trade_date"),
                "market_regime": pb["latest"].get("market_regime"),
                "counts_by_pattern": pb["latest"].get("counts_by_pattern", {}),
            },
            "history": pb["history"],
            "has_replay": pb.get("replay") is not None,
        }
    else:
        pb_summary = None

    summary = {
        "generated_at": _now(),
        "windows": WINDOWS,
        "strategy_names": names,
        "markets": [
            {"id": m, "name": get_market(m).name, "benchmark": get_market(m).benchmark_name} for m in markets
        ],
        "sessions": _latest_logs(track),
        "scorecard": sc,
        "track_comparison": tc,
        "pattern_board": pb_summary,
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
    summary = {
        "average_return_pct": _round(statistics.fmean(returns)) if returns else None,
        "average_excess_return_pct": _round(statistics.fmean(excess)) if excess else None,
        "benchmark_return_pct": _round(item.get("benchmark_return_pct")),
        "evaluated": len(returns),
        "pending": item.get("pending", 0),
        "error": item.get("error"),
    }
    if item.get("benchmark_errors"):
        summary["benchmark_errors"] = list(item["benchmark_errors"])
    return summary


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
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for run in runs:
        groups.setdefault((run["market"], run["strategy"], run.get("track", "rules")), []).append(run)
    rows = []
    for (market, strategy, track_name), group in sorted(groups.items()):
        windows = {}
        for window in WINDOWS:
            outcomes = [o for _, o in _pick_outcomes(group, evaluation, window)]
            done = [o for o in outcomes if o["status"] == "ok" and o["return_pct"] is not None]
            matched = [o for o in done if o["excess_return_pct"] is not None]
            untradable = sum(1 for o in outcomes if o["status"] == "untradable_limit_up")
            windows[str(window)] = {
                "evaluated": len(done),
                "pending": sum(1 for o in outcomes if o["status"] == "pending"),
                "untradable": untradable,
                "untradable_share_pct": _round((untradable / len(outcomes)) * 100.0, 2) if outcomes else 0.0,
                "unavailable": sum(1 for o in outcomes if o["status"] not in {"ok", "pending", "untradable_limit_up"}),
                "average_return_pct": _mean(o["return_pct"] for o in done),
                "win_rate": _round(sum(o["return_pct"] > 0 for o in done) / len(done)) if done else None,
                "matched": len(matched),
                "matched_return_pct": _mean(o["return_pct"] for o in matched),
                "average_excess_return_pct": _mean(o["excess_return_pct"] for o in matched),
                "beat_rate": _round(sum(o["excess_return_pct"] > 0 for o in matched) / len(matched))
                if matched else None,
            }
        rows.append({"market": market, "strategy": strategy, "track": track_name, "runs": len(group),
                     "first_date": group[0]["date"], "last_date": group[-1]["date"], "windows": windows})
    return rows


def track_comparison(scorecard_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair rules and ai rows per (market, strategy) for side-by-side excess comparison."""
    paired: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for row in scorecard_rows:
        paired.setdefault((row["market"], row["strategy"]), {})[row.get("track", "rules")] = row
    comparisons: list[dict[str, Any]] = []
    for (market, strategy), by_track in sorted(paired.items()):
        if "rules" not in by_track or "ai" not in by_track:
            continue
        r_row, a_row = by_track["rules"], by_track["ai"]
        win_deltas: dict[str, Any] = {}
        for window in WINDOWS:
            w = str(window)
            rw, aw = r_row["windows"].get(w, {}), a_row["windows"].get(w, {})
            re, ae = rw.get("average_excess_return_pct"), aw.get("average_excess_return_pct")
            win_deltas[w] = {
                "rules_matched": rw.get("matched", 0),
                "ai_matched": aw.get("matched", 0),
                "rules_excess_pct": re,
                "ai_excess_pct": ae,
                "ai_minus_rules_pct": _round(ae - re) if (ae is not None and re is not None) else None,
            }
        comparisons.append({
            "market": market,
            "strategy": strategy,
            "rules_runs": r_row["runs"],
            "ai_runs": a_row["runs"],
            "windows": win_deltas,
        })
    return comparisons


def _build_pattern_board(track: Path) -> dict[str, Any] | None:
    pat_dir = track / "data" / "patterns"
    if not pat_dir.is_dir():
        return None
    files = sorted(p for p in pat_dir.glob("*.json") if p.name != "replay.json")
    if not files:
        return None
    history: list[dict[str, Any]] = []
    latest_payload: dict[str, Any] | None = None
    for path in files[-15:]:
        data = _read_json(path)
        if not isinstance(data, dict) or not data.get("trade_date"):
            continue
        latest_payload = data
        reg = data.get("market_regime") or {}
        history.append({
            "trade_date": data.get("trade_date"),
            "regime_stage": reg.get("regime_stage"),
            "regime_stage_label": reg.get("regime_stage_label"),
            "advance_ratio_pct": reg.get("advance_ratio_pct"),
            "non_st_limit_up_count": reg.get("non_st_limit_up_count"),
            "non_st_limit_down_count": reg.get("non_st_limit_down_count"),
            "max_consecutive_limit_up": reg.get("max_consecutive_limit_up"),
            "counts_by_pattern": data.get("counts_by_pattern", {}),
        })
    if latest_payload is None:
        return None
    replay = _read_json(pat_dir / "replay.json")
    replay_summary: dict[str, Any] | None = None
    if isinstance(replay, dict):
        replay_summary = {
            "generated_at": replay.get("generated_at"),
            "entry_mode": replay.get("entry_mode", "next_open"),
            "benchmark": replay.get("benchmark", "sh000300"),
            "pack_summary": replay.get("pack_summary"),
            "regime_distribution": replay.get("regime_distribution"),
            "patterns": [
                {
                    "pattern": item.get("pattern"),
                    "display_name": item.get("display_name"),
                    "family": item.get("family"),
                    "mode": item.get("mode"),
                    "untradable_count": item.get("untradable_count"),
                    "untradable_share_pct": item.get("untradable_share_pct"),
                    "horizons": item.get("horizons"),
                    "graduation": item.get("graduation"),
                    "by_regime": item.get("by_regime"),
                    "by_overhead_supply": item.get("by_overhead_supply"),
                }
                for item in (replay.get("patterns") or [])
            ],
        }
    return {
        "latest": latest_payload,
        "history": history,
        "replay": replay_summary,
    }


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
    latest: dict[tuple[str, str, str], dict] = {}
    for run in runs:  # oldest first, so the last one wins
        latest[(run["market"], run["strategy"], run.get("track", "rules"))] = run
    out: dict[str, list[dict]] = {}
    for (market, _, _), run in sorted(latest.items()):
        out.setdefault(market, []).append({k: v for k, v in run.items() if k != "path"})
    return out


def _latest_logs(track: Path) -> dict[str, Any]:
    out = {}
    for session in SESSIONS:
        logs = sorted((track / "data" / "logs").glob(f"*-{session}.json"))
        if logs:
            log = _read_json(logs[-1]) or {}
            entries = log.get("entries", [])
            skipped = sum(1 for e in entries if e.get("status") in SKIPPED_STATUSES)
            out[session] = {
                "finished_at": log.get("finished_at"),
                "ok": sum(1 for e in entries if e.get("status") == "ok"),
                "skipped": skipped,
                "total": len(entries) - skipped,
                "failures": [
                    e for e in entries
                    if e.get("status") != "ok" and e.get("status") not in SKIPPED_STATUSES
                ],
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
        track_suffix = " [AI]" if row.get("track") == "ai" else ""
        lines.append(
            f"| {row['market']} | {names.get(row['strategy'], row['strategy'])}{track_suffix} | {row['runs']} "
            f"| {w5['matched']} | {_pct(w5['average_excess_return_pct'])} | {_rate(w5['beat_rate'])} "
            f"| {w20['matched']} | {_pct(w20['average_excess_return_pct'])} | {_rate(w20['beat_rate'])} |"
        )
    lines += ["", "## Latest session", ""]
    for session, info in summary["sessions"].items():
        skipped_note = f" ({info['skipped']} skipped)" if info.get("skipped") else ""
        lines.append(
            f"- **{session}** finished {info['finished_at']}: {info['ok']}/{info['total']} strategies ok{skipped_note}"
        )
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
    parser.add_argument("command", choices=["screen", "evaluate", "build", "patterns"])
    parser.add_argument("--track", type=Path, required=True, help="checkout of the track-record branch")
    parser.add_argument("--session", choices=sorted(SESSIONS), default="asia")
    parser.add_argument("--markets", default="", help="comma-separated; defaults to the session's markets")
    parser.add_argument(
        "--ai-track", choices=["auto", "on", "off"], default="auto",
        help="whether to run optional AI track on CN after rules pass (auto skips without LLM key)",
    )
    parser.add_argument("--pack-dir", type=Path, default=None, help="optional CN DailyPack directory")
    parser.add_argument("--trade-date", default=None, help="optional trade date for patterns subcommand")
    parser.add_argument("--with-replay", action="store_true", help="also run 250-day next_open replay for patterns board")
    parser.add_argument("--replay-json", type=Path, default=None, help="existing replay JSON to attach to patterns board")
    args = parser.parse_args(argv)
    markets = [m.strip() for m in args.markets.split(",") if m.strip()] or SESSIONS[args.session]

    if args.command == "screen":
        log = run_session(
            args.session, args.track, markets=markets, ai_track=args.ai_track, pack_dir=args.pack_dir
        )
        rules_entries = [e for e in log["entries"] if e.get("track", "rules") == "rules"]
        ok = sum(1 for e in rules_entries if e["status"] == "ok")
        skipped = sum(1 for e in rules_entries if e["status"] in SKIPPED_STATUSES)
        print(f"{ok}/{len(rules_entries) - skipped} strategies saved a run ({skipped} skipped)")
        if ok > 0 or (rules_entries and skipped == len(rules_entries)):
            return 0
        return 1
    if args.command == "evaluate":
        evaluate_markets(args.track, markets)
        return 0
    if args.command == "patterns":
        record_cn_patterns(
            args.track,
            pack_dir=args.pack_dir,
            trade_date=args.trade_date,
            include_replay=args.with_replay,
            replay_json_path=args.replay_json,
        )
        return 0
    build_site(args.track)
    return 0


if __name__ == "__main__":
    sys.exit(main())
