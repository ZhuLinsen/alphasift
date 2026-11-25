# -*- coding: utf-8 -*-
"""CN daily radar report builder (`report.json`), announcement screening, and <1200-char IM card."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from alphasift.candidate_context import (
    classify_announcement_categories,
    classify_negative_events,
    classify_negative_text,
    collect_candidate_context,
)
from alphasift.config import Config
from alphasift.daily_brief import (
    build_cross_strategy_synthesis,
    generate_ai_daily_brief,
    resolve_strategy_display_names,
)
from alphasift.market_news import fetch_cn_market_news
from alphasift.markets import get_market, latest_settled_close
from alphasift.models import ScreenResult
from alphasift.normalize import normalize_code
from alphasift.pack import DailyPack
from alphasift.patterns import PatternSpec, extract_mini_kline_bars, list_patterns, scan_patterns
from alphasift.result_schema import DAILY_REPORT_SCHEMA, DAILY_REPORT_SCHEMA_VERSION
from alphasift.source_guard import call_with_timeout
from alphasift.store import load_screen_result
from alphasift.timeutil import parse_timestamp

IM_CARD_MAX_CHARS = 1199
_ANNOUNCEMENT_TIMEOUT_SEC = 25.0
_MARKET_NEWS_TIMEOUT_SEC = 8.0
_STOCK_NEWS_TIMEOUT_SEC = 15.0
DEFAULT_DASHBOARD_URL = "https://alphasift.zhulinsen.tech/"
_FACTOR_CN_LABELS = {
    "value": "估值",
    "quality": "质量",
    "dividend": "红利",
    "momentum": "动量",
    "reversal": "超跌反转",
    "growth": "成长",
    "low_volatility": "低波",
    "volatility": "低波",
    "stability": "低波稳健",
    "size": "市值规模",
    "activity": "活跃度",
    "theme_heat": "板块热度",
    "liquidity": "流动性",
    "capital_flow": "资金",
    "technical": "技术",
    "trend": "趋势",
    "sentiment": "情绪",
}
_RECENCY_RANK = {"recent": 0, "mid": 1, "unknown": 2, "old": 3}
_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[T\s]\d{2}:\d{2}(?::\d{2})?)?\s*")


def _collect_announcements_default(
    df: pd.DataFrame,
    *,
    max_rows: int,
    cache_dir: Path | None,
) -> tuple[list[dict[str, object]], list[str]]:
    return call_with_timeout(
        collect_candidate_context,
        df,
        max_rows=max_rows,
        providers=["announcement"],
        announcement_limit=3,
        cache_dir=cache_dir,
        timeout_sec=_ANNOUNCEMENT_TIMEOUT_SEC,
        label="announcement risk screening",
    )


def _parse_announcement_match(
    ann_text: str,
    *,
    trade_date: str | None = None,
) -> tuple[str | None, int | None, str, str]:
    """Isolate the specific triggering disclosure, its date, and recency relative to trade_date."""
    items = [part.strip() for part in str(ann_text or "").split("|") if part.strip()]
    matched_raw = ""
    for item in items:
        if classify_negative_text(item):
            matched_raw = item
            break
    if not matched_raw and items:
        matched_raw = items[0]
    if not matched_raw:
        return None, None, "unknown", ""

    m = _DATE_PREFIX_RE.match(matched_raw)
    ann_date = m.group(1) if m else None
    days_ago: int | None = None
    recency = "unknown"
    if ann_date:
        try:
            ref_date = (
                date.fromisoformat(str(trade_date).strip()[:10])
                if trade_date and len(str(trade_date).strip()) >= 10
                else datetime.now().date()
            )
            days_ago = max(0, (ref_date - date.fromisoformat(ann_date)).days)
            if days_ago <= 7:
                recency = "recent"
            elif days_ago <= 21:
                recency = "mid"
            else:
                recency = "old"
        except ValueError:
            days_ago = None
            recency = "unknown"

    cleaned = _clean_announcement_snippet(matched_raw, max_len=160)
    return ann_date, days_ago, recency, cleaned


def screen_announcement_risks(
    candidates: Sequence[dict[str, Any]],
    *,
    max_codes: int = 20,
    cache_dir: Path | None = None,
    collector: Callable[..., tuple[list[dict[str, object]], list[str]]] | None = None,
    trade_date: str | None = None,
    priority_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Best-effort announcement risk check over shortlisted CN candidates."""
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    limit = max(0, int(max_codes))
    for item in candidates:
        code = normalize_code(item.get("code"), allow_ticker=False)
        if not code or code in seen:
            continue
        seen.add(code)
        deduped.append({"code": code, "name": str(item.get("name") or "").strip()})
        if len(deduped) >= limit:
            break

    if not deduped:
        return {
            "checked_count": 0,
            "flagged_count": 0,
            "by_code": {},
            "flagged_items": [],
            "errors": [],
        }

    df = pd.DataFrame(deduped)
    errors: list[str] = []
    rows: list[dict[str, object]] = []
    try:
        if collector is not None:
            rows, coll_errors = collector(df, max_rows=len(deduped), cache_dir=cache_dir)
        else:
            rows, coll_errors = _collect_announcements_default(
                df, max_rows=len(deduped), cache_dir=cache_dir
            )
        errors.extend(str(e) for e in (coll_errors or []))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"announcement screening skipped: {exc}")
        rows = []

    by_code: dict[str, dict[str, Any]] = {}
    flagged_items: list[dict[str, Any]] = []
    name_map = {item["code"]: item["name"] for item in deduped}
    prio = priority_counts or {}

    for row in rows or []:
        code = normalize_code(row.get("code"), allow_ticker=False)
        if not code:
            continue
        neg_flags = list(row.get("negative_event_flags") or classify_negative_events(row))
        ann_cats = list(row.get("announcement_categories") or classify_announcement_categories(row))
        ann_text = str(row.get("announcement") or row.get("announcements") or "").strip()
        ann_date, days_ago, recency, matched_clean = _parse_announcement_match(
            ann_text,
            trade_date=trade_date,
        )
        info = {
            "code": code,
            "name": str(row.get("name") or name_map.get(code, "")),
            "negative_event_flags": neg_flags,
            "announcement_categories": ann_cats,
            "announcement_summary": ann_text[:200],
            "matched_announcement": matched_clean,
            "announcement_date": ann_date,
            "days_ago": days_ago,
            "recency": recency,
            "consensus_count": int(prio.get(code, 0)),
        }
        by_code[code] = info
        if neg_flags:
            flagged_items.append(info)

    flagged_items.sort(
        key=lambda x: (
            _RECENCY_RANK.get(str(x.get("recency") or "unknown"), 2),
            -int(x.get("consensus_count") or 0),
            int(x["days_ago"]) if x.get("days_ago") is not None else 999,
            str(x.get("code") or ""),
        )
    )

    return {
        "checked_count": len(deduped),
        "flagged_count": len(flagged_items),
        "by_code": by_code,
        "flagged_items": flagged_items,
        "errors": errors,
    }


