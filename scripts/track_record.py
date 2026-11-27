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
import hashlib
import inspect
import json
import os
import statistics
import sys
import time
from collections.abc import Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as _xml_escape
from zoneinfo import ZoneInfo

# Ensure direct script execution (`python scripts/track_record.py`) can import
# the local `alphasift` package when the repo root is not on sys.path.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from alphasift.jsonutil import atomic_write_strict_json, atomic_write_text, finite_float, safe_int  # noqa: E402

SESSIONS = {"asia": ["cn", "hk", "jp", "kr", "tw", "in"], "us": ["us"]}
WINDOWS = [5, 10, 20]
SNAPSHOT_TIMEOUT_SEC = 5 * 60
SCREEN_TIMEOUT_SEC = 20 * 60
AI_SCREEN_TIMEOUT_SEC = max(60, safe_int(os.getenv("ALPHASIFT_AI_SCREEN_TIMEOUT_SEC"), default=210))
AI_TRACK_MARKETS = frozenset({"cn"})
MAX_MISSING_RETRY_DAYS = 90
SKIPPED_STATUSES = frozenset({"skipped_holiday", "skipped_duplicate"})
RECENT_DAYS_IN_SUMMARY = 30
NEXT_OPEN_SWITCH_DATE = os.getenv("ALPHASIFT_NEXT_OPEN_SWITCH_DATE", "2026-11-21")
MIN_PAIRED_AI_DAYS = 10
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
    return bool(config.has_usable_llm_config())


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
    expected_trade_date: str | None = None,
    require_exact_date: bool = False,
    allow_stale_pack: bool = False,
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
    target_expected = str(expected_trade_date or trade_date or "").strip() or None
    pack_date = daily_pack.trade_date
    pack_is_stale = bool(target_expected and pack_date < target_expected)

    if require_exact_date and trade_date and trade_date not in dates_set:
        return None
    if pack_is_stale and not allow_stale_pack:
        return None

    target_date = trade_date if (trade_date and trade_date in dates_set) else None
    scan = scan_patterns(daily_pack, trade_date=target_date, include_experimental=True)
    payload = scan.to_dict()
    payload["expected_trade_date"] = target_expected or scan.trade_date
    payload["pack_is_stale"] = pack_is_stale
    if pack_is_stale:
        payload["stale_reason"] = f"数据包截止 {pack_date}，落后目标交易日 {target_expected}（降级展示）"

    sig_codes: list[str] = []
    cap = max(1, safe_int(max_signals_per_pattern, default=20))
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
    atomic_write_strict_json(out_path, payload, indent=2, trailing_newline=True)

    if replay_json_path is not None and Path(replay_json_path).is_file():
        replay_data = _read_json(Path(replay_json_path))
        if isinstance(replay_data, dict):
            atomic_write_strict_json(
                out_dir / "replay.json", replay_data, indent=2, trailing_newline=True
            )
    elif include_replay:
        from alphasift.pattern_replay import load_cn_benchmark, replay_patterns

        bench = load_cn_benchmark(lookback_days=max(len(daily_pack.dates) + 40, 320))
        replay_data = replay_patterns(daily_pack, benchmark_df=bench, cost_bps=25.0)
        atomic_write_strict_json(
            out_dir / "replay.json", replay_data, indent=2, trailing_newline=True
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
    effective_dates: dict[str, str] = {}
    try:
        from alphasift.config import Config
        from alphasift.pipeline import screen
        from alphasift.source_guard import call_with_timeout
        from alphasift.store import save_screen_result

        # Track record is an immutable daily ledger of live picks: never fall back
        # to stale last-good snapshot caches from earlier trading days.
        config = dataclasses.replace(Config.from_env(), fallback_snapshot_path=None)
        cn_pack = None
        if pack_dir is not None and (Path(pack_dir).expanduser() / "manifest.json").is_file() and "cn" in target_markets:
            try:
                from alphasift.pack import load_pack

                cn_pack = load_pack(Path(pack_dir).expanduser())
            except Exception:  # noqa: BLE001
                cn_pack = None
        raw_ctx_env = os.getenv("LLM_CANDIDATE_CONTEXT_ENABLED")
        cn_ai_collect_ctx = (
            False
            if (raw_ctx_env is not None and raw_ctx_env.strip().lower() in {"0", "false", "no", "off"})
            else True
        )
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
                effective_dates[market] = expected_date
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
            effective_dates[market] = effective_date
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
                        daily_pack=cn_pack if market == "cn" else None,
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
                        ai_kwargs: dict[str, Any] = {
                            "market": market,
                            "use_llm": True,
                            "config": config,
                            "snapshot_df": market_snapshot,
                            "allow_snapshot_refetch": False,
                            "daily_pack": cn_pack if market == "cn" else None,
                        }
                        if market == "cn":
                            ai_kwargs["collect_llm_candidate_context"] = cn_ai_collect_ctx
                            ai_kwargs["candidate_context_max_candidates"] = max(
                                12,
                                config.llm_candidate_context_max_candidates,
                            )
                            ai_kwargs["candidate_context_providers"] = [
                                "announcement",
                                "news",
                                "fund_flow",
                            ]
                        ai_result = call_with_timeout(
                            screen,
                            strategy,
                            **ai_kwargs,
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
                        expected_trade_date=effective_date,
                        require_exact_date=True,
                        allow_stale_pack=False,
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
    if effective_dates:
        log["effective_dates"] = effective_dates
    if ai_entries:
        log["ai_entries"] = ai_entries
    log_path = track / "data" / "logs" / f"{log_date}-{session}.json"
    atomic_write_strict_json(log_path, log, indent=2)
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


def _prior_matches_mode(entry: dict[str, Any], target_mode: str) -> bool:
    windows = entry.get("windows")
    if not isinstance(windows, dict):
        return False
    return all(
        ((windows.get(str(w)) or {}).get("entry_mode") or "close") == target_mode
        for w in WINDOWS
    )


def _load_cn_pack_price_paths(
    pack_dir: Path | None,
    config: Any,
    codes: Sequence[str],
) -> dict[str, Any]:
    """Load CN forward-adjusted OHLCV DataFrames (plus raw quotes) from DailyPack."""
    if not codes:
        return {}
    from alphasift.pack import load_pack, pack_dir as resolve_pack_dir, pack_price_paths

    directory = Path(pack_dir).expanduser() if pack_dir is not None else resolve_pack_dir(config)
    if not (directory / "manifest.json").is_file():
        return {}
    try:
        daily_pack = load_pack(directory)
        return pack_price_paths(daily_pack, codes=codes, adjusted=True, include_raw=True)
    except (OSError, ValueError):
        return {}


def evaluate_markets(
    track: Path,
    markets: list[str],
    *,
    pack_dir: Path | None = None,
    entry_mode: str = "auto",
    next_open_from: str | None = None,
) -> dict[str, Any]:
    """T+N evaluation of saved runs in ``markets``.

    ``entry_mode='auto'`` preserves historical ``close`` runs prior to
    ``next_open_from`` (default ``NEXT_OPEN_SWITCH_DATE``) and switches runs on
    or after that date to ``next_open`` with CN exchange limit-up/limit-down
    tradability checks using unadjusted raw prices when available from DailyPack.
    """
    import pandas as pd

    if entry_mode not in ("auto", "close", "next_open"):
        raise ValueError("entry_mode must be 'auto', 'close', or 'next_open'")
    switch_date = str(next_open_from or NEXT_OPEN_SWITCH_DATE).strip()

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

        sig_params = inspect.signature(evaluate_saved_run).parameters
        has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig_params.values())
        supports_entry_mode = has_var_kw or ("entry_mode" in sig_params)
        supports_price_paths = has_var_kw or ("price_paths" in sig_params)
        if entry_mode == "next_open" and not supports_entry_mode:
            raise ValueError("evaluate_saved_run does not support entry_mode=next_open in this build")

        def _target_mode_for_run(run_item: dict[str, Any]) -> str:
            if entry_mode == "auto":
                if not supports_entry_mode:
                    return "close"
                return "next_open" if run_item["date"] >= switch_date else "close"
            return entry_mode

        config = Config.from_env()
        no_snapshot = pd.DataFrame(columns=["code", "price"])  # T+N uses closes/pack, not live quotes
        benchmark_paths: dict[str, pd.DataFrame] = {}
        all_runs = load_runs(track)

        cn_price_paths: dict[str, pd.DataFrame] = {}
        if "cn" in markets and supports_price_paths:
            cn_codes: list[str] = []
            cn_has_benchmark = bool(get_market("cn").benchmark)
            for run in all_runs:
                if run["market"] != "cn":
                    continue
                prior = runs_out.get(run["run_id"])
                allow_missing = _allow_missing_picks(run["created_at"], eval_now)
                run_mode = _target_mode_for_run(run)
                if (
                    prior
                    and prior.get("final")
                    and _is_run_final(prior, has_benchmark=cn_has_benchmark, allow_missing=allow_missing)
                    and _prior_matches_mode(prior, run_mode)
                ):
                    continue
                cn_codes.extend(str(p.get("code", "")) for p in run.get("picks", []) if p.get("code"))
            cn_price_paths = _load_cn_pack_price_paths(pack_dir, config, cn_codes)

        for run in all_runs:
            if run["market"] not in markets:
                continue
            has_benchmark = bool(get_market(run["market"]).benchmark)
            allow_missing = _allow_missing_picks(run["created_at"], eval_now)
            run_mode = _target_mode_for_run(run)
            prior = runs_out.get(run["run_id"])
            if (
                prior
                and prior.get("final")
                and _is_run_final(prior, has_benchmark=has_benchmark, allow_missing=allow_missing)
                and _prior_matches_mode(prior, run_mode)
            ):
                continue
            windows: dict[str, Any] = {}
            for window in WINDOWS:
                eval_kwargs: dict[str, Any] = {
                    "config": config,
                    "current_snapshot": no_snapshot,
                    "with_price_path": True,
                    "horizon_days": window,
                    "benchmark_paths": benchmark_paths,
                }
                if run["market"] == "cn" and cn_price_paths and supports_price_paths:
                    eval_kwargs["price_paths"] = cn_price_paths
                if supports_entry_mode and run_mode != "close":
                    eval_kwargs["entry_mode"] = run_mode
                try:
                    result = evaluate_saved_run(run["path"], **eval_kwargs)
                except Exception as exc:  # one broken run must not stop the record
                    windows[str(window)] = {"error": str(exc)[:300]}
                    continue

                effective_mode = getattr(result, "entry_mode", run_mode) or run_mode
                picks_out: dict[str, Any] = {}
                for pick in result.picks:
                    pick_entry: dict[str, Any] = {
                        "status": pick.status,
                        "return_pct": _round(pick.return_pct),
                        "excess_return_pct": _round(pick.excess_return_pct),
                    }
                    if getattr(pick, "entry_open", None) is not None:
                        pick_entry["entry_open"] = _round(pick.entry_open)
                    if getattr(pick, "entry_date", None):
                        pick_entry["entry_date"] = pick.entry_date
                    if getattr(pick, "exit_date", None):
                        pick_entry["exit_date"] = pick.exit_date
                    if getattr(pick, "tradability_flags", None):
                        pick_entry["tradability_flags"] = list(pick.tradability_flags)
                    picks_out[pick.code] = pick_entry

                window_payload: dict[str, Any] = {
                    "entry_mode": effective_mode,
                    "benchmark": result.benchmark,
                    "benchmark_return_pct": result.benchmark_return_pct,
                    "pending": result.pending_count,
                    "picks": picks_out,
                }
                if effective_mode == "next_open":
                    window_payload["untradable"] = getattr(result, "untradable_count", 0)
                    window_payload["untradable_share_pct"] = _round(
                        getattr(result, "untradable_share_pct", None), 2
                    )
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
            print(
                f"evaluated {run['market']:<3} {run['strategy']:<24} {run['run_id']} mode={run_mode} final={final}",
                flush=True,
            )
    finally:
        if old_data_dir is None:
            os.environ.pop("ALPHASIFT_DATA_DIR", None)
        else:
            os.environ["ALPHASIFT_DATA_DIR"] = old_data_dir
        if old_tushare_date is None:
            os.environ.pop("TUSHARE_TRADE_DATE", None)
        else:
            os.environ["TUSHARE_TRADE_DATE"] = old_tushare_date

    payload = {
        "evaluated_at": eval_now,
        "entry_mode_switch_date": switch_date,
        "windows": WINDOWS,
        "runs": runs_out,
    }
    atomic_write_strict_json(out_path, payload, indent=1)
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
            "degradation_notes": [str(item)[:140] for item in (data.get("degradation") or [])[:4] if str(item).strip()],
            "picks": [
                {
                    **{
                        key: _round(pick.get(key)) if isinstance(pick.get(key), float) else pick.get(key)
                        for key in PICK_FIELDS
                    },
                    **({"ranking_reason": str(pick["ranking_reason"])} if pick.get("ranking_reason") else {}),
                }
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


def _load_latest_report_summary(path: Path) -> dict[str, Any] | None:
    data = _read_json(path)
    if not isinstance(data, dict) or data.get("object") != "DailyReport":
        return None
    ann = data.get("announcement_risks") or {}
    flagged = [
        {
            "code": item.get("code"),
            "name": item.get("name"),
            "negative_event_flags": list(item.get("negative_event_flags") or []),
            "announcement_summary": item.get("announcement_summary", ""),
        }
        for item in (ann.get("flagged_items") or [])
    ]
    syn = data.get("cross_strategy_synthesis") if isinstance(data.get("cross_strategy_synthesis"), dict) else {}
    compact_syn = (
        {
            "consensus_picks": list((syn.get("consensus_picks") or [])[:5]),
            "sector_concentration": list((syn.get("sector_concentration") or [])[:5]),
            "resonance_count": len(syn.get("strategy_pattern_resonance") or []),
        }
        if syn
        else None
    )
    ai_brief = data.get("ai_brief") if isinstance(data.get("ai_brief"), dict) else None
    raw_news = data.get("market_news") if isinstance(data.get("market_news"), dict) else {}
    compact_news = (
        {
            "items": [
                {
                    "title": str(it.get("title") or "")[:140],
                    "source": str(it.get("source") or ""),
                    "time": str(it.get("time") or ""),
                    "url": str(it.get("url") or ""),
                }
                for it in (raw_news.get("items") or [])[:5]
                if isinstance(it, dict) and str(it.get("title") or "").strip()
            ],
            "sources": [str(s) for s in (raw_news.get("sources") or [])[:4] if str(s).strip()],
            "candidate_news": {
                str(code): [
                    {
                        "title": str(n.get("title") or "")[:120],
                        "source": str(n.get("source") or ""),
                        "date": str(n.get("date") or ""),
                    }
                    for n in (items or [])[:2]
                    if isinstance(n, dict) and str(n.get("title") or "").strip()
                ]
                for code, items in list((raw_news.get("candidate_news") or {}).items())[:8]
            },
        }
        if (raw_news.get("items") or raw_news.get("candidate_news"))
        else None
    )
    return {
        "trade_date": data.get("trade_date"),
        "pack_trade_date": data.get("pack_trade_date"),
        "expected_trade_date": data.get("expected_trade_date"),
        "pack_is_stale": bool(data.get("pack_is_stale", False)),
        "stale_reason": data.get("stale_reason"),
        "ai_highlights": list(data.get("ai_highlights") or []),
        "cross_strategy_synthesis": compact_syn,
        "ai_brief": ai_brief,
        "market_news": compact_news,
        "announcement_risks": {
            "checked_count": max(safe_int(ann.get("checked_count"), default=0), 0),
            "flagged_count": len(flagged),
            "flagged_items": flagged,
            "errors": list(ann.get("errors") or []),
        },
        "degradation": list(data.get("degradation") or []),
    }


def build_site(track: Path) -> dict[str, Any]:
    from alphasift.markets import get_market
    from alphasift.strategy import list_strategies

    site = track / "site"
    (site / "days").mkdir(parents=True, exist_ok=True)
    runs = load_runs(track)
    eval_payload = _read_json(site / "evaluation.json") or {}
    evaluation = eval_payload.get("runs", {})
    switch_date = eval_payload.get("entry_mode_switch_date") or NEXT_OPEN_SWITCH_DATE
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
        atomic_write_strict_json(site / "days" / f"{day}.json", payload, indent=None)

    markets = sorted({run["market"] for run in runs}, key=lambda m: list(SESSIONS["asia"] + SESSIONS["us"]).index(m))
    sc = scorecard(runs, evaluation)
    tc = track_comparison(runs, evaluation)
    pb = _build_pattern_board(track)
    if pb is not None:
        atomic_write_strict_json(site / "patterns.json", pb, indent=None)
        latest_pat = pb["latest"]
        pb_summary: dict[str, Any] | None = {
            "latest": {
                "trade_date": latest_pat.get("trade_date"),
                "pack_trade_date": latest_pat.get("pack_trade_date"),
                "expected_trade_date": latest_pat.get("expected_trade_date"),
                "pack_is_stale": bool(latest_pat.get("pack_is_stale", False)),
                "stale_reason": latest_pat.get("stale_reason"),
                "market_regime": latest_pat.get("market_regime"),
                "counts_by_pattern": latest_pat.get("counts_by_pattern", {}),
            },
            "history": pb["history"],
            "has_replay": pb.get("replay") is not None,
        }
    else:
        pb_summary = None

    latest_report = _load_latest_report_summary(site / "report.json")
    report_file = site / "report.json"
    report_html_file = site / "daily_report.html"
    runs_hasher = hashlib.sha256()
    run_files = sorted(
        p for p in (track / "data" / "runs").glob("*.json")
        if p.is_file() and not p.is_symlink()
    )
    for rp in run_files:
        digest = hashlib.sha256(rp.read_bytes()).hexdigest()
        runs_hasher.update(f"{rp.name}:{digest}\n".encode("utf-8"))
    runs_sha256 = runs_hasher.hexdigest()

    integrity_files: dict[str, str] = {}
    pre_summary_candidates: list[tuple[str, Path]] = [
        ("evaluation.json", site / "evaluation.json"),
        ("patterns.json", site / "patterns.json"),
        ("report.json", report_file),
        ("daily_report.html", report_html_file),
    ]
    for dp in sorted((site / "days").glob("*.json")):
        pre_summary_candidates.append((dp.relative_to(site).as_posix(), dp))
    for rel, path in pre_summary_candidates:
        if path.is_file() and not path.is_symlink():
            integrity_files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()

    integrity = {
        "algorithm": "sha256",
        "runs_count": len(run_files),
        "runs_sha256": runs_sha256,
        "files": integrity_files,
        "manifest_path": "site/manifest.sha256",
    }
    artifacts = {
        "patterns": {
            "exists": pb is not None,
            "path": "site/patterns.json",
            "trade_date": pb["latest"].get("trade_date") if pb else None,
            "expected_trade_date": pb["latest"].get("expected_trade_date") if pb else None,
            "pack_is_stale": bool(pb["latest"].get("pack_is_stale", False)) if pb else False,
            "has_replay": bool(pb and pb.get("replay")),
            "reason": None if pb is not None else "cn_daily_pack_unavailable",
        },
        "report": {
            "exists": report_file.is_file(),
            "path": "site/report.json",
            "trade_date": latest_report.get("trade_date") if latest_report else None,
            "expected_trade_date": latest_report.get("expected_trade_date") if latest_report else None,
            "pack_is_stale": bool(latest_report.get("pack_is_stale", False)) if latest_report else False,
            "reason": None if report_file.is_file() else "cn_daily_pack_unavailable",
        },
        "daily_report_html": {
            "exists": report_html_file.is_file(),
            "path": "site/daily_report.html",
            "trade_date": latest_report.get("trade_date") if latest_report else None,
            "expected_trade_date": latest_report.get("expected_trade_date") if latest_report else None,
            "pack_is_stale": bool(latest_report.get("pack_is_stale", False)) if latest_report else False,
            "reason": None if report_html_file.is_file() else "cn_daily_pack_unavailable",
        },
    }
    summary = {
        "generated_at": _now(),
        "windows": WINDOWS,
        "entry_mode_switch_date": switch_date,
        "strategy_names": names,
        "markets": [
            {"id": m, "name": get_market(m).name, "benchmark": get_market(m).benchmark_name} for m in markets
        ],
        "sessions": _latest_logs(track),
        "scorecard": sc,
        "track_comparison": tc,
        "pattern_board": pb_summary,
        "latest_report": latest_report,
        "artifacts": artifacts,
        "integrity": integrity,
        "trend": trend(runs, evaluation, track_filter="rules"),
        "trend_ai": trend(runs, evaluation, track_filter="ai"),
        "latest": _latest_runs(runs),
        "days": [{"date": day, "runs": len(by_day[day])} for day in sorted(by_day, reverse=True)],
        "run_count": len(runs),
    }
    atomic_write_strict_json(site / "summary.json", summary, indent=None)
    atomic_write_text(site / "feed.xml", render_atom_feed(summary))
    atomic_write_text(track / "robots.txt", render_robots_txt())
    atomic_write_text(track / "sitemap.xml", render_sitemap_xml(summary))

    # Emit standard `sha256sum -c` manifest relative to `site/` covering all published site files.
    manifest_path = site / "manifest.sha256"
    manifest_entries: list[str] = []
    for fpath in sorted(p for p in site.rglob("*") if p.is_file() and not p.is_symlink() and p != manifest_path):
        rel = fpath.relative_to(site).as_posix()
        digest = integrity_files.get(rel) or hashlib.sha256(fpath.read_bytes()).hexdigest()
        manifest_entries.append(f"{digest}  {rel}")
    atomic_write_text(manifest_path, "\n".join(manifest_entries) + ("\n" if manifest_entries else ""))

    atomic_write_text(track / "README.md", render_readme(summary))
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
    matched return − benchmark = excess. Pre-switchover close-mode windows report
    ``untradable_share_pct = None`` (``untradable_assessed = False``) so historical
    close runs are clearly marked unassessed rather than 0.0%.
    """
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for run in runs:
        groups.setdefault((run["market"], run["strategy"], run.get("track", "rules")), []).append(run)
    rows = []
    for (market, strategy, track_name), group in sorted(groups.items()):
        windows = {}
        modes_seen: set[str] = set()
        for window in WINDOWS:
            tagged: list[tuple[dict[str, Any], bool]] = []
            for run in group:
                item = ((evaluation.get(run["run_id"]) or {}).get("windows") or {}).get(str(window)) or {}
                picks = item.get("picks") or {}
                if not picks:
                    continue
                mode = str(item.get("entry_mode") or "close")
                modes_seen.add(mode)
                window_assessed = (mode == "next_open") or any(
                    o.get("status") == "untradable_limit_up" or o.get("entry_mode") == "next_open"
                    for o in picks.values()
                )
                for outcome in picks.values():
                    tagged.append((outcome, window_assessed))

            outcomes = [o for o, _ in tagged]
            done = [o for o in outcomes if o["status"] == "ok" and o["return_pct"] is not None]
            matched = [o for o in done if o["excess_return_pct"] is not None]
            assessed_non_pending = [o for o, is_ok in tagged if is_ok and o["status"] != "pending"]
            untradable_cnt = sum(1 for o in outcomes if o["status"] == "untradable_limit_up")
            if assessed_non_pending:
                untradable_val: int | None = untradable_cnt
                untradable_share: float | None = _round((untradable_cnt / len(assessed_non_pending)) * 100.0, 2)
                untradable_assessed = True
            else:
                untradable_val = None
                untradable_share = None
                untradable_assessed = False

            windows[str(window)] = {
                "evaluated": len(done),
                "pending": sum(1 for o in outcomes if o["status"] == "pending"),
                "untradable": untradable_val,
                "untradable_share_pct": untradable_share,
                "untradable_assessed": untradable_assessed,
                "unavailable": sum(1 for o in outcomes if o["status"] not in {"ok", "pending", "untradable_limit_up"}),
                "average_return_pct": _mean(o["return_pct"] for o in done),
                "win_rate": _round(sum(o["return_pct"] > 0 for o in done) / len(done)) if done else None,
                "matched": len(matched),
                "matched_return_pct": _mean(o["return_pct"] for o in matched),
                "average_excess_return_pct": _mean(o["excess_return_pct"] for o in matched),
                "beat_rate": _round(sum(o["excess_return_pct"] > 0 for o in matched) / len(matched))
                if matched else None,
            }
        rows.append({
            "market": market,
            "strategy": strategy,
            "track": track_name,
            "runs": len(group),
            "first_date": group[0]["date"],
            "last_date": group[-1]["date"],
            "entry_modes": sorted(modes_seen) or ["close"],
            "windows": windows,
        })
    return rows


def _window_pick_details(
    run_item: dict[str, Any],
    evaluation: dict[str, Any],
    window: int,
) -> dict[str, dict[str, Any]]:
    win = ((evaluation.get(run_item["run_id"]) or {}).get("windows") or {}).get(str(window)) or {}
    picks = win.get("picks") or {}
    names = {str(p.get("code")): str(p.get("name") or "") for p in run_item.get("picks", []) if p.get("code")}
    details: dict[str, dict[str, Any]] = {}
    for code, out in picks.items():
        ex_val = finite_float(out.get("excess_return_pct"))
        if out.get("status") == "ok" and ex_val is not None:
            sc = str(code)
            details[sc] = {
                "date": str(run_item.get("date") or ""),
                "code": sc,
                "name": names.get(sc, ""),
                "return_pct": _round(finite_float(out.get("return_pct")), 2),
                "excess_return_pct": _round(ex_val, 2),
            }
    return details


def _window_day_excess_stats(
    run_item: dict[str, Any],
    evaluation: dict[str, Any],
    window: int,
) -> tuple[float | None, dict[str, float]]:
    win = ((evaluation.get(run_item["run_id"]) or {}).get("windows") or {}).get(str(window)) or {}
    picks = win.get("picks") or {}
    by_code: dict[str, float] = {}
    for code, out in picks.items():
        ex_val = finite_float(out.get("excess_return_pct"))
        if out.get("status") == "ok" and ex_val is not None:
            by_code[str(code)] = ex_val
    if not by_code:
        return None, {}
    return float(statistics.fmean(by_code.values())), by_code


def track_comparison(
    runs: list[dict],
    evaluation: dict,
    *,
    min_paired_days: int = MIN_PAIRED_AI_DAYS,
) -> list[dict[str, Any]]:
    """Compare rules vs AI strictly over identical signal dates with attribution & missing rate."""
    by_strat: dict[tuple[str, str], dict[str, dict[str, dict]]] = {}
    for run in runs:
        tr = run.get("track", "rules")
        if tr not in {"rules", "ai"}:
            continue
        bucket = by_strat.setdefault((run["market"], run["strategy"]), {"rules": {}, "ai": {}})
        # Keep the latest run if multiple runs exist on the same signal date.
        bucket[tr][run["date"]] = run

    comparisons: list[dict[str, Any]] = []
    for (market, strategy), tracks in sorted(by_strat.items()):
        rules_by_date, ai_by_date = tracks["rules"], tracks["ai"]
        if not rules_by_date or not ai_by_date:
            continue
        common_dates_all = sorted(set(rules_by_date) & set(ai_by_date))
        first_ai_date = min(ai_by_date)
        eligible_rules_dates = sorted(d for d in rules_by_date if d >= first_ai_date)
        ai_missing_days = sum(1 for d in eligible_rules_dates if d not in ai_by_date)
        ai_missing_rate_pct = (
            round((ai_missing_days / len(eligible_rules_dates)) * 100.0, 1)
            if eligible_rules_dates
            else 0.0
        )

        overlaps: list[float] = []
        for d in common_dates_all:
            r_codes = {str(p.get("code")) for p in rules_by_date[d].get("picks", []) if p.get("code")}
            a_codes = {str(p.get("code")) for p in ai_by_date[d].get("picks", []) if p.get("code")}
            union_cnt = len(r_codes | a_codes)
            if union_cnt > 0:
                overlaps.append(len(r_codes & a_codes) / union_cnt * 100.0)
        avg_overlap_pct = _round(statistics.fmean(overlaps), 1) if overlaps else None

        win_deltas: dict[str, Any] = {}
        for window in WINDOWS:
            rules_day_vals: list[float] = []
            ai_day_vals: list[float] = []
            deltas: list[float] = []
            ai_win_days = 0
            rules_matched = 0
            ai_matched = 0
            ai_unique_vals: list[float] = []
            rules_dropped_vals: list[float] = []
            ai_unique_items: list[dict[str, Any]] = []
            rules_dropped_items: list[dict[str, Any]] = []

            for d in common_dates_all:
                r_mean, r_map = _window_day_excess_stats(rules_by_date[d], evaluation, window)
                a_mean, a_map = _window_day_excess_stats(ai_by_date[d], evaluation, window)
                if r_mean is None or a_mean is None:
                    continue
                r_details = _window_pick_details(rules_by_date[d], evaluation, window)
                a_details = _window_pick_details(ai_by_date[d], evaluation, window)
                rules_day_vals.append(r_mean)
                ai_day_vals.append(a_mean)
                delta = a_mean - r_mean
                deltas.append(delta)
                if delta > 0:
                    ai_win_days += 1
                rules_matched += len(r_map)
                ai_matched += len(a_map)

                r_set = set(r_map)
                a_set = set(a_map)
                for c in a_set - r_set:
                    ai_unique_vals.append(a_map[c])
                    if c in a_details:
                        ai_unique_items.append(a_details[c])
                for c in r_set - a_set:
                    rules_dropped_vals.append(r_map[c])
                    if c in r_details:
                        rules_dropped_items.append(r_details[c])

            paired_days = len(deltas)
            min_days = max(safe_int(min_paired_days, default=MIN_PAIRED_AI_DAYS), 1)
            sample_sufficient = paired_days >= min_days
            re = _round(statistics.fmean(rules_day_vals)) if rules_day_vals else None
            ae = _round(statistics.fmean(ai_day_vals)) if ai_day_vals else None
            best_ai_adds = sorted(
                (
                    item for item in ai_unique_items
                    if (v := finite_float(item.get("excess_return_pct"))) is not None and v > 0
                ),
                key=lambda x: (-(finite_float(x.get("excess_return_pct")) or 0.0), x["date"], x["code"]),
            )[:3]
            worst_ai_adds = sorted(
                (
                    item for item in ai_unique_items
                    if (v := finite_float(item.get("excess_return_pct"))) is not None and v < 0
                ),
                key=lambda x: (finite_float(x.get("excess_return_pct")) or 0.0, x["date"], x["code"]),
            )[:2]
            best_ai_avoids = sorted(
                (
                    item for item in rules_dropped_items
                    if (v := finite_float(item.get("excess_return_pct"))) is not None and v < 0
                ),
                key=lambda x: (finite_float(x.get("excess_return_pct")) or 0.0, x["date"], x["code"]),
            )[:3]
            missed_by_ai = sorted(
                (
                    item for item in rules_dropped_items
                    if (v := finite_float(item.get("excess_return_pct"))) is not None and v > 0
                ),
                key=lambda x: (-(finite_float(x.get("excess_return_pct")) or 0.0), x["date"], x["code"]),
            )[:2]
            win_deltas[str(window)] = {
                "paired_days": paired_days,
                "min_paired_days": min_days,
                "sample_sufficient": sample_sufficient,
                "rules_matched": rules_matched,
                "ai_matched": ai_matched,
                "rules_excess_pct": re,
                "ai_excess_pct": ae,
                "ai_minus_rules_pct": _round(statistics.fmean(deltas)) if sample_sufficient else None,
                "delta_hidden_reason": None if sample_sufficient else f"同日配对 {paired_days} < {min_days} 天",
                "ai_win_days": ai_win_days,
                "ai_win_day_rate": _round(ai_win_days / paired_days, 3) if paired_days else None,
                "ai_unique_count": len(ai_unique_vals),
                "ai_unique_excess_pct": _round(statistics.fmean(ai_unique_vals)) if ai_unique_vals else None,
                "rules_dropped_count": len(rules_dropped_vals),
                "rules_dropped_excess_pct": _round(statistics.fmean(rules_dropped_vals)) if rules_dropped_vals else None,
                "ai_case_studies": {
                    "best_ai_adds": best_ai_adds,
                    "worst_ai_adds": worst_ai_adds,
                    "best_ai_avoids": best_ai_avoids,
                    "missed_by_ai": missed_by_ai,
                },
            }

        comparisons.append({
            "market": market,
            "strategy": strategy,
            "rules_runs": len(rules_by_date),
            "ai_runs": len(ai_by_date),
            "common_days": len(common_dates_all),
            "first_ai_date": first_ai_date,
            "ai_missing_days": ai_missing_days,
            "ai_missing_rate_pct": ai_missing_rate_pct,
            "avg_pick_overlap_pct": avg_overlap_pct,
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
            "cost_bps": finite_float(replay.get("cost_bps")) or 0.0,
            "graduation_rule": replay.get("graduation_rule"),
            "pack_summary": replay.get("pack_summary"),
            "regime_distribution": replay.get("regime_distribution"),
            "universe_baseline": replay.get("universe_baseline"),
            "regime_filter": replay.get("regime_filter"),
            "overhead_filter": replay.get("overhead_filter"),
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
                    "stability": item.get("stability"),
                    "multiple_testing": item.get("multiple_testing"),
                    "by_regime": item.get("by_regime"),
                    "by_overhead_supply": item.get("by_overhead_supply"),
                    "walk_forward_regime_audit": item.get("walk_forward_regime_audit"),
                }
                for item in (replay.get("patterns") or [])
            ],
        }
    return {
        "latest": latest_payload,
        "history": history,
        "replay": replay_summary,
    }


def trend(runs: list[dict], evaluation: dict, *, track_filter: str = "rules") -> dict[str, Any]:
    """Expanding mean excess return by entry date for a single track (rules vs ai)."""
    out: dict[str, Any] = {}
    for window in WINDOWS:
        sums: dict[tuple[str, str], list[float]] = {}
        for run, outcome in _pick_outcomes(runs, evaluation, window):
            if (run.get("track") or "rules") != track_filter:
                continue
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
    switch_d = summary.get("entry_mode_switch_date") or NEXT_OPEN_SWITCH_DATE
    lines = [
        "# AlphaSift track record",
        "",
        "Every trading day after the close, a GitHub Action runs each built-in strategy with "
        "`--no-llm --save-run` and commits the saved run here. Picks are never edited afterwards; "
        "the git history is the timestamped record. Each pick is then measured at T+5 / T+10 / T+20 "
        "trading days against its market benchmark.",
        "",
        "**Dashboard:** https://alphasift.zhulinsen.tech/ · Code: "
        "[ZhuLinsen/alphasift](https://github.com/ZhuLinsen/alphasift) · "
        f"Updated {summary['generated_at']} · {summary['run_count']} saved runs",
        "",
        f"> For research only, not investment advice. From {switch_d}, entry uses `next_open` "
        "(explicitly tracking one-price limit-up untradable blocks); legacy pre-switch runs used signal-day `close`. "
        "Returns deduct round-trip costs, ignore dividends, and small samples are noisy.",
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


def _atom_escape_attr(value: str) -> str:
    return _xml_escape(value, {'"': "&quot;"})


def _resolve_dashboard_url(dashboard_url: str | None = None) -> str:
    base = (
        str(dashboard_url or os.getenv("ALPHASIFT_DASHBOARD_URL") or "https://alphasift.zhulinsen.tech/").strip()
        or "https://alphasift.zhulinsen.tech/"
    )
    if not base.endswith("/"):
        base += "/"
    return base


def render_robots_txt(*, dashboard_url: str | None = None) -> str:
    """Render fork-safe robots.txt pointing crawlers to the live sitemap."""
    base = _resolve_dashboard_url(dashboard_url)
    return f"User-agent: *\nAllow: /\n\nSitemap: {base}sitemap.xml\n"


def render_sitemap_xml(summary: dict[str, Any], *, dashboard_url: str | None = None) -> str:
    """Render a minimal sitemap.xml covering the live dashboard, printable report, and Atom feed."""
    base = _resolve_dashboard_url(dashboard_url)
    days = summary.get("days") or []
    latest_day = str(days[0].get("date") or "").strip() if days and isinstance(days[0], dict) else ""
    fallback_date = latest_day or str(summary.get("generated_at") or _now())[:10]

    urls: list[tuple[str, str, str, str]] = [
        (base, fallback_date, "daily", "1.0"),
    ]
    report_html_art = ((summary.get("artifacts") or {}).get("daily_report_html") or {})
    if report_html_art.get("exists"):
        rep_date = str(report_html_art.get("trade_date") or "").strip() or fallback_date
        urls.append((f"{base}site/daily_report.html", rep_date, "daily", "0.8"))
    urls.append((f"{base}site/feed.xml", fallback_date, "daily", "0.6"))

    url_blocks = [
        "\n".join([
            "  <url>",
            f"    <loc>{_xml_escape(loc)}</loc>",
            f"    <lastmod>{_xml_escape(lastmod)}</lastmod>",
            f"    <changefreq>{changefreq}</changefreq>",
            f"    <priority>{priority}</priority>",
            "  </url>",
        ])
        for loc, lastmod, changefreq, priority in urls
    ]
    return "\n".join([
        '<?xml version="1.0" encoding="utf-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        *url_blocks,
        "</urlset>",
        "",
    ])


def render_atom_feed(
    summary: dict[str, Any],
    *,
    dashboard_url: str | None = None,
    max_entries: int = 14,
) -> str:
    """Render an Atom 1.0 RSS feed (zero external dependencies) for static Pages subscriptions."""
    base = _resolve_dashboard_url(dashboard_url)
    feed_url = f"{base}site/feed.xml"
    report_url = f"{base}site/daily_report.html"
    updated = str(summary.get("generated_at") or _now())

    sc = summary.get("scorecard") or []
    t5_leaders = [
        r
        for r in sc
        if finite_float(((r.get("windows") or {}).get("5") or {}).get("average_excess_return_pct")) is not None
    ]
    t5_leaders.sort(
        key=lambda r: finite_float(((r.get("windows") or {}).get("5") or {}).get("average_excess_return_pct")) or 0.0,
        reverse=True,
    )
    leader_line = ""
    if t5_leaders:
        top = t5_leaders[0]
        w5 = top["windows"]["5"]
        s_name = (summary.get("strategy_names") or {}).get(top.get("strategy"), top.get("strategy"))
        ex = finite_float(w5.get("average_excess_return_pct")) or 0.0
        beat = finite_float(w5.get("beat_rate"))
        beat_txt = f", beat {round(beat * 100)}%" if beat is not None else ""
        ev_cnt = max(safe_int(w5.get("evaluated"), default=0), 0)
        leader_line = (
            f"T+5 leader ({top.get('market', '').upper()}): "
            f"{s_name} ({ex:+.2f}% excess, n={ev_cnt}{beat_txt})."
        )

    latest_rep = summary.get("latest_report") or {}
    brief_headline = str(((latest_rep.get("ai_brief") or {}).get("headline") or "")).strip()
    rep_date = str(latest_rep.get("trade_date") or "").strip()

    days = (summary.get("days") or [])[: max(1, safe_int(max_entries, default=14))]
    entries_xml: list[str] = []
    latest_by_mkt = summary.get("latest") or {}
    for idx, day_info in enumerate(days):
        day = str(day_info.get("date") or "").strip()
        if not day:
            continue
        run_cnt = max(safe_int(day_info.get("runs"), default=0), 0)
        entry_updated = updated if idx == 0 else f"{day}T18:30:00+08:00"
        title_bits = [f"AlphaSift · {day}", f"{run_cnt} runs"]
        summary_bits = [f"{run_cnt} strategy runs recorded on {day}."]
        if idx == 0 and leader_line:
            summary_bits.append(leader_line)
        if rep_date == day and brief_headline:
            summary_bits.append(f"CN brief: {brief_headline}")
        mkt_highlights: list[str] = []
        if idx == 0 and isinstance(latest_by_mkt, dict):
            for mkt, m_runs in latest_by_mkt.items():
                if not m_runs:
                    continue
                first_run = m_runs[0]
                if first_run.get("date") == day:
                    picks = ", ".join(
                        f"{p.get('code')} {p.get('name')}"
                        for p in (first_run.get("picks") or [])[:3]
                    )
                    if picks:
                        s_lbl = (summary.get("strategy_names") or {}).get(
                            first_run.get("strategy"),
                            first_run.get("strategy"),
                        )
                        mkt_highlights.append(f"<li><b>{_xml_escape(str(mkt).upper())}</b> ({_xml_escape(str(s_lbl))}): {_xml_escape(picks)}</li>")

        entry_summary = " ".join(summary_bits)
        content_html = f"<p>{_xml_escape(entry_summary)}</p>"
        if mkt_highlights:
            content_html += f"<ul>{''.join(mkt_highlights)}</ul>"
        content_html += (
            f'<p><a href="{_atom_escape_attr(base)}">Live Dashboard</a> · '
            f'<a href="{_atom_escape_attr(report_url)}">CN Daily Report</a></p>'
        )
        entries_xml.append(
            "\n".join([
                "  <entry>",
                f"    <id>{_xml_escape(f'{base}#day-{day}')}</id>",
                f"    <title>{_xml_escape(' · '.join(title_bits))}</title>",
                f'    <link href="{_atom_escape_attr(base)}" rel="alternate" type="text/html"/>',
                f"    <updated>{_xml_escape(entry_updated)}</updated>",
                f"    <summary>{_xml_escape(entry_summary)}</summary>",
                f'    <content type="html">{_xml_escape(content_html)}</content>',
                "  </entry>",
            ])
        )

    return "\n".join([
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        "  <title>AlphaSift · Quantitative Discovery &amp; Track Record</title>",
        "  <subtitle>Multi-market YAML screening, empirical pattern radar, and T+5/T+10/T+20 audited excess returns.</subtitle>",
        f"  <id>{_xml_escape(base)}</id>",
        f'  <link href="{_atom_escape_attr(base)}" rel="alternate" type="text/html"/>',
        f'  <link href="{_atom_escape_attr(feed_url)}" rel="self" type="application/atom+xml"/>',
        f"  <updated>{_xml_escape(updated)}</updated>",
        "  <author><name>AlphaSift</name></author>",
        *entries_xml,
        "</feed>",
        "",
    ])


# --------------------------------------------------------------------------- helpers


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _round(value: Any, digits: int = 4) -> Any:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, float):
        return round(value, digits) if finite_float(value) is not None else None
    return value


def _mean(values) -> float | None:
    clean = [v for raw in values if (v := finite_float(raw)) is not None]
    return _round(statistics.fmean(clean)) if clean else None


def _pct(value: float | None) -> str:
    num = finite_float(value)
    return "–" if num is None else f"{num:+.2f}%"


def _rate(value: float | None) -> str:
    num = finite_float(value)
    return "–" if num is None else f"{num * 100:.0f}%"


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
    parser.add_argument(
        "--entry-mode", choices=["auto", "close", "next_open"], default="auto",
        help="evaluation entry timing (auto keeps legacy close prior to switch date and uses next_open afterwards)",
    )
    parser.add_argument(
        "--next-open-from", default=None,
        help="override cutoff signal date (YYYY-MM-DD) from which auto mode uses next_open",
    )
    parser.add_argument("--trade-date", default=None, help="optional trade date for patterns subcommand")
    parser.add_argument(
        "--expected-trade-date", default=None,
        help="target CN trade date for freshness checking; older packs are marked stale when --allow-stale-pack is set",
    )
    parser.add_argument(
        "--allow-stale-pack", action="store_true",
        help="allow older pack in patterns command while explicitly flagging pack_is_stale",
    )
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
        evaluate_markets(
            args.track,
            markets,
            pack_dir=args.pack_dir,
            entry_mode=args.entry_mode,
            next_open_from=args.next_open_from,
        )
        return 0
    if args.command == "patterns":
        record_cn_patterns(
            args.track,
            pack_dir=args.pack_dir,
            trade_date=args.trade_date,
            expected_trade_date=args.expected_trade_date,
            allow_stale_pack=args.allow_stale_pack,
            include_replay=args.with_replay,
            replay_json_path=args.replay_json,
        )
        return 0
    build_site(args.track)
    return 0


if __name__ == "__main__":
    sys.exit(main())
