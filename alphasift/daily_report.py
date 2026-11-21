# -*- coding: utf-8 -*-
"""CN daily radar report builder (`report.json`), announcement screening, and <1200-char IM card."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from alphasift.candidate_context import (
    classify_announcement_categories,
    classify_negative_events,
    collect_candidate_context,
)
from alphasift.config import Config
from alphasift.daily_brief import build_cross_strategy_synthesis, generate_ai_daily_brief
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
_ANNOUNCEMENT_TIMEOUT_SEC = 15.0
DEFAULT_DASHBOARD_URL = "https://zhulinsen.github.io/alphasift/"


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


def screen_announcement_risks(
    candidates: Sequence[dict[str, Any]],
    *,
    max_codes: int = 12,
    cache_dir: Path | None = None,
    collector: Callable[..., tuple[list[dict[str, object]], list[str]]] | None = None,
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

    for row in rows or []:
        code = normalize_code(row.get("code"), allow_ticker=False)
        if not code:
            continue
        neg_flags = list(row.get("negative_event_flags") or classify_negative_events(row))
        ann_cats = list(row.get("announcement_categories") or classify_announcement_categories(row))
        ann_text = str(row.get("announcement") or row.get("announcements") or "").strip()
        info = {
            "code": code,
            "name": str(row.get("name") or name_map.get(code, "")),
            "negative_event_flags": neg_flags,
            "announcement_categories": ann_cats,
            "announcement_summary": ann_text[:200],
        }
        by_code[code] = info
        if neg_flags:
            flagged_items.append(info)

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
        cand = Path(ref)
        if not cand.is_file() and (target_runs_dir / f"{ref}.json").is_file():
            cand = target_runs_dir / f"{ref}.json"
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


def _format_strategy_entry(run: ScreenResult) -> dict[str, Any]:
    track = run.track or ("ai" if run.llm_ranked else "rules")
    picks = []
    for p in run.picks[:5]:
        picks.append({
            "rank": int(p.rank),
            "code": str(p.code),
            "name": str(p.name),
            "industry": str(p.industry),
            "final_score": round(float(p.final_score), 2),
            "screen_score": round(float(p.screen_score), 2),
            "change_pct": round(float(p.change_pct), 2) if p.change_pct is not None else None,
            "risk_level": str(p.risk_level),
            "risk_flags": list(p.risk_flags),
            "ranking_reason": str(getattr(p, "ranking_reason", "") or "")[:120],
            "announcement_risk_flags": [],
        })
    return {
        "run_id": run.run_id,
        "strategy": run.strategy,
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
    announcement_max_codes: int = 12,
    announcement_cache_dir: Path | None = None,
    announcement_collector: Callable[..., tuple[list[dict[str, object]], list[str]]] | None = None,
    patterns_dir: Path | None = None,
    max_card_chars: int = 1150,
    max_signals_per_pattern: int = 10,
    ai_brief_mode: str = "off",
    config: Config | None = None,
    track_comparison: Sequence[dict[str, Any]] | None = None,
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

    active_patterns: list[dict[str, Any]] = []
    experimental_patterns: list[dict[str, Any]] = []
    for pat_name in scan.patterns_evaluated:
        spec = specs_by_name.get(pat_name)
        status = spec.status if spec is not None else "experimental"
        display_name = spec.display_name if spec is not None else pat_name
        family = spec.family if spec is not None else "unknown"
        mode = spec.mode if spec is not None else "direct"
        hits = scan.signals_by_pattern.get(pat_name, [])
        entry = {
            "pattern": pat_name,
            "display_name": display_name,
            "family": family,
            "mode": mode,
            "status": status,
            "aligned_strategy": spec.aligned_strategy if spec is not None else None,
            "hit_count": len(hits),
            "signals": [sig.to_dict() for sig in hits[: max(1, int(max_signals_per_pattern))]],
        }
        if status == "active":
            active_patterns.append(entry)
        else:
            experimental_patterns.append(entry)

    strategy_entries = [_format_strategy_entry(run) for run in (strategy_runs or [])]

    # Candidate pool for announcement check: strategy picks -> active patterns -> experimental hits.
    ann_candidates: list[dict[str, str]] = []
    for st in strategy_entries:
        for pk in st["picks"]:
            ann_candidates.append({"code": pk["code"], "name": pk["name"]})
    for pat in active_patterns:
        for sig in pat["signals"][:5]:
            ann_candidates.append({"code": sig["code"], "name": sig["name"]})
    for pat in experimental_patterns:
        for sig in pat["signals"][:3]:
            ann_candidates.append({"code": sig["code"], "name": sig["name"]})

    degradation: list[str] = []
    if include_announcements:
        ann_risks = screen_announcement_risks(
            ann_candidates,
            max_codes=announcement_max_codes,
            cache_dir=announcement_cache_dir,
            collector=announcement_collector,
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

    ai_highlights = _build_ai_highlights(strategy_runs or [])
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
        "market_regime": scan.market_regime.to_dict(),
        "strategies": strategy_entries,
        "ai_highlights": ai_highlights,
        "patterns": {
            "active": active_patterns,
            "experimental": experimental_patterns,
        },
        "announcement_risks": ann_risks,
        "degradation": degradation,
        "non_goals": list(DAILY_REPORT_SCHEMA["non_goals"]),
    }

    report["cross_strategy_synthesis"] = build_cross_strategy_synthesis(report)
    report["ai_brief"] = generate_ai_daily_brief(
        report,
        config=config,
        track_comparison=track_comparison,
        use_llm=ai_brief_mode,
        llm_caller=llm_caller,
    )

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
    amt_str = "-" if amt is None else f"{float(amt):.0f}亿"
    med = reg.get("median_return_pct")
    med_part = "" if med is None else f"(中位 {float(med):+.2f}%)"

    lines = [f"**AlphaSift A股量化观测日报 ({report.get('trade_date', '-')})**"]
    if report.get("pack_is_stale"):
        lines.append(
            f"> ⚠️ **旧包降级**：数据包日期 {report.get('pack_trade_date', '-')} 落后于目标交易日 "
            f"{report.get('expected_trade_date', '-')}，仅供参考"
        )
    lines.append(
        f"> 盘面 **{reg.get('regime_stage_label', '-')}({reg.get('regime_stage', '-')})**[仅切片]｜"
        f"上涨 {float(reg.get('advance_ratio_pct', 0.0)):.1f}%{med_part}｜"
        f"涨跌停 {reg.get('non_st_limit_up_count', 0)}/{reg.get('non_st_limit_down_count', 0)}(封板 {seal_str})｜"
        f"连板最高 {reg.get('max_consecutive_limit_up', 0)}板｜昨涨停 {prev_str}｜成交 {amt_str}"
    )

    # Alert-first block: announcement risks BEFORE strategies and patterns, with reserved budget.
    ann = report.get("announcement_risks") or {}
    flagged = ann.get("flagged_items") or []
    checked = int(ann.get("checked_count") or 0)
    if flagged:
        lines.append(f"**⚠️ 公告排雷预警({checked}检/{len(flagged)}中)**")
        bullet_budget = 340
        used_ann = 0
        shown = 0
        for item in flagged[:5]:
            flags = "/".join(str(x) for x in (item.get("negative_event_flags") or [])[:2])
            bullet = f"- {item.get('code', '')} {str(item.get('name', ''))[:8]}[{flags}]"
            snip = str(item.get("announcement_summary") or "").replace("\n", " ").strip()[:24]
            if snip and len(bullet) + len(snip) + 2 <= 68:
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
        lines.append(f"**策略概览**：规则 {len(rules_runs)} 组({rules_picks}只，完整候选见看板)")
    else:
        lines.append("**策略概览**：今日暂无已保存 CN 策略运行")

    syn = report.get("cross_strategy_synthesis") or {}
    consensus = syn.get("consensus_picks") or []
    if consensus:
        top_c = "、".join(
            f"{c['code']}{str(c.get('name') or '')[:6]}({c['strategy_count']}策略)"
            for c in consensus[:2]
        )
        lines.append(f"**多策略共识({len(consensus)})**：{top_c}")
    brief = report.get("ai_brief") or {}
    if brief.get("mode") == "llm" and brief.get("headline"):
        lines.append(f"**[AI] 简评**：{str(brief['headline'])[:64]}")

    # Compact pattern radar summary (counts only, experimental lists live in web dashboard).
    pat_sec = report.get("patterns") or {}
    active = pat_sec.get("active") or []
    experimental = pat_sec.get("experimental") or []
    active_hits = sum(int(p.get("hit_count") or 0) for p in active)
    exp_hits = sum(int(p.get("hit_count") or 0) for p in experimental)
    lines.append(
        f"**形态雷达**：正式(active) {len(active)} 组({active_hits}只) / "
        f"观察期(experimental) {len(experimental)} 组({exp_hits}只，详见看板)"
    )

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
