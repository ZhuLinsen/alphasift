# -*- coding: utf-8 -*-
"""Cross-strategy synthesis and AI / deterministic daily editorial brief for CN reports."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
import re
from typing import Any

from alphasift.config import Config

BRIEF_DISCLAIMER = "仅供量化研究与复盘观察，不构成投资建议。"


def build_cross_strategy_synthesis(report: dict[str, Any]) -> dict[str, Any]:
    """Build deterministic cross-strategy consensus, sector concentration, resonance, and risk spotlight."""
    strategies = report.get("strategies") or []
    by_code: dict[str, dict[str, Any]] = {}
    sector_counts: dict[str, dict[str, Any]] = {}
    pick_pairs_seen: set[tuple[str, str]] = set()
    total_pick_slots = 0

    for st in strategies:
        if not isinstance(st, dict):
            continue
        strat_name = str(st.get("strategy") or "").strip()
        track_name = str(st.get("track") or ("ai" if st.get("llm_ranked") else "rules"))
        for pk in st.get("picks") or []:
            if not isinstance(pk, dict):
                continue
            code = str(pk.get("code") or "").strip()
            if not code:
                continue
            name = str(pk.get("name") or "").strip()
            industry = str(pk.get("industry") or "").strip()
            score = pk.get("final_score")
            chg = pk.get("change_pct")
            ann_flags = [str(f) for f in (pk.get("announcement_risk_flags") or []) if f]
            risk_flags = [str(f) for f in (pk.get("risk_flags") or []) if f]
            risk_level = str(pk.get("risk_level") or "").strip()

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
                entry["scores"].append(float(score))
            if entry["change_pct"] is None and chg is not None:
                entry["change_pct"] = chg
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
        consensus_picks.append({
            "code": code,
            "name": item["name"],
            "industry": item["industry"],
            "strategy_count": len(item["strategies"]),
            "strategies": sorted(item["strategies"]),
            "tracks": sorted(item["tracks"]),
            "avg_final_score": avg_score,
            "change_pct": item["change_pct"],
            "announcement_risk_flags": sorted(item["announcement_risk_flags"]),
        })
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

    pat_sec = report.get("patterns") or {}
    pat_hits: dict[str, dict[str, Any]] = {}
    for bucket, pat_key in (("active", "active_patterns"), ("experimental", "experimental_patterns")):
        for pat in pat_sec.get(bucket) or []:
            if not isinstance(pat, dict):
                continue
            pname = str(pat.get("display_name") or pat.get("pattern") or "").strip()
            for sig in pat.get("signals") or []:
                if not isinstance(sig, dict):
                    continue
                code = str(sig.get("code") or "").strip()
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
    ann = report.get("announcement_risks") or {}
    for item in ann.get("flagged_items") or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        if not code:
            continue
        flags = [str(f) for f in (item.get("negative_event_flags") or []) if f]
        risk_map[code] = {
            "code": code,
            "name": str(item.get("name") or "").strip(),
            "severity": "high",
            "flags": flags,
            "summary": str(item.get("announcement_summary") or "").strip()[:160],
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
    cleaned = (raw or "").strip()
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

    headline = str(parsed.get("headline") or "").strip()
    regime_interp = str(parsed.get("regime_interpretation") or "").strip()
    consensus_edge = str(parsed.get("consensus_and_ai_edge") or "").strip()
    if not headline or not regime_interp:
        raise ValueError("brief_json_missing_required_fields")

    warnings = [
        str(x).strip()
        for x in (parsed.get("risk_warnings") or [])
        if str(x).strip()
    ][:5]
    watches = [
        str(x).strip()
        for x in (parsed.get("watch_points") or [])
        if str(x).strip()
    ][:5]
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
    reg = report.get("market_regime") or {}
    stage_label = str(reg.get("regime_stage_label") or "-")
    stage = str(reg.get("regime_stage") or "-")
    adv = float(reg.get("advance_ratio_pct") or 0.0)
    med = reg.get("median_return_pct")
    med_txt = f"中位数 {float(med):+.2f}%" if med is not None else "中位数待统计"
    lu = int(reg.get("non_st_limit_up_count") or 0)
    ld = int(reg.get("non_st_limit_down_count") or 0)
    seal = reg.get("seal_rate_pct")
    seal_txt = f"{float(seal):.1f}%" if seal is not None else "-"
    prev_lu = reg.get("prev_limit_up_avg_return_pct")
    prev_txt = f"{float(prev_lu):+.2f}%" if prev_lu is not None else "-"
    max_streak = int(reg.get("max_consecutive_limit_up") or 0)
    amt = reg.get("total_amount_yi")
    amt_txt = f"{float(amt):.0f}亿" if amt is not None else "-"

    syn = report.get("cross_strategy_synthesis") or build_cross_strategy_synthesis(report)
    consensus = syn.get("consensus_picks") or []
    sectors = syn.get("sector_concentration") or []
    ann = report.get("announcement_risks") or {}
    flagged = ann.get("flagged_items") or []
    ai_hl = report.get("ai_highlights") or []
    stale_prefix = "【旧包降级】" if report.get("pack_is_stale") else ""

    headline = (
        f"{stale_prefix}市场处于{stage_label}({stage})，上涨 {adv:.1f}%（{med_txt}），"
        f"涨跌停 {lu}/{ld}（封板率 {seal_txt}）"
    )
    if flagged:
        headline += f"，公告排雷命中 {len(flagged)} 只高风险"
    elif consensus:
        headline += f"，跨策略共识 {len(consensus)} 只"

    regime_interpretation = (
        f"{report.get('trade_date', '-')} 盘面阶段判定为 {stage_label}({stage})（仅切片参考）："
        f"全市场上涨占比 {adv:.1f}%、{med_txt}，成交额 {amt_txt}；"
        f"非 ST 涨停 {lu} 只 / 跌停 {ld} 只，首板封板率 {seal_txt}，连板最高 {max_streak} 板，昨涨停今日均表现 {prev_txt}。"
    )

    parts: list[str] = []
    if consensus:
        top_c = "、".join(
            f"{c['code']}{c['name']}({c['strategy_count']}策略)" for c in consensus[:3]
        )
        parts.append(f"多策略共振标的前列：{top_c}")
    else:
        parts.append("当日各策略候选分散，未出现 ≥2 个策略共同命中的重合股")
    if sectors:
        top_s = "、".join(f"{s['industry']}({s['share_pct']}%)" for s in sectors[:3])
        parts.append(f"行业主要集中在 {top_s}")
    if ai_hl:
        added_n = sum(len(h.get("added_by_ai") or []) for h in ai_hl if isinstance(h, dict))
        dropped_n = sum(len(h.get("dropped_by_ai") or []) for h in ai_hl if isinstance(h, dict))
        parts.append(f"AI 赛道当日调仓累计新增 {added_n} 只 / 剔除 {dropped_n} 只")
    elif track_comparison:
        cn_cmp = [c for c in track_comparison if c.get("market") == "cn"]
        if cn_cmp:
            parts.append(f"当前已追踪 {len(cn_cmp)} 组 CN 规则 vs AI 同日配对样本")
    consensus_and_ai_edge = "；".join(parts) + "。"

    risk_warnings: list[str] = []
    if report.get("pack_is_stale"):
        risk_warnings.append(
            f"数据包滞后（包日期 {report.get('pack_trade_date')} < 目标日 {report.get('expected_trade_date')}），盘面与形态仅供参考。"
        )
    for item in flagged[:3]:
        fl = "/".join(str(x) for x in (item.get("negative_event_flags") or [])[:2])
        risk_warnings.append(f"公告预警：{item.get('code')} {item.get('name', '')} 命中 [{fl}]")
    if not flagged and int(ann.get("checked_count") or 0) > 0:
        risk_warnings.append(f"已抽检 {int(ann.get('checked_count') or 0)} 只核心候选，未触发减持/立案等负面关键词。")
    if ld >= 20 or (seal is not None and float(seal) < 55.0):
        risk_warnings.append(f"短线承接偏弱（非 ST 跌停 {ld} 只，封板率 {seal_txt}），警惕高位接力退潮风险。")
    if not risk_warnings:
        risk_warnings.append("关注次日开盘一字涨停导致的不可成交剔除以及市场成交额持续性。")

    watch_points = [
        f"观察次日上涨占比能否从 {adv:.1f}% 修复、跌停家数（{ld} 只）是否收敛；",
        f"跟踪昨日涨停溢价（{prev_txt}）与连板梯队（{max_streak} 板）高度延续情况；",
    ]
    if consensus:
        watch_points.append(
            f"复盘多策略共识标的（{consensus[0]['code']} {consensus[0]['name']} 等）次日开盘承接与换手。"
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
    reg = report.get("market_regime") or {}
    compact_context = {
        "trade_date": report.get("trade_date"),
        "pack_trade_date": report.get("pack_trade_date"),
        "pack_is_stale": bool(report.get("pack_is_stale", False)),
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
            "consensus_picks": (synthesis.get("consensus_picks") or [])[:5],
            "sector_concentration": (synthesis.get("sector_concentration") or [])[:5],
            "strategy_pattern_resonance": (synthesis.get("strategy_pattern_resonance") or [])[:5],
            "risk_spotlight": (synthesis.get("risk_spotlight") or [])[:5],
        },
        "ai_highlights": (report.get("ai_highlights") or [])[:4],
        "announcement_flagged": ((report.get("announcement_risks") or {}).get("flagged_items") or [])[:5],
        "paired_ai_track_summary": [
            {
                "strategy": item.get("strategy"),
                "common_days": item.get("common_days"),
                "t5": (item.get("windows") or {}).get("5"),
            }
            for item in (track_comparison or [])
            if item.get("market") == "cn"
        ][:4],
    }
    payload_json = json.dumps(compact_context, ensure_ascii=False)
    return (
        "你是 AlphaSift A 股量化观测系统的盘后投研编辑。请仅基于下面提供的结构化观测数据，"
        "用克制、客观、信息密度高的专业中文撰写盘后简报。\n"
        "严格约束：\n"
        "1. 禁止编造任何数据中不存在的股票代码、价格、涨跌幅、公告内容或目标价；\n"
        "2. 不给出任何买卖建议或收益承诺；\n"
        "3. 仅返回纯 JSON 对象（不要 Markdown 解释），包含字段：\n"
        '   {"headline": "不超过80字核心结论", '
        '"regime_interpretation": "120-240字盘面宽度与情绪结构解读", '
        '"consensus_and_ai_edge": "100-220字跨策略共识、行业集中与AI调仓对比解读", '
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
    timeout_sec: float = 20.0,
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
            config.llm_api_key
            or config.llm_channels
            or config.llm_config_path
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

    try:
        if llm_caller is not None:
            raw_text = llm_caller(prompt)
        else:
            from alphasift.ranker import _call_llm

            assert config is not None
            raw_text = _call_llm(
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
                timeout_sec=min(float(timeout_sec), float(config.llm_timeout_sec)),
                max_tokens=900,
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
        "model": model_name,
        "headline": parsed["headline"],
        "regime_interpretation": parsed["regime_interpretation"],
        "consensus_and_ai_edge": parsed["consensus_and_ai_edge"],
        "risk_warnings": parsed["risk_warnings"],
        "watch_points": parsed["watch_points"],
        "disclaimer": BRIEF_DISCLAIMER,
        "fallback_reason": None,
    }
