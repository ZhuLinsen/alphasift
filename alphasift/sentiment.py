# -*- coding: utf-8 -*-
"""Deterministic, evidence-backed sentiment assessment for shortlisted picks."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from alphasift.models import Pick
from alphasift.normalize import normalize_code

_SOURCE_RELIABILITY = {
    "announcement": 1.0,
    "fund_flow": 0.85,
    "news": 0.65,
    "quote": 0.55,
}
_POSITIVE_KEYWORDS = {
    "回购增持": ("回购", "增持"),
    "业绩改善": ("预增", "扭亏", "净利润增长", "业绩增长", "超预期"),
    "订单催化": ("中标", "签订合同", "获得订单", "重大订单", "战略合作", "项目定点"),
    "股东回报": ("分红", "派息", "现金红利"),
    "经营进展": ("获批", "投产", "产能释放", "机构调研"),
}
_NEGATIVE_KEYWORDS = {
    "减持": ("减持", "被动减持"),
    "监管": ("处罚", "立案", "监管函", "问询函", "警示函", "调查"),
    "业绩压力": ("预亏", "亏损", "业绩下滑", "业绩减少", "净利润下降"),
    "财务风险": ("债务逾期", "违约", "商誉减值", "资产减值", "资金占用"),
    "退市风险": ("退市", "*ST", "终止上市"),
    "诉讼风险": ("诉讼", "仲裁", "冻结", "质押违约"),
    "经营风险": ("停产", "订单取消", "合同终止", "项目终止"),
}
_NEGATION_PREFIX = re.compile(
    r"(?:不|未|无|并未|不会|没有|不存在|否认|停止|终止|取消|撤回|放弃)[^，。；;！？!?]{0,5}$"
)
_NEGATION_SUFFIX = re.compile(
    r"^[^，。；;！？!?]{0,5}(?:取消|终止|撤回|不实施|不存在|不属实)"
)
_DATE_PATTERN = re.compile(r"(?<!\d)(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})(?:日)?(?!\d)")


def assess_pick_sentiment(
    pick: Pick,
    *,
    context_row: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Assess one pick from collected and host-provided context.

    No recognizable evidence means unavailable. A neutral score is never
    fabricated merely because a candidate has no sentiment data.
    """
    evidence: list[dict[str, Any]] = []
    dates: list[str] = []
    row = context_row if isinstance(context_row, dict) else {}

    _append_text_evidence(evidence, dates, "announcement", row.get("announcement"))
    _append_text_evidence(evidence, dates, "announcement", row.get("announcements"))
    _append_text_evidence(evidence, dates, "news", row.get("news"))
    _append_fund_flow_evidence(evidence, dates, row.get("fund_flow") or row.get("fundflow"))
    _append_quote_evidence(evidence, dates, row.get("quote"))

    dsa_context = pick.dsa_context if isinstance(pick.dsa_context, dict) else {}
    _append_dsa_news_evidence(evidence, dates, dsa_context.get("news"))
    _append_dsa_news_evidence(evidence, dates, pick.dsa_news)
    _append_fund_flow_evidence(evidence, dates, _dsa_capital_flow(dsa_context))
    _append_quote_evidence(evidence, dates, dsa_context.get("quote"))
    evidence = _deduplicate_evidence(evidence)[:12]

    if not evidence:
        return {
            "available": False,
            "score": None,
            "label": "unavailable",
            "confidence": 0.0,
            "source_count": 0,
            "positive_events": [],
            "negative_events": [],
            "evidence": [],
            "as_of": "",
        }

    signed_weight = sum(
        float(item["signal"]) * float(item["weight"])
        for item in evidence
    )
    total_weight = sum(
        abs(float(item["signal"])) * float(item["weight"])
        for item in evidence
    )
    score = 50.0 if total_weight <= 0 else 50.0 + 40.0 * signed_weight / total_weight
    score = round(min(100.0, max(0.0, score)), 2)
    sources = sorted({str(item["source"]) for item in evidence})
    confidence = _sentiment_confidence(sources, len(evidence))
    positive_events = _dedupe_strings([
        str(item["category"])
        for item in evidence
        if float(item["signal"]) > 0
    ])
    negative_events = _dedupe_strings([
        str(item["category"])
        for item in evidence
        if float(item["signal"]) < 0
    ])
    return {
        "available": True,
        "score": score,
        "label": _sentiment_label(score),
        "confidence": confidence,
        "source_count": len(sources),
        "positive_events": positive_events,
        "negative_events": negative_events,
        "evidence": [
            {
                "source": item["source"],
                "polarity": "positive" if float(item["signal"]) > 0 else "negative",
                "category": item["category"],
                "text": item["text"],
                "weight": round(float(item["weight"]), 4),
            }
            for item in evidence
        ],
        "as_of": max(dates) if dates else datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def apply_sentiment_overlay(
    picks: list[Pick],
    *,
    context_rows: list[dict[str, object]] | None = None,
    weight: float = 0.0,
    min_confidence: float = 0.45,
    max_delta: float = 5.0,
) -> tuple[list[Pick], list[str]]:
    """Attach sentiment fields and optionally adjust final scores within a cap."""
    if not picks:
        return picks, []

    rows_by_code = {
        normalize_code(row.get("code"), allow_ticker=True): row
        for row in (context_rows or [])
        if isinstance(row, dict) and normalize_code(row.get("code"), allow_ticker=True)
    }
    effective_weight = min(1.0, max(0.0, _finite_float(weight)))
    confidence_floor = min(1.0, max(0.0, _finite_float(min_confidence)))
    delta_cap = max(0.0, _finite_float(max_delta))
    assessed_count = 0
    applied_count = 0

    for pick in picks:
        code = normalize_code(pick.code, allow_ticker=True)
        assessment = assess_pick_sentiment(pick, context_row=rows_by_code.get(code))
        pick.sentiment_available = bool(assessment["available"])
        pick.sentiment_score = assessment["score"]
        pick.sentiment_label = str(assessment["label"])
        pick.sentiment_confidence = float(assessment["confidence"])
        pick.sentiment_source_count = int(assessment["source_count"])
        pick.sentiment_positive_events = list(assessment["positive_events"])
        pick.sentiment_negative_events = list(assessment["negative_events"])
        pick.sentiment_evidence = list(assessment["evidence"])
        pick.sentiment_as_of = str(assessment["as_of"])
        pick.sentiment_score_delta = 0.0
        if pick.sentiment_available:
            assessed_count += 1
        if (
            effective_weight <= 0
            or delta_cap <= 0
            or not pick.sentiment_available
            or pick.sentiment_score is None
            or pick.sentiment_confidence < confidence_floor
        ):
            continue
        raw_delta = (
            (float(pick.sentiment_score) - 50.0)
            * effective_weight
            * pick.sentiment_confidence
        )
        delta = min(delta_cap, max(-delta_cap, raw_delta))
        pick.sentiment_score_delta = round(delta, 4)
        pick.final_score = round(float(pick.final_score) + delta, 4)
        applied_count += 1

    if applied_count:
        picks.sort(key=lambda item: item.final_score, reverse=True)
        for rank, pick in enumerate(picks, start=1):
            pick.rank = rank

    notes: list[str] = []
    if effective_weight > 0:
        notes.append(
            "Sentiment overlay "
            f"assessed={assessed_count}/{len(picks)}, applied={applied_count}, "
            f"weight={effective_weight:.2f}, max_delta={delta_cap:.2f}"
        )
    return picks, notes


def _append_text_evidence(
    evidence: list[dict[str, Any]],
    dates: list[str],
    source: str,
    value: object,
) -> None:
    text = _compact_text(value)
    if not text:
        return
    dates.extend(_extract_dates(text))
    reliability = _SOURCE_RELIABILITY[source]
    for polarity, mapping, signal in (
        ("positive", _POSITIVE_KEYWORDS, 1.0),
        ("negative", _NEGATIVE_KEYWORDS, -1.0),
    ):
        for category, keywords in mapping.items():
            match = _first_non_negated_keyword(text, keywords)
            if match is None:
                continue
            evidence.append({
                "source": source,
                "polarity": polarity,
                "category": category,
                "text": _evidence_snippet(text, match[0], match[1]),
                "signal": signal,
                "weight": reliability,
            })


def _append_dsa_news_evidence(
    evidence: list[dict[str, Any]],
    dates: list[str],
    value: object,
) -> None:
    if isinstance(value, dict):
        items = value.get("results")
    else:
        items = value
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        published = item.get("published_date") or item.get("publishedDate") or item.get("date")
        dates.extend(_extract_dates(published))
        text = " ".join(
            _compact_text(item.get(key))
            for key in ("title", "snippet", "summary")
            if _compact_text(item.get(key))
        )
        _append_text_evidence(evidence, dates, "news", text)


def _append_fund_flow_evidence(
    evidence: list[dict[str, Any]],
    dates: list[str],
    value: object,
) -> None:
    text = _flatten_context(value)
    if not text:
        return
    dates.extend(_extract_dates(text))
    signal = _fund_flow_signal(value, text)
    if signal == 0:
        return
    evidence.append({
        "source": "fund_flow",
        "polarity": "positive" if signal > 0 else "negative",
        "category": "主力净流入" if signal > 0 else "主力净流出",
        "text": text[:180],
        "signal": signal,
        "weight": _SOURCE_RELIABILITY["fund_flow"],
    })


def _append_quote_evidence(
    evidence: list[dict[str, Any]],
    dates: list[str],
    value: object,
) -> None:
    text = _flatten_context(value)
    if not text:
        return
    dates.extend(_extract_dates(text))
    change_pct = _quote_change_pct(value, text)
    if change_pct is None or abs(change_pct) < 2.0:
        return
    signal = min(abs(change_pct) / 8.0, 0.75)
    if change_pct < 0:
        signal = -signal
    evidence.append({
        "source": "quote",
        "polarity": "positive" if signal > 0 else "negative",
        "category": "短线价格走强" if signal > 0 else "短线价格走弱",
        "text": f"涨跌幅={change_pct:.2f}%",
        "signal": signal,
        "weight": _SOURCE_RELIABILITY["quote"],
    })


def _dsa_capital_flow(context: dict[str, Any]) -> object:
    fundamentals = context.get("fundamentals")
    if not isinstance(fundamentals, dict):
        return None
    capital_flow = fundamentals.get("capital_flow")
    if not isinstance(capital_flow, dict):
        return None
    data = capital_flow.get("data")
    return data if isinstance(data, dict) else capital_flow


def _fund_flow_signal(value: object, text: str) -> float:
    numeric_signals: list[float] = []
    if isinstance(value, dict):
        for key, number in _numeric_items(value):
            normalized = key.lower().replace("-", "_")
            if "净流入" in key or "net_inflow" in normalized or "main_inflow" in normalized:
                numeric_signals.append(number)
            elif "净流出" in key or "net_outflow" in normalized:
                numeric_signals.append(-abs(number))
    for match in re.finditer(
        r"净流入[^=：:，；;|]{0,24}[=：:]\s*([-+]?\d+(?:\.\d+)?)",
        text,
        flags=re.IGNORECASE,
    ):
        numeric_signals.append(float(match.group(1)))
    if numeric_signals:
        total = sum(1.0 if number > 0 else -1.0 if number < 0 else 0.0 for number in numeric_signals)
        if total > 0:
            return 0.85
        if total < 0:
            return -0.85
    if "净流出" in text or "资金流出" in text:
        return -0.75
    if "净流入" in text or "资金流入" in text:
        return 0.75
    return 0.0


def _quote_change_pct(value: object, text: str) -> float | None:
    if isinstance(value, dict):
        for key in ("change_pct", "changePercent", "pct_chg", "涨跌幅"):
            number = _optional_float(value.get(key))
            if number is not None:
                return number
    match = re.search(r"(?:涨跌幅|change_pct)\s*[=：:]\s*([-+]?\d+(?:\.\d+)?)", text, re.IGNORECASE)
    return float(match.group(1)) if match else None


def _first_non_negated_keyword(text: str, keywords: tuple[str, ...]) -> tuple[int, int] | None:
    for keyword in sorted(keywords, key=len, reverse=True):
        start = 0
        while True:
            index = text.find(keyword, start)
            if index < 0:
                break
            end = index + len(keyword)
            prefix = text[max(0, index - 12):index]
            suffix = text[end:end + 12]
            if not _NEGATION_PREFIX.search(prefix) and not _NEGATION_SUFFIX.search(suffix):
                return index, end
            start = end
    return None


def _evidence_snippet(text: str, start: int, end: int) -> str:
    left = max(0, start - 44)
    right = min(len(text), end + 72)
    return text[left:right].strip(" |，。；;:")


def _sentiment_confidence(sources: list[str], evidence_count: int) -> float:
    if not sources:
        return 0.0
    quality = sum(_SOURCE_RELIABILITY.get(source, 0.5) for source in sources) / len(sources)
    diversity_multiplier = min(0.88, 0.62 + 0.13 * (len(sources) - 1))
    evidence_bonus = min(0.12, 0.05 * evidence_count)
    return round(min(1.0, quality * diversity_multiplier + evidence_bonus), 4)


def _sentiment_label(score: float) -> str:
    if score >= 75:
        return "strong_positive"
    if score >= 58:
        return "positive"
    if score <= 25:
        return "strong_negative"
    if score <= 42:
        return "negative"
    return "neutral"


def _extract_dates(value: object) -> list[str]:
    text = _compact_text(value)
    dates = []
    for year, month, day in _DATE_PATTERN.findall(text):
        try:
            dates.append(f"{int(year):04d}-{int(month):02d}-{int(day):02d}")
        except ValueError:
            continue
    return dates


def _numeric_items(value: dict[str, Any], prefix: str = "") -> list[tuple[str, float]]:
    items: list[tuple[str, float]] = []
    for key, raw in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(raw, dict):
            items.extend(_numeric_items(raw, path))
            continue
        number = _optional_float(raw)
        if number is not None:
            items.append((path, number))
    return items


def _flatten_context(value: object) -> str:
    if isinstance(value, dict):
        parts = []
        for key, raw in value.items():
            nested = _flatten_context(raw)
            if nested:
                parts.append(f"{key}={nested}")
        return "，".join(parts)[:720]
    if isinstance(value, list):
        return " | ".join(_flatten_context(item) for item in value if _flatten_context(item))[:720]
    return _compact_text(value)


def _compact_text(value: object) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).replace("\n", " ").split()).strip()
    if text.lower() in {"", "none", "nan", "<na>"}:
        return ""
    return text[:1200]


def _optional_float(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        text = str(value).replace(",", "").replace("%", "").strip()
        number = float(text)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _finite_float(value: object) -> float:
    number = _optional_float(value)
    return number if number is not None else 0.0


def _deduplicate_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (str(item["source"]), str(item["polarity"]), str(item["category"]))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _dedupe_strings(items: list[str]) -> list[str]:
    result = []
    seen = set()
    for item in items:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
