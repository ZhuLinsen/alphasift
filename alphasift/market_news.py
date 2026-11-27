# -*- coding: utf-8 -*-
"""Multi-source market-wide and candidate catalyst news fetching for daily reports."""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import json
from alphasift.jsonutil import atomic_write_strict_json, safe_int
import os
from pathlib import Path
import re
from typing import Any

import requests

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_NOISE_PATTERNS = (
    "互动平台",
    "融资融券余额",
    "股吧",
    "龙虎榜营业部",
    "资金流向",
    "代表团",
    "民航组织",
    "实时行情, 股票股价",
)
_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("宏观政策", ("央行", "证监会", "上交所", "深交所", "北交所", "沪深交易所", "中国结算", "发改委", "财政", "国务院", "降准", "降息", "LPR", "政策", "PMI", "GDP", "CPI", "关税")),
    ("海外市场", ("美联储", "美股", "纳斯达克", "道指", "标普", "欧股", "港股", "恒生", "日元", "美元", "油价", "黄金")),
    ("板块产业", ("板块", "产业链", "算力", "AI", "人工智能", "芯片", "半导体", "新能源", "光伏", "锂电", "医药", "创新药", "银行", "券商", "低空", "机器人", "军工")),
    ("公司动态", ("回购", "增持", "减持", "业绩", "预告", "分红", "并购", "重组", "中标", "涨停", "跌停")),
)


def _norm_title_key(text: str) -> str:
    return re.sub(r"[\W_]+", "", str(text or "")).lower()[:48]


def _classify_news_category(text: str) -> str:
    for label, keywords in _CATEGORY_RULES:
        if any(kw in text for kw in keywords):
            return label
    return "市场要闻"


def _extract_list(payload: object, *keys: str) -> list[Any]:
    cur: object = payload
    for key in keys:
        if not isinstance(cur, dict):
            return []
        cur = cur.get(key)
    return cur if isinstance(cur, list) else []


def _format_pub_time(raw: object) -> str:
    val = str(raw or "").strip()
    if not val:
        return ""
    if val.isdigit():
        if not re.fullmatch(r"\d{10,13}", val):
            return ""
        try:
            ts = int(val)
            if ts > 1_000_000_000_000:
                ts //= 1000
            if not (946_684_800 <= ts <= 4_102_444_800):
                return ""
            return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
        except (OSError, ValueError, OverflowError):
            return ""
    m = re.search(r"(\d{2}-\d{2})[\sT]+(\d{2}:\d{2})", val)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    m2 = re.search(r"(\d{4}-\d{2}-\d{2})", val)
    return m2.group(1) if m2 else val[:16]


def _clean_line(text: object, *, max_len: int = 120) -> str:
    s = " ".join(re.sub(r"<[^>]+>", " ", str(text or "")).split())
    if len(s) > max_len:
        return s[: max_len - 1].rstrip() + "…"
    return s


def _redact_text(text: str, secrets: Sequence[str] = ()) -> str:
    out = str(text or "")
    for s in secrets:
        if s:
            out = out.replace(s, "***")
    out = re.sub(r"(?i)(api[_-]?key|token|tvly-|key)[=:\s]+[^\s&,'\"]+", r"\1=***", out)
    return out[:180]


def _fetch_eastmoney_fast_news(*, limit: int = 8, timeout_sec: float = 5.0) -> list[dict[str, Any]]:
    url = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
    collected: list[dict[str, Any]] = []
    # Column 103 focuses on A-share listed companies / market moves; 102 covers broader macro/market headlines.
    for col in ("103", "102"):
        resp = requests.get(
            url,
            params={
                "client": "web",
                "biz": "web_724",
                "fastColumn": col,
                "sortEnd": "",
                "pageSize": max(limit, 10),
                "req_trace": str(int(datetime.now().timestamp() * 1000)),
            },
            headers=_HEADERS,
            timeout=timeout_sec,
        )
        resp.raise_for_status()
        payload = resp.json()
        rows = _extract_list(payload, "data", "fastNewsList")
        for item in rows:
            if not isinstance(item, dict):
                continue
            title = _clean_line(item.get("title") or item.get("summary") or "", max_len=110)
            if not title or len(title) < 6:
                continue
            summary = _clean_line(item.get("summary") or "", max_len=140)
            collected.append({
                "title": title,
                "summary": summary if summary and summary != title else "",
                "published_at": _format_pub_time(item.get("showTime")),
                "source": "东方财富7x24",
                "category": _classify_news_category(f"{title} {summary}"),
            })
        if len(collected) >= limit * 2:
            break
    return collected


