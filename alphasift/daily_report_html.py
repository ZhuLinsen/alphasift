# -*- coding: utf-8 -*-
"""Standalone, self-contained printable HTML renderer for CN DailyReport payloads."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from alphasift.daily_brief import BRIEF_DISCLAIMER

_DIST_BUCKETS: tuple[tuple[str, str, str], ...] = (
    ("le_neg7", "≤-7%", "down"),
    ("neg7_neg3", "-7~-3%", "down"),
    ("neg3_0", "-3~0%", "down"),
    ("flat", "平盘", "flat"),
    ("pos0_3", "0~3%", "up"),
    ("pos3_7", "3~7%", "up"),
    ("ge_pos7", "≥7%", "up"),
)
_GITHUB_URL = "https://github.com/ZhuLinsen/alphasift"


def _esc(val: object) -> str:
    return html.escape("" if val is None else str(val), quote=True)


def _fmt_pct(val: object, digits: int = 2) -> str:
    if val is None:
        return '<span class="dim">–</span>'
    try:
        num = float(val)
    except (TypeError, ValueError):
        return '<span class="dim">–</span>'
    if num != num:
        return '<span class="dim">–</span>'
    cls = "up" if num > 0 else ("down" if num < 0 else "")
    sign = "+" if num > 0 else ""
    return f'<span class="{cls}">{sign}{num:.{digits}f}%</span>'


def _fmt_num(val: object, digits: int = 1, suffix: str = "") -> str:
    if val is None:
        return '<span class="dim">–</span>'
    try:
        num = float(val)
    except (TypeError, ValueError):
        return '<span class="dim">–</span>'
    if num != num:
        return '<span class="dim">–</span>'
    return f"{num:.{digits}f}{suffix}"


def _render_dist_svg(dist: dict[str, Any] | None) -> str:
    if not isinstance(dist, dict) or not dist:
        return '<div class="empty">暂无涨跌幅分布统计</div>'
    counts = [int(dist.get(k) or 0) for k, _, _ in _DIST_BUCKETS]
    max_v = max(1, *counts)
    width, height, top, bot = 360, 120, 18, 22
    bar_h = height - top - bot
    step = width / len(_DIST_BUCKETS)
    bw = step * 0.58
    parts: list[str] = []
    for idx, (_key, label, tone) in enumerate(_DIST_BUCKETS):
        val = counts[idx]
        h = max(4.0 if val > 0 else 0.0, (val / max_v) * bar_h)
        x = idx * step + (step - bw) / 2.0
        y = top + (bar_h - h)
        fill = "var(--up)" if tone == "up" else ("var(--down)" if tone == "down" else "var(--muted)")
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="3" fill="{fill}" opacity="0.88"/>'
        )
        parts.append(
            f'<text x="{x + bw / 2:.1f}" y="{max(12.0, y - 4):.1f}" text-anchor="middle" font-size="10" '
            f'font-family="var(--font-mono)" fill="var(--ink-2)">{val}</text>'
        )
        parts.append(
            f'<text x="{x + bw / 2:.1f}" y="{height - 5}" text-anchor="middle" font-size="10" '
            f'font-family="var(--font-mono)" fill="var(--muted)">{_esc(label)}</text>'
        )
    return f'<svg class="dist-svg" viewBox="0 0 {width} {height}" role="img" aria-label="A股7档涨跌幅分布">{"".join(parts)}</svg>'


def _render_mini_kline_svg(bars: list[Any] | None) -> str:
    if not isinstance(bars, list) or not bars:
        return '<span class="dim">–</span>'
    parsed: list[tuple[float, float, float, float]] = []
    for item in bars:
        if isinstance(item, (list, tuple)) and len(item) >= 4:
            try:
                parsed.append((float(item[0]), float(item[1]), float(item[2]), float(item[3])))
            except (TypeError, ValueError):
                continue
    if not parsed:
        return '<span class="dim">–</span>'
    lo = min(b[2] for b in parsed)
    hi = max(b[1] for b in parsed)
    span = max(hi - lo, hi * 0.005, 1e-6)
    w, h, pad = 96, 28, 2
    step = (w - pad * 2) / len(parsed)
    bw = max(1.8, step * 0.65)
    shapes: list[str] = []
    for i, (o, hi_p, lo_p, c) in enumerate(parsed):
        cx = pad + (i + 0.5) * step
        col = "var(--up)" if c >= o else "var(--down)"
        y_hi = pad + (1.0 - (hi_p - lo) / span) * (h - pad * 2)
        y_lo = pad + (1.0 - (lo_p - lo) / span) * (h - pad * 2)
        y_top = pad + (1.0 - (max(o, c) - lo) / span) * (h - pad * 2)
        y_bot = pad + (1.0 - (min(o, c) - lo) / span) * (h - pad * 2)
        bh = max(1.4, y_bot - y_top)
        shapes.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{y_hi:.1f}" y2="{y_lo:.1f}" stroke="{col}" stroke-width="1"/>')
        shapes.append(f'<rect x="{cx - bw / 2:.1f}" y="{y_top:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="0.5" fill="{col}"/>')
    return f'<svg class="kline" viewBox="0 0 {w} {h}" aria-label="近{len(parsed)}日K线">{"".join(shapes)}</svg>'


def _render_ladder(ladder: dict[str, Any] | None) -> str:
    if not isinstance(ladder, dict) or not ladder:
        return '<div class="empty">今日无非 ST 连板或首板分布</div>'
    items = sorted(((int(k), int(v)) for k, v in ladder.items() if int(v or 0) > 0), reverse=True)
    if not items:
        return '<div class="empty">今日无非 ST 连板分布</div>'
    max_cnt = max(1, *(cnt for _, cnt in items))
    rows = []
    for board, cnt in items:
        w = max(8.0, (cnt / max_cnt) * 100.0)
        rows.append(
            f'<div class="ladder-row"><span>{board}板</span>'
            f'<div class="ladder-track"><div class="ladder-fill" style="width:{w:.1f}%"></div></div>'
            f'<span class="ladder-num">{cnt} 只</span></div>'
        )
    return f'<div class="ladder-list">{"".join(rows)}</div>'


def _render_case_studies(track_summary: dict[str, Any] | None) -> str:
    if not isinstance(track_summary, dict):
        return ""
    comparisons = track_summary.get("track_comparison") or []
    cards: list[str] = []
    for cmp in comparisons:
        if not isinstance(cmp, dict):
            continue
        windows = cmp.get("windows") or {}
        win = windows.get("5") or next(iter(windows.values()), {})
        cases = (win or {}).get("ai_case_studies") or {}
        adds = cases.get("best_ai_adds") or []
        avoids = cases.get("best_ai_avoids") or []
        misses = cases.get("missed_by_ai") or []
        if not (adds or avoids or misses):
            continue
        strat = (track_summary.get("strategy_names") or {}).get(cmp.get("strategy"), cmp.get("strategy"))
        bits: list[str] = []
        if adds:
            bits.append(
                "<li><b>AI 独选高光：</b>"
                + "；".join(f"{_esc(x.get('date'))} {_esc(x.get('name'))}({_esc(x.get('code'))}) {_fmt_pct(x.get('excess_return_pct'))}" for x in adds)
                + "</li>"
            )
        if avoids:
            bits.append(
                "<li><b>AI 避坑剔除：</b>"
                + "；".join(f"{_esc(x.get('date'))} {_esc(x.get('name'))}({_esc(x.get('code'))}) {_fmt_pct(x.get('excess_return_pct'))}" for x in avoids)
                + "</li>"
            )
        if misses:
            bits.append(
                "<li><b>AI 错杀遗憾：</b>"
                + "；".join(f"{_esc(x.get('date'))} {_esc(x.get('name'))}({_esc(x.get('code'))}) {_fmt_pct(x.get('excess_return_pct'))}" for x in misses)
                + "</li>"
            )
        cards.append(
            f'<div class="card"><div class="card-top"><h3><span>{_esc(strat)}</span><span class="badge ai">T+5 实盘案例</span></h3></div>'
            f'<ul class="bullet-list" style="padding:10px 14px 12px 28px;margin:0;">{"".join(bits)}</ul></div>'
        )
    if not cards:
        return ""
    return f'<div style="margin-top:14px;"><h3 class="subhead">历史同日配对 · AI 个股级案例复盘</h3><div class="grid">{"".join(cards)}</div></div>'


def render_daily_report_html(
    report: dict[str, Any],
    *,
    track_summary: dict[str, Any] | None = None,
) -> str:
    """Render a standalone, dependency-free, printable HTML daily research report."""
    trade_date = _esc(report.get("trade_date") or "-")
    pack_date = _esc(report.get("pack_trade_date") or "-")
    detail_url = str(report.get("detail_url") or "").strip() or "../index.html"
    is_stale = bool(report.get("pack_is_stale"))
    stale_reason = str(report.get("stale_reason") or "").strip()

    reg = report.get("market_regime") or {}
    syn = report.get("cross_strategy_synthesis") or {}
    brief = report.get("ai_brief") or {}
    ann = report.get("announcement_risks") or {}
    strategies = report.get("strategies") or []
    ai_hl = report.get("ai_highlights") or []
    pat_sec = report.get("patterns") or {}
    degradation = report.get("degradation") or []
    strategy_names = (track_summary.get("strategy_names") or {}) if isinstance(track_summary, dict) else {}

    def _sname(key: object) -> str:
        raw = "" if key is None else str(key)
        return _esc(strategy_names.get(raw) or raw)

    # 1. Brief / Executive Summary
    brief_mode = str(brief.get("mode") or "rule_fallback")
    brief_badge = (
        f'<span class="badge ai">AI 深度合成 · {_esc(brief.get("model") or "LLM")}</span>'
        if brief_mode == "llm"
        else '<span class="badge accent">规则统计合成</span>'
    )
    warn_items = "".join(f"<li>{_esc(w)}</li>" for w in (brief.get("risk_warnings") or []))
    watch_items = "".join(f"<li>{_esc(w)}</li>" for w in (brief.get("watch_points") or []))
    brief_block = f"""
    <section class="panel brief-box">
      <div class="sec-head"><h2>盘后要点综述</h2>{brief_badge}</div>
      <div class="brief-headline">{_esc(brief.get("headline") or "暂无摘要")}</div>
      <div class="grid two-col">
        <div class="sub-panel">
          <h3 class="subhead">盘面宽度与情绪</h3>
          <p class="prose">{_esc(brief.get("regime_interpretation") or "-")}</p>
        </div>
        <div class="sub-panel">
          <h3 class="subhead">策略共振与 AI 观察</h3>
          <p class="prose">{_esc(brief.get("consensus_and_ai_edge") or "-")}</p>
        </div>
      </div>
      <div class="grid two-col" style="margin-top:10px;">
        <div class="sub-panel"><h3 class="subhead">风险提示</h3><ul class="bullet-list">{warn_items or "<li>无额外提示</li>"}</ul></div>
        <div class="sub-panel"><h3 class="subhead">次日观察点</h3><ul class="bullet-list">{watch_items or "<li>关注开盘量能变化</li>"}</ul></div>
      </div>
    </section>
    """

    # 2. Panorama Section
    adv_pct = _fmt_num(reg.get("advance_ratio_pct"), 1, "%")
    med_pct = _fmt_pct(reg.get("median_return_pct"))
    amt_str = _fmt_num(reg.get("total_amount_yi"), 0, " 亿")
    seal_str = _fmt_num(reg.get("seal_rate_pct"), 1, "%")
    prev_lu = _fmt_pct(reg.get("prev_limit_up_avg_return_pct"))
    lu = int(reg.get("non_st_limit_up_count") or 0)
    ld = int(reg.get("non_st_limit_down_count") or 0)
    max_streak = int(reg.get("max_consecutive_limit_up") or 0)
    stage_txt = f"{_esc(reg.get('regime_stage_label') or '-')} ({_esc(reg.get('regime_stage') or '-')}) [仅切片]"

    panorama_block = f"""
    <section class="panel" style="padding:0;overflow:hidden;">
      <div class="sec-head" style="padding:14px 18px 10px;margin:0;">
        <h2>A 股盘面全景（{trade_date}）</h2>
        <span class="badge accent">{stage_txt}</span>
      </div>
      <div class="kpi-strip">
        <div class="kpi-cell"><div class="lbl">上涨占比</div><div class="val">{adv_pct}</div><div class="sub">涨 {int(reg.get('advancing_count') or 0)} / 跌 {int(reg.get('declining_count') or 0)}</div></div>
        <div class="kpi-cell"><div class="lbl">全市场中位数</div><div class="val">{med_pct}</div><div class="sub">成交 {int(reg.get('traded_count') or 0)} 只</div></div>
        <div class="kpi-cell"><div class="lbl">两市成交额</div><div class="val">{amt_str}</div><div class="sub">封板率 {seal_str}</div></div>
        <div class="kpi-cell"><div class="lbl">非ST 涨停 / 跌停</div><div class="val"><span class="up">{lu}</span> / <span class="down">{ld}</span></div><div class="sub">一字 {int(reg.get('one_price_limit_up_count') or 0)}/{int(reg.get('one_price_limit_down_count') or 0)}</div></div>
        <div class="kpi-cell"><div class="lbl">连板最高</div><div class="val">{max_streak} 板</div><div class="sub">炸板 {int(reg.get('non_st_broken_board_count') or 0)} 只</div></div>
        <div class="kpi-cell"><div class="lbl">昨涨停今日均收益</div><div class="val">{prev_lu}</div><div class="sub">红盘率 {_fmt_num(reg.get('prev_limit_up_win_rate_pct'), 1, '%')}</div></div>
      </div>
      <div class="grid two-col" style="padding:14px 18px 18px;">
        <div class="sub-panel"><h3 class="subhead">7 档涨跌幅分布</h3>{_render_dist_svg(reg.get("return_distribution"))}</div>
        <div class="sub-panel"><h3 class="subhead">连板高度梯队</h3>{_render_ladder(reg.get("consecutive_board_ladder"))}</div>
      </div>
    </section>
    """

    # 3. Announcement Risk Alerts & Spotlight
    flagged = ann.get("flagged_items") or []
    spotlight = syn.get("risk_spotlight") or []
    checked = int(ann.get("checked_count") or 0)
    if flagged:
        flag_cards = "".join(
            f'<div class="alert-card"><b>{_esc(x.get("code"))} {_esc(x.get("name"))}</b> '
            f'<span class="badge bad">{_esc("/".join(x.get("negative_event_flags") or []))}</span>'
            f'<div class="small dim" style="margin-top:3px;">{_esc(x.get("announcement_summary") or "触发公告负面关键词")}</div></div>'
            for x in flagged
        )
    elif checked > 0:
        flag_cards = f'<div class="ok-box">✓ 已核验 {checked} 只重点候选，暂未发现减持 / 立案 / 退市等负面关键词。</div>'
    else:
        flag_cards = '<div class="dim small">本期日报跳过公告抽检或无候选股。</div>'
    extra_risk = "".join(
        f'<li>{_esc(r.get("code"))} {_esc(r.get("name"))} <span class="badge">{_esc("/".join(r.get("flags") or []))}</span></li>'
        for r in spotlight
        if r.get("source") != "announcement"
    )
    ann_block = f"""
    <section class="panel {'alert-hot' if flagged else ''}">
      <div class="sec-head">
        <h2>⚠️ 公告排雷与风险聚焦</h2>
        <span class="badge {'bad' if flagged else ''}">抽检 {checked} · 高风险 {len(flagged)}</span>
      </div>
      {flag_cards}
      {f'<div style="margin-top:8px;"><span class="small dim">候选附加风控标签：</span><ul class="bullet-list">{extra_risk}</ul></div>' if extra_risk else ""}
    </section>
    """

    # 4. Cross-strategy Consensus, Sector Concentration & AI Attribution
    consensus = syn.get("consensus_picks") or []
    if consensus:
        c_rows_parts: list[str] = []
        for idx, c in enumerate(consensus, start=1):
            ann_str = _esc("/".join(c.get("announcement_risk_flags") or [])) or '<span class="dim">–</span>'
            strat_list = list(c.get("strategies") or [])
            strat_badges = "".join(f'<span class="badge">{_sname(st)}</span>' for st in strat_list[:3])
            if len(strat_list) > 3:
                strat_badges += f' <span class="dim small">+{len(strat_list) - 3}</span>'
            c_rows_parts.append(
                f'<tr><td><span class="rank-num {"top" if idx <= 3 else ""}">{idx}</span></td>'
                f'<td class="l"><strong>{_esc(c.get("name"))}</strong> <span class="mono dim small">{_esc(c.get("code"))}</span></td>'
                f'<td class="l dim">{_esc(c.get("industry"))}</td>'
                f'<td><span class="badge accent">{int(c.get("strategy_count") or 0)} 策略</span></td>'
                f'<td class="l">{strat_badges}</td>'
                f'<td class="mono">{_fmt_num(c.get("avg_final_score"), 1)}</td>'
                f'<td class="mono">{_fmt_pct(c.get("change_pct"))}</td>'
                f'<td class="l">{ann_str}</td></tr>'
            )
        consensus_html = (
            '<div class="scroll"><table><thead><tr><th>#</th><th class="l">股票</th><th class="l">行业</th><th>命中策略数</th>'
            '<th class="l">覆盖策略</th><th>均分</th><th>涨跌</th><th class="l">公告预警</th></tr></thead>'
            f'<tbody>{"".join(c_rows_parts)}</tbody></table></div>'
        )
    else:
        consensus_html = '<div class="empty">今日暂无 ≥2 个策略同时选中的共识标的。</div>'

    sectors = syn.get("sector_concentration") or []
    sector_html = (
        "".join(
            f'<div class="ladder-row"><span>{_esc(s.get("industry"))}</span>'
            f'<div class="ladder-track"><div class="ladder-fill accent-bg" style="width:{min(100.0, float(s.get("share_pct") or 0.0)):.1f}%"></div></div>'
            f'<span class="ladder-num">{int(s.get("pick_count") or 0)} ({_fmt_num(s.get("share_pct"), 1, "%")})</span></div>'
            for s in sectors
        )
        or '<div class="dim small">暂无行业分布</div>'
    )

    ai_cards_parts: list[str] = []
    for h in ai_hl:
        overlap_txt = _fmt_num(h.get("overlap_pct"), 1, "%") if h.get("overlap_pct") is not None else "–"
        mv = h.get("llm_market_view")
        view_html = f"<div><b>市场观点：</b>{_esc(mv)}</div>" if mv else ""
        added_names = "、".join(f'{x.get("name")}({x.get("code")})' for x in (h.get("added_by_ai") or [])) or "无"
        dropped_names = "、".join(f'{x.get("name")}({x.get("code")})' for x in (h.get("dropped_by_ai") or [])) or "无"
        ai_cards_parts.append(
            f'<div class="card"><div class="card-top"><h3><span>{_sname(h.get("strategy"))}</span><span class="badge ai">AI 调仓</span></h3>'
            f'<div class="sub">重合度 {overlap_txt} · 规则 {int(h.get("rules_pick_count") or 0)} / AI {int(h.get("ai_pick_count") or 0)}</div></div>'
            f'<div class="prose small" style="padding:10px 14px;">{view_html}'
            f'<div><b>AI 新增：</b>{_esc(added_names)}</div>'
            f'<div><b>AI 剔除：</b>{_esc(dropped_names)}</div>'
            "</div></div>"
        )
    ai_cards = "".join(ai_cards_parts)

    resonance = syn.get("strategy_pattern_resonance") or []
    res_html = (
        '<ul class="bullet-list">'
        + "".join(
            f'<li><b>{_esc(r.get("code"))} {_esc(r.get("name"))}</b> · 策略[{", ".join(_sname(s) for s in (r.get("strategies") or []))}] × '
            f'形态[{_esc(", ".join([*(r.get("active_patterns") or []), *(r.get("experimental_patterns") or [])]))}]</li>'
            for r in resonance
        )
        + "</ul>"
        if resonance
        else '<div class="dim small">今日策略候选与扫描形态暂无重叠个股。</div>'
    )

    synthesis_block = f"""
    <section class="panel">
      <div class="sec-head"><h2>跨策略共识、行业分布与 AI 归因</h2></div>
      <h3 class="subhead">多策略共识标的</h3>
      {consensus_html}
      <div class="grid two-col" style="margin-top:12px;">
        <div class="sub-panel"><h3 class="subhead">候选行业集中度</h3><div class="ladder-list">{sector_html}</div></div>
        <div class="sub-panel"><h3 class="subhead">策略 × 形态共振观察</h3>{res_html}</div>
      </div>
      {f'<div style="margin-top:12px;"><h3 class="subhead">今日 AI 调仓对比</h3><div class="grid">{ai_cards}</div></div>' if ai_cards else ""}
      {_render_case_studies(track_summary)}
    </section>
    """

    # 5. Strategy Picks Full Cards
    strat_cards = []
    for st in strategies:
        tr = "ai" if st.get("track") == "ai" or st.get("llm_ranked") else "rules"
        badge = '<span class="badge ai">AI</span>' if tr == "ai" else '<span class="badge">规则</span>'
        picks = st.get("picks") or []
        if picks:
            rows = "".join(
                f'<tr><td><span class="rank-num {"top" if int(pk.get("rank") or 9) <= 3 else ""}">{int(pk.get("rank") or 0)}</span></td>'
                f'<td class="l"><strong>{_esc(pk.get("name"))}</strong> <span class="mono dim small">{_esc(pk.get("code"))}</span></td>'
                f'<td class="l dim">{_esc(pk.get("industry"))}</td>'
                f'<td class="mono">{_fmt_num(pk.get("final_score"), 1)}</td>'
                f'<td class="mono">{_fmt_pct(pk.get("change_pct"))}</td>'
                f'<td class="l small">{_esc("/".join(pk.get("announcement_risk_flags") or [])) or _esc(pk.get("ranking_reason") or "–")}</td></tr>'
                for pk in picks
            )
            tbl = (
                '<div class="scroll"><table><thead><tr><th>#</th><th class="l">股票</th><th class="l">行业</th>'
                '<th>综合分</th><th>涨跌</th><th class="l">备注/风险</th></tr></thead>'
                f"<tbody>{rows}</tbody></table></div>"
            )
        else:
            tbl = '<div class="empty">无入选股票</div>'
        strat_cards.append(
            f'<div class="card"><div class="card-top"><h3><span>{_sname(st.get("strategy"))}</span>{badge}</h3>'
            f'<div class="sub">入选 {int(st.get("pick_count") or len(picks))} 只</div></div>{tbl}</div>'
        )
    strat_block = f"""
    <section class="panel">
      <div class="sec-head"><h2>今日策略精选全览</h2><span class="badge">{len(strategies)} 组运行</span></div>
      {f'<div class="grid">{"".join(strat_cards)}</div>' if strat_cards else '<div class="empty">未附加策略运行结果。</div>'}
    </section>
    """

    # 6. Pattern Radar Cards (active + muted experimental)
    pat_cards = []
    for bucket, is_active in (("active", True), ("experimental", False)):
        for pat in pat_sec.get(bucket) or []:
            dname = _esc(pat.get("display_name") or pat.get("pattern"))
            badge = '<span class="badge active">active</span>' if is_active else '<span class="badge">experimental</span>'
            sigs = pat.get("signals") or []
            if sigs:
                s_rows = "".join(
                    f'<tr><td class="l"><strong>{_esc(s.get("name"))}</strong> <span class="mono dim small">{_esc(s.get("code"))}</span></td>'
                    f'<td class="mono">{_fmt_pct(s.get("change_pct"))}</td>'
                    f'<td class="dim mono">{_fmt_num(s.get("overhead_supply_10pct"), 0, "%")}</td>'
                    f'<td>{_render_mini_kline_svg(s.get("kline"))}</td></tr>'
                    for s in sigs[:8]
                )
                body = f'<div class="scroll"><table><thead><tr><th class="l">股票</th><th>涨跌</th><th>上方套牢</th><th>近20日K线</th></tr></thead><tbody>{s_rows}</tbody></table></div>'
            else:
                body = '<div class="empty">今日无触发信号</div>'
            pat_cards.append(
                f'<div class="card {"muted-card" if not is_active else ""}"><div class="card-top"><h3><span>{dname}</span>{badge}</h3>'
                f'<div class="sub">命中 {int(pat.get("hit_count") or 0)} 只</div></div>{body}</div>'
            )
    pat_block = f"""
    <section class="panel">
      <div class="sec-head"><h2>无状态形态雷达命中</h2></div>
      <div class="grid">{"".join(pat_cards) if pat_cards else '<div class="empty">无形态扫描记录</div>'}</div>
    </section>
    """

    stale_html = (
        f'<div class="stale-banner">⚠️ <b>旧包降级模式</b>：数据包日期 <code>{pack_date}</code> 落后于目标交易日 '
        f'<code>{_esc(report.get("expected_trade_date"))}</code>（{_esc(stale_reason)}），数据仅供观察，已自动拦截未强制 IM 推送。</div>'
        if is_stale
        else ""
    )
    deg_html = (
        f'<div class="notice">降级说明：{"；".join(_esc(d) for d in degradation)}</div>'
        if degradation
        else ""
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AlphaSift · A 股盘后投研日报 ({trade_date})</title>
<style>
:root {{
  --bg: #09090b; --surface: #111115; --sub: #17171d; --ink: #f4f4f5; --ink-2: #d4d4d8;
  --muted: #8e8e9a; --border: rgba(255,255,255,0.085); --border-strong: rgba(255,255,255,0.16);
  --glass: rgba(9,9,11,0.82); --accent: #3b82f6; --accent-hi: #60a5fa; --accent-soft: rgba(59,130,246,0.14);
  --up: #f87171; --up-soft: rgba(248,113,113,0.12);
  --down: #34d399; --down-soft: rgba(52,211,153,0.12);
  --warn: #fbbf24; --warn-soft: rgba(251,191,36,0.14); --chip: rgba(255,255,255,0.06);
  --font-sans: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  --font-mono: "JetBrains Mono", "SFMono-Regular", ui-monospace, Menlo, Consolas, monospace;
}}
:root[data-theme="light"] {{
  --bg: #fafafa; --surface: #ffffff; --sub: #f4f4f5; --ink: #09090b; --ink-2: #27272a;
  --muted: #52525b; --border: rgba(9,9,11,0.09); --border-strong: rgba(9,9,11,0.18);
  --glass: rgba(250,250,250,0.88); --accent: #1d4ed8; --accent-hi: #2563eb; --accent-soft: rgba(37,99,235,0.1);
  --up: #dc2626; --up-soft: rgba(220,38,38,0.09);
  --down: #059669; --down-soft: rgba(5,150,105,0.1);
  --warn: #b45309; --warn-soft: rgba(180,83,9,0.1); --chip: rgba(9,9,11,0.055);
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; background-color: var(--bg); color: var(--ink);
  background-image: radial-gradient(ellipse 75% 340px at 50% -60px, var(--accent-soft), transparent 72%);
  font: 13.5px/1.6 var(--font-sans); -webkit-font-smoothing: antialiased;
}}
a {{ color: var(--accent-hi); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
code {{ font-family: var(--font-mono); font-size: 0.9em; background: var(--chip); padding: 1px 5px; border-radius: 5px; border: 1px solid var(--border); }}
.topbar {{
  position: sticky; top: 0; z-index: 40;
  background: var(--glass); border-bottom: 1px solid var(--border); backdrop-filter: blur(12px);
}}
.topbar-inner {{
  max-width: 1180px; margin: 0 auto; padding: 10px 20px;
  display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px;
}}
.brand {{ display: inline-flex; align-items: center; gap: 9px; font-weight: 700; font-size: 15px; color: var(--ink); }}
.brand-mark {{
  width: 24px; height: 24px; border-radius: 6px; display: inline-flex; align-items: center; justify-content: center;
  background: var(--sub); border: 1px solid var(--border-strong); color: var(--accent-hi);
}}
.actions {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
.btn-link, .theme-btn, .github-btn {{
  display: inline-flex; align-items: center; gap: 6px;
  border: 1px solid var(--border); background: var(--surface); color: var(--ink-2);
  border-radius: 8px; padding: 5px 11px; font: inherit; font-size: 12px; font-weight: 500; cursor: pointer; text-decoration: none;
}}
.btn-link:hover, .theme-btn:hover {{ border-color: var(--border-strong); color: var(--ink); text-decoration: none; }}
.github-btn {{ background: var(--ink); color: var(--bg); border-color: var(--ink); font-weight: 600; }}
.github-btn:hover {{ opacity: 0.9; text-decoration: none; color: var(--bg); }}

main {{ max-width: 1180px; margin: 0 auto; padding: 24px 20px 60px; }}
.rpt-header {{
  padding-bottom: 16px; border-bottom: 1px solid var(--border);
}}
.rpt-header h1 {{ margin: 4px 0 8px; font-size: clamp(21px, 2.5vw, 27px); letter-spacing: -0.025em; }}
.eyebrow {{ font-family: var(--font-mono); font-size: 11px; font-weight: 600; letter-spacing: 0.08em; color: var(--accent-hi); }}
.meta-row {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 12px; color: var(--muted); font-family: var(--font-mono); }}

.panel {{
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 16px 18px; margin-top: 18px;
}}
.panel.alert-hot {{ border-color: rgba(248,113,113,0.45); }}
.brief-box {{ border-left: 3px solid var(--accent-hi); }}
.brief-headline {{ font-size: 16px; font-weight: 700; margin: 4px 0 12px; color: var(--ink); letter-spacing: -0.01em; }}
.sec-head {{ display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }}
.sec-head h2 {{ margin: 0; font-size: 16px; font-weight: 700; letter-spacing: -0.01em; }}
.subhead {{ margin: 0 0 6px; font-size: 13px; font-weight: 700; color: var(--ink); }}
.sub-panel {{ background: var(--sub); border: 1px solid var(--border); border-radius: 9px; padding: 12px 14px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 12px; }}
.two-col {{ grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }}
.card {{
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; break-inside: avoid;
}}
.card-top {{ padding: 10px 13px 8px; border-bottom: 1px solid var(--border); background: var(--sub); }}
.card h3 {{ margin: 0; font-size: 13.5px; display: flex; justify-content: space-between; align-items: center; gap: 8px; }}
.card .sub {{ font-size: 11.5px; color: var(--muted); margin-top: 2px; font-family: var(--font-mono); }}
.muted-card {{ opacity: 0.72; }}

.kpi-strip {{
  display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 1px;
  background: var(--border); border-top: 1px solid var(--border); border-bottom: 1px solid var(--border);
}}
.kpi-cell {{ background: var(--sub); padding: 11px 13px; }}
.kpi-cell .lbl {{ font-size: 11px; color: var(--muted); }}
.kpi-cell .val {{ font-size: 16px; font-weight: 700; margin-top: 2px; font-variant-numeric: tabular-nums; font-family: var(--font-mono); }}
.kpi-cell .sub {{ font-size: 11px; color: var(--muted); margin-top: 2px; }}
@media (max-width: 960px) {{ .kpi-strip {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }} }}
@media (max-width: 600px) {{ .kpi-strip {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}

.badge {{
  display: inline-block; padding: 1px 7px; border-radius: 5px; font-size: 11px; font-weight: 600;
  background: var(--chip); color: var(--muted); border: 1px solid var(--border); vertical-align: middle;
}}
.badge.ai, .badge.accent {{ color: var(--accent-hi); background: var(--accent-soft); border-color: rgba(59,130,246,0.3); }}
.badge.active, .badge.ok {{ color: var(--down); background: var(--down-soft); border-color: rgba(52,211,153,0.3); }}
.badge.bad {{ color: var(--up); background: var(--up-soft); border-color: rgba(248,113,113,0.3); }}
.badge.warn {{ color: var(--warn); background: var(--warn-soft); border-color: rgba(251,191,36,0.3); }}

.rank-num {{
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 20px; height: 18px; border-radius: 4px; padding: 0 4px;
  font-family: var(--font-mono); font-size: 11px; font-weight: 600; background: var(--chip); color: var(--muted);
}}
.rank-num.top {{ background: var(--accent-soft); color: var(--accent-hi); }}

.stale-banner {{
  margin-top: 12px; padding: 10px 14px; border-radius: 9px; background: var(--warn-soft);
  border: 1px solid rgba(251,191,36,0.38); font-size: 12.5px;
}}
.notice {{
  margin-top: 12px; padding: 9px 12px; border-radius: 8px; background: var(--surface);
  border: 1px solid var(--border); border-left: 3px solid var(--warn); color: var(--muted); font-size: 12.5px;
}}
.alert-card {{
  padding: 10px 12px; border-radius: 8px; background: var(--up-soft); border: 1px solid rgba(248,113,113,0.28); margin-bottom: 8px;
}}
.ok-box {{
  padding: 9px 12px; border-radius: 8px; background: var(--down-soft); border: 1px solid rgba(52,211,153,0.25);
  color: var(--down); font-size: 12.5px;
}}
.bullet-list {{ margin: 4px 0 0 18px; padding: 0; font-size: 12.5px; color: var(--ink-2); }}
.bullet-list li {{ margin-bottom: 4px; }}
.prose {{ margin: 0; font-size: 13px; color: var(--ink-2); }}
.dist-svg {{ width: 100%; height: 120px; display: block; }}
.kline {{ width: 96px; height: 28px; display: inline-block; vertical-align: middle; }}
.ladder-list {{ display: flex; flex-direction: column; gap: 6px; }}
.ladder-row {{ display: grid; grid-template-columns: 78px 1fr 78px; align-items: center; gap: 8px; font-size: 12px; }}
.ladder-track {{ background: var(--chip); border-radius: 999px; height: 7px; overflow: hidden; }}
.ladder-fill {{ height: 100%; border-radius: 999px; background: var(--up); }}
.accent-bg {{ background: var(--accent-hi); }}
.ladder-num {{ text-align: right; font-weight: 600; font-variant-numeric: tabular-nums; font-family: var(--font-mono); }}
.scroll {{ overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }}
th, td {{ padding: 7px 10px; text-align: right; white-space: nowrap; border-bottom: 1px solid var(--border); font-size: 12px; }}
th {{ color: var(--muted); font-weight: 600; font-size: 11px; background: var(--sub); }}
th.l, td.l, th:first-child, td:first-child {{ text-align: left; }}
tr:last-child td {{ border-bottom: 0; }}
.up {{ color: var(--up); }} .down {{ color: var(--down); }} .dim {{ color: var(--muted); }}
.small {{ font-size: 11.5px; }} .mono {{ font-family: var(--font-mono); }}
.ico {{ width: 13.5px; height: 13.5px; display: inline-block; vertical-align: -2px; flex-shrink: 0; }}
.empty {{ padding: 14px; text-align: center; color: var(--muted); font-size: 12.5px; }}
footer {{ margin-top: 32px; padding-top: 16px; border-top: 1px solid var(--border); color: var(--muted); font-size: 12px; }}
@media print {{
  .no-print, .topbar {{ display: none !important; }}
  :root {{ --bg: #ffffff; --surface: #ffffff; --sub: #f8fafc; --ink: #111111; --ink-2: #222222; --muted: #555555; --border: #dddddd; }}
  body {{ background: #ffffff; color: #111111; }}
  main {{ max-width: 100%; padding: 0; }}
  .panel {{ box-shadow: none; break-inside: avoid; border-color: #dddddd; }}
}}
</style>
</head>
<body>
<nav class="topbar no-print">
  <div class="topbar-inner">
    <span class="brand">
      <span class="brand-mark" aria-hidden="true">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 5h18l-7 8v5l-4 2v-7L3 5z"/>
        </svg>
      </span>
      <span>AlphaSift · 盘后研报</span>
    </span>
    <div class="actions">
      <a class="btn-link" href="{_esc(detail_url)}">
        <svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>
        <span>返回在线看板</span>
      </a>
      <a class="github-btn" href="{_GITHUB_URL}" target="_blank" rel="noopener">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.57.11.78-.25.78-.55 0-.27-.01-1.18-.02-2.14-3.2.7-3.87-1.36-3.87-1.36-.52-1.33-1.28-1.68-1.28-1.68-1.05-.72.08-.71.08-.71 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.71 1.26 3.37.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.29 1.19-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11.06 11.06 0 0 1 5.78 0c2.21-1.49 3.18-1.18 3.18-1.18.63 1.59.23 2.76.11 3.05.74.8 1.19 1.83 1.19 3.09 0 4.42-2.69 5.39-5.26 5.68.41.36.78 1.06.78 2.15 0 1.55-.01 2.8-.01 3.18 0 .31.21.67.79.55C20.21 21.39 23.5 17.08 23.5 12 23.5 5.65 18.35.5 12 .5z"/>
        </svg>
        <span>GitHub</span>
      </a>
      <button type="button" class="theme-btn" onclick="window.print()">
        <svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
        <span>打印 / PDF</span>
      </button>
      <button type="button" class="theme-btn" id="theme-toggle">亮色</button>
    </div>
  </div>
</nav>
<main>
  <header class="rpt-header">
    <div class="eyebrow">OPEN-SOURCE DAILY QUANTITATIVE RESEARCH BRIEF</div>
    <h1>AlphaSift · A 股盘后量化投研日报</h1>
    <div class="meta-row">
      <span>交易日 <b>{trade_date}</b></span>
      <span>· 数据包 <code>{pack_date}</code></span>
      <span class="badge {'warn' if is_stale else 'ok'}">{'旧包降级' if is_stale else '数据同步'}</span>
      <span>· 口径：<code>{_esc(report.get('usage_policy') or 'cn_only')}</code></span>
    </div>
  </header>
  {stale_html}
  {deg_html}
  {brief_block}
  {panorama_block}
  {ann_block}
  {synthesis_block}
  {strat_block}
  {pat_block}
  <footer>{_esc(BRIEF_DISCLAIMER)} · 量化形态观测与回测基准 · <a href="{_GITHUB_URL}">GitHub 开源仓库</a> · Generated {_esc(report.get("generated_at") or "")}</footer>
</main>
<script>
(function () {{
  var theme = "dark";
  try {{
    var q = new URLSearchParams(window.location.search).get("theme");
    var saved = localStorage.getItem("alphasift-theme");
    if (q === "light" || q === "dark") theme = q;
    else if (saved === "light" || saved === "dark") theme = saved;
  }} catch (e) {{}}
  document.documentElement.setAttribute("data-theme", theme);
  var ICO_SUN = '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32 1.41 1.41M2 12h2m16 0h2M4.93 19.07l1.41-1.41m11.32-11.32 1.41-1.41"/></svg>';
  var ICO_MOON = '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
  var btn = document.getElementById("theme-toggle");
  function sync(t) {{ if (btn) btn.innerHTML = t === "light" ? ICO_MOON + "<span>暗色</span>" : ICO_SUN + "<span>亮色</span>"; }}
  sync(theme);
  if (btn) {{
    btn.addEventListener("click", function () {{
      var cur = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
      var next = cur === "light" ? "dark" : "light";
      document.documentElement.setAttribute("data-theme", next);
      sync(next);
      try {{ localStorage.setItem("alphasift-theme", next); }} catch (e) {{}}
    }});
  }}
}})();
</script>
</body>
</html>
"""


def write_daily_report_html(
    output_path: str | Path,
    report: dict[str, Any],
    *,
    track_summary: dict[str, Any] | None = None,
) -> Path:
    """Render and write a standalone HTML daily report to disk."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_daily_report_html(report, track_summary=track_summary),
        encoding="utf-8",
    )
    return path
