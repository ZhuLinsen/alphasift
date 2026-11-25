# -*- coding: utf-8 -*-
"""Multi-market (US / HK / JP / KR / TW / IN / global) daily screening digest builder."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from alphasift.config import Config
from alphasift.daily_brief import resolve_strategy_display_names
from alphasift.daily_report import IM_CARD_MAX_CHARS, _format_strategy_entry, ensure_im_card_length
from alphasift.market_news import fetch_region_market_news
from alphasift.markets import get_market, latest_settled_close
from alphasift.models import ScreenResult
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
    req_markets = list(dict.fromkeys(str(m).strip().lower() for m in markets if str(m).strip()))
    req_set = set(req_markets)
    if not req_set:
        return {}

    target_runs_dir = Path(runs_dir).expanduser() if runs_dir is not None else (config.data_dir / "runs")
    grouped: dict[str, list[tuple[str, ScreenResult]]] = {m: [] for m in req_markets}
    if not target_runs_dir.is_dir():
        return {m: [] for m in req_markets}

    for path in sorted(target_runs_dir.glob("*.json")):
        try:
            sr = load_screen_result(path, data_dir=config.data_dir)
        except Exception:  # noqa: BLE001
            continue
        mkt = (sr.market or "cn").strip().lower()
        if mkt not in req_set:
            continue
        sess_date = _market_session_date(sr.created_at or "", mkt)
        if trade_date and sess_date != trade_date:
            continue
        grouped.setdefault(mkt, []).append((sess_date, sr))

    out: dict[str, list[ScreenResult]] = {}
    for mkt in req_markets:
        candidates = grouped.get(mkt) or []
        if not candidates:
            out[mkt] = []
            continue
        target_sess = trade_date or max((sd for sd, _ in candidates if sd), default="")
        # Deduplicate by (strategy, track) keeping latest created_at for target session date
        by_key: dict[tuple[str, str], ScreenResult] = {}
        for sd, sr in candidates:
            if target_sess and sd != target_sess:
                continue
            tr = sr.track or ("ai" if sr.llm_ranked else "rules")
            key = (str(sr.strategy), tr)
            prev = by_key.get(key)
            if prev is None or str(sr.created_at or "") >= str(prev.created_at or ""):
                by_key[key] = sr
        runs = sorted(
            by_key.values(),
            key=lambda r: (str(r.strategy), 0 if (r.track or "rules") == "rules" else 1),
        )
        out[mkt] = runs
    return out


def _finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _top_picks_for_market(
    strategy_entries: list[dict[str, Any]],
    *,
    display_names: dict[str, str],
) -> list[dict[str, Any]]:
    by_code: dict[str, dict[str, Any]] = {}
    for st in strategy_entries:
        sname = str(st.get("strategy") or "")
        for pk in st.get("picks") or []:
            code = str(pk.get("code") or "").strip()
            if not code:
                continue
            item = by_code.setdefault(
                code,
                {
                    "code": code,
                    "name": str(pk.get("name") or "").strip(),
                    "industry": str(pk.get("industry") or "").strip(),
                    "strategies": [],
                    "scores": [],
                    "price": _finite_float(pk.get("price")),
                    "pe_ratio": _finite_float(pk.get("pe_ratio")),
                    "pb_ratio": _finite_float(pk.get("pb_ratio")),
                    "change_pct": _finite_float(pk.get("change_pct")),
                    "ranking_reason": str(pk.get("ranking_reason") or "").strip(),
                },
            )
            if sname and sname not in item["strategies"]:
                item["strategies"].append(sname)
            score_val = _finite_float(pk.get("final_score"))
            if score_val is not None:
                item["scores"].append(score_val)
            for fld in ("price", "pe_ratio", "pb_ratio", "change_pct"):
                if item[fld] is None:
                    finite_val = _finite_float(pk.get(fld))
                    if finite_val is not None:
                        item[fld] = finite_val
            if not item["ranking_reason"] and pk.get("ranking_reason"):
                item["ranking_reason"] = str(pk.get("ranking_reason") or "").strip()

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
    sections = digest.get("market_sections") or []
    mkt_labels = "·".join(s.get("market_name") or str(s.get("market") or "").upper() for s in sections)
    lines = [f"**AlphaSift 全球市场盘后精选 ({digest.get('trade_date', '-')})｜{mkt_labels or '多市场'}**"]
    if sections:
        for sec in sections[:6]:
            m_name = sec.get("market_name") or str(sec.get("market") or "").upper()
            st_cnt = int(sec.get("strategy_count") or 0)
            top = sec.get("top_picks") or []
            if top:
                top_txt = "、".join(
                    f"{p.get('code')} {str(p.get('name') or '')[:8]}({(_finite_float(p.get('avg_final_score')) or 0.0):.1f}分)"
                    for p in top[:3]
                )
                lines.append(f"- **{m_name}**（{st_cnt} 组策略 · {sec.get('trade_date', '-')}）：{top_txt}")
            else:
                lines.append(f"- **{m_name}**：今日无新增候选")
    else:
        lines.append("**概览**：所选市场暂无已保存的策略运行记录")

    mnews = ((digest.get("market_news") or {}).get("items") or []) if isinstance(digest.get("market_news"), dict) else []
    if mnews:
        lines.append(f"**市场快讯**：{str(mnews[0].get('title') or '')[:55]}")

    detail_url = str(digest.get("detail_url") or "").strip()
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
    req_markets = list(dict.fromkeys(str(m).strip().lower() for m in markets if str(m).strip()))
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
        mkt_date = trade_date or (max(sess_dates) if sess_dates else "-")
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

    resolved_date = trade_date or (max(session_dates) if session_dates else datetime.now(timezone.utc).date().isoformat())

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
            market_news_section["items"] = list(n_items or [])
            market_news_section["sources"] = list(n_sources or [])
        except Exception as exc:  # noqa: BLE001
            market_news_section["errors"].append(f"regional news skipped: {exc}")

    digest: dict[str, Any] = {
        "schema_version": 1,
        "object": "MarketDigest",
        "trade_date": resolved_date,
        "market": "+".join(req_markets) or "global",
        "markets": req_markets,
        "detail_url": str(detail_url or "").strip(),
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
