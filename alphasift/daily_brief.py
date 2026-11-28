# -*- coding: utf-8 -*-
"""Cross-strategy synthesis and AI / deterministic daily editorial brief for CN reports."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
from pathlib import Path
import re
from typing import Any

from alphasift.config import Config
from alphasift.jsonutil import dumps_strict_json, finite_float, safe_int
from alphasift.normalize import safe_text

BRIEF_DISCLAIMER = "仅供量化研究与复盘观察，不构成投资建议。"

BUILTIN_STRATEGY_DISPLAY_NAMES: dict[str, str] = {
    "balanced_alpha": "均衡多因子",
    "blue_chip_income": "蓝筹收益质量",
    "capital_heat": "资金热度",
    "dual_low": "双低选股",
    "global_value": "全球低估值",
    "low_volatility_quality": "低波质量",
    "momentum_quality": "趋势质量",
    "oversold_reversal": "超跌反转",
    "quality_value": "稳健价值",
    "shrink_pullback": "缩量回踩",
    "us_momentum_quality": "美股趋势质量",
    "volume_breakout": "放量突破",
}
_STRATEGY_NAMES_CACHE: dict[Path | None, dict[str, str]] = {}
_THINK_CLOSED_RE = re.compile(r"<think>.*?</think>", flags=re.IGNORECASE | re.DOTALL)
_THINK_UNCLOSED_TAIL_RE = re.compile(r"<think>.*$", flags=re.IGNORECASE | re.DOTALL)


def resolve_strategy_display_names(
    strategies_dir: Path | None = None,
    *,
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return mapping of strategy slug -> localized display name."""
    cache_key = strategies_dir.resolve() if isinstance(strategies_dir, Path) else None
    base = _STRATEGY_NAMES_CACHE.get(cache_key)
    if base is None:
        merged = dict(BUILTIN_STRATEGY_DISPLAY_NAMES)
        try:
            from alphasift.strategy import list_strategies

            for info in list_strategies(strategies_dir):
                if info.name and info.display_name:
                    # Keep clean Chinese label for us_momentum_quality when YAML uses ASCII title
                    if info.name in BUILTIN_STRATEGY_DISPLAY_NAMES and info.display_name.isascii():
                        continue
                    merged[info.name] = str(info.display_name).strip()
        except Exception:  # noqa: BLE001
            pass
        _STRATEGY_NAMES_CACHE[cache_key] = merged
        base = merged
    out = dict(base)
    if isinstance(overrides, dict):
        for k, v in overrides.items():
            key_txt = safe_text(k)
            val_txt = safe_text(v)
            if key_txt and val_txt:
                out[key_txt] = val_txt
    return out


def _string_flags(raw: object) -> list[str]:
    if isinstance(raw, (list, tuple, set)):
        return [txt for item in raw if (txt := safe_text(item))]
    if isinstance(raw, str):
        cleaned = safe_text(raw)
        return [cleaned] if cleaned else []
    return []


def _brief_bullet_list(value: object, *, limit: int = 5) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [txt for item in value if (txt := safe_text(item, max_len=200))][:limit]
    if isinstance(value, str):
        cleaned = safe_text(value, max_len=200)
        return [cleaned] if cleaned else []
    return []