def _fetch_ths_fast_news(*, limit: int = 8, timeout_sec: float = 5.0) -> list[dict[str, Any]]:
    resp = requests.get(
        "https://news.10jqka.com.cn/tapp/news/push/stock",
        params={"page": 1, "tag": "", "track": "website", "pagesize": max(limit, 12)},
        headers=_HEADERS,
        timeout=timeout_sec,
    )
    resp.raise_for_status()
    payload = resp.json()
    rows = _extract_list(payload, "data", "list")
    out: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        title = _clean_line(item.get("title") or item.get("digest") or "", max_len=110)
        if not title or len(title) < 6:
            continue
        summary = _clean_line(item.get("digest") or "", max_len=140)
        out.append({
            "title": title,
            "summary": summary if summary and summary != title else "",
            "published_at": _format_pub_time(item.get("rtime") or item.get("ctime")),
            "source": "同花顺快讯",
            "category": _classify_news_category(f"{title} {summary}"),
        })
    return out


def _fetch_sina_fast_news(*, limit: int = 8, timeout_sec: float = 5.0) -> list[dict[str, Any]]:
    resp = requests.get(
        "https://zhibo.sina.com.cn/api/zhibo/feed",
        params={"page": 1, "page_size": max(limit, 12), "zhibo_id": 152, "tag_id": 0, "dire": "f", "dpc": 1, "type": 1},
        headers=_HEADERS,
        timeout=timeout_sec,
    )
    resp.raise_for_status()
    payload = resp.json()
    rows = _extract_list(payload, "result", "data", "feed", "list")
    out: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        raw_text = _clean_line(item.get("rich_text") or "", max_len=160)
        if not raw_text or len(raw_text) < 8:
            continue
        m = re.match(r"^【([^】]{4,70})】\s*(.*)$", raw_text)
        if m:
            title = m.group(1).strip()
            summary = m.group(2).strip()[:120]
        else:
            title = raw_text[:100]
            summary = ""
        out.append({
            "title": title,
            "summary": summary,
            "published_at": _format_pub_time(item.get("create_time")),
            "source": "新浪财经7x24",
            "category": _classify_news_category(raw_text),
        })
    return out


def _resolve_search_keys(
    explicit: Sequence[str] | None,
    *env_names: str,
) -> list[str]:
    if explicit is not None:
        return [str(k).strip() for k in explicit if str(k).strip()]
    out: list[str] = []
    for env_name in env_names:
        raw = os.getenv(env_name, "").strip()
        if raw and raw.lower() not in {"0", "false", "none", "off"}:
            for item in raw.split(","):
                k = item.strip()
                if k and k not in out:
                    out.append(k)
    return out


