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
    bw = step * 0.56
    parts: list[str] = []
    for idx, (_key, label, tone) in enumerate(_DIST_BUCKETS):
        val = counts[idx]
        h = max(3.0 if val > 0 else 0.0, (val / max_v) * bar_h)
        x = idx * step + (step - bw) / 2.0
        y = top + (bar_h - h)
        fill = "var(--up)" if tone == "up" else ("var(--down)" if tone == "down" else "var(--muted)")
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="2.5" fill="{fill}" opacity="0.88"/>'
        )
        parts.append(
            f'<text x="{x + bw / 2:.1f}" y="{max(11.0, y - 4):.1f}" text-anchor="middle" font-size="10" fill="var(--ink)">{val}</text>'
        )
        parts.append(
            f'<text x="{x + bw / 2:.1f}" y="{height - 5}" text-anchor="middle" font-size="10" fill="var(--muted)">{_esc(label)}</text>'
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
    bw = max(1.5, step * 0.65)
    shapes: list[str] = []
    for i, (o, hi_p, lo_p, c) in enumerate(parsed):
        cx = pad + (i + 0.5) * step
        col = "var(--up)" if c >= o else "var(--down)"
        y_hi = pad + (1.0 - (hi_p - lo) / span) * (h - pad * 2)
        y_lo = pad + (1.0 - (lo_p - lo) / span) * (h - pad * 2)
        y_top = pad + (1.0 - (max(o, c) - lo) / span) * (h - pad * 2)
        y_bot = pad + (1.0 - (min(o, c) - lo) / span) * (h - pad * 2)
        bh = max(1.2, y_bot - y_top)
        shapes.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{y_hi:.1f}" y2="{y_lo:.1f}" stroke="{col}" stroke-width="1"/>')
        shapes.append(f'<rect x="{cx - bw / 2:.1f}" y="{y_top:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="{col}"/>')
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
            f'<div class="card"><h3>{_esc(strat)} <span class="badge ai">T+5 实盘案例</span></h3>'
            f'<ul class="bullet-list">{"".join(bits)}</ul></div>'
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
    detail_url = str(report.get("detail_url") or "").strip()
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

    # 1. Brief / Executive Summary
    brief_mode = str(brief.get("mode") or "rule_fallback")
    brief_badge = (
        f'<span class="badge ai">AI 深度合成 · {_esc(brief.get("model") or "LLM")}</span>'
        if brief_mode == "llm"
        else '<span class="badge">规则统计合成</span>'
    )
    warn_items = "".join(f"<li>{_esc(w)}</li>" for w in (brief.get("risk_warnings") or []))
    watch_items = "".join(f"<li>{_esc(w)}</li>" for w in (brief.get("watch_points") or []))
    brief_block = f"""
    <section class="panel brief-box">
      <div class="sec-head"><h2>盘后要点综述 {brief_badge}</h2></div>
      <div class="brief-headline">{_esc(brief.get("headline") or "暂无摘要")}</div>
      <div class="grid two-col">
        <div>
          <h3 class="subhead">盘面宽度与情绪</h3>
          <p class="prose">{_esc(brief.get("regime_interpretation") or "-")}</p>
        </div>
        <div>
          <h3 class="subhead">策略共振与 AI 观察</h3>
          <p class="prose">{_esc(brief.get("consensus_and_ai_edge") or "-")}</p>
        </div>
      </div>
      <div class="grid two-col" style="margin-top:8px;">
        <div><h3 class="subhead">风险提示</h3><ul class="bullet-list">{warn_items or "<li>无额外提示</li>"}</ul></div>
        <div><h3 class="subhead">次日观察点</h3><ul class="bullet-list">{watch_items or "<li>关注开盘量能变化</li>"}</ul></div>
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
    <section class="panel">
      <div class="sec-head">
        <h2>A 股盘面全景（{trade_date}）</h2>
        <span class="badge accent">{stage_txt}</span>
      </div>
      <div class="kpi-grid">
        <div class="kpi"><div class="lbl">上涨占比</div><div class="val">{adv_pct}</div><div class="sub">涨 {int(reg.get('advancing_count') or 0)} / 跌 {int(reg.get('declining_count') or 0)}</div></div>
        <div class="kpi"><div class="lbl">全市场中位数</div><div class="val">{med_pct}</div><div class="sub">成交 {int(reg.get('traded_count') or 0)} 只</div></div>
        <div class="kpi"><div class="lbl">两市成交额</div><div class="val">{amt_str}</div><div class="sub">封板率 {seal_str}</div></div>
        <div class="kpi"><div class="lbl">非ST 涨停 / 跌停</div><div class="val"><span class="up">{lu}</span> / <span class="down">{ld}</span></div><div class="sub">一字 {int(reg.get('one_price_limit_up_count') or 0)}/{int(reg.get('one_price_limit_down_count') or 0)}</div></div>
        <div class="kpi"><div class="lbl">连板最高</div><div class="val">{max_streak} 板</div><div class="sub">炸板 {int(reg.get('non_st_broken_board_count') or 0)} 只</div></div>
        <div class="kpi"><div class="lbl">昨涨停今日均收益</div><div class="val">{prev_lu}</div><div class="sub">红盘率 {_fmt_num(reg.get('prev_limit_up_win_rate_pct'), 1, '%')}</div></div>
      </div>
      <div class="grid two-col" style="margin-top:12px;">
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
            f'<div class="small dim">{_esc(x.get("announcement_summary") or "触发公告负面关键词")}</div></div>'
            for x in flagged
        )
    elif checked > 0:
        flag_cards = f'<div class="ok-box">已核验 {checked} 只重点候选，暂未发现减持 / 立案 / 退市等负面关键词。</div>'
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
        for c in consensus:
            ann_str = _esc("/".join(c.get("announcement_risk_flags") or [])) or '<span class="dim">–</span>'
            c_rows_parts.append(
                f'<tr><td class="l">{_esc(c.get("name"))} <span class="dim small">{_esc(c.get("code"))}</span></td>'
                f'<td class="l dim">{_esc(c.get("industry"))}</td>'
                f'<td><b>{int(c.get("strategy_count") or 0)}</b></td>'
                f'<td class="l small">{_esc(", ".join(c.get("strategies") or []))}</td>'
                f'<td>{_fmt_num(c.get("avg_final_score"), 1)}</td>'
                f'<td>{_fmt_pct(c.get("change_pct"))}</td>'
                f'<td class="l">{ann_str}</td></tr>'
            )
        consensus_html = (
            '<div class="scroll"><table><tr><th class="l">股票</th><th class="l">行业</th><th>命中策略数</th>'
            '<th class="l">覆盖策略</th><th>均分</th><th>涨跌</th><th class="l">公告预警</th></tr>'
            f'{"".join(c_rows_parts)}</table></div>'
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
            f'<div class="card"><h3>{_esc(h.get("strategy"))} <span class="badge ai">AI 调仓</span></h3>'
            f'<div class="sub">重合度 {overlap_txt} · 规则 {int(h.get("rules_pick_count") or 0)} / AI {int(h.get("ai_pick_count") or 0)}</div>'
            f'<div class="prose small">{view_html}'
            f'<div><b>AI 新增：</b>{_esc(added_names)}</div>'
            f'<div><b>AI 剔除：</b>{_esc(dropped_names)}</div>'
            "</div></div>"
        )
    ai_cards = "".join(ai_cards_parts)

    resonance = syn.get("strategy_pattern_resonance") or []
    res_html = (
        "<ul class=\"bullet-list\">"
        + "".join(
            f'<li><b>{_esc(r.get("code"))} {_esc(r.get("name"))}</b> · 策略[{_esc(", ".join(r.get("strategies") or []))}] × '
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
                f'<tr><td>{int(pk.get("rank") or 0)}</td>'
                f'<td class="l">{_esc(pk.get("name"))} <span class="dim small">{_esc(pk.get("code"))}</span></td>'
                f'<td class="l dim">{_esc(pk.get("industry"))}</td>'
                f'<td>{_fmt_num(pk.get("final_score"), 1)}</td>'
                f'<td>{_fmt_pct(pk.get("change_pct"))}</td>'
                f'<td class="l small">{_esc("/".join(pk.get("announcement_risk_flags") or [])) or _esc(pk.get("ranking_reason") or "–")}</td></tr>'
                for pk in picks
            )
            tbl = (
                '<div class="scroll"><table><tr><th>#</th><th class="l">股票</th><th class="l">行业</th>'
                '<th>综合分</th><th>涨跌</th><th class="l">备注/风险</th></tr>'
                f"{rows}</table></div>"
            )
        else:
            tbl = '<div class="empty">无入选股票</div>'
        strat_cards.append(
            f'<div class="card"><h3>{_esc(st.get("strategy"))} {badge}</h3>'
            f'<div class="sub">入选 {int(st.get("pick_count") or len(picks))} 只</div>{tbl}</div>'
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
                    f'<tr><td class="l">{_esc(s.get("name"))} <span class="dim small">{_esc(s.get("code"))}</span></td>'
                    f'<td>{_fmt_pct(s.get("change_pct"))}</td>'
                    f'<td class="dim">{_fmt_num(s.get("overhead_supply_10pct"), 0, "%")}</td>'
                    f'<td>{_render_mini_kline_svg(s.get("kline"))}</td></tr>'
                    for s in sigs[:8]
                )
                body = f'<div class="scroll"><table><tr><th class="l">股票</th><th>涨跌</th><th>上方套牢</th><th>近20日K线</th></tr>{s_rows}</table></div>'
            else:
                body = '<div class="empty">今日无触发信号</div>'
            pat_cards.append(
                f'<div class="card {"muted-card" if not is_active else ""}"><h3>{dname} {badge}</h3>'
                f'<div class="sub">命中 {int(pat.get("hit_count") or 0)} 只</div>{body}</div>'
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
    dash_btn = (
        f'<a class="btn-link no-print" href="{_esc(detail_url)}">🌐 返回在线看板</a>'
        if detail_url
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
  --bg: #f4f6f9; --panel: #ffffff; --sub: #f8fafc; --ink: #171a1f; --muted: #646b75; --line: #e3e6ec;
  --accent: #2457d6; --accent-soft: rgba(36, 87, 214, 0.1);
  --up: #c8332b; --up-soft: rgba(200, 51, 43, 0.08);
  --down: #18864b; --down-soft: rgba(24, 134, 75, 0.09);
  --warn: #b26b00; --warn-soft: rgba(178, 107, 0, 0.12); --chip: #eef1f6;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg: #101318; --panel: #181c23; --sub: #1f242d; --ink: #e8eaee; --muted: #98a0ac; --line: #2a303b;
    --accent: #6c96ff; --accent-soft: rgba(108, 150, 255, 0.14);
    --up: #f1786d; --up-soft: rgba(241, 120, 109, 0.12);
    --down: #49c481; --down-soft: rgba(73, 196, 129, 0.12);
    --warn: #eab354; --warn-soft: rgba(234, 179, 84, 0.15); --chip: #232832;
  }}
}}
:root[data-theme="dark"] {{
  --bg: #101318; --panel: #181c23; --sub: #1f242d; --ink: #e8eaee; --muted: #98a0ac; --line: #2a303b;
  --accent: #6c96ff; --accent-soft: rgba(108, 150, 255, 0.14);
  --up: #f1786d; --up-soft: rgba(241, 120, 109, 0.12);
  --down: #49c481; --down-soft: rgba(73, 196, 129, 0.12);
  --warn: #eab354; --warn-soft: rgba(234, 179, 84, 0.15); --chip: #232832;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; background: var(--bg); color: var(--ink);
  font: 14px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}}
main {{ max-width: 1160px; margin: 0 auto; padding: 24px 16px 56px; }}
.rpt-header {{
  display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 14px;
}}
.rpt-header h1 {{ margin: 0 0 4px; font-size: 22px; }}
.meta-row {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 12px; color: var(--muted); }}
.actions {{ display: flex; gap: 8px; align-items: center; }}
.btn-link, .theme-btn {{
  border: 1px solid var(--line); background: var(--panel); color: var(--ink);
  border-radius: 7px; padding: 6px 12px; font: inherit; font-size: 12.5px; cursor: pointer; text-decoration: none;
}}
.panel {{
  background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 16px 18px; margin-top: 16px;
}}
.panel.alert-hot {{ border-color: var(--up); }}
.brief-box {{ border-left: 4px solid var(--accent); }}
.brief-headline {{ font-size: 16px; font-weight: 700; margin: 4px 0 10px; }}
.sec-head {{ display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 10px; }}
.sec-head h2 {{ margin: 0; font-size: 16.5px; }}
.subhead {{ margin: 8px 0 6px; font-size: 13.5px; color: var(--ink); }}
.sub-panel {{ background: var(--sub); border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 12px; }}
.two-col {{ grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }}
.card {{
  background: var(--sub); border: 1px solid var(--line); border-radius: 8px; padding: 12px 13px; break-inside: avoid;
}}
.card h3 {{ margin: 0 0 3px; font-size: 14px; }}
.card .sub {{ font-size: 12px; color: var(--muted); margin-bottom: 8px; }}
.muted-card {{ opacity: 0.78; }}
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 8px; }}
.kpi {{ background: var(--sub); border: 1px solid var(--line); border-radius: 8px; padding: 9px 11px; }}
.kpi .lbl {{ font-size: 11px; color: var(--muted); }}
.kpi .val {{ font-size: 16px; font-weight: 700; margin-top: 2px; font-variant-numeric: tabular-nums; }}
.kpi .sub {{ font-size: 11px; color: var(--muted); margin-top: 2px; }}
.badge {{
  display: inline-block; padding: 2px 7px; border-radius: 999px; font-size: 11px;
  font-weight: 600; background: var(--chip); color: var(--muted); vertical-align: middle;
}}
.badge.ai {{ color: var(--accent); background: var(--accent-soft); }}
.badge.accent {{ color: var(--accent); background: var(--accent-soft); }}
.badge.active {{ color: var(--down); background: var(--down-soft); }}
.badge.bad {{ color: var(--up); background: var(--up-soft); }}
.badge.warn {{ color: var(--warn); background: var(--warn-soft); }}
.badge.ok {{ color: var(--down); background: var(--down-soft); }}
.stale-banner {{
  margin-top: 10px; padding: 10px 14px; border-radius: 8px; background: var(--warn-soft);
  border: 1px solid var(--warn); font-size: 13px;
}}
.notice {{
  margin-top: 10px; padding: 9px 12px; border-radius: 7px; background: var(--panel);
  border: 1px solid var(--line); border-left: 3px solid var(--warn); color: var(--muted); font-size: 12.5px;
}}
.alert-card {{
  padding: 9px 12px; border-radius: 7px; background: var(--up-soft); border-left: 3px solid var(--up); margin-bottom: 8px;
}}
.ok-box {{ padding: 9px 12px; border-radius: 7px; background: var(--down-soft); color: var(--down); font-size: 13px; }}
.bullet-list {{ margin: 4px 0 0 18px; padding: 0; font-size: 13px; }}
.bullet-list li {{ margin-bottom: 4px; }}
.prose {{ margin: 0; font-size: 13.5px; color: var(--ink); }}
.dist-svg {{ width: 100%; height: 120px; display: block; }}
.kline {{ width: 96px; height: 28px; display: inline-block; vertical-align: middle; }}
.ladder-list {{ display: flex; flex-direction: column; gap: 6px; }}
.ladder-row {{ display: grid; grid-template-columns: 74px 1fr 78px; align-items: center; gap: 8px; font-size: 12px; }}
.ladder-track {{ background: var(--chip); border-radius: 999px; height: 8px; overflow: hidden; }}
.ladder-fill {{ height: 100%; border-radius: 999px; background: var(--up); }}
.accent-bg {{ background: var(--accent); }}
.ladder-num {{ text-align: right; font-weight: 600; font-variant-numeric: tabular-nums; }}
.scroll {{ overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }}
th, td {{ padding: 7px 9px; text-align: right; white-space: nowrap; border-bottom: 1px solid var(--line); font-size: 12.5px; }}
th {{ color: var(--muted); font-weight: 600; font-size: 11.5px; }}
th.l, td.l, th:first-child, td:first-child {{ text-align: left; }}
.up {{ color: var(--up); }} .down {{ color: var(--down); }} .dim {{ color: var(--muted); }}
.small {{ font-size: 11.5px; }}
.empty {{ padding: 14px; text-align: center; color: var(--muted); font-size: 12.5px; }}
footer {{ margin-top: 28px; padding-top: 14px; border-top: 1px solid var(--line); color: var(--muted); font-size: 12px; }}
@media print {{
  .no-print {{ display: none !important; }}
  body {{ background: #fff; color: #111; }}
  main {{ max-width: 100%; padding: 0; }}
  .panel {{ box-shadow: none; break-inside: avoid; }}
}}
</style>
</head>
<body>
<main>
  <header class="rpt-header">
    <div>
      <h1>AlphaSift · A 股盘后量化投研日报</h1>
      <div class="meta-row">
        <span>交易日 <b>{trade_date}</b></span>
        <span>· 数据包 <code>{pack_date}</code></span>
        <span class="badge {'warn' if is_stale else 'ok'}">{'旧包降级' if is_stale else '数据同步'}</span>
        <span>· 口径：<code>{_esc(report.get('usage_policy') or 'cn_only')}</code></span>
      </div>
    </div>
    <div class="actions">
      {dash_btn}
      <button type="button" class="theme-btn no-print" onclick="window.print()">🖨️ 打印 / 导出 PDF</button>
      <button type="button" class="theme-btn no-print" id="theme-toggle">🌓 主题</button>
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
  <footer>{_esc(BRIEF_DISCLAIMER)} · 量化形态观测与回测基准，历史表现不代表未来收益 · Generated {_esc(report.get("generated_at") or "")}</footer>
</main>
<script>
(function () {{
  try {{
    var saved = localStorage.getItem("alphasift-theme");
    if (saved === "dark" || saved === "light") document.documentElement.setAttribute("data-theme", saved);
  }} catch (e) {{}}
  var btn = document.getElementById("theme-toggle");
  if (btn) {{
    btn.addEventListener("click", function () {{
      var cur = document.documentElement.getAttribute("data-theme");
      var nxt = cur === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", nxt);
      try {{ localStorage.setItem("alphasift-theme", nxt); }} catch (e) {{}}
    }});
  }}
}})();
</script>
</body>
</html>
"""


def write_daily_report_html(
    path: str | Path,
    report: dict[str, Any],
    *,
    track_summary: dict[str, Any] | None = None,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_daily_report_html(report, track_summary=track_summary),
        encoding="utf-8",
    )
    return output