def build_cross_strategy_synthesis(
    report: dict[str, Any],
    *,
    strategy_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build deterministic cross-strategy consensus, sector concentration, resonance, and risk spotlight."""
    report_dict = report if isinstance(report, dict) else {}
    display_overrides = report_dict.get("strategy_display_names")
    display_map = resolve_strategy_display_names(
        overrides=(strategy_names or (display_overrides if isinstance(display_overrides, dict) else None))
    )
    mnews_raw = report_dict.get("market_news")
    cand_news = (
        mnews_raw.get("candidate_news")
        if isinstance(mnews_raw, dict) and isinstance(mnews_raw.get("candidate_news"), dict)
        else {}
    )
    raw_strategies = report_dict.get("strategies")
    strategies = raw_strategies if isinstance(raw_strategies, list) else []
    by_code: dict[str, dict[str, Any]] = {}
    sector_counts: dict[str, dict[str, Any]] = {}
    pick_pairs_seen: set[tuple[str, str]] = set()
    total_pick_slots = 0

    for st in strategies:
        if not isinstance(st, dict):
            continue
        strat_name = safe_text(st.get("strategy"))
        track_name = safe_text(st.get("track")) or ("ai" if st.get("llm_ranked") else "rules")
        raw_picks = st.get("picks")
        for pk in raw_picks if isinstance(raw_picks, list) else []:
            if not isinstance(pk, dict):
                continue
            code = safe_text(pk.get("code"))
            if not code:
                continue
            name = safe_text(pk.get("name"))
            industry = safe_text(pk.get("industry"))
            score = finite_float(pk.get("final_score"))
            chg = finite_float(pk.get("change_pct"))
            reason = safe_text(pk.get("ranking_reason"))
            ann_flags = _string_flags(pk.get("announcement_risk_flags"))
            risk_flags = _string_flags(pk.get("risk_flags"))
            risk_level = safe_text(pk.get("risk_level"))

            entry = by_code.setdefault(
                code,
                {
                    "code": code,
                    "name": name,
                    "industry": industry,
                    "strategies": set(),
                    "tracks": set(),
                    "scores": [],
                    "change_pct": chg,
                    "price": finite_float(pk.get("price")),
                    "pe_ratio": finite_float(pk.get("pe_ratio")),
                    "pb_ratio": finite_float(pk.get("pb_ratio")),
                    "market_cap_yi": finite_float(pk.get("market_cap_yi")),
                    "reasons": [],
                    "announcement_risk_flags": set(),
                    "risk_flags": set(),
                    "risk_level": risk_level,
                },
            )
            if not entry["name"] and name:
                entry["name"] = name
            if not entry["industry"] and industry:
                entry["industry"] = industry
            if strat_name:
                entry["strategies"].add(strat_name)
            entry["tracks"].add(track_name)
            if score is not None:
                entry["scores"].append(score)
            if entry["change_pct"] is None and chg is not None:
                entry["change_pct"] = chg
            for fld in ("price", "pe_ratio", "pb_ratio", "market_cap_yi"):
                if entry[fld] is None:
                    fval = finite_float(pk.get(fld))
                    if fval is not None:
                        entry[fld] = fval
            if reason and reason not in entry["reasons"] and len(entry["reasons"]) < 2:
                entry["reasons"].append(reason)
            entry["announcement_risk_flags"].update(ann_flags)
            entry["risk_flags"].update(risk_flags)
            if not entry["risk_level"] and risk_level:
                entry["risk_level"] = risk_level

            pair_key = (strat_name or track_name, code)
            if pair_key not in pick_pairs_seen:
                pick_pairs_seen.add(pair_key)
                total_pick_slots += 1
                ind_key = industry or "未分类"
                sec = sector_counts.setdefault(ind_key, {"industry": ind_key, "pick_count": 0, "codes": set()})
                sec["pick_count"] += 1
                sec["codes"].add(code)

    consensus_picks: list[dict[str, Any]] = []
    for code, item in by_code.items():
        if len(item["strategies"]) < 2:
            continue
        avg_score = round(sum(item["scores"]) / len(item["scores"]), 2) if item["scores"] else 0.0
        sorted_strats = sorted(item["strategies"])
        news_list = cand_news.get(code) if isinstance(cand_news, dict) else None
        first_news = ""
        if isinstance(news_list, list) and news_list:
            first_item = news_list[0]
            if isinstance(first_item, dict):
                first_news = safe_text(first_item.get("title"), max_len=100)
            else:
                first_news = safe_text(first_item, max_len=100)
        rec: dict[str, Any] = {
            "code": code,
            "name": item["name"],
            "industry": item["industry"],
            "strategy_count": len(sorted_strats),
            "strategies": sorted_strats,
            "strategy_display_names": [display_map.get(s, s) for s in sorted_strats],
            "tracks": sorted(item["tracks"]),
            "avg_final_score": avg_score,
            "change_pct": item["change_pct"],
            "announcement_risk_flags": sorted(item["announcement_risk_flags"]),
        }
        for fld in ("price", "pe_ratio", "pb_ratio", "market_cap_yi"):
            if item[fld] is not None:
                rec[fld] = item[fld]
        if item["reasons"]:
            rec["reasons"] = item["reasons"]
        if first_news:
            rec["news_headline"] = first_news
        consensus_picks.append(rec)
    consensus_picks.sort(key=lambda x: (-x["strategy_count"], -x["avg_final_score"], x["code"]))

    sector_concentration: list[dict[str, Any]] = []
    for sec in sector_counts.values():
        sector_concentration.append({
            "industry": sec["industry"],
            "pick_count": sec["pick_count"],
            "unique_codes": len(sec["codes"]),
            "share_pct": round((sec["pick_count"] / total_pick_slots) * 100.0, 1) if total_pick_slots else 0.0,
        })
    sector_concentration.sort(key=lambda x: (-x["pick_count"], -x["unique_codes"], x["industry"]))

    raw_patterns = report_dict.get("patterns")
    pat_sec = raw_patterns if isinstance(raw_patterns, dict) else {}
    pat_hits: dict[str, dict[str, Any]] = {}
    for bucket, pat_key in (("active", "active_patterns"), ("experimental", "experimental_patterns")):
        bucket_items = pat_sec.get(bucket)
        for pat in bucket_items if isinstance(bucket_items, list) else []:
            if not isinstance(pat, dict):
                continue
            pname = safe_text(pat.get("display_name")) or safe_text(pat.get("pattern"))
            signals = pat.get("signals")
            for sig in signals if isinstance(signals, list) else []:
                if not isinstance(sig, dict):
                    continue
                code = safe_text(sig.get("code"))
                if code not in by_code:
                    continue
                rec = pat_hits.setdefault(code, {"active_patterns": [], "experimental_patterns": []})
                if pname and pname not in rec[pat_key]:
                    rec[pat_key].append(pname)

    strategy_pattern_resonance: list[dict[str, Any]] = []
    for code in sorted(pat_hits):
        st_info = by_code[code]
        p_info = pat_hits[code]
        strategy_pattern_resonance.append({
            "code": code,
            "name": st_info["name"],
            "strategies": sorted(st_info["strategies"]),
            "active_patterns": p_info["active_patterns"],
            "experimental_patterns": p_info["experimental_patterns"],
            "announcement_risk_flags": sorted(st_info["announcement_risk_flags"]),
        })
    strategy_pattern_resonance.sort(
        key=lambda x: (-len(x["active_patterns"]), -len(x["strategies"]), -len(x["experimental_patterns"]), x["code"])
    )

    risk_map: dict[str, dict[str, Any]] = {}
    raw_ann = report_dict.get("announcement_risks")
    ann = raw_ann if isinstance(raw_ann, dict) else {}
    flagged_items = ann.get("flagged_items")
    for item in flagged_items if isinstance(flagged_items, list) else []:
        if not isinstance(item, dict):
            continue
        code = safe_text(item.get("code"))
        if not code:
            continue
        flags = _string_flags(item.get("negative_event_flags"))
        risk_map[code] = {
            "code": code,
            "name": safe_text(item.get("name")),
            "severity": "high",
            "flags": flags,
            "summary": safe_text(item.get("announcement_summary"), max_len=160),
            "source": "announcement",
        }
    for code, item in by_code.items():
        if code in risk_map:
            continue
        flags = sorted(item["announcement_risk_flags"] | item["risk_flags"])
        lvl = item["risk_level"].lower()
        if flags or lvl in {"high", "warning"}:
            risk_map[code] = {
                "code": code,
                "name": item["name"],
                "severity": "high" if (item["announcement_risk_flags"] or lvl == "high") else "medium",
                "flags": flags or [item["risk_level"]],
                "summary": "",
                "source": "pick_risk",
            }
    risk_spotlight = sorted(
        risk_map.values(),
        key=lambda x: (0 if x["severity"] == "high" else 1, -len(x["flags"]), x["code"]),
    )

    return {
        "consensus_picks": consensus_picks[:12],
        "sector_concentration": sector_concentration[:8],
        "strategy_pattern_resonance": strategy_pattern_resonance[:10],
        "risk_spotlight": risk_spotlight[:10],
    }


def _strip_json_fences(raw: str) -> str:
    cleaned = _THINK_CLOSED_RE.sub("", str(raw or "")).strip()
    cleaned = _THINK_UNCLOSED_TAIL_RE.sub("", cleaned).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _parse_brief_json(raw: str) -> dict[str, Any]:
    cleaned = _strip_json_fences(raw)
    try:
        parsed = json.loads(cleaned)
    except ValueError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("no_json_object_in_brief_response") from None
        parsed = json.loads(cleaned[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("brief_json_not_object")

    headline = safe_text(parsed.get("headline"))
    regime_interp = safe_text(parsed.get("regime_interpretation"))
    consensus_edge = safe_text(parsed.get("consensus_and_ai_edge"))
    if not headline or not regime_interp:
        raise ValueError("brief_json_missing_required_fields")

    warnings = _brief_bullet_list(parsed.get("risk_warnings"), limit=5)
    watches = _brief_bullet_list(parsed.get("watch_points"), limit=5)
    return {
        "headline": headline[:140],
        "regime_interpretation": regime_interp[:400],
        "consensus_and_ai_edge": (consensus_edge or "多策略结果仅作同口径跟踪对照。")[:400],
        "risk_warnings": warnings,
        "watch_points": watches,
    }


def _build_rule_daily_brief(
    report: dict[str, Any],
    *,
    track_comparison: Sequence[dict[str, Any]] | None = None,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    report_dict = report if isinstance(report, dict) else {}
    raw_reg = report_dict.get("market_regime")
    reg = raw_reg if isinstance(raw_reg, dict) else {}
    stage_label = safe_text(reg.get("regime_stage_label")) or "-"
    adv_val = finite_float(reg.get("advance_ratio_pct"))
    adv = adv_val if adv_val is not None else 0.0
    med = finite_float(reg.get("median_return_pct"))
    med_txt = f"中位数 {med:+.2f}%" if med is not None else "中位数待统计"
    lu = safe_int(reg.get("non_st_limit_up_count"))
    ld = safe_int(reg.get("non_st_limit_down_count"))
    seal = finite_float(reg.get("seal_rate_pct"))
    seal_txt = f"{seal:.1f}%" if seal is not None else "-"
    prev_lu = finite_float(reg.get("prev_limit_up_avg_return_pct"))
    prev_txt = f"{prev_lu:+.2f}%" if prev_lu is not None else "-"
    max_streak = safe_int(reg.get("max_consecutive_limit_up"))
    amt = finite_float(reg.get("total_amount_yi"))
    amt_txt = f"{amt:.0f}亿" if amt is not None else "-"

    raw_syn = report_dict.get("cross_strategy_synthesis")
    syn = raw_syn if isinstance(raw_syn, dict) and raw_syn else build_cross_strategy_synthesis(report_dict)
    raw_consensus = syn.get("consensus_picks")
    consensus = [c for c in raw_consensus if isinstance(c, dict)] if isinstance(raw_consensus, list) else []
    raw_sectors = syn.get("sector_concentration")
    sectors = [s for s in raw_sectors if isinstance(s, dict)] if isinstance(raw_sectors, list) else []
    raw_ann = report_dict.get("announcement_risks")
    ann = raw_ann if isinstance(raw_ann, dict) else {}
    raw_flagged = ann.get("flagged_items")
    flagged = [item for item in raw_flagged if isinstance(item, dict)] if isinstance(raw_flagged, list) else []
    raw_ai_hl = report_dict.get("ai_highlights")
    ai_hl = [h for h in raw_ai_hl if isinstance(h, dict)] if isinstance(raw_ai_hl, list) else []
    stale_prefix = "【旧包降级】" if report_dict.get("pack_is_stale") else ""

    headline = (
        f"{stale_prefix}盘面处于{stage_label}阶段，上涨 {adv:.1f}%（{med_txt}），"
        f"涨跌停 {lu}/{ld}（封板率 {seal_txt}）"
    )
    if flagged:
        headline += f"，公告排雷命中 {len(flagged)} 只预警"
    elif consensus:
        headline += f"，跨策略共识 {len(consensus)} 只"

    trade_date_lbl = safe_text(report_dict.get("trade_date")) or "-"
    regime_interpretation = (
        f"{trade_date_lbl} 全市场情绪处于「{stage_label}」阶段："
        f"全市场上涨占比 {adv:.1f}%、{med_txt}，成交额 {amt_txt}；"
        f"非 ST 涨停 {lu} 只 / 跌停 {ld} 只，首板封板率 {seal_txt}，连板最高 {max_streak} 板，昨涨停今日均表现 {prev_txt}。"
    )

    parts: list[str] = []
    consensus_chips = []
    for c in consensus[:3]:
        c_code = safe_text(c.get("code"))
        if not c_code:
            continue
        c_name = safe_text(c.get("name"))
        c_cnt = max(safe_int(c.get("strategy_count"), default=0), 0)
        consensus_chips.append(f"{c_code}{c_name}({c_cnt}策略)")
    if consensus_chips:
        parts.append(f"多策略共振标的前列：{'、'.join(consensus_chips)}")
    else:
        parts.append("当日各策略候选分散，未出现 ≥2 个策略共同命中的重合股")
    sector_chips = []
    for s in sectors[:3]:
        ind = safe_text(s.get("industry")) or "未分类"
        share_val = finite_float(s.get("share_pct"))
        share_num = 0.0 if share_val is None else share_val
        sector_chips.append(f"{ind}({share_num}%)")
    if sector_chips:
        parts.append(f"行业主要集中在 {'、'.join(sector_chips)}")
    if ai_hl:
        added_n = sum(len(h.get("added_by_ai") or []) for h in ai_hl if isinstance(h.get("added_by_ai"), list))
        dropped_n = sum(len(h.get("dropped_by_ai") or []) for h in ai_hl if isinstance(h.get("dropped_by_ai"), list))
        parts.append(f"AI 赛道当日调仓累计新增 {added_n} 只 / 剔除 {dropped_n} 只")
    elif track_comparison:
        cn_cmp = [c for c in track_comparison if isinstance(c, dict) and c.get("market") == "cn"]
        if cn_cmp:
            parts.append(f"当前已追踪 {len(cn_cmp)} 组 CN 规则 vs AI 同日配对样本")
    consensus_and_ai_edge = "；".join(parts) + "。"

    risk_warnings: list[str] = []
    if report_dict.get("pack_is_stale"):
        pack_date = safe_text(report_dict.get("pack_trade_date")) or "-"
        exp_date = safe_text(report_dict.get("expected_trade_date")) or "-"
        risk_warnings.append(
            f"数据包滞后（包日期 {pack_date} < 目标日 {exp_date}），盘面与形态仅供参考。"
        )
    for item in flagged[:3]:
        fl = "/".join(_string_flags(item.get("negative_event_flags"))[:2])
        item_code = safe_text(item.get("code"))
        item_name = safe_text(item.get("name"))
        if item_code:
            risk_warnings.append(f"公告预警：{item_code} {item_name} 命中 [{fl}]")
    checked_count = safe_int(ann.get("checked_count"))
    if not flagged and checked_count > 0:
        risk_warnings.append(f"已抽检 {checked_count} 只核心候选，未触发减持/立案等负面关键词。")
    if ld >= 20 or (seal is not None and seal < 55.0):
        risk_warnings.append(f"短线承接偏弱（非 ST 跌停 {ld} 只，封板率 {seal_txt}），警惕高位接力退潮风险。")
    if not risk_warnings:
        risk_warnings.append("关注次日开盘一字涨停导致的不可成交剔除以及市场成交额持续性。")

    watch_points = [
        f"观察次日上涨占比能否从 {adv:.1f}% 修复、跌停家数（{ld} 只）是否收敛；",
        f"跟踪昨日涨停溢价（{prev_txt}）与连板梯队（{max_streak} 板）高度延续情况；",
    ]
    if consensus_chips:
        c0 = consensus[0]
        c0_label = f"{safe_text(c0.get('code'))} {safe_text(c0.get('name'))}".strip()
        if c0_label:
            watch_points.append(
                f"复盘多策略共识标的（{c0_label} 等）次日开盘承接与换手。"
            )

    return {
        "mode": "rule_fallback",
        "model": None,
        "headline": headline[:140],
        "regime_interpretation": regime_interpretation,
        "consensus_and_ai_edge": consensus_and_ai_edge,
        "risk_warnings": risk_warnings[:5],
        "watch_points": watch_points[:4],
        "disclaimer": BRIEF_DISCLAIMER,
        "fallback_reason": fallback_reason,
    }


def _build_brief_prompt(
    report: dict[str, Any],
    *,
    synthesis: dict[str, Any],
    track_comparison: Sequence[dict[str, Any]] | None = None,
) -> str:
    report_dict = report if isinstance(report, dict) else {}
    reg = report_dict.get("market_regime") if isinstance(report_dict.get("market_regime"), dict) else {}
    mnews = report_dict.get("market_news") if isinstance(report_dict.get("market_news"), dict) else {}
    strat_names = report_dict.get("strategy_display_names")
    if not isinstance(strat_names, dict) or not strat_names:
        strat_names = resolve_strategy_display_names()
    raw_items = mnews.get("items")
    compact_news = [
        {
            "category": n.get("category"),
            "source": n.get("source"),
            "time": n.get("published_at"),
            "title": n.get("title"),
        }
        for n in (raw_items[:5] if isinstance(raw_items, list) else [])
        if isinstance(n, dict) and safe_text(n.get("title"))
    ]
    syn_dict = synthesis if isinstance(synthesis, dict) else {}
    ann_dict = report_dict.get("announcement_risks") if isinstance(report_dict.get("announcement_risks"), dict) else {}
    raw_ai_hl = report_dict.get("ai_highlights")
    raw_flagged = ann_dict.get("flagged_items")
    compact_context: dict[str, Any] = {
        "trade_date": report_dict.get("trade_date"),
        "pack_trade_date": report_dict.get("pack_trade_date"),
        "pack_is_stale": bool(report_dict.get("pack_is_stale", False)),
        "strategy_display_names": strat_names,
        "market_regime": {
            "stage": reg.get("regime_stage"),
            "stage_label": reg.get("regime_stage_label"),
            "advance_ratio_pct": reg.get("advance_ratio_pct"),
            "median_return_pct": reg.get("median_return_pct"),
            "non_st_limit_up": reg.get("non_st_limit_up_count"),
            "non_st_limit_down": reg.get("non_st_limit_down_count"),
            "seal_rate_pct": reg.get("seal_rate_pct"),
            "max_consecutive_limit_up": reg.get("max_consecutive_limit_up"),
            "prev_limit_up_avg_return_pct": reg.get("prev_limit_up_avg_return_pct"),
            "total_amount_yi": reg.get("total_amount_yi"),
            "return_distribution": reg.get("return_distribution"),
        },
        "cross_strategy_synthesis": {
            "consensus_picks": (syn_dict.get("consensus_picks") if isinstance(syn_dict.get("consensus_picks"), list) else [])[:5],
            "sector_concentration": (syn_dict.get("sector_concentration") if isinstance(syn_dict.get("sector_concentration"), list) else [])[:5],
            "strategy_pattern_resonance": (syn_dict.get("strategy_pattern_resonance") if isinstance(syn_dict.get("strategy_pattern_resonance"), list) else [])[:5],
            "risk_spotlight": (syn_dict.get("risk_spotlight") if isinstance(syn_dict.get("risk_spotlight"), list) else [])[:5],
        },
        "ai_highlights": (raw_ai_hl if isinstance(raw_ai_hl, list) else [])[:4],
        "announcement_flagged": (raw_flagged if isinstance(raw_flagged, list) else [])[:5],
        "paired_ai_track_summary": [
            {
                "strategy": item.get("strategy"),
                "common_days": item.get("common_days"),
                "t5": (item.get("windows") or {}).get("5") if isinstance(item.get("windows"), dict) else None,
            }
            for item in (track_comparison or [])
            if isinstance(item, dict) and item.get("market") == "cn"
        ][:4],
    }
    if compact_news:
        compact_context["market_news"] = compact_news
    payload_json = dumps_strict_json(compact_context, indent=None)
    return (
        "你是 AlphaSift A 股量化观测系统的盘后投研编辑。请仅基于下面提供的结构化观测数据，"
        "用克制、客观、信息密度高的专业中文撰写盘后简报。\n"
        "严格约束：\n"
        "1. 禁止编造任何数据中不存在的股票代码、价格、涨跌幅、公告或新闻内容、目标价；\n"
        "2. 用中文策略名描述策略（使用 strategy_display_names），不输出系统内部英文代号；\n"
        "3. 不给出任何买卖建议或收益承诺；\n"
        "4. 仅返回纯 JSON 对象（不要输出思考过程或 Markdown 解释），包含字段：\n"
        '   {"headline": "不超过80字核心结论", '
        '"regime_interpretation": "120-240字盘面宽度、情绪结构与市场快讯催化解读", '
        '"consensus_and_ai_edge": "100-220字跨策略共识、行业集中与个股/AI观察解读", '
        '"risk_warnings": ["风险提示1", "风险提示2"], '
        '"watch_points": ["次日客观观察指标1", "次日客观观察指标2"]}\n\n'
        f"结构化数据：\n{payload_json}\n"
    )


def generate_ai_daily_brief(
    report: dict[str, Any],
    *,
    config: Config | None = None,
    track_comparison: Sequence[dict[str, Any]] | None = None,
    use_llm: str = "auto",
    llm_caller: Callable[..., str] | None = None,
    timeout_sec: float = 45.0,
) -> dict[str, Any]:
    """Generate structured AI daily brief with grounded deterministic fallback."""
    mode = (use_llm or "auto").strip().lower()
    if mode not in {"auto", "on", "off"}:
        raise ValueError("use_llm must be 'auto', 'on', or 'off'")

    if mode == "off":
        return _build_rule_daily_brief(report, track_comparison=track_comparison, fallback_reason=None)

    has_llm_cfg = bool(
        config is not None
        and (
            config.has_usable_llm_config()
            if hasattr(config, "has_usable_llm_config")
            else (config.llm_api_key or config.llm_channels or config.llm_config_path)
        )
    )
    if mode == "auto" and not has_llm_cfg and llm_caller is None:
        return _build_rule_daily_brief(
            report,
            track_comparison=track_comparison,
            fallback_reason="no_llm_configured",
        )
    if mode == "on" and not has_llm_cfg and llm_caller is None:
        return _build_rule_daily_brief(
            report,
            track_comparison=track_comparison,
            fallback_reason="llm_requested_but_not_configured",
        )

    synthesis = report.get("cross_strategy_synthesis") or build_cross_strategy_synthesis(report)
    prompt = _build_brief_prompt(report, synthesis=synthesis, track_comparison=track_comparison)
    model_name = config.llm_model if config is not None else "custom"
    used_model = model_name

    try:
        if llm_caller is not None:
            raw_text = llm_caller(prompt)
            parsed = _parse_brief_json(raw_text)
        else:
            from alphasift.llm_client import DEFAULT_LLM_MAX_TOKENS
            from alphasift.ranker import _call_llm_with_metadata

            assert config is not None
            brief_max_tokens = max(
                1,
                safe_int(
                    getattr(config, "llm_max_tokens", DEFAULT_LLM_MAX_TOKENS),
                    default=DEFAULT_LLM_MAX_TOKENS,
                ),
            )
            t_req = finite_float(timeout_sec)
            t_cfg = finite_float(getattr(config, "llm_timeout_sec", 60.0))
            eff_timeout = min(
                t_req if t_req is not None and t_req > 0 else 60.0,
                t_cfg if t_cfg is not None and t_cfg > 0 else 60.0,
            )
            raw_text, used_model = _call_llm_with_metadata(
                prompt,
                api_key=config.llm_api_key,
                model=config.llm_model,
                base_url=config.llm_base_url,
                fallback_models=config.llm_fallback_models,
                temperature=0.2,
                json_mode=True,
                silent=True,
                channels=config.llm_channels,
                config_path=str(config.llm_config_path or ""),
                timeout_sec=eff_timeout,
                max_tokens=brief_max_tokens,
                reasoning_effort="low",
                validator=_parse_brief_json,
            )
            parsed = _parse_brief_json(raw_text)
    except Exception as exc:  # noqa: BLE001
        return _build_rule_daily_brief(
            report,
            track_comparison=track_comparison,
            fallback_reason=f"llm_error:{type(exc).__name__}:{str(exc)[:120]}",
        )

    return {
        "mode": "llm",
        "model": used_model or model_name,
        "headline": parsed["headline"],
        "regime_interpretation": parsed["regime_interpretation"],
        "consensus_and_ai_edge": parsed["consensus_and_ai_edge"],
        "risk_warnings": parsed["risk_warnings"],
        "watch_points": parsed["watch_points"],
        "disclaimer": BRIEF_DISCLAIMER,
        "fallback_reason": None,
    }
