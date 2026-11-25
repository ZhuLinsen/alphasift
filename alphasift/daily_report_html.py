# -*- coding: utf-8 -*-
"""Standalone, self-contained printable HTML renderer for CN DailyReport payloads."""

from __future__ import annotations

import html
import math
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from alphasift.daily_brief import BRIEF_DISCLAIMER, resolve_strategy_display_names
from alphasift.daily_report import _is_wf_joint_positive
from alphasift.jsonutil import atomic_write_text, dumps_strict_json

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
_WF_MIN_DAYS = 15


def _build_wf_cli(pat: dict[str, Any]) -> str:
    """Build reproducible CLI replay command matching the pattern's Walk-Forward filter."""
    pat_id = str(pat.get("pattern") or "").strip()
    if not pat_id:
        return ""
    adv = [str(s).strip() for s in (pat.get("wf_h1_adverse_regimes") or []) if str(s).strip()]
    pos = [str(s).strip() for s in (pat.get("wf_h1_positive_regimes") or []) if str(s).strip()]
    joint_days = int(pat.get("wf_non_adverse_low_overhead_days") or 0)
    raw_cap = pat.get("wf_low_overhead_threshold_pct")
    ov_cap = int(round(float(raw_cap))) if raw_cap not in (None, "") else 15
    if adv or joint_days > 0:
        adv_arg = f" --exclude-regimes {','.join(adv)}" if adv else ""
        ov_arg = f" --max-overhead-pct {ov_cap}" if joint_days > 0 else ""
        return f"alphasift patterns replay --pattern {pat_id}{adv_arg}{ov_arg}"
    if pos:
        return f"alphasift patterns replay --pattern {pat_id} --allowed-regimes {','.join(pos)}"
    return f"alphasift patterns replay --pattern {pat_id}"


def _esc(val: object) -> str:
    return html.escape("" if val is None else str(val), quote=True)


def _safe_detail_url(raw: object, fallback: str = "../index.html") -> str:
    """Allow only http(s) URLs or clean same-origin relative paths without HTML/control delimiters."""
    cleaned = str(raw or "").strip()
    if not cleaned:
        return fallback
    if any(ch in cleaned for ch in '<>"\'\r\n\t\0'):
        return fallback
    if cleaned.startswith("//"):
        return fallback
    parsed = urlsplit(cleaned)
    if parsed.scheme:
        if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
            return cleaned
        return fallback
    if parsed.netloc:
        return fallback
    if cleaned.startswith("../index.html") or (cleaned.startswith("/") and not cleaned.startswith("//")) or cleaned.startswith("index.html"):
        return cleaned
    return fallback


