# -*- coding: utf-8 -*-
"""CN daily radar report builder (`report.json`), announcement screening, and <1200-char IM card."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import pandas as pd

from alphasift.candidate_context import (
    classify_announcement_categories,
    classify_negative_events,
    collect_candidate_context,
)
from alphasift.models import ScreenResult
from alphasift.normalize import normalize_code
from alphasift.pack import DailyPack
from alphasift.patterns import PatternSpec, list_patterns, scan_patterns
from alphasift.result_schema import DAILY_REPORT_SCHEMA, DAILY_REPORT_SCHEMA_VERSION
from alphasift.source_guard import call_with_timeout

IM_CARD_MAX_CHARS = 1199
_ANNOUNCEMENT_TIMEOUT_SEC = 15.0


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
            "announcement_risk_flags": [],
        })
    return {
        "run_id": run.run_id,
        "strategy": run.strategy,
        "market": run.market,
        "track": track,
        "llm_ranked": bool(run.llm_ranked),
        "created_at": run.created_at,
        "pick_count": len(run.picks),
        "degradation": list(run.degradation),
        "picks": picks,
    }


def build_daily_report(
    daily_pack: DailyPack,
    *,
    trade_date: str | None = None,
    strategy_runs: Sequence[ScreenResult] | None = None,
    include_experimental_patterns: bool = True,
    include_announcements: bool = True,
    announcement_max_codes: int = 12,
    announcement_cache_dir: Path | None = None,
    announcement_collector: Callable[..., tuple[list[dict[str, object]], list[str]]] | None = None,
    patterns_dir: Path | None = None,
    max_card_chars: int = 1150,
    max_signals_per_pattern: int = 10,
) -> dict[str, Any]:
    """Build machine-readable CN ``DailyReport`` payload and <1200 char IM card."""
    scan = scan_patterns(
        daily_pack,
        trade_date=trade_date,
        include_experimental=include_experimental_patterns,
        patterns_dir=patterns_dir,
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

    report: dict[str, Any] = {
        "schema_version": DAILY_REPORT_SCHEMA_VERSION,
        "object": "DailyReport",
        "trade_date": scan.trade_date,
        "pack_trade_date": scan.pack_trade_date,
        "market": "cn",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "usage_policy": "cn_only_regime_slice_only",
        "market_regime": scan.market_regime.to_dict(),
        "strategies": strategy_entries,
        "patterns": {
            "active": active_patterns,
            "experimental": experimental_patterns,
        },
        "announcement_risks": ann_risks,
        "degradation": degradation,
        "non_goals": list(DAILY_REPORT_SCHEMA["non_goals"]),
    }

    card = render_daily_im_card(report, max_chars=min(int(max_card_chars), IM_CARD_MAX_CHARS))
    report["im_card_markdown"] = card
    report["im_card_chars"] = len(card)
    return report


def ensure_im_card_length(text: str, *, max_chars: int = IM_CARD_MAX_CHARS) -> str:
    """Guarantee IM card fits strictly within ``max_chars`` (<= 1199)."""
    limit = min(max(80, int(max_chars)), IM_CARD_MAX_CHARS)
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    footer = "注：量化形态观测与回测基准，非投资建议。"
    lines = cleaned.splitlines()
    kept: list[str] = []
    reserve = len(footer) + 6
    budget = limit - reserve
    used = 0
    for line in lines:
        if line == footer:
            continue
        add_len = len(line) + (1 if kept else 0)
        if used + add_len <= budget:
            kept.append(line)
            used += add_len
        else:
            break
    if not kept:
        return cleaned[: limit - 3] + "..."
    result = "\n".join(kept) + "\n...\n" + footer
    if len(result) > limit:
        result = result[: limit - 3] + "..."
    return result


def render_daily_im_card(
    report: dict[str, Any],
    *,
    max_chars: int = 1150,
) -> str:
    """Render concise <1200-char Markdown card summarizing regime, picks, patterns, and risks."""
    reg = report.get("market_regime") or {}
    seal = reg.get("seal_rate_pct")
    seal_str = "-" if seal is None else f"{float(seal):.1f}%"
    prev_ret = reg.get("prev_limit_up_avg_return_pct")
    prev_str = "-" if prev_ret is None else f"{float(prev_ret):+.2f}%"
    amt = reg.get("total_amount_yi")
    amt_str = "-" if amt is None else f"{float(amt):.0f}亿"
    ladder = reg.get("consecutive_board_ladder") or {}
    ladder_str = " ".join(f"{k}板:{v}" for k, v in sorted(ladder.items(), key=lambda kv: int(kv[0]))) or "无"

    lines = [
        f"**AlphaSift A股量化观测日报 ({report.get('trade_date', '-')})**",
        (
            f"> 阶段: **{reg.get('regime_stage_label', '-')}({reg.get('regime_stage', '-')})** [仅切片] | "
            f"上涨: {float(reg.get('advance_ratio_pct', 0.0)):.1f}% | 成交: {amt_str}"
        ),
        (
            f"> 涨停/跌停(非ST): {reg.get('non_st_limit_up_count', 0)}/{reg.get('non_st_limit_down_count', 0)} | "
            f"封板率: {seal_str} | 连板最高: {reg.get('max_consecutive_limit_up', 0)} ({ladder_str}) | 昨涨停: {prev_str}"
        ),
    ]

    strategies = report.get("strategies") or []
    if strategies:
        lines.append("**策略精选**")
        for st in strategies[:4]:
            tag = "AI" if st.get("track") == "ai" or st.get("llm_ranked") else "规则"
            picks = st.get("picks") or []
            if picks:
                pick_bits = []
                for p in picks[:3]:
                    rflags = p.get("announcement_risk_flags") or []
                    warn = f"(!{'/'.join(rflags[:2])})" if rflags else ""
                    pick_bits.append(f"{p['code']} {p['name']}{warn}")
                lines.append(f"- [{tag}] {st['strategy']}: " + "，".join(pick_bits))
            else:
                lines.append(f"- [{tag}] {st['strategy']}: 无候选")

    pat_sec = report.get("patterns") or {}
    active = pat_sec.get("active") or []
    experimental = pat_sec.get("experimental") or []
    lines.append("**形态雷达**")
    if active:
        for pat in active[:4]:
            sigs = pat.get("signals") or []
            top_txt = "、".join(f"{s['code']} {s['name']}" for s in sigs[:3]) or "无"
            lines.append(f"- [active] {pat['display_name']}({pat['hit_count']}): {top_txt}")
    else:
        lines.append("- 正式形态(active): 暂无达标信号（均未过 T+5 门槛）")

    if experimental:
        exp_parts = []
        for pat in experimental:
            cnt = int(pat.get("hit_count") or 0)
            sigs = pat.get("signals") or []
            head = f" {sigs[0]['code']}{sigs[0]['name']}" if sigs else ""
            exp_parts.append(f"{pat['display_name']}:{cnt}{head}")
        lines.append("- [experimental] " + " | ".join(exp_parts[:6]))

    ann = report.get("announcement_risks") or {}
    flagged = ann.get("flagged_items") or []
    checked = int(ann.get("checked_count") or 0)
    if flagged:
        risk_txt = "；".join(
            f"{item['code']} {item.get('name', '')}[{'/'.join(item['negative_event_flags'][:2])}]"
            for item in flagged[:4]
        )
        lines.append(f"**公告排雷({checked}只抽检/{len(flagged)}预警)**: {risk_txt}")
    elif checked > 0 and ann.get("errors"):
        lines.append(f"**公告排雷**: 抽检 {checked} 只（部分降级：{ann['errors'][0][:45]}）")
    elif checked > 0:
        lines.append(f"**公告排雷**: 已核验 {checked} 只，暂未发现减持/监管等负面关键词")

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