def _cn_run_session_date(created_at: str) -> str:
    """Resolve the CN exchange session date (YYYY-MM-DD) for a run timestamp."""
    parsed = parse_timestamp(created_at)
    if parsed is None:
        return str(created_at or "")[:10]
    settled = latest_settled_close("cn", parsed)
    if settled is not None:
        return settled[0].isoformat()
    return parsed.astimezone(ZoneInfo(get_market("cn").timezone)).date().isoformat()


def load_daily_report_runs(
    config: Config,
    *,
    run_refs: Sequence[str] | None = None,
    runs_dir: Path | None = None,
    trade_date: str | None = None,
) -> list[ScreenResult]:
    """Unified run loader for CLI ``daily-report`` and HTTP ``/daily-report``."""
    target_runs_dir = Path(runs_dir).expanduser() if runs_dir is not None else (config.data_dir / "runs")
    loaded: list[ScreenResult] = []
    seen_ids: set[str] = set()

    for ref in run_refs or []:
        if isinstance(ref, Path):
            cand = ref
        else:
            direct = Path(ref)
            in_runs = target_runs_dir / f"{ref}.json"
            # When ref is a bare run_id (no path separators), prefer target_runs_dir over CWD.
            if "/" not in str(ref) and "\\" not in str(ref) and in_runs.is_file():
                cand = in_runs
            else:
                cand = direct if direct.is_file() else in_runs
        sr = load_screen_result(cand, data_dir=config.data_dir)
        key_id = sr.run_id or str(cand)
        if key_id not in seen_ids:
            seen_ids.add(key_id)
            loaded.append(sr)

    if (runs_dir is not None or not run_refs) and target_runs_dir.is_dir():
        for path in sorted(target_runs_dir.glob("*.json")):
            try:
                sr = load_screen_result(path, data_dir=config.data_dir)
            except Exception:  # noqa: BLE001
                continue
            if (sr.market or "cn").lower() != "cn":
                continue
            if trade_date and sr.created_at and _cn_run_session_date(sr.created_at) != trade_date:
                continue
            key_id = sr.run_id or str(path)
            if key_id not in seen_ids:
                seen_ids.add(key_id)
                loaded.append(sr)

    loaded.sort(
        key=lambda r: (
            str(r.strategy),
            0 if (r.track or ("ai" if r.llm_ranked else "rules")) == "rules" else 1,
            str(r.created_at or ""),
            str(r.run_id or ""),
        )
    )
    return loaded


def _derive_pick_reason(p: Any) -> str:
    explicit = str(getattr(p, "ranking_reason", "") or "").strip()
    if explicit:
        return explicit[:120]
    fscores = getattr(p, "factor_scores", None)
    if isinstance(fscores, dict) and fscores:
        ranked_f = sorted(
            ((k, float(v)) for k, v in fscores.items() if v is not None),
            key=lambda kv: -kv[1],
        )
        labels = [_FACTOR_CN_LABELS.get(k, k) for k, _ in ranked_f[:2]]
        if labels:
            return f"{'+'.join(labels)}因子靠前"
    bits: list[str] = []
    pe = getattr(p, "pe_ratio", None)
    pb = getattr(p, "pb_ratio", None)
    if pe is not None and float(pe) > 0:
        bits.append(f"PE {float(pe):.1f}")
    if pb is not None and float(pb) > 0:
        bits.append(f"PB {float(pb):.2f}")
    return " · ".join(bits)