def search_stock_news_via_web(
    query: str,
    *,
    limit: int = 3,
    tavily_keys: Sequence[str] | None = None,
    serpapi_keys: Sequence[str] | None = None,
    timeout_sec: float = 6.0,
) -> list[dict[str, str]]:
    """Search stock or market news via optional Tavily / SerpAPI keys without exposing credentials."""
    t_keys = _resolve_search_keys(tavily_keys, "TAVILY_API_KEYS", "TAVILY_API_KEY")
    s_keys = _resolve_search_keys(serpapi_keys, "SERPAPI_API_KEYS", "SERPAPI_API_KEY")
    max_res = max(1, min(safe_int(limit, default=3), 8))

    for key in t_keys:
        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": key,
                    "query": query,
                    "search_depth": "basic",
                    "topic": "news",
                    "max_results": max_res,
                    "days": 7,
                },
                headers={"Content-Type": "application/json"},
                timeout=timeout_sec,
            )
            if resp.status_code in {401, 403, 429, 432}:
                continue
            resp.raise_for_status()
            data = resp.json()
            results = _extract_list(data, "results")
            items: list[dict[str, str]] = []
            for r in results[:max_res]:
                if not isinstance(r, dict):
                    continue
                title = _clean_line(r.get("title") or "", max_len=110)
                if not title:
                    continue
                items.append({
                    "title": title,
                    "summary": _clean_line(r.get("content") or "", max_len=120),
                    "published_at": _format_pub_time(r.get("published_date")),
                    "source": "Tavily",
                    "category": _classify_news_category(title),
                })
            if items:
                return items
        except Exception:  # noqa: BLE001
            continue

    for key in s_keys:
        try:
            resp = requests.get(
                "https://serpapi.com/search.json",
                params={"q": query, "api_key": key, "num": max_res, "tbm": "nws", "hl": "zh-cn"},
                timeout=timeout_sec,
            )
            if resp.status_code in {401, 403, 429}:
                continue
            resp.raise_for_status()
            data = resp.json()
            results = _extract_list(data, "news_results") or _extract_list(data, "organic_results")
            items = []
            for r in results[:max_res]:
                if not isinstance(r, dict):
                    continue
                title = _clean_line(r.get("title") or "", max_len=110)
                if not title:
                    continue
                items.append({
                    "title": title,
                    "summary": _clean_line(r.get("snippet") or "", max_len=120),
                    "published_at": _format_pub_time(r.get("date")),
                    "source": str(r.get("source") or "SerpAPI")[:24],
                    "category": _classify_news_category(title),
                })
            if items:
                return items
        except Exception:  # noqa: BLE001
            continue

    return []


