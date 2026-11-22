# -*- coding: utf-8 -*-
"""Optional Top-K candidate news, announcement and fund-flow context."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import inspect
import json
from pathlib import Path
import re

import pandas as pd
import requests

from alphasift.source_guard import call_with_timeout

_NEGATIVE_EVENT_KEYWORDS = {
    "减持": ("减持", "拟减持", "被动减持"),
    "监管": ("处罚", "立案", "监管函", "问询函", "警示函", "调查"),
    "业绩压力": ("预亏", "亏损", "业绩下滑", "业绩减少", "净利润下降"),
    "财务风险": (
        "债务违约",
        "债务逾期",
        "逾期",
        "违约",
        "债务危机",
        "债务纠纷",
        "重大债务",
        "资不抵债",
        "资金链断裂",
        "无法清偿",
        "商誉减值",
        "资产减值",
    ),
    "退市风险": ("退市", "终止上市", "风险警示"),
    "诉讼风险": ("诉讼", "涉诉", "仲裁"),
    "质押冻结": ("冻结", "质押"),
}
_ITEM_SPLIT_RE = re.compile(r"\s*\|\s*|[；。\n]+")
_NEGATION_REDUCTION_RE = re.compile(
    r"(?:承诺|决定|同意|提前)?(?:不|未|无|终止|取消|放弃)减持|提前终止减持(?:计划)?|减持时间届满且未减持"
)
_NEGATION_REGULATOR_RE = re.compile(
    r"不予处罚|免于处罚|未被立案|无监管处罚|不存在(?:被)?处罚|解除警示"
)
_NEGATION_EARNINGS_RE = re.compile(
    r"(?:不存在|无)(?:业绩下滑|亏损)|同比减亏|亏损收窄|扭亏为盈"
)
_BENIGN_FINANCE_RE = re.compile(
    r"(?:非金融企业)?债务融资工具|发行(?:公司|科技)?债券|科技创新债券|偿还债务|债务豁免|可转债"
)
_ROUTINE_IMPAIRMENT_RE = re.compile(r"计提(?:各项|信用|资产|信用及资产)?减值准备")
_SEVERE_IMPAIRMENT_CUES = ("商誉减值", "大额", "巨额", "预亏", "亏损", "净利润下降", "重大", "大幅")
_ST_SYMBOL_RE = re.compile(r"(?<![A-Za-z0-9])\*?ST(?![A-Za-z0-9])")
_NEGATION_DELIST_RE = re.compile(
    r"撤销(?:退市|其他)?风险警示|不存在退市风险|不触发退市|申请摘帽"
)
_NEGATION_PLEDGE_RE = re.compile(
    r"(?:部分|全部)?(?:股份|股权)?(?:解除|解押)(?:部分|全部)?(?:股份|股权)?(?:质押|冻结)"
    r"|(?:质押|冻结)(?:已)?解除|(?:银行)?账户(?:解除|解冻)|质押展期|已解押"
)
_NEGATION_LITIGATION_RE = re.compile(
    r"(?:诉讼|涉诉|仲裁)(?:事项)?(?:进展)?[^，；|]{0,12}(?:胜诉|撤诉|结案|和解|终结|驳回)"
    r"|(?:撤诉|胜诉|终结(?:执行)?|达成和解)[^，；|]{0,12}(?:诉讼|涉诉|仲裁)"
    r"|(?:不涉及|无|不存在)(?:重大)?(?:诉讼|涉诉|仲裁)"
)
_POSITIVE_EVENT_KEYWORDS = {
    "回购增持": ("回购", "增持"),
    "订单经营": ("中标", "合同", "订单", "定点", "合作"),
    "业绩改善": ("预增", "扭亏", "增长", "净利润增长"),
    "股东回报": ("分红", "派息"),
    "激励": ("股权激励", "员工持股"),
}
_ANNOUNCEMENT_CATEGORY_KEYWORDS = {
    "业绩": ("业绩", "利润", "营收", "预增", "预亏", "扭亏", "年报", "季报"),
    "回购增持": ("回购", "增持"),
    "减持": ("减持", "被动减持"),
    "监管问询": ("监管函", "问询函", "警示函", "立案", "调查", "处罚"),
    "重大合同": ("中标", "合同", "订单", "定点", "合作协议"),
    "分红融资": ("分红", "派息", "配股", "定增", "可转债", "融资"),
    "诉讼担保": ("诉讼", "仲裁", "担保", "冻结", "质押"),
    "股权激励": ("股权激励", "员工持股"),
}
_SOURCE_WEIGHTS = {
    "announcement": 1.0,
    "quote": 0.85,
    "news": 0.65,
    "fund_flow": 0.75,
}
_DEFAULT_MAX_WORKERS = 6


def collect_candidate_context(
    candidate_df: pd.DataFrame,
    *,
    max_rows: int = 8,
    providers: list[str] | None = None,
    news_limit: int = 3,
    announcement_limit: int = 3,
    cache_dir: str | Path | None = None,
    cache_ttl_hours: int = 24,
    source_weights: dict[str, float] | None = None,
) -> tuple[list[dict[str, object]], list[str]]:
    """Collect candidate-level context rows keyed by stock code.

    The function is optional and best-effort. It should never decide
    eligibility; it only supplies LLM research material for already shortlisted
    candidates.
    """
    if candidate_df.empty or "code" not in candidate_df.columns or max_rows <= 0:
        return [], []

    providers = _normalize_providers(providers or [])
    tasks: list[dict[str, str]] = []
    for _, candidate in candidate_df.head(max_rows).iterrows():
        code = _normalize_code(candidate.get("code", ""))
        if not code or code == "000000":
            continue
        tasks.append(
            {
                "code": code,
                "name": str(candidate.get("name", "") or ""),
            }
        )

    if not tasks:
        return [], []

    results: list[tuple[dict[str, object] | None, list[str]] | None] = [None] * len(tasks)
    max_workers = min(_DEFAULT_MAX_WORKERS, len(tasks))
    if max_workers <= 1:
        for index, task in enumerate(tasks):
            results[index] = _collect_candidate_context_row(
                task,
                providers=providers,
                news_limit=news_limit,
                announcement_limit=announcement_limit,
                cache_dir=cache_dir,
                cache_ttl_hours=cache_ttl_hours,
                source_weights=source_weights,
            )
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_index = {
                executor.submit(
                    _collect_candidate_context_row,
                    task,
                    providers=providers,
                    news_limit=news_limit,
                    announcement_limit=announcement_limit,
                    cache_dir=cache_dir,
                    cache_ttl_hours=cache_ttl_hours,
                    source_weights=source_weights,
                ): index
                for index, task in enumerate(tasks)
            }
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    results[index] = future.result()
                except Exception as exc:
                    results[index] = (None, [f"{tasks[index]['code']} context: {exc}"])

    rows: list[dict[str, object]] = []
    errors: list[str] = []
    for result in results:
        if result is None:
            continue
        row, row_errors = result
        errors.extend(row_errors)
        if row is not None:
            rows.append(row)
    return rows, errors


def _collect_candidate_context_row(
    candidate: dict[str, str],
    *,
    providers: list[str],
    news_limit: int,
    announcement_limit: int,
    cache_dir: str | Path | None,
    cache_ttl_hours: int,
    source_weights: dict[str, float] | None,
) -> tuple[dict[str, object] | None, list[str]]:
    code = candidate["code"]
    errors: list[str] = []
    try:
        cached = _read_cache(cache_dir, code, providers, cache_ttl_hours=cache_ttl_hours)
        if cached is not None:
            _ensure_context_row_enrichment(
                cached,
                requested_sources=providers,
                source_weights=source_weights,
            )
            return cached, []
        row: dict[str, object] = {
            "code": code,
            "name": candidate.get("name", ""),
        }
        successful_sources: list[str] = []
        if "news" in providers:
            try:
                sig_params = inspect.signature(fetch_stock_news_summary).parameters
                if "name" in sig_params:
                    row["news"] = fetch_stock_news_summary(code, limit=news_limit, name=candidate.get("name", ""))
                else:
                    row["news"] = fetch_stock_news_summary(code, limit=news_limit)
                if row["news"]:
                    successful_sources.append("news")
            except Exception as exc:
                errors.append(f"{code} news: {exc}")
        if "announcement" in providers or "announcements" in providers:
            try:
                row["announcement"] = fetch_stock_announcement_summary(code, limit=announcement_limit)
                if row["announcement"]:
                    successful_sources.append("announcement")
            except Exception as exc:
                errors.append(f"{code} announcement: {exc}")
        if "fund_flow" in providers or "fundflow" in providers:
            try:
                row["fund_flow"] = fetch_stock_fund_flow_summary(code)
                if row["fund_flow"]:
                    successful_sources.append("fund_flow")
            except Exception as exc:
                errors.append(f"{code} fund_flow: {exc}")
        if "quote" in providers:
            try:
                row["quote"] = fetch_stock_quote_summary(code)
                if row["quote"]:
                    successful_sources.append("quote")
            except Exception as exc:
                errors.append(f"{code} quote: {exc}")
        if any(value for key, value in row.items() if key not in {"code", "name"}):
            row["source_count"] = len(successful_sources)
            row["source_confidence"] = _source_confidence(successful_sources, providers)
            row["source_weight_score"] = _source_weight_score(
                successful_sources,
                providers,
                source_weights=source_weights,
            )
            _ensure_context_row_enrichment(
                row,
                requested_sources=providers,
                successful_sources=successful_sources,
                source_weights=source_weights,
            )
            try:
                _write_cache(cache_dir, code, providers, row)
            except Exception as exc:
                errors.append(f"{code} cache: {exc}")
            return row, errors
        return None, errors
    except Exception as exc:
        return None, [*errors, f"{code} context: {exc}"]


def _fetch_stock_news_search_fallback(code: str, *, limit: int = 3, name: str = "") -> str:
    norm_code = str(code).zfill(6)
    clean_name = str(name or "").strip()
    query = f'"{clean_name}" {norm_code} 股票 最新新闻' if clean_name else f"{norm_code} 股票 最新新闻 公告"
    try:
        from alphasift.market_news import search_stock_news_via_web

        items = search_stock_news_via_web(query, limit=max(limit * 2, 4))
    except Exception:  # noqa: BLE001
        return ""
    cur_year = datetime.now().year
    stale_years = tuple(f"{y}年" for y in range(2020, cur_year))
    lines: list[str] = []
    for item in items:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        # Reject index/quote-page SEO boilerplate (e.g. 上证指数 000001 or stale historical snapshots)
        if ("实时行情" in title and "股价" in title) or ("上证指数" in title and "银行" in clean_name):
            continue
        if any(sy in title for sy in stale_years):
            continue
        line = " ".join(x for x in (item.get("published_at"), item.get("source"), title) if x)
        if line:
            lines.append(line)
        if len(lines) >= limit:
            break
    return _compress_text(" | ".join(_dedupe(lines)), max_len=520)


def fetch_stock_news_summary(code: str, *, limit: int = 3, name: str = "") -> str:
    norm_code = str(code).zfill(6)
    items: list[str] = []
    try:
        import akshare as ak

        df = call_with_timeout(
            ak.stock_news_em,
            symbol=norm_code,
            timeout_sec=4.0,
            label=f"stock_news_em:{norm_code}",
        )
        if df is not None and not df.empty:
            for _, row in df.head(max(limit, 1)).iterrows():
                title = _first_value(row, ["新闻标题", "标题", "title"])
                published_at = _first_value(row, ["发布时间", "时间", "date"])
                source = _first_value(row, ["文章来源", "来源", "source"])
                text = " ".join(item for item in [published_at, source, title] if item)
                if text:
                    items.append(text)
    except Exception:  # noqa: BLE001
        items = []

    if not items:
        fallback = _fetch_stock_news_search_fallback(norm_code, limit=limit, name=name)
        if fallback:
            return fallback
        return ""
    return _compress_text(" | ".join(_dedupe(items)), max_len=520)


def fetch_stock_announcement_summary(code: str, *, limit: int = 3) -> str:
    import akshare as ak

    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=45)).strftime("%Y%m%d")
    df = ak.stock_zh_a_disclosure_report_cninfo(
        symbol=str(code).zfill(6),
        market="沪深京",
        start_date=start,
        end_date=end,
    )
    if df is None or df.empty:
        return ""
    dated_items: list[tuple[str, str]] = []
    for _, row in df.iterrows():
        title = _first_value(row, ["公告标题", "标题", "announcementTitle", "title"])
        date = _first_value(row, ["公告时间", "公告日期", "date"])
        if title:
            dated_items.append((date, " ".join(item for item in [date, title] if item)))
    # Ensure newest disclosures appear first before slicing to `limit`.
    dated_items.sort(key=lambda pair: pair[0], reverse=True)
    items = [text for _, text in dated_items[: max(limit, 1)]]
    return _compress_text(" | ".join(_dedupe(items)), max_len=520)


def fetch_stock_fund_flow_summary(code: str) -> str:
    import akshare as ak

    market = _market_for_code(code)
    if not market:
        return ""
    df = ak.stock_individual_fund_flow(stock=str(code).zfill(6), market=market)
    if df is None or df.empty:
        return ""
    row = df.iloc[-1]
    fields = []
    for column in df.columns:
        name = str(column)
        if any(keyword in name for keyword in ["日期", "主力净流入", "超大单净流入", "大单净流入", "净占比"]):
            value = _safe_text(row.get(column))
            if value:
                fields.append(f"{name}={value}")
    return _compress_text("，".join(fields[:8]), max_len=420)


def fetch_stock_quote_summary(code: str) -> str:
    """Fetch lightweight Tencent quote/fundamental context for one candidate."""
    symbol = _tencent_symbol_for_code(code)
    if not symbol:
        return ""
    resp = requests.get(
        f"https://qt.gtimg.cn/q={symbol}",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=8,
    )
    resp.raise_for_status()
    text = resp.text or ""
    if "=\"" not in text:
        return ""
    body = text.split("=\"", 1)[1].split("\";", 1)[0]
    parts = body.split("~")
    if len(parts) < 46:
        return ""
    fields = [
        ("名称", _part(parts, 1)),
        ("现价", _part(parts, 3)),
        ("涨跌幅", _part(parts, 32)),
        ("最高", _part(parts, 33)),
        ("最低", _part(parts, 34)),
        ("成交额万元", _part(parts, 37)),
        ("换手率", _part(parts, 38)),
        ("市盈率", _part(parts, 39)),
        ("总市值亿元", _part(parts, 45)),
        ("流通市值亿元", _part(parts, 44)),
    ]
    return _compress_text(
        "，".join(f"{name}={value}" for name, value in fields if value),
        max_len=360,
    )


def _classify_negative_clause(clause: str) -> list[str]:
    flags: list[str] = []
    if not clause:
        return flags

    red_text = _NEGATION_REDUCTION_RE.sub("", clause)
    if any(kw in red_text for kw in _NEGATIVE_EVENT_KEYWORDS["减持"]):
        flags.append("减持")

    reg_text = _NEGATION_REGULATOR_RE.sub("", clause)
    if any(kw in reg_text for kw in _NEGATIVE_EVENT_KEYWORDS["监管"]):
        flags.append("监管")

    earn_text = _NEGATION_EARNINGS_RE.sub("", clause)
    if any(kw in earn_text for kw in _NEGATIVE_EVENT_KEYWORDS["业绩压力"]):
        flags.append("业绩压力")

    fin_text = _BENIGN_FINANCE_RE.sub("", clause)
    if _ROUTINE_IMPAIRMENT_RE.search(fin_text) and not any(cue in fin_text for cue in _SEVERE_IMPAIRMENT_CUES):
        fin_text = _ROUTINE_IMPAIRMENT_RE.sub("", fin_text)
    if any(kw in fin_text for kw in _NEGATIVE_EVENT_KEYWORDS["财务风险"]):
        flags.append("财务风险")

    delist_text = _NEGATION_DELIST_RE.sub("", clause)
    if any(kw in delist_text for kw in _NEGATIVE_EVENT_KEYWORDS["退市风险"]) or _ST_SYMBOL_RE.search(delist_text):
        flags.append("退市风险")

    lit_text = _NEGATION_LITIGATION_RE.sub("", clause)
    if any(kw in lit_text for kw in _NEGATIVE_EVENT_KEYWORDS["诉讼风险"]):
        flags.append("诉讼风险")

    pledge_text = _NEGATION_PLEDGE_RE.sub("", clause)
    if any(kw in pledge_text for kw in _NEGATIVE_EVENT_KEYWORDS["质押冻结"]):
        flags.append("质押冻结")

    return flags


def classify_negative_text(text: str) -> list[str]:
    """Classify negative event flags across piped/punctuated clauses with negation disambiguation."""
    flags: list[str] = []
    for clause in _ITEM_SPLIT_RE.split(str(text or "")):
        cleaned = clause.strip()
        if cleaned:
            flags.extend(_classify_negative_clause(cleaned))
    return _dedupe(flags)


def classify_context_events(row: dict[str, object]) -> list[str]:
    """Return coarse event tags from already collected candidate context."""
    text = _row_text(row)
    tags: list[str] = []
    for label, keywords in _POSITIVE_EVENT_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            tags.append(label)
    for label in classify_negative_text(text):
        tags.append(f"风险:{label}")
    return _dedupe(tags)


def classify_negative_events(row: dict[str, object]) -> list[str]:
    """Return negative event categories detected in candidate context."""
    return classify_negative_text(_row_text(row))


def classify_announcement_categories(row: dict[str, object]) -> list[str]:
    """Return coarse announcement categories from candidate context."""
    text = " ".join(
        str(row.get(key) or "")
        for key in ("announcement", "announcements")
        if row.get(key)
    )
    categories = [
        label
        for label, keywords in _ANNOUNCEMENT_CATEGORY_KEYWORDS.items()
        if any(keyword in text for keyword in keywords)
    ]
    return _dedupe(categories)


def _ensure_context_row_enrichment(
    row: dict[str, object],
    *,
    requested_sources: list[str] | None = None,
    successful_sources: list[str] | None = None,
    source_weights: dict[str, float] | None = None,
) -> None:
    successful_sources = successful_sources or _successful_sources_from_row(row)
    requested_sources = requested_sources or successful_sources
    if source_weights is not None or not isinstance(row.get("source_weight_score"), (int, float)):
        row["source_weight_score"] = _source_weight_score(
            successful_sources,
            requested_sources,
            source_weights=source_weights,
        )
    if not isinstance(row.get("announcement_categories"), list):
        row["announcement_categories"] = classify_announcement_categories(row)
    if not isinstance(row.get("event_tags"), list):
        row["event_tags"] = classify_context_events(row)
    if not isinstance(row.get("negative_event_flags"), list):
        row["negative_event_flags"] = classify_negative_events(row)
    summary = _safe_text(row.get("context_summary"), max_len=600)
    needs_summary = not summary
    if isinstance(row.get("event_tags"), list) and row["event_tags"] and "事件标签:" not in summary:
        needs_summary = True
    if (
        isinstance(row.get("announcement_categories"), list)
        and row["announcement_categories"]
        and "公告类别:" not in summary
    ):
        needs_summary = True
    if (
        isinstance(row.get("negative_event_flags"), list)
        and row["negative_event_flags"]
        and "负面风险:" not in summary
    ):
        needs_summary = True
    if needs_summary:
        row["context_summary"] = _summarize_row_context(row)


def _market_for_code(code: str) -> str:
    code = _normalize_code(code)
    if code.startswith("6"):
        return "sh"
    if code.startswith(("0", "3")):
        return "sz"
    return ""


def _tencent_symbol_for_code(code: str) -> str:
    code = _normalize_code(code)
    if code.startswith(("6", "5", "9")):
        return f"sh{code}"
    if code.startswith(("0", "3")):
        return f"sz{code}"
    if code.startswith(("4", "8", "920")):
        return f"bj{code}"
    return ""


def _part(parts: list[str], index: int) -> str:
    return _safe_text(parts[index] if index < len(parts) else "", max_len=80)


def _first_value(row: pd.Series, columns: list[str]) -> str:
    for column in columns:
        if column in row.index:
            value = _safe_text(row.get(column))
            if value:
                return value
    return ""


def _safe_text(value: object, *, max_len: int = 240) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "<na>"}:
        return ""
    return text[:max_len]


def _normalize_code(value: object) -> str:
    text = _safe_text(value, max_len=80)
    if not text:
        return ""
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if text.isdigit():
        return text.zfill(6)[-6:]
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", text)
    if match:
        return match.group(1)
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits.zfill(6)[-6:] if digits else ""


def _normalize_providers(providers: list[str]) -> list[str]:
    aliases = {"announcements": "announcement", "fundflow": "fund_flow"}
    result = []
    seen = set()
    for item in providers:
        key = aliases.get(str(item).strip().lower(), str(item).strip().lower())
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result


def _source_confidence(successful_sources: list[str], requested_sources: list[str]) -> float:
    requested = set(requested_sources)
    if not requested:
        return 0.0
    coverage = len(set(successful_sources)) / len(requested)
    return round(min(1.0, max(0.0, coverage)), 4)


def _source_weight_score(
    successful_sources: list[str],
    requested_sources: list[str],
    *,
    source_weights: dict[str, float] | None = None,
) -> float:
    requested = _normalize_providers(requested_sources)
    successful = set(_normalize_providers(successful_sources))
    weights = _normalized_source_weights(source_weights)
    total = sum(weights.get(source, 0.5) for source in requested)
    if total <= 0:
        return 0.0
    score = sum(weights.get(source, 0.5) for source in successful if source in requested) / total
    return round(min(1.0, max(0.0, score)), 4)


def _normalized_source_weights(source_weights: dict[str, float] | None) -> dict[str, float]:
    result = dict(_SOURCE_WEIGHTS)
    for key, value in (source_weights or {}).items():
        normalized = _normalize_providers([str(key)])
        if not normalized:
            continue
        try:
            result[normalized[0]] = max(float(value), 0.0)
        except (TypeError, ValueError):
            continue
    return result


def _summarize_row_context(row: dict[str, object]) -> str:
    parts = []
    for key, label in (
        ("news", "新闻"),
        ("announcement", "公告"),
        ("fund_flow", "资金流"),
        ("quote", "行情估值"),
    ):
        value = _compress_text(row.get(key), max_len=180)
        if value:
            parts.append(f"{label}:{value}")
    event_tags = row.get("event_tags")
    if isinstance(event_tags, list) and event_tags:
        parts.append("事件标签:" + ",".join(str(item) for item in event_tags[:6]))
    announcement_categories = row.get("announcement_categories")
    if isinstance(announcement_categories, list) and announcement_categories:
        parts.append("公告类别:" + ",".join(str(item) for item in announcement_categories[:6]))
    negative_flags = row.get("negative_event_flags")
    if isinstance(negative_flags, list) and negative_flags:
        parts.append("负面风险:" + ",".join(str(item) for item in negative_flags[:6]))
    return _compress_text("；".join(parts), max_len=520)


def _row_text(row: dict[str, object]) -> str:
    fields = []
    for key in ("news", "announcement", "announcements", "fund_flow", "quote", "summary", "context", "text"):
        value = row.get(key)
        if value:
            fields.append(str(value))
    return " ".join(fields)


def _successful_sources_from_row(row: dict[str, object]) -> list[str]:
    sources = []
    if row.get("news"):
        sources.append("news")
    if row.get("announcement") or row.get("announcements"):
        sources.append("announcement")
    if row.get("fund_flow") or row.get("fundflow"):
        sources.append("fund_flow")
    if row.get("quote"):
        sources.append("quote")
    return sources


def _compress_text(value: object, *, max_len: int) -> str:
    text = _safe_text(value, max_len=max(max_len * 2, 240))
    if not text:
        return ""
    text = " ".join(text.replace("\n", " ").split())
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    for delimiter in (" | ", "；", "。", "，", " "):
        idx = cut.rfind(delimiter)
        if idx >= max_len * 0.55:
            return cut[:idx].rstrip() + "..."
    return cut.rstrip() + "..."


def _cache_path(cache_dir: str | Path | None, code: str, providers: list[str]) -> Path | None:
    if cache_dir is None:
        return None
    key = "_".join(providers) or "none"
    return Path(cache_dir) / f"{str(code).zfill(6)}_{key}.json"


def _read_cache(
    cache_dir: str | Path | None,
    code: str,
    providers: list[str],
    *,
    cache_ttl_hours: int,
) -> dict[str, object] | None:
    path = _cache_path(cache_dir, code, providers)
    if path is None or not path.is_file() or cache_ttl_hours <= 0:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cached_at = datetime.fromisoformat(str(data.get("cached_at", "")))
        if datetime.now() - cached_at > timedelta(hours=cache_ttl_hours):
            return None
        row = data.get("row")
        return row if isinstance(row, dict) else None
    except Exception:
        return None


def _write_cache(
    cache_dir: str | Path | None,
    code: str,
    providers: list[str],
    row: dict[str, object],
) -> None:
    path = _cache_path(cache_dir, code, providers)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"cached_at": datetime.now().isoformat(), "row": row}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        key = item.strip()
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result