def _format_strategy_entry(
    run: ScreenResult,
    *,
    display_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    track = run.track or ("ai" if run.llm_ranked else "rules")
    names_map = display_names or resolve_strategy_display_names()
    picks = []
    for p in run.picks[:5]:
        raw_price = getattr(p, "price", None)
        price_val = round(float(raw_price), 2) if raw_price is not None and float(raw_price) > 0 else None
        raw_pe = getattr(p, "pe_ratio", None)
        pe_val = round(float(raw_pe), 1) if raw_pe is not None else None
        raw_pb = getattr(p, "pb_ratio", None)
        pb_val = round(float(raw_pb), 2) if raw_pb is not None else None
        raw_mv = getattr(p, "total_mv", None)
        mv_yi = (
            round(float(raw_mv) / 1e8, 1)
            if raw_mv is not None and float(raw_mv) >= 1e6
            else None
        )
        picks.append({
            "rank": int(p.rank),
            "code": str(p.code),
            "name": str(p.name),
            "industry": str(p.industry),
            "price": price_val,
            "pe_ratio": pe_val,
            "pb_ratio": pb_val,
            "market_cap_yi": mv_yi,
            "final_score": round(float(p.final_score), 2),
            "screen_score": round(float(p.screen_score), 2),
            "change_pct": round(float(p.change_pct), 2) if p.change_pct is not None else None,
            "risk_level": str(p.risk_level),
            "risk_flags": list(p.risk_flags),
            "ranking_reason": _derive_pick_reason(p),
            "announcement_risk_flags": [],
        })
    return {
        "run_id": run.run_id,
        "strategy": run.strategy,
        "display_name": names_map.get(run.strategy, run.strategy),
        "market": run.market,
        "track": track,
        "llm_ranked": bool(run.llm_ranked),
        "llm_market_view": str(getattr(run, "llm_market_view", "") or "")[:160],
        "created_at": run.created_at,
        "pick_count": len(run.picks),
        "degradation": list(run.degradation),
        "picks": picks,
    }


def _build_ai_highlights(strategy_runs: Sequence[ScreenResult]) -> list[dict[str, Any]]:
    """Summarize same-strategy rules-vs-AI deltas and LLM rationale for DailyReport."""
    by_strat: dict[str, dict[str, ScreenResult]] = {}
    for run in strategy_runs:
        tr = run.track or ("ai" if run.llm_ranked else "rules")
        if tr not in {"rules", "ai"}:
            continue
        by_strat.setdefault(str(run.strategy), {})[tr] = run

    highlights: list[dict[str, Any]] = []
    for strategy in sorted(by_strat):
        pair = by_strat[strategy]
        ai_run = pair.get("ai")
        if ai_run is None:
            continue
        rules_run = pair.get("rules")
        ai_codes = {str(p.code) for p in ai_run.picks}
        rules_codes = {str(p.code) for p in rules_run.picks} if rules_run is not None else set()
        union_cnt = len(ai_codes | rules_codes)
        overlap_pct = (
            round((len(ai_codes & rules_codes) / union_cnt) * 100.0, 1)
            if rules_run is not None and union_cnt > 0
            else None
        )
        added = [
            {
                "code": str(p.code),
                "name": str(p.name),
                "final_score": round(float(p.final_score), 2),
                "ranking_reason": str(getattr(p, "ranking_reason", "") or "")[:120],
            }
            for p in ai_run.picks
            if rules_run is None or str(p.code) not in rules_codes
        ]
        dropped = (
            [
                {"code": str(p.code), "name": str(p.name)}
                for p in rules_run.picks
                if str(p.code) not in ai_codes
            ]
            if rules_run is not None
            else []
        )
        highlights.append({
            "strategy": strategy,
            "run_id": ai_run.run_id,
            "rules_pick_count": len(rules_run.picks) if rules_run is not None else 0,
            "ai_pick_count": len(ai_run.picks),
            "overlap_pct": overlap_pct,
            "added_by_ai": added,
            "dropped_by_ai": dropped,
            "llm_market_view": str(getattr(ai_run, "llm_market_view", "") or "")[:200],
            "llm_selection_logic": str(getattr(ai_run, "llm_selection_logic", "") or "")[:200],
            "llm_portfolio_risk": str(getattr(ai_run, "llm_portfolio_risk", "") or "")[:200],
        })
    return highlights


def _extract_strategy_track_stats(
    track_summary: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(track_summary, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in track_summary.get("scorecard") or []:
        if not isinstance(row, dict) or str(row.get("market") or "").lower() != "cn":
            continue
        strat = str(row.get("strategy") or "").strip()
        if not strat:
            continue
        track_name = str(row.get("track") or "rules")
        w5 = ((row.get("windows") or {}).get("5") or {}) if isinstance(row.get("windows"), dict) else {}
        matched = int(w5.get("matched") or 0)
        ex = w5.get("average_excess_return_pct")
        beat = w5.get("beat_rate")
        if matched <= 0 and ex is None:
            continue
        # Prefer rules baseline row unless only ai track exists for that strategy
        if strat in out and track_name != "rules":
            continue
        out[strat] = {
            "track": track_name,
            "t5_matched": matched,
            "t5_avg_excess_pct": round(float(ex), 2) if ex is not None else None,
            "t5_beat_rate_pct": round(float(beat) * 100.0, 1) if beat is not None else None,
        }
    return out


def _extract_pattern_replay_map(
    pattern_replay: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(pattern_replay, dict):
        return {}
    replay_obj = pattern_replay.get("replay") if isinstance(pattern_replay.get("replay"), dict) else pattern_replay
    if not isinstance(replay_obj, dict):
        return {}
    items = replay_obj.get("patterns")
    if isinstance(items, dict):
        iter_items = [{"pattern": k, **(v if isinstance(v, dict) else {})} for k, v in items.items()]
    elif isinstance(items, list):
        iter_items = [x for x in items if isinstance(x, dict)]
    else:
        return {}
    cost_pct = float(replay_obj.get("cost_bps") or 0.0) / 100.0
    out: dict[str, dict[str, Any]] = {}
    for p in iter_items:
        pname = str(p.get("pattern") or "").strip()
        if not pname:
            continue
        h5 = ((p.get("horizons") or {}).get("t5") or {}) if isinstance(p.get("horizons"), dict) else {}
        grad = p.get("graduation") if isinstance(p.get("graduation"), dict) else {}
        net_val = grad.get("t5_net_excess_mean_pct")
        if net_val is None:
            net_val = h5.get("net_excess_mean_pct")
        if net_val is None:
            gross_val = h5.get("gross_excess_mean_pct")
            if gross_val is None:
                gross_val = h5.get("excess_mean_pct")
            if gross_val is not None:
                net_val = float(gross_val) - cost_pct
        win_val = h5.get("excess_win_rate_pct")
        if win_val is None:
            win_val = h5.get("win_rate_pct")
        samples = h5.get("excess_scored")
        if samples is None:
            samples = h5.get("scored")
        wf = p.get("walk_forward_regime_audit") if isinstance(p.get("walk_forward_regime_audit"), dict) else {}
        wf_adv = [str(s) for s in (wf.get("h1_adverse_regimes") or []) if str(s).strip()] if wf else []
        wf_pos = [str(s) for s in (wf.get("h1_positive_regimes") or []) if str(s).strip()] if wf else []
        raw_ov_cap = wf.get("low_overhead_threshold_pct") if wf else None
        wf_ov_cap = int(round(float(raw_ov_cap))) if raw_ov_cap is not None else 15
        wf_joint = wf.get("h2_non_adverse_low_overhead") if isinstance(wf.get("h2_non_adverse_low_overhead"), dict) else {}
        wf_joint_days = int(wf_joint.get("days") or 0)
        wf_joint_mean = wf_joint.get("daily_mean_pct")
        wf_joint_delta = wf.get("delta_non_adverse_low_overhead_vs_h2_baseline_pct")
        out[pname] = {
            "replay_t5_net_excess_pct": round(float(net_val), 2) if net_val is not None else None,
            "replay_t5_win_rate_pct": round(float(win_val), 1) if win_val is not None else None,
            "replay_samples": int(samples) if samples is not None else None,
            "wf_h1_adverse_regimes": wf_adv,
            "wf_h1_positive_regimes": wf_pos,
            "wf_low_overhead_threshold_pct": wf_ov_cap,
            "wf_non_adverse_low_overhead_pct": (
                round(float(wf_joint_mean), 2) if wf_joint_days > 0 and wf_joint_mean is not None else None
            ),
            "wf_non_adverse_low_overhead_days": wf_joint_days,
            "wf_joint_delta_pct": round(float(wf_joint_delta), 2) if wf_joint_delta is not None else None,
        }
    return out


def _collect_candidate_stock_news(
    df: pd.DataFrame,
    *,
    cache_dir: Path | None,
) -> tuple[list[dict[str, object]], list[str]]:
    return call_with_timeout(
        collect_candidate_context,
        df,
        max_rows=len(df),
        providers=["news"],
        news_limit=2,
        cache_dir=cache_dir,
        timeout_sec=_STOCK_NEWS_TIMEOUT_SEC,
        label="candidate stock news",
    )


def _parse_piped_stock_news(raw_text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for chunk in str(raw_text or "").split("|"):
        cleaned = " ".join(chunk.split()).strip()
        if not cleaned:
            continue
        m = _DATE_PREFIX_RE.match(cleaned)
        pub = m.group(1)[5:] if m else ""
        title = _DATE_PREFIX_RE.sub("", cleaned, count=1).strip()
        out.append({"title": title[:110], "published_at": pub})
    return out[:2]


def build_daily_report(
    daily_pack: DailyPack,
    *,
    trade_date: str | None = None,
    expected_trade_date: str | None = None,
    allow_stale_pack: bool = True,
    detail_url: str | None = None,
    strategy_runs: Sequence[ScreenResult] | None = None,
    include_experimental_patterns: bool = True,
    include_announcements: bool = True,
    announcement_max_codes: int = 20,
    announcement_cache_dir: Path | None = None,
    announcement_collector: Callable[..., tuple[list[dict[str, object]], list[str]]] | None = None,
    include_news: bool = False,
    news_max_items: int = 6,
    news_cache_dir: Path | None = None,
    market_news_collector: Callable[..., tuple[list[dict[str, Any]], list[str], list[str]]] | None = None,
    stock_news_collector: Callable[..., tuple[list[dict[str, object]], list[str]]] | None = None,
    patterns_dir: Path | None = None,
    max_card_chars: int = 1150,
    max_signals_per_pattern: int = 10,
    ai_brief_mode: str = "off",
    config: Config | None = None,
    track_comparison: Sequence[dict[str, Any]] | None = None,
    track_summary: dict[str, Any] | None = None,
    pattern_replay: dict[str, Any] | None = None,
    warn_if_no_runs: bool = False,
    llm_caller: Callable[..., str] | None = None,
) -> dict[str, Any]:
    """Build machine-readable CN ``DailyReport`` payload and <1200 char IM card."""
    scan = scan_patterns(
        daily_pack,
        trade_date=trade_date,
        include_experimental=include_experimental_patterns,
        patterns_dir=patterns_dir,
    )
    expected = (expected_trade_date or "").strip() or None
    pack_is_stale = bool(expected and str(scan.pack_trade_date) < expected)
    stale_reason = (
        f"pack_trade_date={scan.pack_trade_date} < expected_trade_date={expected}"
        if pack_is_stale
        else None
    )
    if pack_is_stale and not allow_stale_pack:
        raise ValueError(
            f"CN DailyPack is stale ({stale_reason}); pass allow_stale_pack=True for degraded display"
        )
    specs_by_name: dict[str, PatternSpec] = {
        spec.name: spec
        for spec in list_patterns(include_experimental=True, patterns_dir=patterns_dir)
    }
    replay_map = _extract_pattern_replay_map(pattern_replay)
    summary_names = (
        track_summary.get("strategy_names")
        if isinstance(track_summary, dict) and isinstance(track_summary.get("strategy_names"), dict)
        else None
    )
    display_names = resolve_strategy_display_names(
        config.strategies_dir if config is not None else None,
        overrides=summary_names,
    )
    track_stats = _extract_strategy_track_stats(track_summary)
    effective_track_cmp = (
        track_comparison
        if track_comparison is not None
        else (track_summary.get("track_comparison") if isinstance(track_summary, dict) else None)
    )

    cur_stage = str(getattr(scan.market_regime, "regime_stage", "") or "").strip()
    active_patterns: list[dict[str, Any]] = []
    experimental_patterns: list[dict[str, Any]] = []
    for pat_name in scan.patterns_evaluated:
        spec = specs_by_name.get(pat_name)
        status = spec.status if spec is not None else "experimental"
        display_name = spec.display_name if spec is not None else pat_name
        family = spec.family if spec is not None else "unknown"
        mode = spec.mode if spec is not None else "direct"
        hits = scan.signals_by_pattern.get(pat_name, [])
        rep_stats = replay_map.get(pat_name) or {}
        net_ex = rep_stats.get("replay_t5_net_excess_pct")
        if status == "active":
            exp_tier = "active"
        elif net_ex is not None:
            exp_tier = "positive_watch" if float(net_ex) >= 0 else "negative_watch"
        else:
            exp_tier = "unrated"
        entry: dict[str, Any] = {
            "pattern": pat_name,
            "display_name": display_name,
            "family": family,
            "mode": mode,
            "status": status,
            "expectancy_tier": exp_tier,
            "aligned_strategy": spec.aligned_strategy if spec is not None else None,
            "hit_count": len(hits),
            "signals": [sig.to_dict() for sig in hits[: max(1, int(max_signals_per_pattern))]],
        }
        if rep_stats:
            entry.update(rep_stats)
            entry["wf_today_adverse"] = bool(
                cur_stage and cur_stage in (rep_stats.get("wf_h1_adverse_regimes") or [])
            )
        if status == "active":
            active_patterns.append(entry)
        else:
            experimental_patterns.append(entry)

    strategy_entries = [_format_strategy_entry(run, display_names=display_names) for run in (strategy_runs or [])]
    ai_highlights = _build_ai_highlights(strategy_runs or [])

    # Consensus-first candidate prioritization for announcement checks & stock news:
    # 1) Multi-strategy consensus >= 2, 2) AI-added picks, 3) Round-robin picks rank 1..5 across all strategies,
    # 4) Active patterns -> positive/unrated experimental patterns -> remaining patterns.
    code_strats: dict[str, set[str]] = {}
    code_scores: dict[str, list[float]] = {}
    code_names: dict[str, str] = {}
    for st in strategy_entries:
        sname = str(st.get("strategy") or "")
        for pk in st["picks"]:
            norm_c = normalize_code(pk["code"], allow_ticker=False)
            if not norm_c:
                continue
            code_strats.setdefault(norm_c, set()).add(sname)
            if pk.get("final_score") is not None:
                code_scores.setdefault(norm_c, []).append(float(pk["final_score"]))
            if not code_names.get(norm_c) and pk.get("name"):
                code_names[norm_c] = str(pk["name"]).strip()
    priority_counts = {c: len(s) for c, s in code_strats.items()}
    consensus_codes = sorted(
        (c for c, cnt in priority_counts.items() if cnt >= 2),
        key=lambda c: (
            -priority_counts[c],
            -(sum(code_scores[c]) / len(code_scores[c]) if code_scores.get(c) else 0.0),
            c,
        ),
    )

    ann_candidates: list[dict[str, str]] = [
        {"code": c, "name": code_names.get(c, "")} for c in consensus_codes
    ]
    for hl in ai_highlights:
        for item in hl.get("added_by_ai") or []:
            c = normalize_code(item.get("code"), allow_ticker=False)
            if c:
                ann_candidates.append({"code": c, "name": str(item.get("name") or "")})
    max_picks_len = max((len(st["picks"]) for st in strategy_entries), default=0)
    for rank_idx in range(max_picks_len):
        for st in strategy_entries:
            if rank_idx < len(st["picks"]):
                pk = st["picks"][rank_idx]
                ann_candidates.append({"code": pk["code"], "name": pk["name"]})
    for pat in active_patterns:
        for sig in pat["signals"][:5]:
            ann_candidates.append({"code": sig["code"], "name": sig["name"]})
    ordered_exp = sorted(
        experimental_patterns,
        key=lambda p: 0 if p.get("expectancy_tier") != "negative_watch" else 1,
    )
    for pat in ordered_exp:
        for sig in pat["signals"][:3]:
            ann_candidates.append({"code": sig["code"], "name": sig["name"]})

    degradation: list[str] = []
    if warn_if_no_runs and not strategy_entries:
        degradation.append(f"No CN strategy runs matched trade_date={scan.trade_date}")

    if include_announcements:
        ann_risks = screen_announcement_risks(
            ann_candidates,
            max_codes=announcement_max_codes,
            cache_dir=announcement_cache_dir,
            collector=announcement_collector,
            trade_date=scan.trade_date,
            priority_counts=priority_counts,
        )
        for err in ann_risks["errors"]:
            degradation.append(f"Announcement screening: {err}")
    else:
        ann_risks = {
            "checked_count": 0,
            "flagged_count": 0,
            "by_code": {},
            "flagged_items": [],
            "errors": [],
        }

    market_news_section: dict[str, Any] = {
        "items": [],
        "sources": [],
        "candidate_news": {},
        "errors": [],
    }
    if include_news:
        try:
            if market_news_collector is not None:
                m_items, m_sources, m_errs = market_news_collector(
                    limit=news_max_items,
                    trade_date=scan.trade_date,
                    cache_dir=news_cache_dir or announcement_cache_dir,
                )
            else:
                m_items, m_sources, m_errs = call_with_timeout(
                    fetch_cn_market_news,
                    limit=news_max_items,
                    trade_date=scan.trade_date,
                    cache_dir=news_cache_dir or announcement_cache_dir,
                    tavily_keys=config.tavily_api_keys if config is not None else None,
                    serpapi_keys=config.serpapi_api_keys if config is not None else None,
                    timeout_sec=_MARKET_NEWS_TIMEOUT_SEC,
                    label="cn market news",
                )
            market_news_section["items"] = list(m_items or [])
            market_news_section["sources"] = list(m_sources or [])
            market_news_section["errors"].extend(str(e) for e in (m_errs or []))
        except Exception as exc:  # noqa: BLE001
            market_news_section["errors"].append(f"market news skipped: {exc}")

        # Fetch catalyst news only for top 5 priority candidates (consensus first, then top strategy picks).
        news_focus: list[dict[str, str]] = []
        news_seen: set[str] = set()
        for item in ann_candidates:
            c = normalize_code(item.get("code"), allow_ticker=False)
            if not c or c in news_seen:
                continue
            news_seen.add(c)
            news_focus.append({"code": c, "name": str(item.get("name") or "")})
            if len(news_focus) >= 5:
                break
        if news_focus:
            try:
                news_df = pd.DataFrame(news_focus)
                if stock_news_collector is not None:
                    s_rows, s_errs = stock_news_collector(
                        news_df,
                        max_rows=len(news_focus),
                        cache_dir=announcement_cache_dir,
                    )
                else:
                    s_rows, s_errs = _collect_candidate_stock_news(
                        news_df,
                        cache_dir=announcement_cache_dir,
                    )
                for row in s_rows or []:
                    rc = normalize_code(row.get("code"), allow_ticker=False)
                    raw_n = str(row.get("news") or "").strip()
                    if rc and raw_n:
                        parsed_n = _parse_piped_stock_news(raw_n)
                        if parsed_n:
                            market_news_section["candidate_news"][rc] = parsed_n
                for e in s_errs or []:
                    market_news_section["errors"].append(str(e))
            except Exception as exc:  # noqa: BLE001
                market_news_section["errors"].append(f"candidate news skipped: {exc}")

        if market_news_section["errors"] and not market_news_section["items"] and not market_news_section["candidate_news"]:
            degradation.append(f"News enrichment: {market_news_section['errors'][0]}")

    sig_codes: list[str] = []
    seen_sig_codes: set[str] = set()
    for group in (active_patterns, experimental_patterns):
        for pat in group:
            for sig in pat["signals"]:
                c = str(sig.get("code") or "")
                if c and c not in seen_sig_codes:
                    seen_sig_codes.add(c)
                    sig_codes.append(c)
    kline_map = (
        extract_mini_kline_bars(daily_pack, sig_codes, trade_date=scan.trade_date, bars=20)
        if sig_codes
        else {}
    )

    risk_map = ann_risks["by_code"]
    for st in strategy_entries:
        for pk in st["picks"]:
            pk["announcement_risk_flags"] = list((risk_map.get(pk["code"]) or {}).get("negative_event_flags") or [])
    for group in (active_patterns, experimental_patterns):
        for pat in group:
            for sig in pat["signals"]:
                sig["announcement_risk_flags"] = list(
                    (risk_map.get(sig["code"]) or {}).get("negative_event_flags") or []
                )
                sig["kline"] = kline_map.get(str(sig.get("code") or ""), [])

    if pack_is_stale and stale_reason:
        degradation.append(f"Stale pack: {stale_reason}")
    resolved_detail_url = (
        DEFAULT_DASHBOARD_URL if detail_url is None else str(detail_url).strip()
    )

    report: dict[str, Any] = {
        "schema_version": DAILY_REPORT_SCHEMA_VERSION,
        "object": "DailyReport",
        "trade_date": scan.trade_date,
        "pack_trade_date": scan.pack_trade_date,
        "expected_trade_date": expected,
        "pack_is_stale": pack_is_stale,
        "stale_reason": stale_reason,
        "detail_url": resolved_detail_url,
        "market": "cn",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "usage_policy": "cn_only_regime_slice_only",
        "strategy_display_names": display_names,
        "strategy_track_stats": track_stats,
        "market_regime": scan.market_regime.to_dict(),
        "strategies": strategy_entries,
        "ai_highlights": ai_highlights,
        "patterns": {
            "active": active_patterns,
            "experimental": experimental_patterns,
        },
        "announcement_risks": ann_risks,
        "market_news": market_news_section,
        "degradation": degradation,
        "non_goals": list(DAILY_REPORT_SCHEMA["non_goals"]),
    }

    report["cross_strategy_synthesis"] = build_cross_strategy_synthesis(
        report,
        strategy_names=display_names,
    )
    report["ai_brief"] = generate_ai_daily_brief(
        report,
        config=config,
        track_comparison=effective_track_cmp,
        use_llm=ai_brief_mode,
        llm_caller=llm_caller,
    )
    fb_reason = str((report["ai_brief"] or {}).get("fallback_reason") or "")
    if ai_brief_mode in {"auto", "on"} and fb_reason.startswith("llm_error:"):
        report["degradation"].append(f"AI brief fallback: {fb_reason}")

    card = render_daily_im_card(report, max_chars=min(int(max_card_chars), IM_CARD_MAX_CHARS))
    report["im_card_markdown"] = card
    report["im_card_chars"] = len(card)
    return report


def ensure_im_card_length(text: str, *, max_chars: int = IM_CARD_MAX_CHARS) -> str:
    """Guarantee IM card fits strictly within ``max_chars`` (<= 1199), preserving alerts & links."""
    limit = min(max(80, int(max_chars)), IM_CARD_MAX_CHARS)
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    footer = "注：量化形态观测与回测基准，非投资建议。"
    lines = [line for line in cleaned.splitlines() if line.strip() != footer]

    head: list[str] = []
    alerts: list[str] = []
    links: list[str] = []
    middle: list[str] = []

    in_alerts = False
    for idx, line in enumerate(lines):
        if line.startswith("🔗") or ("http://" in line or "https://" in line):
            in_alerts = False
            links.append(line)
        elif "公告预警" in line or "公告排雷" in line:
            in_alerts = True
            alerts.append(line)
        elif in_alerts and line.startswith("- "):
            alerts.append(line)
        else:
            in_alerts = False
            if idx == 0 or (len(head) < 3 and ("旧包降级" in line or line.startswith("> "))):
                head.append(line)
            else:
                middle.append(line)

    essential: list[str] = [*head, *alerts]
    tail_links: list[str] = [*links, footer]

    reserved_tail = "\n".join(tail_links)
    max_body = max(20, limit - len(reserved_tail) - 1)

    kept_essential: list[str] = []
    used = 0
    for line in essential:
        add_len = len(line) + (1 if kept_essential else 0)
        if used + add_len <= max_body:
            kept_essential.append(line)
            used += add_len
        elif not kept_essential:
            kept_essential.append(line[: max(10, max_body - 3)] + "...")
            used = len(kept_essential[0])
            break

    kept_middle: list[str] = []
    for line in middle:
        add_len = len(line) + (1 if (kept_essential or kept_middle) else 0)
        if used + add_len <= max_body - 4:
            kept_middle.append(line)
            used += add_len
        else:
            break

    assembled = [*kept_essential, *kept_middle]
    if len(kept_middle) < len(middle):
        ellipsis_len = 4 if assembled else 3
        if used + ellipsis_len <= max_body:
            assembled.append("...")

    result = "\n".join([*assembled, *tail_links])
    if len(result) > limit:
        result = result[: limit - 3] + "..."
    return result


_LEADING_TS_RE = re.compile(r"(?:^|(\|\s*))\d{4}-\d{2}-\d{2}(?:[T\s]\d{2}:\d{2}(?::\d{2})?)?\s*")


def _clean_announcement_snippet(text: object, *, max_len: int = 44) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    cleaned = _LEADING_TS_RE.sub(lambda m: " · " if m.group(1) else "", cleaned).strip(" :：-—·")
    cleaned = re.sub(r"\s*\|\s*", " · ", cleaned)
    if max_len > 0 and len(cleaned) > max_len:
        return cleaned[: max(1, max_len - 1)].rstrip() + "…"
    return cleaned


def _is_wf_joint_positive(pat: dict[str, Any]) -> bool:
    """Return True when today is non-adverse and H2 Joint OOS (>=15d) is positive."""
    if pat.get("wf_today_adverse"):
        return False
    joint_pct = pat.get("wf_non_adverse_low_overhead_pct")
    if joint_pct is None:
        return False
    return (
        int(pat.get("wf_non_adverse_low_overhead_days") or 0) >= 15
        and float(joint_pct) > 0.0
    )


def _im_pattern_rank_key(pat: dict[str, Any]) -> tuple[int, int, float, str]:
    is_active = pat.get("status") == "active"
    adverse = bool(pat.get("wf_today_adverse"))
    non_neg = pat.get("expectancy_tier") != "negative_watch"
    if is_active:
        tier = 1 if adverse else 0
    elif non_neg and not adverse:
        tier = 2
    elif _is_wf_joint_positive(pat):
        tier = 3
    elif non_neg:
        tier = 4
    elif not adverse:
        tier = 5
    else:
        tier = 6
    joint_val = pat.get("wf_non_adverse_low_overhead_pct")
    joint_sort = -float(joint_val) if joint_val is not None else 999.0
    return (
        tier,
        -int(pat.get("hit_count") or 0),
        joint_sort,
        str(pat.get("pattern") or ""),
    )


def render_daily_im_card(
    report: dict[str, Any],
    *,
    max_chars: int = 1150,
) -> str:
    """Render alert-first concise <1200-char Markdown card directing details to the dashboard."""
    reg = report.get("market_regime") or {}
    seal = reg.get("seal_rate_pct")
    seal_str = "-" if seal is None else f"{float(seal):.1f}%"
    prev_ret = reg.get("prev_limit_up_avg_return_pct")
    prev_str = "-" if prev_ret is None else f"{float(prev_ret):+.2f}%"
    amt = reg.get("total_amount_yi")
    amt_str = "-" if amt is None else f"{float(amt):,.0f}亿"
    med = reg.get("median_return_pct")
    med_part = "" if med is None else f" · 中位 {float(med):+.2f}%"

    lines = [f"**AlphaSift A股盘后观察 ({report.get('trade_date', '-')})**"]
    if report.get("pack_is_stale"):
        lines.append(
            f"> ⚠️ **旧包降级**：数据包日期 {report.get('pack_trade_date', '-')} 落后于目标交易日 "
            f"{report.get('expected_trade_date', '-')}，仅供参考"
        )
    lines.append(
        f"> 盘面 **{reg.get('regime_stage_label', '-')}**｜"
        f"上涨 {float(reg.get('advance_ratio_pct', 0.0)):.1f}%{med_part}｜"
        f"涨跌停 {reg.get('non_st_limit_up_count', 0)}/{reg.get('non_st_limit_down_count', 0)}（封板 {seal_str}）｜"
        f"最高 {reg.get('max_consecutive_limit_up', 0)}板 · 昨涨停 {prev_str} · 成交 {amt_str}"
    )

    # Alert-first block: announcement risks BEFORE strategies and patterns, with reserved budget.
    ann = report.get("announcement_risks") or {}
    flagged = ann.get("flagged_items") or []
    checked = int(ann.get("checked_count") or 0)
    if flagged:
        lines.append(f"**⚠️ 公告排雷预警（{checked}检/{len(flagged)}中）**")
        bullet_budget = 340
        used_ann = 0
        shown = 0
        for item in flagged[:5]:
            flags = "/".join(str(x) for x in (item.get("negative_event_flags") or [])[:2])
            date_tag = f"{str(item.get('announcement_date'))[5:]}·" if item.get("announcement_date") else ""
            rec_tag = "旧·" if item.get("recency") == "old" else ""
            bullet = f"- {item.get('code', '')} {str(item.get('name', ''))[:8]} [{date_tag}{rec_tag}{flags}]"
            raw_ann = item.get("matched_announcement") or item.get("announcement_summary")
            snip = _clean_announcement_snippet(raw_ann, max_len=34)
            if snip and len(bullet) + len(snip) + 2 <= 82:
                bullet += f": {snip}"
            if shown > 0 and used_ann + len(bullet) + 1 > bullet_budget:
                break
            lines.append(bullet)
            used_ann += len(bullet) + 1
            shown += 1
        if len(flagged) > shown:
            lines.append(f"- …其余 {len(flagged) - shown} 条高风险见网页详情")
    elif checked > 0 and ann.get("errors"):
        lines.append(f"**⚠️ 公告排雷**：抽检 {checked} 只（降级：{str(ann['errors'][0])[:40]}）")
    elif checked > 0:
        lines.append(f"**✅ 公告排雷**：抽检 {checked} 只暂未见减持/立案/监管等负面关键词")
    else:
        lines.append("**ℹ️ 公告排雷**：未抽检或无候选")

    # Compact strategy & AI overview (NO candidate stock lists on IM card).
    strategies = report.get("strategies") or []
    rules_runs = [s for s in strategies if not (s.get("track") == "ai" or s.get("llm_ranked"))]
    ai_runs = [s for s in strategies if (s.get("track") == "ai" or s.get("llm_ranked"))]
    rules_picks = sum(
        int(s["pick_count"]) if s.get("pick_count") is not None else len(s.get("picks") or [])
        for s in rules_runs
    )
    ai_picks = sum(
        int(s["pick_count"]) if s.get("pick_count") is not None else len(s.get("picks") or [])
        for s in ai_runs
    )
    ai_hl = report.get("ai_highlights") or []
    if ai_runs:
        added_n = sum(len(h.get("added_by_ai") or []) for h in ai_hl if isinstance(h, dict))
        dropped_n = sum(len(h.get("dropped_by_ai") or []) for h in ai_hl if isinstance(h, dict))
        delta_part = f"，AI调仓 +{added_n}/-{dropped_n}" if ai_hl else ""
        views = [
            str(h.get("llm_market_view") or "").replace("\n", " ").strip()
            for h in ai_hl
            if isinstance(h, dict) and h.get("llm_market_view")
        ]
        view_part = f"（{views[0][:42]}）" if views else ""
        lines.append(
            f"**策略与 [AI]**：规则 {len(rules_runs)} 组({rules_picks}只) / "
            f"[AI] {len(ai_runs)} 组({ai_picks}只){delta_part}{view_part}"
        )
    elif rules_runs:
        lines.append(f"**策略概览**：规则 {len(rules_runs)} 组共 {rules_picks} 只候选")
    else:
        lines.append("**策略概览**：当日未附带 CN 策略选股（仅输出盘面与形态雷达）")

    syn = report.get("cross_strategy_synthesis") or {}
    consensus = syn.get("consensus_picks") or []
    if consensus:
        top_c = "、".join(
            f"{c['code']} {str(c.get('name') or '')[:6]}({c['strategy_count']}策略)"
            for c in consensus[:4]
        )
        lines.append(f"**多策略共识({len(consensus)})**：{top_c}")
    brief = report.get("ai_brief") or {}
    if brief.get("mode") == "llm" and brief.get("headline"):
        lines.append(f"**[AI] 简评**：{str(brief['headline'])[:72]}")
    elif brief.get("headline"):
        lines.append(f"**盘后摘要**：{str(brief['headline'])[:72]}")

    # Compact pattern radar summary: positive/active expectations first; collapse negative-expectancy patterns.
    pat_sec = report.get("patterns") or {}
    active = pat_sec.get("active") or []
    experimental = pat_sec.get("experimental") or []
    active_hits = sum(int(p.get("hit_count") or 0) for p in active)
    exp_hits = sum(int(p.get("hit_count") or 0) for p in experimental)
    top_hit_pats = [
        p for p in (*active, *experimental)
        if int(p.get("hit_count") or 0) > 0
    ]
    top_hit_pats.sort(key=_im_pattern_rank_key)
    preferred_pats = [
        p for p in top_hit_pats
        if p.get("status") == "active" or p.get("expectancy_tier") != "negative_watch" or _is_wf_joint_positive(p)
    ] or top_hit_pats
    if preferred_pats:
        pat_parts = []
        for p in preferred_pats[:3]:
            dname = str(p.get("display_name") or p.get("pattern") or "")
            sigs = "、".join(str(s.get("name") or s.get("code") or "")[:6] for s in (p.get("signals") or [])[:2])
            tag_parts: list[str] = []
            if p.get("status") != "active":
                tag_parts.append("观察期")
            if p.get("wf_today_adverse"):
                tag_parts.append("逆风")
            elif _is_wf_joint_positive(p):
                tag_parts.append(f"联合OOS{float(p['wf_non_adverse_low_overhead_pct']):+.2f}%")
            tag = ("·" + "·".join(tag_parts)) if tag_parts else ""
            sig_txt = f"：{sigs}" if sigs else ""
            pat_parts.append(f"{dname}({int(p.get('hit_count') or 0)}只{tag}{sig_txt})")
        lines.append("**形态雷达**：" + "；".join(pat_parts))
    else:
        lines.append(
            f"**形态雷达**：active {len(active)} 组({active_hits}只) / "
            f"观察期 {len(experimental)} 组({exp_hits}只)"
        )

    mnews_items = ((report.get("market_news") or {}).get("items") or []) if isinstance(report.get("market_news"), dict) else []
    if mnews_items:
        top_title = str(mnews_items[0].get("title") or "").strip()[:48]
        if top_title:
            lines.append(f"**盘后要闻**：{top_title}")

    detail_url = (
        DEFAULT_DASHBOARD_URL
        if report.get("detail_url") is None
        else str(report.get("detail_url") or "").strip()
    )
    if detail_url:
        lines.append(f"🔗 完整候选、AI归因与K线详情：{detail_url}")

    lines.append("注：量化形态观测与回测基准，非投资建议。")
    return ensure_im_card_length("\n".join(lines), max_chars=max_chars)


def write_daily_report(path: str | Path, report: dict[str, Any]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def write_daily_card(path: str | Path, card_text: str) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(ensure_im_card_length(card_text) + "\n", encoding="utf-8")
    return output