def _select_and_dedupe_news(raw_items: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    # First pass excludes low-signal platform Q&A / boilerplate; second pass backfills if needed.
    for allow_noise in (False, True):
        for item in raw_items:
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            if not allow_noise and any(p in title for p in _NOISE_PATTERNS):
                continue
            key = _norm_title_key(title)
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(item)
            if len(deduped) >= limit:
                return deduped
    return deduped


def _read_news_cache(cache_file: Path | None, ttl_hours: int) -> dict[str, Any] | None:
    ttl = safe_int(ttl_hours, default=0)
    if cache_file is None or not cache_file.is_file() or ttl <= 0:
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        raw_ts = str(data.get("cached_at") or "").strip()
        if raw_ts.endswith("Z"):
            raw_ts = raw_ts[:-1] + "+00:00"
        cached_at = datetime.fromisoformat(raw_ts)
        now = datetime.now(cached_at.tzinfo) if cached_at.tzinfo is not None else datetime.now()
        if now - cached_at > timedelta(hours=ttl):
            return None
        raw_items = data.get("items")
        if not isinstance(raw_items, list):
            return None
        valid_items = [
            item for item in raw_items
            if isinstance(item, dict) and str(item.get("title") or "").strip()
        ]
        if not valid_items:
            return None
        return {**data, "items": valid_items}
    except Exception:  # noqa: BLE001
        return None


def _write_news_cache(cache_file: Path | None, payload: dict[str, Any]) -> None:
    if cache_file is None:
        return
    try:
        atomic_write_strict_json(
            cache_file,
            {"cached_at": datetime.now().isoformat(), **payload},
            indent=2,
        )
    except OSError:
        pass


def fetch_cn_market_news(
    *,
    limit: int = 6,
    trade_date: str | None = None,
    cache_dir: Path | None = None,
    cache_ttl_hours: int = 2,
    tavily_keys: Sequence[str] | None = None,
    serpapi_keys: Sequence[str] | None = None,
    timeout_sec: float = 5.0,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Fetch recent CN market / policy / sector headlines with multi-source fallback."""
    target_limit = max(1, safe_int(limit, default=6))
    date_tag = (trade_date or datetime.now().strftime("%Y-%m-%d")).strip()
    safe_date_tag = re.sub(r"[^0-9A-Za-z._-]", "_", date_tag).strip("._") or "latest"
    cache_file = Path(cache_dir) / f"market_news_cn_{safe_date_tag}.json" if cache_dir else None
    cached = _read_news_cache(cache_file, cache_ttl_hours)
    if cached is not None:
        return list(cached["items"])[:target_limit], list(cached.get("sources") or []), []

    raw_items: list[dict[str, Any]] = []
    sources: list[str] = []
    errors: list[str] = []
    secrets = [
        *_resolve_search_keys(tavily_keys, "TAVILY_API_KEYS", "TAVILY_API_KEY"),
        *_resolve_search_keys(serpapi_keys, "SERPAPI_API_KEYS", "SERPAPI_API_KEY"),
    ]

    providers = (
        ("东方财富7x24", _fetch_eastmoney_fast_news),
        ("同花顺快讯", _fetch_ths_fast_news),
        ("新浪财经7x24", _fetch_sina_fast_news),
    )
    # Query EastMoney + Tonghuashun in parallel, then assemble in deterministic priority order
    # (EastMoney CN company/market news first, then Tonghuashun market headlines).
    rows_by_label: dict[str, list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = {
            pool.submit(fn, limit=max(target_limit, 8), timeout_sec=timeout_sec): label
            for label, fn in providers[:2]
        }
        for fut in as_completed(futs):
            label = futs[fut]
            try:
                rows = fut.result()
                if rows:
                    rows_by_label[label] = rows
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{label}: {_redact_text(str(exc), secrets)}")
    for label, _ in providers[:2]:
        if label in rows_by_label:
            raw_items.extend(rows_by_label[label])
            sources.append(label)

    items = _select_and_dedupe_news(raw_items, limit=target_limit)
    if len(items) < min(3, target_limit):
        try:
            sina_rows = _fetch_sina_fast_news(limit=max(target_limit, 8), timeout_sec=timeout_sec)
            if sina_rows:
                raw_items.extend(sina_rows)
                sources.append("新浪财经7x24")
                items = _select_and_dedupe_news(raw_items, limit=target_limit)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"新浪财经7x24: {_redact_text(str(exc), secrets)}")

    if len(items) < min(3, target_limit):
        query = f"A股 {date_tag} 收盘 板块 要闻 政策" if trade_date else "A股 今日 收盘 板块 要闻 政策"
        web_rows = search_stock_news_via_web(
            query,
            limit=target_limit,
            tavily_keys=tavily_keys,
            serpapi_keys=serpapi_keys,
            timeout_sec=timeout_sec + 1.0,
        )
        if web_rows:
            raw_items.extend(web_rows)
            sources.extend(sorted({r["source"] for r in web_rows if r.get("source")}))
            items = _select_and_dedupe_news(raw_items, limit=target_limit)

    deduped_sources = list(dict.fromkeys(sources))
    if items:
        _write_news_cache(cache_file, {"items": items, "sources": deduped_sources})
    return items, deduped_sources, (errors if not items else [])


def fetch_region_market_news(
    markets: Sequence[str],
    *,
    limit: int = 4,
    tavily_keys: Sequence[str] | None = None,
    serpapi_keys: Sequence[str] | None = None,
    timeout_sec: float = 6.0,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Best-effort news fetch for US/Asia/Global market digests when web search keys exist."""
    mkt_set = {str(m).strip().lower() for m in markets if str(m).strip()}
    if not mkt_set:
        return [], []
    if "us" in mkt_set and len(mkt_set) == 1:
        query = "US stock market S&P 500 Nasdaq closing highlights today"
    elif "hk" in mkt_set:
        query = "港股 恒生指数 亚太股市 收盘 要闻"
    else:
        query = "Global equity markets Asia US stocks closing news today"
    rows = search_stock_news_via_web(
        query,
        limit=limit,
        tavily_keys=tavily_keys,
        serpapi_keys=serpapi_keys,
        timeout_sec=timeout_sec,
    )
    return rows, sorted({r["source"] for r in rows if r.get("source")})