def _js_json(val: object) -> str:
    """Serialize JSON safely for inline <script> blocks by escaping HTML-closing sequences."""
    return (
        dumps_strict_json(val, indent=None)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _i18n(key: str, **vars_map: object) -> str:
    if not vars_map:
        return f'data-i18n="{_esc(key)}"'
    payload = html.escape(dumps_strict_json(vars_map, indent=None), quote=True)
    return f'data-i18n="{_esc(key)}" data-i18n-vars="{payload}"'


def _fmt_pct(val: object, digits: int = 2) -> str:
    if val is None:
        return '<span class="dim">–</span>'
    try:
        num = float(val)
    except (TypeError, ValueError):
        return '<span class="dim">–</span>'
    if not math.isfinite(num):
        return '<span class="dim">–</span>'
    cls = "up" if num > 0 else ("down" if num < 0 else "")
    sign = "+" if num > 0 else ""
    return f'<span class="{cls}">{sign}{num:.{digits}f}%</span>'


def _fmt_num(val: object, digits: int = 1, suffix: str = "", suffix_i18n: str = "") -> str:
    if val is None:
        return '<span class="dim">–</span>'
    try:
        num = float(val)
    except (TypeError, ValueError):
        return '<span class="dim">–</span>'
    if not math.isfinite(num):
        return '<span class="dim">–</span>'
    if suffix_i18n:
        return f'{num:.{digits}f}<span {_i18n(suffix_i18n)}>{_esc(suffix)}</span>'
    return f"{num:.{digits}f}{_esc(suffix)}"


def _render_dist_svg(dist: dict[str, Any] | None) -> str:
    if not isinstance(dist, dict) or not dist:
        return f'<div class="empty" {_i18n("no_dist")}>暂无涨跌幅分布统计</div>'
    counts = [int(dist.get(k) or 0) for k, _, _ in _DIST_BUCKETS]
    max_v = max(1, *counts)
    width, height, top, bot = 360, 120, 18, 22
    bar_h = height - top - bot
    step = width / len(_DIST_BUCKETS)
    bw = step * 0.58
    parts: list[str] = []
    for idx, (key, label, tone) in enumerate(_DIST_BUCKETS):
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
        flat_attr = ' data-dist-flat="1"' if key == "flat" else ""
        parts.append(
            f'<text{flat_attr} x="{x + bw / 2:.1f}" y="{height - 5}" text-anchor="middle" font-size="10" '
            f'font-family="var(--font-mono)" fill="var(--muted)">{_esc(label)}</text>'
        )
    return f'<svg class="dist-svg" viewBox="0 0 {width} {height}" role="img">{"".join(parts)}</svg>'


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
    return f'<svg class="kline" viewBox="0 0 {w} {h}" aria-label="{len(parsed)}D">{"".join(shapes)}</svg>'


def _render_ladder(ladder: dict[str, Any] | None) -> str:
    if not isinstance(ladder, dict) or not ladder:
        return f'<div class="empty" {_i18n("ladder_empty")}>今日无非 ST 连板或首板分布</div>'
    items = sorted(((int(k), int(v)) for k, v in ladder.items() if int(v or 0) > 0), reverse=True)
    if not items:
        return f'<div class="empty" {_i18n("ladder_empty")}>今日无非 ST 连板分布</div>'
    max_cnt = max(1, *(cnt for _, cnt in items))
    rows = []
    for board, cnt in items:
        w = max(8.0, (cnt / max_cnt) * 100.0)
        rows.append(
            f'<div class="ladder-row"><span {_i18n("ladder_board", b=board)}>{board}板</span>'
            f'<div class="ladder-track"><div class="ladder-fill" style="width:{w:.1f}%"></div></div>'
            f'<span class="ladder-num" {_i18n("ladder_cnt", n=cnt)}>{cnt} 只</span></div>'
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
        strat_key = str(cmp.get("strategy") or "")
        strat = (track_summary.get("strategy_names") or {}).get(strat_key, strat_key)
        bits: list[str] = []
        if adds:
            bits.append(
                f'<li><b {_i18n("case_adds")}>AI 独选高光：</b>'
                + "；".join(f"{_esc(x.get('date'))} {_esc(x.get('name'))}({_esc(x.get('code'))}) {_fmt_pct(x.get('excess_return_pct'))}" for x in adds)
                + "</li>"
            )
        if avoids:
            bits.append(
                f'<li><b {_i18n("case_avoids")}>AI 避坑剔除：</b>'
                + "；".join(f"{_esc(x.get('date'))} {_esc(x.get('name'))}({_esc(x.get('code'))}) {_fmt_pct(x.get('excess_return_pct'))}" for x in avoids)
                + "</li>"
            )
        if misses:
            bits.append(
                f'<li><b {_i18n("case_misses")}>AI 错杀遗憾：</b>'
                + "；".join(f"{_esc(x.get('date'))} {_esc(x.get('name'))}({_esc(x.get('code'))}) {_fmt_pct(x.get('excess_return_pct'))}" for x in misses)
                + "</li>"
            )
        cards.append(
            f'<div class="card"><div class="card-top"><h3><span data-strategy="{_esc(strat_key)}">{_esc(strat)}</span><span class="badge ai" {_i18n("case_badge")}>T+5 实盘案例</span></h3></div>'
            f'<ul class="bullet-list" style="padding:10px 14px 12px 28px;margin:0;">{"".join(bits)}</ul></div>'
        )
    if not cards:
        return ""
    return f'<div style="margin-top:14px;"><h3 class="subhead" {_i18n("case_section_title")}>历史同日配对 · AI 个股级案例复盘</h3><div class="grid">{"".join(cards)}</div></div>'


def _policy_html(raw: object) -> str:
    policy = str(raw or "cn_only").strip() or "cn_only"
    if policy == "cn_only_regime_slice_only":
        return f'<code {_i18n("policy_cn_slice")}>仅A股 · 情绪仅切片观察</code>'
    if policy == "cn_only":
        return f'<code {_i18n("policy_cn")}>仅A股</code>'
    return f"<code>{_esc(policy)}</code>"


def render_daily_report_html(
    report: dict[str, Any],
    *,
    track_summary: dict[str, Any] | None = None,
) -> str:
    """Render a standalone, dependency-free, printable HTML daily research report."""
    trade_date = _esc(report.get("trade_date") or "-")
    pack_date = _esc(report.get("pack_trade_date") or "-")
    detail_url = _safe_detail_url(report.get("detail_url"), fallback="../index.html")
    dash_base = detail_url.split("#", 1)[0].split("?", 1)[0]

    def _dash_link(hash_frag: str, i18n_key: str, zh_text: str, *, pat_id: str | None = None) -> str:
        href = f"{dash_base}?pat={pat_id}#{hash_frag}" if pat_id else f"{dash_base}#{hash_frag}"
        pat_attr = f' data-dash-pat="{_esc(pat_id)}"' if pat_id else ""
        return (
            f'<a class="dash-link no-print" data-dash-hash="{_esc(hash_frag)}"{pat_attr}'
            f' href="{_esc(href)}" {_i18n(i18n_key)}>{zh_text}</a>'
        )
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
    summary_names = (track_summary.get("strategy_names") or {}) if isinstance(track_summary, dict) else {}
    report_names = report.get("strategy_display_names") if isinstance(report.get("strategy_display_names"), dict) else {}
    strategy_names = resolve_strategy_display_names(overrides={**report_names, **summary_names})

    def _sname_span(key: object) -> str:
        raw = "" if key is None else str(key)
        label = strategy_names.get(raw) or raw
        return f'<span data-strategy="{_esc(raw)}">{_esc(label)}</span>'

    # 1. Brief / Executive Summary
    brief_mode = str(brief.get("mode") or "rule_fallback")
    brief_model = str(brief.get("model") or "LLM")
    brief_badge = (
        f'<span class="badge ai" {_i18n("brief_badge_llm", model=brief_model)}>AI 深度合成 · {_esc(brief_model)}</span>'
        if brief_mode == "llm"
        else f'<span class="badge accent" {_i18n("brief_badge_rule")}>规则统计合成</span>'
    )
    warn_items = "".join(f"<li>{_esc(w)}</li>" for w in (brief.get("risk_warnings") or []))
    watch_items = "".join(f"<li>{_esc(w)}</li>" for w in (brief.get("watch_points") or []))
    brief_block = f"""
    <section class="panel brief-box" id="brief">
      <div class="sec-head"><h2 {_i18n("sec_brief")}>盘后要点综述</h2>{brief_badge}</div>
      <div class="brief-headline">{_esc(brief.get("headline") or "暂无摘要")}</div>
      <div class="grid two-col">
        <div class="sub-panel">
          <h3 class="subhead" {_i18n("sub_regime")}>盘面宽度与情绪</h3>
          <p class="prose">{_esc(brief.get("regime_interpretation") or "-")}</p>
        </div>
        <div class="sub-panel">
          <h3 class="subhead" {_i18n("sub_consensus")}>策略共振与 AI 观察</h3>
          <p class="prose">{_esc(brief.get("consensus_and_ai_edge") or "-")}</p>
        </div>
      </div>
      <div class="grid two-col" style="margin-top:10px;">
        <div class="sub-panel"><h3 class="subhead" {_i18n("sub_risk")}>风险提示</h3><ul class="bullet-list">{warn_items or f'<li {_i18n("empty_warn")}>无额外提示</li>'}</ul></div>
        <div class="sub-panel"><h3 class="subhead" {_i18n("sub_watch")}>次日观察点</h3><ul class="bullet-list">{watch_items or f'<li {_i18n("empty_watch")}>关注开盘量能变化</li>'}</ul></div>
      </div>
    </section>
    """

    # 2. Panorama Section
    adv_pct = _fmt_num(reg.get("advance_ratio_pct"), 1, "%")
    med_pct = _fmt_pct(reg.get("median_return_pct"))
    amt_str = _fmt_num(reg.get("total_amount_yi"), 0, " 亿", suffix_i18n="unit_yi")
    seal_str = _fmt_num(reg.get("seal_rate_pct"), 1, "%")
    prev_lu = _fmt_pct(reg.get("prev_limit_up_avg_return_pct"))
    lu = int(reg.get("non_st_limit_up_count") or 0)
    ld = int(reg.get("non_st_limit_down_count") or 0)
    max_streak = int(reg.get("max_consecutive_limit_up") or 0)
    reg_code = str(reg.get("regime_stage") or "-")
    reg_label = str(reg.get("regime_stage_label") or "-")
    stage_txt = f"盘面 · {_esc(reg_label)}"

    panorama_block = f"""
    <section class="panel" id="panorama" style="padding:0;overflow:hidden;">
      <div class="sec-head" style="padding:14px 18px 10px;margin:0;">
        <h2 {_i18n("sec_panorama", d=report.get("trade_date") or "-")}>A 股盘面全景（{trade_date}）</h2>
        <span class="badge accent" data-regime="{_esc(reg_code)}" data-regime-raw="{_esc(reg_label)}">{stage_txt}</span>
      </div>
      <div class="kpi-strip">
        <div class="kpi-cell"><div class="lbl" {_i18n("kpi_adv")}>上涨占比</div><div class="val">{adv_pct}</div><div class="sub" {_i18n("kpi_adv_sub", adv=int(reg.get('advancing_count') or 0), dec=int(reg.get('declining_count') or 0))}>涨 {int(reg.get('advancing_count') or 0)} / 跌 {int(reg.get('declining_count') or 0)}</div></div>
        <div class="kpi-cell"><div class="lbl" {_i18n("kpi_med")}>全市场中位数</div><div class="val">{med_pct}</div><div class="sub" {_i18n("kpi_med_sub", n=int(reg.get('traded_count') or 0))}>成交 {int(reg.get('traded_count') or 0)} 只</div></div>
        <div class="kpi-cell"><div class="lbl" {_i18n("kpi_amt")}>两市成交额</div><div class="val">{amt_str}</div><div class="sub" {_i18n("kpi_amt_sub", seal=f"{float(reg.get('seal_rate_pct') or 0):.1f}%" if reg.get("seal_rate_pct") is not None else "–")}>封板率 {seal_str}</div></div>
        <div class="kpi-cell"><div class="lbl" {_i18n("kpi_luld")}>非ST 涨停 / 跌停</div><div class="val"><span class="up">{lu}</span> / <span class="down">{ld}</span></div><div class="sub" {_i18n("kpi_luld_sub", up=int(reg.get('one_price_limit_up_count') or 0), dn=int(reg.get('one_price_limit_down_count') or 0))}>一字 {int(reg.get('one_price_limit_up_count') or 0)}/{int(reg.get('one_price_limit_down_count') or 0)}</div></div>
        <div class="kpi-cell"><div class="lbl" {_i18n("kpi_streak")}>连板最高</div><div class="val" {_i18n("kpi_streak_val", n=max_streak)}>{max_streak} 板</div><div class="sub" {_i18n("kpi_streak_sub", n=int(reg.get('non_st_broken_board_count') or 0))}>炸板 {int(reg.get('non_st_broken_board_count') or 0)} 只</div></div>
        <div class="kpi-cell"><div class="lbl" {_i18n("kpi_prevlu")}>昨涨停今日均收益</div><div class="val">{prev_lu}</div><div class="sub" {_i18n("kpi_prevlu_sub", win=f"{float(reg.get('prev_limit_up_win_rate_pct') or 0):.1f}%" if reg.get("prev_limit_up_win_rate_pct") is not None else "–")}>红盘率 {_fmt_num(reg.get('prev_limit_up_win_rate_pct'), 1, '%')}</div></div>
      </div>
      <div class="grid two-col" style="padding:14px 18px 18px;">
        <div class="sub-panel"><h3 class="subhead" {_i18n("sub_dist")}>7 档涨跌幅分布</h3>{_render_dist_svg(reg.get("return_distribution"))}</div>
        <div class="sub-panel"><h3 class="subhead" {_i18n("sub_ladder")}>连板高度梯队</h3>{_render_ladder(reg.get("consecutive_board_ladder"))}</div>
      </div>
    </section>
    """

    # 3. Announcement Risk Alerts & Spotlight
    flagged = ann.get("flagged_items") or []
    spotlight = syn.get("risk_spotlight") or []
    checked = int(ann.get("checked_count") or 0)
    if flagged:
        flag_cards_parts: list[str] = []
        for x in flagged:
            ann_date = str(x.get("announcement_date") or "").strip()
            recency = str(x.get("recency") or "").strip()
            date_chip = f'<span class="badge">{_esc(ann_date)}</span> ' if ann_date else ""
            old_chip = f'<span class="badge warn" {_i18n("ann_old")}>历史进展</span> ' if recency == "old" else ""
            snip = x.get("matched_announcement") or x.get("announcement_summary") or "触发公告负面关键词"
            flag_cards_parts.append(
                f'<div class="alert-card"><b>{_esc(x.get("code"))} {_esc(x.get("name"))}</b> '
                f'{date_chip}{old_chip}'
                f'<span class="badge bad">{_esc("/".join(x.get("negative_event_flags") or []))}</span>'
                f'<div class="small dim" style="margin-top:3px;">{_esc(snip)}</div></div>'
            )
        flag_cards = "".join(flag_cards_parts)
    elif checked > 0:
        flag_cards = f'<div class="ok-box" {_i18n("ann_ok", n=checked)}>✓ 已核验 {checked} 只重点候选，暂未发现减持 / 立案 / 退市等负面关键词。</div>'
    else:
        flag_cards = f'<div class="dim small" {_i18n("ann_skipped")}>本期日报跳过公告抽检或无候选股。</div>'
    extra_risk = "".join(
        f'<li>{_esc(r.get("code"))} {_esc(r.get("name"))} <span class="badge">{_esc("/".join(r.get("flags") or []))}</span></li>'
        for r in spotlight
        if r.get("source") != "announcement"
    )
    ann_block = f"""
    <section class="panel {'alert-hot' if flagged else ''}" id="announcements">
      <div class="sec-head">
        <h2 {_i18n("sec_ann")}>⚠️ 公告排雷与风险聚焦</h2>
        <span class="badge {'bad' if flagged else ''}" {_i18n("ann_badge", c=checked, f=len(flagged))}>抽检 {checked} · 高风险 {len(flagged)}</span>
      </div>
      {flag_cards}
      {f'<div style="margin-top:8px;"><span class="small dim" {_i18n("ann_extra")}>候选附加风控标签：</span><ul class="bullet-list">{extra_risk}</ul></div>' if extra_risk else ""}
    </section>
    """

    # 3b. Market News & Catalysts (when collected)
    mnews = report.get("market_news") or {}
    news_items = mnews.get("items") or []
    news_sources = " · ".join(str(s) for s in (mnews.get("sources") or []) if s)
    if news_items:
        n_rows = "".join(
            f'<li><span class="badge">{_esc(it.get("category") or "要闻")}</span> '
            f'<b>{_esc(it.get("title"))}</b> '
            f'<span class="dim small">{_esc(it.get("source") or "")} {_esc(it.get("published_at") or "")}</span></li>'
            for it in news_items[:6]
            if isinstance(it, dict) and it.get("title")
        )
        news_block = f"""
    <section class="panel" id="news">
      <div class="sec-head">
        <h2 {_i18n("sec_news")}>📰 市场热点与政策快讯</h2>
        {f'<span class="badge">{_esc(news_sources)}</span>' if news_sources else ""}
      </div>
      <ul class="bullet-list">{n_rows}</ul>
    </section>
    """
    else:
        news_block = ""

    # 4. Cross-strategy Consensus, Sector Concentration & AI Attribution
    consensus = syn.get("consensus_picks") or []
    if consensus:
        c_rows_parts: list[str] = []
        for idx, c in enumerate(consensus, start=1):
            ann_str = _esc("/".join(c.get("announcement_risk_flags") or [])) or '<span class="dim">–</span>'
            strat_list = list(c.get("strategies") or [])
            strat_badges = "".join(f'<span class="badge">{_sname_span(st)}</span>' for st in strat_list[:3])
            if len(strat_list) > 3:
                strat_badges += f' <span class="dim small">+{len(strat_list) - 3}</span>'
            val_parts: list[str] = []
            if c.get("price") is not None:
                val_parts.append(f'¥{float(c["price"]):.2f}')
            if c.get("pe_ratio") is not None:
                val_parts.append(f'PE {float(c["pe_ratio"]):.1f}')
            if c.get("pb_ratio") is not None:
                val_parts.append(f'PB {float(c["pb_ratio"]):.2f}')
            val_sub = f'<div class="small dim mono">{" · ".join(val_parts)}</div>' if val_parts else ""
            reason_sub = ""
            if c.get("reasons"):
                reason_sub = f'<div class="small dim">{_esc("；".join(str(r) for r in c["reasons"][:1]))}</div>'
            c_rows_parts.append(
                f'<tr><td><span class="rank-num {"top" if idx <= 3 else ""}">{idx}</span></td>'
                f'<td class="l"><strong>{_esc(c.get("name"))}</strong> <span class="mono dim small">{_esc(c.get("code"))}</span>{val_sub}{reason_sub}</td>'
                f'<td class="l dim">{_esc(c.get("industry"))}</td>'
                f'<td><span class="badge accent" {_i18n("n_strats", n=int(c.get("strategy_count") or 0))}>{int(c.get("strategy_count") or 0)} 策略</span></td>'
                f'<td class="l">{strat_badges}</td>'
                f'<td class="mono">{_fmt_num(c.get("avg_final_score"), 1)}</td>'
                f'<td class="mono">{_fmt_pct(c.get("change_pct"))}</td>'
                f'<td class="l">{ann_str}</td></tr>'
            )
        consensus_html = (
            '<div class="scroll"><table><thead><tr><th>#</th>'
            f'<th class="l" {_i18n("col_stock")}>股票</th>'
            f'<th class="l" {_i18n("col_ind")}>行业</th>'
            f'<th {_i18n("col_hits")}>命中策略数</th>'
            f'<th class="l" {_i18n("col_strats")}>覆盖策略</th>'
            f'<th {_i18n("col_score")}>均分</th>'
            f'<th {_i18n("col_chg")}>涨跌</th>'
            f'<th class="l" {_i18n("col_ann")}>公告预警</th></tr></thead>'
            f'<tbody>{"".join(c_rows_parts)}</tbody></table></div>'
        )
    else:
        consensus_html = f'<div class="empty" {_i18n("no_consensus")}>今日暂无 ≥2 个策略同时选中的共识标的。</div>'

    sectors = syn.get("sector_concentration") or []
    sector_html = (
        "".join(
            f'<div class="ladder-row"><span>{_esc(s.get("industry"))}</span>'
            f'<div class="ladder-track"><div class="ladder-fill accent-bg" style="width:{min(100.0, float(s.get("share_pct") or 0.0)):.1f}%"></div></div>'
            f'<span class="ladder-num">{int(s.get("pick_count") or 0)} ({_fmt_num(s.get("share_pct"), 1, "%")})</span></div>'
            for s in sectors
        )
        or f'<div class="dim small" {_i18n("no_sector")}>暂无行业分布</div>'
    )

    ai_cards_parts: list[str] = []
    none_span = f'<span {_i18n("none_lbl")}>无</span>'
    for h in ai_hl:
        overlap_txt = f"{float(h.get('overlap_pct')):.1f}%" if h.get("overlap_pct") is not None else "–"
        mv = h.get("llm_market_view")
        view_html = f'<div><b {_i18n("ai_view")}>市场观点：</b>{_esc(mv)}</div>' if mv else ""
        added_names = "、".join(f'{x.get("name")}({x.get("code")})' for x in (h.get("added_by_ai") or []))
        dropped_names = "、".join(f'{x.get("name")}({x.get("code")})' for x in (h.get("dropped_by_ai") or []))
        added_html = _esc(added_names) if added_names else none_span
        dropped_html = _esc(dropped_names) if dropped_names else none_span
        ai_cards_parts.append(
            f'<div class="card"><div class="card-top"><h3>{_sname_span(h.get("strategy"))}<span class="badge ai" {_i18n("ai_rebalance")}>AI 调仓</span></h3>'
            f'<div class="sub" {_i18n("ai_sub", ov=overlap_txt, r=int(h.get("rules_pick_count") or 0), a=int(h.get("ai_pick_count") or 0))}>重合度 {overlap_txt} · 规则 {int(h.get("rules_pick_count") or 0)} / AI {int(h.get("ai_pick_count") or 0)}</div></div>'
            f'<div class="prose small" style="padding:10px 14px;">{view_html}'
            f'<div><b {_i18n("ai_add")}>AI 新增：</b>{added_html}</div>'
            f'<div><b {_i18n("ai_drop")}>AI 剔除：</b>{dropped_html}</div>'
            "</div></div>"
        )
    ai_cards = "".join(ai_cards_parts)

    resonance = syn.get("strategy_pattern_resonance") or []
    res_items: list[str] = []
    for r in resonance:
        strat_spans = ", ".join(_sname_span(s) for s in (r.get("strategies") or []))
        pat_list = [*(r.get("active_patterns") or []), *(r.get("experimental_patterns") or [])]
        pat_spans = ", ".join(f'<span data-pattern="{_esc(p)}">{_esc(p)}</span>' for p in pat_list)
        res_items.append(
            f'<li><b>{_esc(r.get("code"))} {_esc(r.get("name"))}</b> · '
            f'<span {_i18n("res_strat")}>策略</span>[{strat_spans}] × '
            f'<span {_i18n("res_pat")}>形态</span>[{pat_spans}]</li>'
        )
    res_html = (
        f'<ul class="bullet-list">{"".join(res_items)}</ul>'
        if res_items
        else f'<div class="dim small" {_i18n("no_resonance")}>今日策略候选与扫描形态暂无重叠个股。</div>'
    )

    synthesis_block = f"""
    <section class="panel" id="synthesis">
      <div class="sec-head"><h2 {_i18n("sec_syn")}>跨策略共识、行业分布与 AI 归因</h2>{_dash_link("track-comparison-section", "link_ai_board", "历史 AI 归因 →")}</div>
      <h3 class="subhead" {_i18n("sub_multi_cons")}>多策略共识标的</h3>
      {consensus_html}
      <div class="grid two-col" style="margin-top:12px;">
        <div class="sub-panel"><h3 class="subhead" {_i18n("sub_sector_conc")}>候选行业集中度</h3><div class="ladder-list">{sector_html}</div></div>
        <div class="sub-panel"><h3 class="subhead" {_i18n("sub_res")}>策略 × 形态共振观察</h3>{res_html}</div>
      </div>
      {f'<div id="ai-rebalance" style="margin-top:12px;"><h3 class="subhead" {_i18n("sub_ai_today")}>今日 AI 调仓对比</h3><div class="grid">{ai_cards}</div></div>' if ai_cards else ""}
      {_render_case_studies(track_summary)}
    </section>
    """

    # 5. Strategy Picks Full Cards
    strat_cards = []
    for st in strategies:
        tr = "ai" if st.get("track") == "ai" or st.get("llm_ranked") else "rules"
        badge = '<span class="badge ai">AI</span>' if tr == "ai" else f'<span class="badge" {_i18n("badge_rules")}>规则</span>'
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
                '<div class="scroll"><table><thead><tr><th>#</th>'
                f'<th class="l" {_i18n("col_stock")}>股票</th>'
                f'<th class="l" {_i18n("col_ind")}>行业</th>'
                f'<th {_i18n("col_total_score")}>综合分</th>'
                f'<th {_i18n("col_chg")}>涨跌</th>'
                f'<th class="l" {_i18n("col_note")}>备注/风险</th></tr></thead>'
                f"<tbody>{rows}</tbody></table></div>"
            )
        else:
            tbl = f'<div class="empty" {_i18n("no_picks")}>无入选股票</div>'
        n_picks = int(st.get("pick_count") or len(picks))
        strat_cards.append(
            f'<div class="card"><div class="card-top"><h3>{_sname_span(st.get("strategy"))}{badge}</h3>'
            f'<div class="sub" {_i18n("strat_picks_cnt", n=n_picks)}>入选 {n_picks} 只</div></div>{tbl}</div>'
        )
    strat_block = f"""
    <section class="panel" id="strategies">
      <div class="sec-head"><h2 {_i18n("sec_strats")}>今日策略精选全览</h2><span style="display:inline-flex;align-items:center;gap:6px;flex-wrap:wrap;"><span class="badge" {_i18n("strat_runs_badge", n=len(strategies))}>{len(strategies)} 组运行</span>{_dash_link("leaderboard", "link_leaderboard", "T+N 排行 →")}</span></div>
      {f'<div class="grid">{"".join(strat_cards)}</div>' if strat_cards else f'<div class="empty" {_i18n("no_strats")}>未附加策略运行结果。</div>'}
    </section>
    """

    # 6. Pattern Radar Cards (active + expectancy-tiered experimental)
    pat_cards = []
    for bucket, is_active in (("active", True), ("experimental", False)):
        pats_list = list(pat_sec.get(bucket) or [])
        if not is_active:
            pats_list.sort(
                key=lambda p: (
                    0 if p.get("expectancy_tier") == "positive_watch" and not p.get("wf_today_adverse") else (
                        1 if _is_wf_joint_positive(p) else (
                            2 if p.get("expectancy_tier") != "negative_watch" and not p.get("wf_today_adverse") else (
                                3 if p.get("expectancy_tier") != "negative_watch" else (
                                    4 if not p.get("wf_today_adverse") else 5
                                )
                            )
                        )
                    ),
                    -int(p.get("hit_count") or 0),
                    str(p.get("pattern") or ""),
                )
            )
        for pat in pats_list:
            pkey = str(pat.get("pattern") or "")
            dname = str(pat.get("display_name") or pkey)
            exp_tier = str(pat.get("expectancy_tier") or "")
            badge = '<span class="badge active">active</span>' if is_active else (
                f'<span class="badge warn" {_i18n("pat_neg_watch")}>负期望·观察</span>'
                if exp_tier == "negative_watch"
                else f'<span class="badge" {_i18n("pat_exp_watch")}>观察期</span>'
            )
            p_mid = str(pat.get("wf_eval_mid_date") or "").strip()
            p_sig = int(pat.get("wf_h1_purged_signals") or 0)
            p_days = int(pat.get("wf_h1_purged_days") or 0)
            purged_tip = (
                (f"H1 exit_date < {p_mid} · purged {p_sig} ({p_days}d)" if p_mid else f"purged {p_sig} ({p_days}d)")
                if pat.get("wf_boundary_verified")
                else ""
            )
            purged_title_attr = f' title="{_esc(purged_tip)}"' if purged_tip else ""
            wf_adv_badge = (
                f'<span class="badge bad"{purged_title_attr} {_i18n("pat_wf_adverse")}>今日情绪逆风</span>'
                if pat.get("wf_today_adverse")
                else ""
            )
            wf_pending_badge = (
                f'<span class="badge warn" {_i18n("pat_wf_pending")}>边界待复核</span>'
                if pat.get("wf_boundary_verified") is False
                else ""
            )
            net_ex = pat.get("replay_t5_net_excess_pct")
            replay_note = (
                f'<span {_i18n("pat_t5_net", v=f"{float(net_ex):+.2f}%")}> · T+5净超额 {float(net_ex):+.2f}%</span>'
                if net_ex is not None
                else ""
            )
            wf_joint_pct = pat.get("wf_non_adverse_low_overhead_pct")
            wf_joint_days = int(pat.get("wf_non_adverse_low_overhead_days") or 0)
            if wf_joint_pct is not None and wf_joint_days > 0:
                wf_joint_low = wf_joint_days < _WF_MIN_DAYS
                cls_attr = ' class="wf-low"' if wf_joint_low else ""
                low_tag = f'<span class="tag-low">&lt;{_WF_MIN_DAYS}d</span>' if wf_joint_low else ""
                replay_note += (
                    f'<span{cls_attr}{purged_title_attr} {_i18n("pat_wf_joint", v=f"{float(wf_joint_pct):+.2f}%", d=wf_joint_days)}>'
                    f' · 联合OOS {float(wf_joint_pct):+.2f}%({wf_joint_days}d)</span>{low_tag}'
                )
            sigs = pat.get("signals") or []
            if sigs:
                s_rows = "".join(
                    f'<tr><td class="l"><strong>{_esc(s.get("name"))}</strong> <span class="mono dim small">{_esc(s.get("code"))}</span></td>'
                    f'<td class="mono">{_fmt_pct(s.get("change_pct"))}</td>'
                    f'<td class="dim mono">{_fmt_num(s.get("overhead_supply_10pct"), 0, "%")}</td>'
                    f'<td>{_render_mini_kline_svg(s.get("kline"))}</td></tr>'
                    for s in sigs[:8]
                )
                body = (
                    '<div class="scroll"><table><thead><tr>'
                    f'<th class="l" {_i18n("col_stock")}>股票</th>'
                    f'<th {_i18n("col_chg")}>涨跌</th>'
                    f'<th {_i18n("col_overhead")}>上方套牢</th>'
                    f'<th {_i18n("col_kline")}>近20日K线</th></tr></thead><tbody>{s_rows}</tbody></table></div>'
                )
            else:
                body = f'<div class="empty" {_i18n("no_pat_sig")}>今日无触发信号</div>'
            hits_n = int(pat.get("hit_count") or 0)
            pat_link = _dash_link("walk-forward-wrap", "link_pat_wf", "样本外回放 →", pat_id=pkey) if pkey else ""
            cli_cmd = _build_wf_cli(pat) if pkey else ""
            wf_cli_btn = (
                f'<button type="button" class="wf-cli-btn no-print" data-cli="{_esc(cli_cmd)}" '
                f'title="{_esc(cli_cmd)}" aria-label="{_esc(cli_cmd)}" '
                f'{_i18n("wf_cli_btn")}>CLI</button>'
                if cli_cmd
                else ""
            )
            pat_id_attr = f' id="pat-{_esc(pkey)}"' if pkey else ""
            pat_cards.append(
                f'<div class="card {"muted-card" if not is_active else ""}"{pat_id_attr}><div class="card-top"><h3><span data-pattern="{_esc(pkey)}">{_esc(dname)}</span><span style="display:inline-flex;flex-wrap:wrap;gap:4px;">{badge}{wf_adv_badge}{wf_pending_badge}</span></h3>'
                f'<div class="sub"><span {_i18n("pat_hits_cnt", n=hits_n)}>命中 {hits_n} 只</span>{replay_note}{pat_link}{wf_cli_btn}</div></div>{body}</div>'
            )
    all_scan_pats = [*(pat_sec.get("active") or []), *(pat_sec.get("experimental") or [])]
    wf_mid_date = next((str(p.get("wf_eval_mid_date") or "").strip() for p in all_scan_pats if str(p.get("wf_eval_mid_date") or "").strip()), "")
    total_purged = sum(int(p.get("wf_h1_purged_signals") or 0) for p in all_scan_pats)
    pat_boundary_footer = (
        f'<p class="dim small" style="margin:10px 0 0;" {_i18n("pat_wf_boundary_note_stats", mid=wf_mid_date, n=total_purged)}>'
        f'注：Walk-Forward H1 严格按实际退出日 &lt; {_esc(wf_mid_date)} 截断（累计剔除 {total_purged} 条跨界信号），避免 H2 价格区间泄漏进逆风判定。</p>'
        if wf_mid_date
        else f'<p class="dim small" style="margin:10px 0 0;" {_i18n("pat_wf_boundary_note")}>注：Walk-Forward H1 严格按实际退出日 &lt; 切分日截断并剔除跨界样本，避免 H2 价格区间泄漏进逆风判定。</p>'
    )
    pat_block = f"""
    <section class="panel" id="patterns">
      <div class="sec-head"><h2 {_i18n("sec_patterns")}>无状态形态雷达命中</h2>{_dash_link("walk-forward-wrap", "link_wf_board", "250日 Walk-Forward 回放 →")}</div>
      <div class="grid">{"".join(pat_cards) if pat_cards else f'<div class="empty" {_i18n("no_pats")}>无形态扫描记录</div>'}</div>
      {pat_boundary_footer}
    </section>
    """

    stale_html = (
        f'<div class="stale-banner" {_i18n("stale_banner", pack=pack_date, exp=str(report.get("expected_trade_date") or "-"), reason=stale_reason)}>⚠️ <b>旧包降级模式</b>：数据包日期 <code>{pack_date}</code> 落后于目标交易日 '
        f'<code>{_esc(report.get("expected_trade_date"))}</code>（{_esc(stale_reason)}），数据仅供观察，已自动拦截未强制 IM 推送。</div>'
        if is_stale
        else ""
    )
    deg_html = (
        f'<div class="notice"><span {_i18n("deg_prefix")}>降级说明：</span>{"；".join(_esc(d) for d in degradation)}</div>'
        if degradation
        else ""
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%23090d16'/%3E%3Cpath d='M6 8h20l-7.5 8.8v6.6l-5 2.4V16.8L6 8z' fill='%233b82f6' fill-opacity='.25' stroke='%2360a5fa' stroke-width='2.2' stroke-linejoin='round'/%3E%3Ccircle cx='23' cy='23' r='2.5' fill='%2334d399'/%3E%3C/svg%3E">
<title>AlphaSift · A 股盘后投研日报 ({trade_date})</title>
<style>
:root {{
  --bg: #09090b; --surface: #111115; --sub: #17171d; --ink: #f4f4f5; --ink-2: #d4d4d8;
  --muted: #8e8e9a; --border: rgba(255,255,255,0.085); --border-strong: rgba(255,255,255,0.16);
  --glass: rgba(9,9,11,0.82); --accent: #3b82f6; --accent-hi: #60a5fa; --accent-soft: rgba(59,130,246,0.14);
  --up: #f87171; --up-soft: rgba(248,113,113,0.12);
  --down: #34d399; --down-soft: rgba(52,211,153,0.12);
  --warn: #fbbf24; --warn-soft: rgba(251,191,36,0.14); --chip: rgba(255,255,255,0.06);
  --font-sans: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", "Hiragino Kaku Gothic ProN", sans-serif;
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
.actions {{ display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }}
.btn-link, .theme-btn, .github-btn {{
  display: inline-flex; align-items: center; gap: 6px;
  border: 1px solid var(--border); background: var(--surface); color: var(--ink-2);
  border-radius: 8px; padding: 5px 10px; font: inherit; font-size: 12px; font-weight: 500; cursor: pointer; text-decoration: none;
}}
.btn-link:hover, .theme-btn:hover {{ border-color: var(--border-strong); color: var(--ink); text-decoration: none; }}
.github-btn {{ background: var(--ink); color: var(--bg); border-color: var(--ink); font-weight: 600; }}
.github-btn:hover {{ opacity: 0.9; text-decoration: none; color: var(--bg); }}

.lang-switch {{
  display: inline-flex; align-items: center;
  border: 1px solid var(--border); background: var(--surface); border-radius: 8px; padding: 2px; gap: 2px;
}}
.lang-switch button {{
  border: 0; background: transparent; color: var(--muted);
  padding: 3px 7px; border-radius: 6px; font: inherit; font-size: 11.5px; font-weight: 600; cursor: pointer;
}}
.lang-switch button:hover {{ color: var(--ink); background: var(--chip); }}
.lang-switch button[aria-pressed="true"] {{ background: var(--accent-soft); color: var(--accent-hi); }}

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
.dash-link {{
  display: inline-flex; align-items: center; gap: 3px; font-size: 11px; font-weight: 600;
  color: var(--accent-hi); padding: 2px 8px; border-radius: 5px;
  background: var(--accent-soft); border: 1px solid rgba(59,130,246,0.22);
  text-decoration: none; white-space: nowrap; font-family: var(--font-sans);
}}
.dash-link:hover {{ background: rgba(59,130,246,0.22); text-decoration: none; }}
.card .sub .dash-link {{ margin-left: 6px; padding: 0 6px; font-size: 10.5px; vertical-align: middle; }}
.wf-low {{ opacity: 0.72; }}
.tag-low {{
  display: inline-block; margin-left: 4px; padding: 0 4px; border-radius: 4px;
  font-size: 10px; font-weight: 600; font-family: var(--font-mono);
  color: var(--warn); background: var(--warn-soft); border: 1px solid rgba(251,191,36,0.3);
  vertical-align: middle;
}}
.wf-cli-btn {{
  display: inline-flex; align-items: center; margin-left: 5px; padding: 0 6px;
  border-radius: 5px; border: 1px solid var(--border); background: var(--surface);
  color: var(--accent-hi); font-family: var(--font-mono); font-size: 10.5px; font-weight: 600;
  cursor: pointer; vertical-align: middle; line-height: 1.5;
}}
.wf-cli-btn:hover {{ border-color: var(--accent-hi); background: var(--accent-soft); }}
.wf-cli-btn.copied {{ border-color: var(--down); color: var(--down); background: var(--down-soft); }}
section[id], #ai-rebalance, .card[id] {{ scroll-margin-top: 64px; }}
.card:target {{ border-color: var(--accent-hi); box-shadow: 0 0 0 1px var(--accent-hi); opacity: 1; }}

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
  @page {{ margin: 12mm; }}
  .no-print, .topbar {{ display: none !important; }}
  :root {{ --bg: #ffffff; --surface: #ffffff; --sub: #f8fafc; --ink: #111111; --ink-2: #222222; --muted: #555555; --border: #dddddd; }}
  body {{ background: #ffffff; color: #111111; font-size: 12px; }}
  main {{ max-width: 100%; padding: 0; }}
  .panel {{ box-shadow: none; break-inside: avoid; border-color: #dddddd; }}
  .card, tr {{ break-inside: avoid; }}
  .grid, .grid.two-col {{ grid-template-columns: 1fr; }}
  table {{ font-size: 11px; }}
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
      <span {_i18n("brand_title")}>AlphaSift · 盘后研报</span>
    </span>
    <div class="actions">
      <a class="btn-link" id="back-dashboard-link" href="{_esc(detail_url)}">
        <svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>
        <span {_i18n("btn_back")}>返回在线看板</span>
      </a>
      <a class="github-btn" href="{_GITHUB_URL}" target="_blank" rel="noopener">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.57.11.78-.25.78-.55 0-.27-.01-1.18-.02-2.14-3.2.7-3.87-1.36-3.87-1.36-.52-1.33-1.28-1.68-1.28-1.68-1.05-.72.08-.71.08-.71 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.71 1.26 3.37.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.29 1.19-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11.06 11.06 0 0 1 5.78 0c2.21-1.49 3.18-1.18 3.18-1.18.63 1.59.23 2.76.11 3.05.74.8 1.19 1.83 1.19 3.09 0 4.42-2.69 5.39-5.26 5.68.41.36.78 1.06.78 2.15 0 1.55-.01 2.8-.01 3.18 0 .31.21.67.79.55C20.21 21.39 23.5 17.08 23.5 12 23.5 5.65 18.35.5 12 .5z"/>
        </svg>
        <span>GitHub</span>
      </a>
      <button type="button" class="theme-btn" id="print-btn">
        <svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
        <span {_i18n("btn_print")}>打印 / PDF</span>
      </button>
      <div class="lang-switch" id="lang-switch" role="group" aria-label="Language">
        <button type="button" data-lang="zh" aria-pressed="true">中</button>
        <button type="button" data-lang="en" aria-pressed="false">EN</button>
        <button type="button" data-lang="ja" aria-pressed="false">日</button>
      </div>
      <button type="button" class="theme-btn" id="theme-toggle">亮色</button>
    </div>
  </div>
</nav>
<main>
  <header class="rpt-header">
    <div class="eyebrow">OPEN-SOURCE DAILY QUANTITATIVE RESEARCH BRIEF</div>
    <h1 {_i18n("rpt_title")}>AlphaSift · A 股盘后量化投研日报</h1>
    <div class="meta-row">
      <span><span {_i18n("meta_tdate")}>交易日</span> <b>{trade_date}</b></span>
      <span>· <span {_i18n("meta_pdate")}>数据包</span> <code>{pack_date}</code></span>
      <span class="badge {'warn' if is_stale else 'ok'}" {_i18n("badge_stale" if is_stale else "badge_sync")}>{'旧包降级' if is_stale else '数据同步'}</span>
      <span>· <span {_i18n("meta_policy")}>口径：</span>{_policy_html(report.get('usage_policy'))}</span>
    </div>
  </header>
  {stale_html}
  {deg_html}
  {brief_block}
  {panorama_block}
  {news_block}
  {ann_block}
  {synthesis_block}
  {strat_block}
  {pat_block}
  <footer><span {_i18n("disclaimer")}>{_esc(BRIEF_DISCLAIMER)}</span> · <span {_i18n("footer_tag")}>量化形态观测与回测基准</span> · <a href="{_GITHUB_URL}" {_i18n("footer_repo")}>GitHub 开源仓库</a> · Generated {_esc(report.get("generated_at") or "")}</footer>
</main>
<script>
(function () {{
  var TRADE_DATE = {_js_json(str(report.get("trade_date") or "-"))};
  var DETAIL_BASE = {_js_json(detail_url)};
  var I18N = {{
    zh: {{
      page_title: "AlphaSift · A 股盘后投研日报 (" + TRADE_DATE + ")",
      brand_title: "AlphaSift · 盘后研报",
      btn_back: "返回在线看板",
      btn_print: "打印 / PDF",
      theme_light: "亮色",
      theme_dark: "暗色",
      rpt_title: "AlphaSift · A 股盘后量化投研日报",
      meta_tdate: "交易日",
      meta_pdate: "数据包",
      badge_stale: "旧包降级",
      badge_sync: "数据同步",
      meta_policy: "口径：",
      sec_brief: "盘后要点综述",
      brief_badge_rule: "规则统计合成",
      sub_regime: "盘面宽度与情绪",
      sub_consensus: "策略共振与 AI 观察",
      sub_risk: "风险提示",
      sub_watch: "次日观察点",
      empty_warn: "无额外提示",
      empty_watch: "关注开盘量能变化",
      unit_yi: " 亿",
      kpi_adv: "上涨占比",
      kpi_med: "全市场中位数",
      kpi_amt: "两市成交额",
      kpi_luld: "非ST 涨停 / 跌停",
      kpi_streak: "连板最高",
      kpi_prevlu: "昨涨停今日均收益",
      sub_dist: "7 档涨跌幅分布",
      sub_ladder: "连板高度梯队",
      no_dist: "暂无涨跌幅分布统计",
      ladder_empty: "今日无非 ST 连板或首板分布",
      sec_ann: "⚠️ 公告排雷与风险聚焦",
      ann_old: "历史进展",
      ann_skipped: "本期日报跳过公告抽检或无候选股。",
      ann_extra: "候选附加风控标签：",
      sec_news: "📰 市场热点与政策快讯",
      sec_syn: "跨策略共识、行业分布与 AI 归因",
      sub_multi_cons: "多策略共识标的",
      col_stock: "股票",
      col_ind: "行业",
      col_hits: "命中策略数",
      col_strats: "覆盖策略",
      col_score: "均分",
      col_chg: "涨跌",
      col_ann: "公告预警",
      no_consensus: "今日暂无 ≥2 个策略同时选中的共识标的。",
      sub_sector_conc: "候选行业集中度",
      no_sector: "暂无行业分布",
      sub_res: "策略 × 形态共振观察",
      no_resonance: "今日策略候选与扫描形态暂无重叠个股。",
      res_strat: "策略",
      res_pat: "形态",
      sub_ai_today: "今日 AI 调仓对比",
      ai_rebalance: "AI 调仓",
      ai_view: "市场观点：",
      ai_add: "AI 新增：",
      ai_drop: "AI 剔除：",
      none_lbl: "无",
      case_section_title: "历史同日配对 · AI 个股级案例复盘",
      case_badge: "T+5 实盘案例",
      case_adds: "AI 独选高光：",
      case_avoids: "AI 避坑剔除：",
      case_misses: "AI 错杀遗憾：",
      sec_strats: "今日策略精选全览",
      badge_rules: "规则",
      col_total_score: "综合分",
      col_note: "备注/风险",
      no_picks: "无入选股票",
      no_strats: "未附加策略运行结果。",
      sec_patterns: "无状态形态雷达命中",
      col_overhead: "上方套牢",
      col_kline: "近20日K线",
      no_pat_sig: "今日无触发信号",
      no_pats: "无形态扫描记录",
      pat_neg_watch: "负期望·观察",
      pat_exp_watch: "观察期",
      pat_wf_adverse: "今日情绪逆风",
      pat_wf_joint: " · 联合OOS {{v}}({{d}}d)",
      policy_cn_slice: "仅A股 · 情绪仅切片观察",
      policy_cn: "仅A股",
      deg_prefix: "降级说明：",
      footer_tag: "量化形态观测与回测基准",
      footer_repo: "GitHub 开源仓库",
      dist_flat: "平盘",
      link_ai_board: "历史 AI 归因 →",
      link_leaderboard: "T+N 排行 →",
      link_wf_board: "250日 Walk-Forward 回放 →",
      link_pat_wf: "样本外回放 →",
      wf_cli_btn: "CLI",
      wf_cli_copied: "已复制",
      pat_wf_pending: "边界待复核",
      pat_wf_boundary_note: "注：Walk-Forward H1 严格按实际退出日 &lt; 切分日截断并剔除跨界样本，避免 H2 价格区间泄漏进逆风判定。",
      pat_wf_boundary_note_stats: "注：Walk-Forward H1 严格按实际退出日 &lt; {{mid}} 截断（累计剔除 {{n}} 条跨界信号），避免 H2 价格区间泄漏进逆风判定。",
    }},
    en: {{
      page_title: "AlphaSift · CN Post-Close Research Brief (" + TRADE_DATE + ")",
      brand_title: "AlphaSift · Daily Brief",
      btn_back: "Dashboard",
      btn_print: "Print / PDF",
      theme_light: "Light",
      theme_dark: "Dark",
      rpt_title: "AlphaSift · CN Post-Close Quantitative Research Brief",
      meta_tdate: "Session",
      meta_pdate: "Pack",
      badge_stale: "Stale Fallback",
      badge_sync: "Pack Synced",
      meta_policy: "Policy: ",
      sec_brief: "Executive Post-Close Brief",
      brief_badge_llm: "AI Brief · {{model}}",
      brief_badge_rule: "Rule Synthesis",
      sub_regime: "Market Breadth & Regime",
      sub_consensus: "Consensus & AI Observations",
      sub_risk: "Risk Warnings",
      sub_watch: "Next-Session Watchpoints",
      empty_warn: "No extra warnings",
      empty_watch: "Watch opening auction & volume continuity",
      sec_panorama: "CN Market Panorama ({{d}})",
      unit_yi: "00M",
      kpi_adv: "Advancing Share",
      kpi_adv_sub: "Adv {{adv}} / Dec {{dec}}",
      kpi_med: "Universe Median",
      kpi_med_sub: "{{n}} traded",
      kpi_amt: "Total Turnover",
      kpi_amt_sub: "Seal {{seal}}",
      kpi_luld: "Non-ST Limit-Up / Dn",
      kpi_luld_sub: "Locked {{up}} / {{dn}}",
      kpi_streak: "Max Streak",
      kpi_streak_val: "{{n}}d",
      kpi_streak_sub: "Broken {{n}}",
      kpi_prevlu: "Prev LU Avg Return",
      kpi_prevlu_sub: "Green {{win}}",
      sub_dist: "7-Bucket Return Distribution",
      sub_ladder: "Limit-Up Streak Ladder",
      no_dist: "No return distribution data",
      ladder_empty: "No non-ST consecutive limit-ups today",
      ladder_board: "{{b}}d",
      ladder_cnt: "{{n}}",
      sec_ann: "⚠️ Announcement Risk Screening",
      ann_old: "Earlier Update",
      ann_badge: "{{c}} checked · {{f}} flagged",
      ann_ok: "✓ Screened {{n}} shortlisted candidates — no negative filing keywords detected.",
      ann_skipped: "Announcement screening skipped or no shortlisted candidates.",
      ann_extra: "Additional candidate risk flags:",
      sec_news: "📰 Market Headlines & Catalysts",
      sec_syn: "Cross-Strategy Consensus, Sector Mix & AI Attribution",
      sub_multi_cons: "Multi-Strategy Consensus",
      col_stock: "Security",
      col_ind: "Sector",
      col_hits: "Hits",
      col_strats: "Strategies",
      col_score: "Score",
      col_chg: "Chg%",
      col_ann: "Filings",
      n_strats: "{{n}} strats",
      no_consensus: "No CN stock selected by ≥2 strategies today.",
      sub_sector_conc: "Sector Concentration",
      no_sector: "No sector breakdown available",
      sub_res: "Strategy × Pattern Resonance",
      no_resonance: "No overlap between strategy picks and pattern hits today.",
      res_strat: "Strats",
      res_pat: "Patterns",
      sub_ai_today: "Today's AI Re-Ranking Deltas",
      ai_rebalance: "AI Re-Rank",
      ai_sub: "Overlap {{ov}} · Rules {{r}} / AI {{a}}",
      ai_view: "Market View: ",
      ai_add: "AI Added: ",
      ai_drop: "AI Dropped: ",
      none_lbl: "None",
      case_section_title: "Paired Attribution · T+5 AI Case Studies",
      case_badge: "T+5 Case Study",
      case_adds: "Top AI Adds: ",
      case_avoids: "AI Avoided Losses: ",
      case_misses: "Missed by AI: ",
      sec_strats: "Today's Strategy Picks Overview",
      strat_runs_badge: "{{n}} runs",
      badge_rules: "Rules",
      col_total_score: "Score",
      col_note: "Note / Risk",
      no_picks: "No qualifying picks",
      no_strats: "No strategy runs attached.",
      strat_picks_cnt: "{{n}} picks",
      sec_patterns: "Stateless Pattern Radar Hits",
      col_overhead: "Overhead",
      col_kline: "20D K-Line",
      no_pat_sig: "No signals triggered today",
      no_pats: "No pattern scan recorded",
      pat_hits_cnt: "{{n}} hits",
      pat_neg_watch: "Neg Exp · Watch",
      pat_exp_watch: "Observational",
      pat_t5_net: " · T+5 Net {{v}}",
      pat_wf_adverse: "WF Adverse Regime",
      pat_wf_joint: " · Joint OOS {{v}}({{d}}d)",
      policy_cn_slice: "CN Only · Regime Slice",
      policy_cn: "CN Only",
      stale_banner: "⚠️ <b>Stale Pack Mode</b>: Pack date <code>{{pack}}</code> trails target <code>{{exp}}</code> ({{reason}}). Rendered in observation mode; unforced IM push suppressed.",
      deg_prefix: "Degradation: ",
      disclaimer: "Research & observational metrics only — not investment advice or buy/sell instructions.",
      footer_tag: "Quantitative Discovery & Benchmark",
      footer_repo: "GitHub Repository",
      dist_flat: "Flat",
      link_ai_board: "Historical AI Attribution →",
      link_leaderboard: "T+N Leaderboard →",
      link_wf_board: "250D Walk-Forward Audit →",
      link_pat_wf: "OOS Audit →",
      wf_cli_btn: "CLI",
      wf_cli_copied: "Copied",
      pat_wf_pending: "Boundary Unverified",
      pat_wf_boundary_note: "Note: Walk-Forward H1 is strictly cut by actual exit_date &lt; split_date with cross-boundary trades purged so H2 prices never leak into adverse-regime selection.",
      pat_wf_boundary_note_stats: "Note: Walk-Forward H1 is cut strictly by actual exit_date &lt; {{mid}} ({{n}} cross-boundary trades purged) so H2 prices never leak into adverse-regime selection.",
    }},
    ja: {{
      page_title: "AlphaSift · 中国A株 引け後クオンツレポート (" + TRADE_DATE + ")",
      brand_title: "AlphaSift · 日次レポート",
      btn_back: "ダッシュボード",
      btn_print: "印刷 / PDF",
      theme_light: "ライト",
      theme_dark: "ダーク",
      rpt_title: "AlphaSift · 中国A株 引け後クオンツ調査レポート",
      meta_tdate: "営業日",
      meta_pdate: "データパック",
      badge_stale: "旧パック縮退",
      badge_sync: "同期済み",
      meta_policy: "方針：",
      sec_brief: "引け後エグゼクティブ要約",
      brief_badge_llm: "AI 分析合成 · {{model}}",
      brief_badge_rule: "統計ルール合成",
      sub_regime: "市場の幅・センチメント",
      sub_consensus: "戦略コンセンサス・AI観測",
      sub_risk: "リスク注意",
      sub_watch: "翌営業日の注目点",
      empty_warn: "追加の警戒事項なし",
      empty_watch: "寄付き出来高の持続性に注目",
      sec_panorama: "中国A株 市場パノラマ ({{d}})",
      unit_yi: "億元",
      kpi_adv: "上昇銘柄比率",
      kpi_adv_sub: "上昇 {{adv}} / 下落 {{dec}}",
      kpi_med: "全市場中央値",
      kpi_med_sub: "出来高 {{n}} 銘柄",
      kpi_amt: "両市場売買代金",
      kpi_amt_sub: "維持率 {{seal}}",
      kpi_luld: "非ST ストップ高 / 安",
      kpi_luld_sub: "一本値 {{up}}/{{dn}}",
      kpi_streak: "最高連騰",
      kpi_streak_val: "{{n}}連騰",
      kpi_streak_sub: "剥がれ {{n}} 銘柄",
      kpi_prevlu: "前日S高 本日平均",
      kpi_prevlu_sub: "陽線率 {{win}}",
      sub_dist: "7段階 騰落率分布",
      sub_ladder: "連騰ストップ高ラダー",
      no_dist: "騰落率分布データなし",
      ladder_empty: "本日非 ST の連騰ストップ高なし",
      ladder_board: "{{b}}連続",
      ladder_cnt: "{{n}} 社",
      sec_ann: "⚠️ 適時開示リスク検査",
      ann_old: "過去の続報",
      ann_badge: "検査 {{c}} · 高リスク {{f}}",
      ann_ok: "✓ 主要候補 {{n}} 銘柄の適時開示を確認済み（持株売却・調査等の警戒語なし）。",
      ann_skipped: "開示検査スキップまたは候補銘柄なし。",
      ann_extra: "追加のリスクタグ：",
      sec_news: "📰 市場トピックス・ニュース",
      sec_syn: "複数戦略コンセンサス・業種分布・AI帰属",
      sub_multi_cons: "複数戦略コンセンサス銘柄",
      col_stock: "銘柄",
      col_ind: "業種",
      col_hits: "戦略数",
      col_strats: "該当戦略",
      col_score: "平均スコア",
      col_chg: "騰落率",
      col_ann: "開示警戒",
      n_strats: "{{n}} 戦略",
      no_consensus: "本日 ≥2 戦略で重複選定された銘柄はありません。",
      sub_sector_conc: "候補業種集中度",
      no_sector: "業種データなし",
      sub_res: "戦略 × パターン共鳴観測",
      no_resonance: "本日戦略候補とパターン検出の重複はありません。",
      res_strat: "戦略",
      res_pat: "パターン",
      sub_ai_today: "本日の AI 再ランク調整",
      ai_rebalance: "AI 調整",
      ai_sub: "重複率 {{ov}} · ルール {{r}} / AI {{a}}",
      ai_view: "市場見通し：",
      ai_add: "AI 追加：",
      ai_drop: "AI 除外：",
      none_lbl: "なし",
      case_section_title: "同日ペア帰属 · AI 個別銘柄ケース振り返り",
      case_badge: "T+5 実測事例",
      case_adds: "AI 独自選定ハイライト：",
      case_avoids: "AI 回避成功：",
      case_misses: "AI 見逃し：",
      sec_strats: "本日の戦略別選定一覧",
      strat_runs_badge: "{{n}} 実行",
      badge_rules: "ルール",
      col_total_score: "総合点",
      col_note: "備考 / リスク",
      no_picks: "該当銘柄なし",
      no_strats: "戦略実行結果がありません。",
      strat_picks_cnt: "{{n}} 銘柄",
      sec_patterns: "ステートレスパターン検出",
      col_overhead: "上値しこり",
      col_kline: "直近20日足",
      no_pat_sig: "本日のシグナルなし",
      no_pats: "パターン検出記録なし",
      pat_hits_cnt: "{{n}} 件検出",
      pat_neg_watch: "負期待・観測",
      pat_exp_watch: "観測期間",
      pat_t5_net: " · T+5純超過 {{v}}",
      pat_wf_adverse: "WF 本日逆風局面",
      pat_wf_joint: " · 複合OOS {{v}}({{d}}日)",
      policy_cn_slice: "中国A株のみ・局面スライス",
      policy_cn: "中国A株のみ",
      stale_banner: "⚠️ <b>旧パック縮退モード</b>：パック日付 <code>{{pack}}</code> が目標日 <code>{{exp}}</code> より古い状態です（{{reason}}）。観測用表示のみとし、強制指定なしの通知は抑制しました。",
      deg_prefix: "縮退説明：",
      disclaimer: "本レポートは研究・エンジニアリング観測目的であり、投資助言や売買推奨ではありません。",
      footer_tag: "クオンツ観測・T+N検証ベンチマーク",
      footer_repo: "GitHub リポジトリ",
      dist_flat: "横ばい",
      link_ai_board: "AI 帰属履歴 →",
      link_leaderboard: "T+N ランキング →",
      link_wf_board: "250日 Walk-Forward 検証 →",
      link_pat_wf: "OOS 検証 →",
      wf_cli_btn: "CLI",
      wf_cli_copied: "コピー済",
      pat_wf_pending: "境界未検証",
      pat_wf_boundary_note: "注：Walk-Forward の H1 は実際の決済日 &lt; 分割日で厳密に切断し境界跨ぎ標本を除外しており、H2 価格の逆風判定への混入を防止しています。",
      pat_wf_boundary_note_stats: "注：Walk-Forward の H1 は実際の決済日 &lt; {{mid}} で厳密に切断（境界跨ぎ {{n}} 件除外）しており、H2 価格の逆風判定への混入を防止しています。",
    }},
  }};
  var REGIME_MAP = {{
    en: {{ freezing: "Freezing", startup: "Startup", main_up: "Main Up", divergence: "Divergence", ebb: "Ebb", neutral: "Choppy" }},
    ja: {{ freezing: "極寒", startup: "初動", main_up: "主昇波", divergence: "分岐", ebb: "後退", neutral: "レンジ" }},
  }};
  var STRAT_MAP = {{
    en: {{ balanced_alpha: "Balanced Alpha", blue_chip_income: "Blue-Chip Income", capital_heat: "Capital Heat", dual_low: "Dual Low Value", global_value: "Global Value", low_volatility_quality: "Low-Vol Quality", momentum_quality: "Momentum Quality", oversold_reversal: "Oversold Reversal", quality_value: "Quality Value", shrink_pullback: "Shrink Pullback", us_momentum_quality: "US Momentum Quality", volume_breakout: "Volume Breakout" }},
    ja: {{ balanced_alpha: "バランス・アルファ", blue_chip_income: "優良高配当株", capital_heat: "資金モメンタム", dual_low: "低PER・低PBR", global_value: "グローバル・バリュー", low_volatility_quality: "低ボラ・クオリティ", momentum_quality: "モメンタム・クオリティ", oversold_reversal: "売られ過ぎ反発", quality_value: "クオリティ・バリュー", shrink_pullback: "出来高縮小押し目", us_momentum_quality: "米国モメンタム", volume_breakout: "出来高ブレイク" }},
  }};
  var PAT_MAP = {{
    en: {{ bottom_volume_yang: "Bottom Volume Surge", box_breakout: "Box Breakout", double_bottom_breakout: "Double Bottom Breakout", ma20_shrink_pullback: "MA20 Low-Vol Pullback", shooting_star_confirm: "Upper-Wick Confirm", single_yang_hold: "Single Bullish Hold", steady_trend_breakout: "Steady Trend Breakout", three_white_soldiers: "Three White Soldiers", three_white_soldiers_pullback: "Three Soldiers Pullback" }},
    ja: {{ bottom_volume_yang: "底値倍増陽線", box_breakout: "ボックス圏ブレイク", double_bottom_breakout: "ダブルボトム突破", ma20_shrink_pullback: "20日線低ボラ押し目", shooting_star_confirm: "上ヒゲ確認", single_yang_hold: "大陽線ホールド", steady_trend_breakout: "低ボラ堅調突破", three_white_soldiers: "赤三兵", three_white_soldiers_pullback: "赤三兵押し目確認" }},
  }};

  var lang = "zh";
  var theme = "dark";
  try {{
    var qs = new URLSearchParams(window.location.search);
    var qTheme = qs.get("theme");
    var qLang = (qs.get("lang") || "").toLowerCase();
    var savedTheme = localStorage.getItem("alphasift-theme");
    var savedLang = (localStorage.getItem("alphasift-lang") || "").toLowerCase();
    if (qTheme === "light" || qTheme === "dark") theme = qTheme;
    else if (savedTheme === "light" || savedTheme === "dark") theme = savedTheme;
    var rawLang = qLang || savedLang || (navigator.language || "").toLowerCase();
    if (rawLang.indexOf("en") === 0) lang = "en";
    else if (rawLang.indexOf("ja") === 0) lang = "ja";
    else lang = "zh";
  }} catch (e) {{}}

  function escHtml(s) {{
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {{
      return ({{ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }}[c]);
    }});
  }}
  function formatTpl(tpl, rawVars) {{
    if (!rawVars) return tpl;
    try {{
      var vars = JSON.parse(rawVars);
      Object.keys(vars).forEach(function (k) {{
        tpl = tpl.split("{{" + k + "}}").join(escHtml(vars[k]));
      }});
    }} catch (e) {{}}
    return tpl;
  }}

  var ICO_SUN = '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32 1.41 1.41M2 12h2m16 0h2M4.93 19.07l1.41-1.41m11.32-11.32 1.41-1.41"/></svg>';
  var ICO_MOON = '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
  var btn = document.getElementById("theme-toggle");
  function syncThemeBtn() {{
    var dict = I18N[lang] || I18N.zh;
    if (btn) btn.innerHTML = theme === "light" ? ICO_MOON + "<span>" + dict.theme_dark + "</span>" : ICO_SUN + "<span>" + dict.theme_light + "</span>";
  }}
  function syncBackLink() {{
    var link = document.getElementById("back-dashboard-link");
    if (!link) return;
    if (DETAIL_BASE.indexOf("http") !== 0 && DETAIL_BASE.indexOf("../index.html") !== 0) return;
    var baseClean = DETAIL_BASE.split("#")[0].split("?")[0];
    var p = new URLSearchParams();
    if (lang !== "zh") p.set("lang", lang);
    if (theme !== "dark") p.set("theme", theme);
    var q = p.toString();
    link.setAttribute("href", q ? baseClean + "?" + q : DETAIL_BASE);
    document.querySelectorAll("a[data-dash-hash]").forEach(function (a) {{
      var h = a.getAttribute("data-dash-hash");
      if (!h) return;
      var ap = new URLSearchParams();
      if (lang !== "zh") ap.set("lang", lang);
      if (theme !== "dark") ap.set("theme", theme);
      var patId = a.getAttribute("data-dash-pat");
      if (patId) ap.set("pat", patId);
      var aq = ap.toString();
      a.setAttribute("href", (aq ? baseClean + "?" + aq : baseClean) + "#" + h);
    }});
  }}
  function applyLang(nextLang) {{
    lang = (nextLang === "en" || nextLang === "ja") ? nextLang : "zh";
    try {{ localStorage.setItem("alphasift-lang", lang); }} catch (e) {{}}
    document.documentElement.lang = lang === "en" ? "en" : lang === "ja" ? "ja" : "zh-CN";
    document.documentElement.setAttribute("data-lang", lang);
    var dict = I18N[lang] || I18N.zh;
    document.title = dict.page_title;
    document.querySelectorAll("[data-i18n]").forEach(function (el) {{
      if (el.dataset.zhHtml === undefined) el.dataset.zhHtml = el.innerHTML;
      var k = el.getAttribute("data-i18n");
      if (lang === "zh") {{
        el.innerHTML = el.dataset.zhHtml;
      }} else if (dict[k] !== undefined) {{
        el.innerHTML = formatTpl(dict[k], el.getAttribute("data-i18n-vars"));
      }}
    }});
    document.querySelectorAll("[data-strategy]").forEach(function (el) {{
      if (el.dataset.zhText === undefined) el.dataset.zhText = el.textContent;
      var k = el.getAttribute("data-strategy");
      el.textContent = (lang === "zh" ? el.dataset.zhText : ((STRAT_MAP[lang] && STRAT_MAP[lang][k]) || el.dataset.zhText));
    }});
    document.querySelectorAll("[data-pattern]").forEach(function (el) {{
      if (el.dataset.zhText === undefined) el.dataset.zhText = el.textContent;
      var k = el.getAttribute("data-pattern");
      el.textContent = (lang === "zh" ? el.dataset.zhText : ((PAT_MAP[lang] && PAT_MAP[lang][k]) || el.dataset.zhText));
    }});
    document.querySelectorAll("[data-regime]").forEach(function (el) {{
      if (el.dataset.zhText === undefined) el.dataset.zhText = el.textContent;
      var k = el.getAttribute("data-regime");
      if (lang === "zh") el.textContent = el.dataset.zhText;
      else el.textContent = (REGIME_MAP[lang] && REGIME_MAP[lang][k]) || el.getAttribute("data-regime-raw") || k;
    }});
    document.querySelectorAll("[data-dist-flat]").forEach(function (el) {{
      el.textContent = dict.dist_flat || "平盘";
    }});
    var sw = document.getElementById("lang-switch");
    if (sw) sw.querySelectorAll("button").forEach(function (b) {{
      b.setAttribute("aria-pressed", String(b.getAttribute("data-lang") === lang));
    }});
    syncThemeBtn();
    syncBackLink();
  }}

  document.documentElement.setAttribute("data-theme", theme);
  applyLang(lang);
  var sw = document.getElementById("lang-switch");
  if (sw) {{
    sw.addEventListener("click", function (e) {{
      var b = e.target.closest("button");
      if (b && b.getAttribute("data-lang")) applyLang(b.getAttribute("data-lang"));
    }});
  }}
  var printBtn = document.getElementById("print-btn");
  if (printBtn) {{
    printBtn.addEventListener("click", function () {{ window.print(); }});
  }}
  if (btn) {{
    btn.addEventListener("click", function () {{
      theme = theme === "light" ? "dark" : "light";
      document.documentElement.setAttribute("data-theme", theme);
      syncThemeBtn();
      syncBackLink();
      try {{ localStorage.setItem("alphasift-theme", theme); }} catch (e) {{}}
    }});
  }}
  function fallbackCopyPlainText(text, onDone) {{
    try {{
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      if (onDone) onDone();
    }} catch (e) {{}}
  }}
  function copyPlainText(text, onDone) {{
    if (navigator.clipboard && navigator.clipboard.writeText) {{
      navigator.clipboard.writeText(text).then(function () {{ if (onDone) onDone(); }}).catch(function () {{
        fallbackCopyPlainText(text, onDone);
      }});
    }} else {{
      fallbackCopyPlainText(text, onDone);
    }}
  }}
  var patSec = document.getElementById("patterns");
  if (patSec) {{
    patSec.addEventListener("click", function (e) {{
      var b = e.target && e.target.closest ? e.target.closest(".wf-cli-btn[data-cli]") : null;
      if (!b) return;
      var cli = b.getAttribute("data-cli");
      if (!cli) return;
      copyPlainText(cli, function () {{
        var dict = I18N[lang] || I18N.zh;
        if (b._cliTimer) clearTimeout(b._cliTimer);
        b.classList.add("copied");
        b.textContent = dict.wf_cli_copied || "Copied";
        b._cliTimer = setTimeout(function () {{
          b.classList.remove("copied");
          b.textContent = (I18N[lang] || I18N.zh).wf_cli_btn || "CLI";
        }}, 1500);
      }});
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
    return atomic_write_text(
        output_path,
        render_daily_report_html(report, track_summary=track_summary),
    )
