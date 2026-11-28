# -*- coding: utf-8 -*-
"""Multi-market (US / HK / JP / KR / TW / IN / global) daily screening digest builder."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from alphasift.config import Config
from alphasift.daily_brief import resolve_strategy_display_names
from alphasift.daily_report import IM_CARD_MAX_CHARS, _format_strategy_entry, ensure_im_card_length
from alphasift.jsonutil import finite_float, safe_int
from alphasift.market_news import fetch_region_market_news
from alphasift.markets import get_market, latest_settled_close
from alphasift.models import ScreenResult
from alphasift.normalize import safe_text
from alphasift.source_guard import call_with_timeout
from alphasift.store import load_screen_result
from alphasift.timeutil import parse_timestamp

MARKET_CN_NAMES: dict[str, str] = {
    "cn": "A股",
    "us": "美股",
    "hk": "港股",
    "jp": "日股",
    "kr": "韩股",
    "tw": "台股",
    "in": "印股",
}
_MARKET_NEWS_TIMEOUT_SEC = 8.0


def _normalize_markets(markets: Sequence[str] | None) -> list[str]:
    if markets is None:
        return []
    return list(
        dict.fromkeys(
            cleaned
            for m in markets
            if (cleaned := safe_text(m).lower())
        )
    )


def _created_at_sort_key(value: object) -> tuple[int, float, str]:
    raw = safe_text(value)
    parsed = parse_timestamp(raw) if raw else None
    if parsed is not None:
        return (1, parsed.astimezone(timezone.utc).timestamp(), raw)
    return (0, 0.0, raw)


def _market_session_date(created_at: str, market: str) -> str:
    parsed = parse_timestamp(created_at)
    if parsed is None:
        return str(created_at or "")[:10]
    settled = latest_settled_close(market, parsed)
    if settled is not None:
        return settled[0].isoformat()
    mkt_info = get_market(market)
    return parsed.astimezone(ZoneInfo(mkt_info.timezone)).date().isoformat()


def load_multi_market_runs(
    config: Config,
    *,
    markets: Sequence[str],
    runs_dir: Path | None = None,
    trade_date: str | None = None,
) -> dict[str, list[ScreenResult]]:
    """Load latest (or trade_date-matched) saved runs grouped by market."""
    req_markets = _normalize_markets(markets)
    req_set = set(req_markets)
    if not req_set:
        return {}

    eff_trade_date = safe_text(trade_date) or None
    target_runs_dir = Path(runs_dir).expanduser() if runs_dir is not None else (config.data_dir / "runs")
    grouped: dict[str, list[tuple[str, ScreenResult]]] = {m: [] for m in req_markets}
    if not target_runs_dir.is_dir():
        return {m: [] for m in req_markets}

    for path in sorted(target_runs_dir.glob("*.json")):
        try:
            sr = load_screen_result(path, data_dir=config.data_dir)
        except Exception:  # noqa: BLE001
            continue
        mkt = safe_text(sr.market).lower() or "cn"
        if mkt not in req_set:
            continue
        sess_date = _market_session_date(sr.created_at or "", mkt)
        if eff_trade_date and sess_date != eff_trade_date:
            continue
        grouped.setdefault(mkt, []).append((sess_date, sr))

    out: dict[str, list[ScreenResult]] = {}
    for mkt in req_markets:
        candidates = grouped.get(mkt) or []
        if not candidates:
            out[mkt] = []
            continue
        target_sess = eff_trade_date or max((sd for sd, _ in candidates if sd), default="")
        # Deduplicate by (strategy, track) keeping latest created_at (UTC-normalized) for target session date
        by_key: dict[tuple[str, str], ScreenResult] = {}
        for sd, sr in candidates:
            if target_sess and sd != target_sess:
                continue
            tr = safe_text(sr.track) or ("ai" if sr.llm_ranked else "rules")
            key = (str(sr.strategy), tr)
            prev = by_key.get(key)
            if prev is None or _created_at_sort_key(sr.created_at) >= _created_at_sort_key(prev.created_at):
                by_key[key] = sr
        runs = sorted(
            by_key.values(),
            key=lambda r: (str(r.strategy), 0 if (r.track or "rules") == "rules" else 1),
        )
        out[mkt] = runs
    return out


def _top_picks_for_market(
    strategy_entries: list[dict[str, Any]],
    *,
    display_names: dict[str, str],
) -> list[dict[str, Any]]:
    by_code: dict[str, dict[str, Any]] = {}
    for st in strategy_entries:
        if not isinstance(st, dict):
            continue
        sname = safe_text(st.get("strategy"))
        raw_picks = st.get("picks")
        for pk in raw_picks if isinstance(raw_picks, list) else []:
            if not isinstance(pk, dict):
                continue
            code = safe_text(pk.get("code"))
            if not code:
                continue
            name_val = safe_text(pk.get("name"))
            industry_val = safe_text(pk.get("industry"))
            reason_val = safe_text(pk.get("ranking_reason"))
            item = by_code.setdefault(
                code,
                {
                    "code": code,
                    "name": name_val,
                    "industry": industry_val,
                    "strategies": [],
                    "scores": [],
                    "price": finite_float(pk.get("price")),
                    "pe_ratio": finite_float(pk.get("pe_ratio")),
                    "pb_ratio": finite_float(pk.get("pb_ratio")),
                    "change_pct": finite_float(pk.get("change_pct")),
                    "ranking_reason": reason_val,
                },
            )
            if sname and sname not in item["strategies"]:
                item["strategies"].append(sname)
            if not item["name"] and name_val:
                item["name"] = name_val
            if not item["industry"] and industry_val:
                item["industry"] = industry_val
            score_val = finite_float(pk.get("final_score"))
            if score_val is not None:
                item["scores"].append(score_val)
            for fld in ("price", "pe_ratio", "pb_ratio", "change_pct"):
                if item[fld] is None:
                    finite_val = finite_float(pk.get(fld))
                    if finite_val is not None:
                        item[fld] = finite_val
            if not item["ranking_reason"] and reason_val:
                item["ranking_reason"] = reason_val

    rows: list[dict[str, Any]] = []
    for item in by_code.values():
        avg_score = round(sum(item["scores"]) / len(item["scores"]), 2) if item["scores"] else 0.0
        rows.append({
            "code": item["code"],
            "name": item["name"],
            "industry": item["industry"],
            "strategy_count": len(item["strategies"]),
            "strategies": item["strategies"],
            "strategy_display_names": [display_names.get(s, s) for s in item["strategies"]],
            "avg_final_score": avg_score,
            "price": item["price"],
            "pe_ratio": item["pe_ratio"],
            "pb_ratio": item["pb_ratio"],
            "change_pct": item["change_pct"],
            "ranking_reason": item["ranking_reason"],
        })
    rows.sort(key=lambda x: (-x["strategy_count"], -x["avg_final_score"], x["code"]))
    return rows[:6]


def render_market_digest_im_card(
    digest: dict[str, Any],
    *,
    max_chars: int = IM_CARD_MAX_CHARS,
) -> str:
    digest_dict = digest if isinstance(digest, dict) else {}
    raw_sections = digest_dict.get("market_sections")
    sections = [s for s in raw_sections if isinstance(s, dict)] if isinstance(raw_sections, list) else []
    label_parts = [
        safe_text(s.get("market_name")) or safe_text(s.get("market")).upper()
        for s in sections
    ]
    mkt_labels = "·".join(lbl for lbl in label_parts if lbl)
    trade_date_lbl = safe_text(digest_dict.get("trade_date")) or "-"
    lines = [f"**AlphaSift 全球市场盘后精选 ({trade_date_lbl})｜{mkt_labels or '多市场'}**"]
    if sections:
        for sec in sections[:6]:
            m_name = safe_text(sec.get("market_name")) or safe_text(sec.get("market")).upper() or "多市场"
            st_cnt = max(safe_int(sec.get("strategy_count"), default=0), 0)
            sec_date = safe_text(sec.get("trade_date")) or "-"
            raw_top = sec.get("top_picks")
            top = [p for p in raw_top if isinstance(p, dict)] if isinstance(raw_top, list) else []
            top_items = []
            for p in top[:3]:
                code_txt = safe_text(p.get("code"))
                if not code_txt:
                    continue
                name_txt = safe_text(p.get("name"), max_len=8)
                score_val = finite_float(p.get("avg_final_score"))
                score_num = 0.0 if score_val is None else score_val
                label = f"{code_txt} {name_txt}".strip()
                top_items.append(f"{label}({score_num:.1f}分)")
            if top_items:
                lines.append(f"- **{m_name}**（{st_cnt} 组策略 · {sec_date}）：{'、'.join(top_items)}")
            else:
                lines.append(f"- **{m_name}**：今日无新增候选")
    else:
        lines.append("**概览**：所选市场暂无已保存的策略运行记录")

    mnews_raw = digest_dict.get("market_news")
    mnews = mnews_raw.get("items") if isinstance(mnews_raw, dict) else []
    if isinstance(mnews, list) and mnews and isinstance(mnews[0], dict):
        headline = safe_text(mnews[0].get("title"), max_len=55)
        if headline:
            lines.append(f"**市场快讯**：{headline}")

    detail_url = safe_text(digest_dict.get("detail_url"))
    if detail_url:
        lines.append(f"🔗 在线交互看板与历史战绩：{detail_url}")
    lines.append("注：量化形态观测与回测基准，非投资建议。")
    return ensure_im_card_length("\n".join(lines), max_chars=max_chars)


def build_markets_digest(
    runs_by_market: dict[str, list[ScreenResult]],
    *,
    markets: Sequence[str],
    trade_date: str | None = None,
    detail_url: str = "",
    include_news: bool = False,
    config: Config | None = None,
    track_summary: dict[str, Any] | None = None,
    regional_news_collector: Callable[..., tuple[list[dict[str, Any]], list[str]]] | None = None,
) -> dict[str, Any]:
    """Build a multi-market post-close screening digest (object='MarketDigest')."""
    req_markets = _normalize_markets(markets)
    eff_trade_date = safe_text(trade_date) or None
    summary_names = (
        track_summary.get("strategy_names")
        if isinstance(track_summary, dict) and isinstance(track_summary.get("strategy_names"), dict)
        else None
    )
    display_names = resolve_strategy_display_names(
        config.strategies_dir if config is not None else None,
        overrides=summary_names,
    )

    sections: list[dict[str, Any]] = []
    session_dates: list[str] = []
    degradation: list[str] = []

    for mkt in req_markets:
        runs = runs_by_market.get(mkt) or []
        mkt_meta = get_market(mkt)
        sess_dates = [
            _market_session_date(r.created_at or "", mkt)
            for r in runs
            if getattr(r, "created_at", "")
        ]
        mkt_date = eff_trade_date or (max(sess_dates) if sess_dates else "-")
        if mkt_date and mkt_date != "-":
            session_dates.append(mkt_date)
        strat_entries = [_format_strategy_entry(r, display_names=display_names) for r in runs]
        top_picks = _top_picks_for_market(strat_entries, display_names=display_names)
        if not runs:
            degradation.append(f"No saved runs found for market={mkt}")
        sections.append({
            "market": mkt,
            "market_name": MARKET_CN_NAMES.get(mkt, mkt_meta.name),
            "benchmark": mkt_meta.benchmark_name,
            "trade_date": mkt_date,
            "strategy_count": len(strat_entries),
            "strategies": strat_entries,
            "top_picks": top_picks,
        })

    resolved_date = eff_trade_date or (max(session_dates) if session_dates else datetime.now(timezone.utc).date().isoformat())

    market_news_section: dict[str, Any] = {"items": [], "sources": [], "errors": []}
    if include_news:
        try:
            if regional_news_collector is not None:
                n_items, n_sources = regional_news_collector(req_markets, limit=4)
            else:
                n_items, n_sources = call_with_timeout(
                    fetch_region_market_news,
                    req_markets,
                    limit=4,
                    tavily_keys=config.tavily_api_keys if config is not None else None,
                    serpapi_keys=config.serpapi_api_keys if config is not None else None,
                    timeout_sec=_MARKET_NEWS_TIMEOUT_SEC,
                    label="regional market news",
                )
            market_news_section["items"] = [item for item in n_items if isinstance(item, dict)] if isinstance(n_items, list) else list(n_items or [])
            market_news_section["sources"] = [s for s in (safe_text(src) for src in (n_sources or [])) if s]
        except Exception as exc:  # noqa: BLE001
            market_news_section["errors"].append(f"regional news skipped: {exc}")

    digest: dict[str, Any] = {
        "schema_version": 1,
        "object": "MarketDigest",
        "trade_date": resolved_date,
        "market": "+".join(req_markets) or "global",
        "markets": req_markets,
        "detail_url": safe_text(detail_url),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy_display_names": display_names,
        "market_sections": sections,
        "market_news": market_news_section,
        "degradation": degradation,
    }
    card = render_market_digest_im_card(digest)
    digest["im_card_markdown"] = card
    digest["im_card_chars"] = len(card)
    return digest
