# -*- coding: utf-8 -*-
"""L2 LLM ranker — relative ranking of shortlisted candidates."""

import json
import logging
import re
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from alphasift.llm_client import LLMClientError, build_attempts, complete, configuration_error
from alphasift.models import Pick
from alphasift.normalize import (
    bounded_float as _bounded_float,
    normalize_code,
    safe_string_list as _safe_string_list,
    safe_text,
)


def _normalize_code(value: object) -> str:
    # Candidate codes and LLM ranking JSON code fields are structured, so
    # US tickers may pass through (see normalize_code docstring).
    return normalize_code(value, allow_ticker=True)


logger = logging.getLogger(__name__)
_DEFAULT_RANKING_PROMPT_MAX_CHARS = 24_000
_PROMPT_TRIM_MARKER = "[prompt_trimmed]"
_ADVERSE_FILING_MARKERS = (
    "unresolved adverse filing",
    "adverse filing",
    "red_flag_capped",
    "立案调查",
    "监管调查",
    "证监会调查",
    "被调查",
    "立案",
    "股东减持",
    "拟减持",
    "大股东减持",
    "业绩预亏",
    "亏损",
    "*st",
    "冻结",
    "留置",
    "退市",
    "终止上市",
    "st风险",
    "警示函",
    "监管函",
    "问询函",
    "行政处罚",
    "处罚",
    "造假",
    "违约",
    "大幅下滑",
    "under investigation",
    "pending investigation",
    "regulatory investigation",
    "delisting",
    "regulatory penalty",
    "regulatory_penalty",
)
_NEGATED_RISK_RE = re.compile(
    r"(?:无|未发生|不存在|不涉及|未受|未遭到|已解除|已撤销|撤销)"
    r"(?:任何|重大|相关|新的)?"
    r"(?:立案调查|监管调查|证监会调查|调查|行政处罚|处罚|退市风险警示|警示|违约|冻结|留置|减持)"
    r"|\b(?:no|not|without|resolved|cleared|lifted)\s+"
    r"(?:pending\s+|under\s+|any\s+)?"
    r"(?:investigation|adverse filing|delisting|penalty)\b",
    re.I,
)
_SEVERE_CONTEXT_FLAGS = frozenset({"监管", "退市风险", "财务风险", "业绩压力", "减持", "诉讼风险", "质押冻结"})
_LLM_RED_FLAG_MAX_SCORE = 35.0


def _strip_negated_risk_phrases(text: str) -> str:
    return _NEGATED_RISK_RE.sub(" ", text)


@dataclass
class RankingParseResult:
    picks: list[Pick]
    coverage: float
    errors: list[str]
    market_view: str = ""
    selection_logic: str = ""
    portfolio_risk: str = ""
    matched_codes: set[str] | None = None
    matched_count: int = 0


@dataclass
class LLMRankingResult:
    picks: list[Pick]
    ranked: bool = False
    market_view: str = ""
    selection_logic: str = ""
    portfolio_risk: str = ""
    coverage: float = 0.0
    errors: list[str] | None = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


def rank_candidates(
    candidates: list[Pick],
    ranking_hints: str,
    llm_api_key: str,
    llm_model: str,
    llm_base_url: str = "",
    *,
    context: str = "",
    rank_weight: float = 0.40,
    max_retries: int = 1,
    min_coverage: float = 0.60,
    fallback_models: list[str] | None = None,
    temperature: float = 0.2,
    json_mode: bool = True,
    silent: bool = True,
    channels: list[dict[str, object]] | None = None,
    config_path: str = "",
    timeout_sec: float = 60.0,
    max_prompt_chars: int | None = _DEFAULT_RANKING_PROMPT_MAX_CHARS,
    max_tokens: int | None = 2048,
) -> list[Pick]:
    """Use LLM to re-rank candidates and add ranking_reason / risk_summary.

    Falls back to screen_score order if LLM call fails.
    """
    return rank_candidates_with_metadata(
        candidates,
        ranking_hints,
        llm_api_key,
        llm_model,
        llm_base_url,
        context=context,
        rank_weight=rank_weight,
        max_retries=max_retries,
        min_coverage=min_coverage,
        fallback_models=fallback_models,
        temperature=temperature,
        json_mode=json_mode,
        silent=silent,
        channels=channels,
        config_path=config_path,
        timeout_sec=timeout_sec,
        max_prompt_chars=max_prompt_chars,
        max_tokens=max_tokens,
    ).picks


def rank_candidates_with_metadata(
    candidates: list[Pick],
    ranking_hints: str,
    llm_api_key: str,
    llm_model: str,
    llm_base_url: str = "",
    *,
    context: str = "",
    rank_weight: float = 0.40,
    max_retries: int = 1,
    min_coverage: float = 0.60,
    fallback_models: list[str] | None = None,
    temperature: float = 0.2,
    json_mode: bool = True,
    silent: bool = True,
    channels: list[dict[str, object]] | None = None,
    config_path: str = "",
    timeout_sec: float = 60.0,
    max_prompt_chars: int | None = _DEFAULT_RANKING_PROMPT_MAX_CHARS,
    degradation: list[str] | None = None,
    max_tokens: int | None = 2048,
    candidate_context_rows: list[dict[str, object]] | None = None,
) -> LLMRankingResult:
    """Use LLM to re-rank candidates and return global research metadata."""
    if not candidates:
        return LLMRankingResult(picks=candidates)

    adverse_context_by_code: dict[str, list[str]] = {}
    for row in candidate_context_rows or []:
        norm_code = _normalize_code(row.get("code", ""))
        if not norm_code:
            continue
        raw_flags = row.get("negative_event_flags")
        if isinstance(raw_flags, (list, tuple, set)):
            flags = [str(x).strip() for x in raw_flags if str(x).strip()]
        elif isinstance(raw_flags, str) and raw_flags.strip():
            flags = [x.strip() for x in raw_flags.replace("，", ",").split(",") if x.strip()]
        else:
            flags = []
        severe = [f for f in flags if f in _SEVERE_CONTEXT_FLAGS]
        if severe:
            adverse_context_by_code[norm_code] = severe

    prompt = _build_ranking_prompt(
        candidates,
        ranking_hints,
        context,
        max_chars=max_prompt_chars,
        degradation=degradation,
    )

    try:
        last_errors: list[str] = []
        parsed: RankingParseResult | None = None
        for attempt in range(max_retries + 1):
            attempt_prompt = prompt
            if attempt:
                attempt_prompt += (
                    "\n\n上一次输出没有满足结构化覆盖率要求。"
                    "请重新返回严格 JSON，并覆盖尽可能多的候选代码。"
                )
            response = _call_llm(
                attempt_prompt,
                llm_api_key,
                llm_model,
                llm_base_url,
                fallback_models=fallback_models or [],
                temperature=temperature,
                json_mode=json_mode,
                silent=silent,
                channels=channels or [],
                config_path=config_path,
                timeout_sec=timeout_sec,
                max_tokens=max_tokens,
            )
            parsed = _parse_ranking_response_detail(
                response,
                [deepcopy(pick) for pick in candidates],
            )
            last_errors = parsed.errors
            if parsed.coverage >= min_coverage and parsed.matched_count > 0:
                break
        if parsed is None or parsed.coverage < min_coverage or parsed.matched_count == 0:
            raise ValueError(
                "LLM ranking response coverage below threshold: "
                f"{0 if parsed is None else parsed.coverage:.2f}; "
                f"errors={last_errors}"
            )
        ranked = parsed.picks
        matched_codes = parsed.matched_codes
        weight = min(max(rank_weight, 0.0), 1.0)
        pre_risk_by_code = {
            _normalize_code(p.code): str(p.risk_summary)
            for p in candidates
            if _normalize_code(p.code) and p.risk_summary
        }
        for i, pick in enumerate(ranked):
            norm_code = _normalize_code(pick.code)
            was_matched = matched_codes is None or norm_code in matched_codes
            prior_risk = pre_risk_by_code.get(norm_code, "")
            if prior_risk and not pick.risk_summary:
                pick.risk_summary = prior_risk
            adverse_reasons = _unresolved_adverse_reasons(
                pick,
                context_flags=adverse_context_by_code.get(norm_code, ()),
                extra_texts=(prior_risk,),
            )
            if not was_matched:
                pick.llm_score = None
                if "llm_omitted" not in pick.risk_flags:
                    pick.risk_flags = [*pick.risk_flags, "llm_omitted"]
                if adverse_reasons:
                    cap_final = float(pick.screen_score) * (1.0 - weight) + _LLM_RED_FLAG_MAX_SCORE * weight
                    pick.final_score = min(float(pick.screen_score), cap_final)
                    if "red_flag_capped" not in pick.risk_flags:
                        pick.risk_flags = [*pick.risk_flags, "red_flag_capped"]
                    note = f"触发红线上限({_LLM_RED_FLAG_MAX_SCORE:.0f}): {', '.join(adverse_reasons[:3])}"
                    pick.risk_summary = f"{pick.risk_summary}; {note}" if pick.risk_summary else note
                else:
                    pick.final_score = float(pick.screen_score)
                continue
            if pick.llm_score is None:
                pick.llm_score = 100.0 - i * (100.0 / max(len(ranked), 1))
            if adverse_reasons and pick.llm_score > _LLM_RED_FLAG_MAX_SCORE:
                pick.llm_score = _LLM_RED_FLAG_MAX_SCORE
                if "red_flag_capped" not in pick.llm_risks:
                    pick.llm_risks = [*pick.llm_risks, "red_flag_capped"]
                if "red_flag_capped" not in pick.risk_flags:
                    pick.risk_flags = [*pick.risk_flags, "red_flag_capped"]
                note = f"触发红线上限({_LLM_RED_FLAG_MAX_SCORE:.0f}): {', '.join(adverse_reasons[:3])}"
                pick.risk_summary = f"{pick.risk_summary}; {note}" if pick.risk_summary else note
            pick.final_score = pick.screen_score * (1 - weight) + (pick.llm_score or 0.0) * weight
        ranked.sort(key=lambda item: item.final_score, reverse=True)
        for i, pick in enumerate(ranked, start=1):
            pick.rank = i
        return LLMRankingResult(
            picks=ranked,
            ranked=True,
            market_view=parsed.market_view,
            selection_logic=parsed.selection_logic,
            portfolio_risk=parsed.portfolio_risk,
            coverage=parsed.coverage,
            errors=parsed.errors,
        )
    except Exception as e:
        logger.warning("LLM ranking failed, falling back to screen_score: %s", e)
        return LLMRankingResult(picks=candidates, errors=[str(e)])


def _unresolved_adverse_reasons(
    pick: Pick,
    *,
    context_flags: tuple[str, ...] | list[str] = (),
    extra_texts: tuple[str, ...] | list[str] = (),
) -> list[str]:
    reasons: list[str] = []
    for flag in context_flags:
        if flag and flag not in reasons:
            reasons.append(str(flag))
    news_items = list(pick.dsa_news or [])
    if not news_items and isinstance(pick.dsa_context, dict):
        news_payload = pick.dsa_context.get("news")
        if isinstance(news_payload, dict) and isinstance(news_payload.get("results"), list):
            news_items = [item for item in news_payload["results"] if isinstance(item, dict)]
    news_titles = [
        str(item.get("title") or "").strip()
        for item in news_items
        if isinstance(item, dict) and item.get("title")
    ]
    text_sources = [
        *pick.llm_risks,
        *pick.risk_flags,
        *pick.deep_analysis_risk_flags,
        pick.risk_summary,
        pick.dsa_analysis_summary,
        *extra_texts,
        *news_titles,
    ]
    cleaned_sources = [_strip_negated_risk_phrases(str(x)) for x in text_sources if x]
    combined = " | ".join(cleaned_sources).lower()
    for marker in _ADVERSE_FILING_MARKERS:
        if marker in combined and marker not in reasons:
            reasons.append(marker)
    return reasons


def _build_ranking_prompt(
    candidates: list[Pick],
    hints: str,
    context: str = "",
    *,
    max_chars: int | None = _DEFAULT_RANKING_PROMPT_MAX_CHARS,
    degradation: list[str] | None = None,
) -> str:
    hints_text = hints.strip() or "无额外排序提示。"
    context_text = context.strip() or "无额外上下文。只能基于候选池结构化数据和策略偏好判断。"
    candidates_text = "\n".join(_format_candidate_for_prompt(p) for p in candidates)
    prompt = _render_ranking_prompt(hints_text, context_text, candidates_text)
    if max_chars is None or len(prompt) <= max_chars:
        return prompt
    return _build_bounded_ranking_prompt(
        candidates,
        hints_text,
        context_text,
        max_chars=max_chars,
        degradation=degradation,
    )


def _render_ranking_prompt(hints: str, context: str, candidates_text: str) -> str:
    return f"""你是一个兼具深度基本面与风险排雷视角的股票研究员，任务是在“已经由代码硬筛过”的候选池内做相对排序。
你不能推荐候选池外股票，不能修改硬筛条件，不能给目标价或承诺收益。请重点发挥代码公式无法替代的语义判断与排雷能力：
1. **情报优先排雷（红旗一票降权）**：认真核查市场/情报上下文与 DSA 信息中的公告类别、新闻标题和负面关键词；若发现未消化重大利空（股东减持、立案调查、监管/问询函、业绩预亏或大幅下滑、商誉/债务/违约风险、退市警戒或纯粹高位蹭热点透支），必须将其 `llm_score` 严格压低到 `<= 35`，并在 `risk_flags` 与 `risk` 中写明依据；
2. **禁止品牌/名气偏见**：严禁仅凭耳熟能详的大盘白马或银行股名气给高分；优先奖励业绩预增/扭亏、大额回购增持、重大合同中标且公告干净、资金与产业逻辑共振的标的；
3. **跨候选可审计对比**：结合策略偏好、行业/概念持续性热度（不追单日过热炒作）对比相对强弱，所有结论必须锚定输入字段或上下文事实，不得编造未提供的数据。

## 排序依据
{hints}

## 市场/情报上下文
{context}

## 候选列表
{candidates_text}

## 输出要求
只返回 JSON，不要 Markdown，不要解释 JSON 以外的文本。
格式：
{{
  "market_view": "一句话概括当前候选池和市场背景是否适合该策略",
  "selection_logic": "说明本次排序最主要的2-3个判断维度",
  "portfolio_risk": "说明最终名单可能存在的集中风险或共同风险",
  "ranked": [
    {{
      "code": "股票代码",
      "llm_score": 0-100,
      "confidence": 0-1,
      "sector": "行业/主题短标签，优先参考候选的 industry/concepts，并尽量统一，如 券商、银行、医药、AI算力",
      "theme": "主要交易逻辑或主题",
      "thesis": "该候选入选的核心投资假设",
      "reason": "一句话排序理由（需锚定具体情报/催化或因子对比）",
      "risk": "一句话主要排雷风险（红旗项须直指具体隐患）",
      "catalysts": ["潜在催化1", "潜在催化2"],
      "risk_flags": ["风险标签1"],
      "tags": ["价值", "趋势", "防守", "事件", "流动性"],
      "style_fit": "与策略风格的匹配度说明",
      "watch_items": ["后续应跟踪的数据或事件"],
      "invalidators": ["会推翻该候选逻辑的观察点"]
    }}
  ]
}}
"""


def _build_bounded_ranking_prompt(
    candidates: list[Pick],
    hints: str,
    context: str,
    *,
    max_chars: int,
    degradation: list[str] | None,
) -> str:
    trimmed: list[str] = []
    identity_text = "\n".join(_format_candidate_for_prompt(p, detail="identity") for p in candidates)
    base_min = _render_ranking_prompt(
        _truncate_prompt_text(hints, 900, "hints", trimmed),
        "",
        identity_text,
    )
    context_budget = max(int(max_chars) - len(base_min) - 80, 0)
    context_text = _truncate_prompt_text(context, context_budget, "context", trimmed)

    prompt_without_candidates = _render_ranking_prompt(
        _truncate_prompt_text(hints, 900, "hints", trimmed),
        context_text,
        "",
    )
    candidate_budget = max(int(max_chars) - len(prompt_without_candidates), 0)
    candidates_text = _fit_candidate_prompt_lines(candidates, candidate_budget, trimmed)
    prompt = _render_ranking_prompt(
        _truncate_prompt_text(hints, 900, "hints", trimmed),
        context_text,
        candidates_text,
    )

    if len(prompt) > max_chars:
        overflow = len(prompt) - int(max_chars)
        context_text = _truncate_prompt_text(
            context_text,
            max(len(context_text) - overflow - 80, 0),
            "context",
            trimmed,
        )
        prompt_without_candidates = _render_ranking_prompt(
            _truncate_prompt_text(hints, 600, "hints", trimmed),
            context_text,
            "",
        )
        candidate_budget = max(int(max_chars) - len(prompt_without_candidates), 0)
        candidates_text = _fit_candidate_prompt_lines(candidates, candidate_budget, trimmed)
        prompt = _render_ranking_prompt(
            _truncate_prompt_text(hints, 600, "hints", trimmed),
            context_text,
            candidates_text,
        )

    if len(prompt) > max_chars:
        marker = f"\n...{_PROMPT_TRIM_MARKER}:hard_cap"
        prompt = prompt[: max(int(max_chars) - len(marker), 0)].rstrip() + marker
        trimmed.append("hard_cap")

    if trimmed and degradation is not None:
        labels = ",".join(dict.fromkeys(trimmed))
        degradation.append(f"LLM ranking prompt truncated: trimmed={labels}")
    return prompt[:max_chars]


def _format_candidate_for_prompt(p: Pick, *, detail: str = "full") -> str:
    if detail == "identity":
        return (
            f"- {p.code} {p.name}: rank={p.rank}, "
            f"screen_score={p.screen_score:.1f}, final_score={p.final_score:.1f}"
        )
    if detail == "compact":
        return (
            f"- {p.code} {p.name}: rank={p.rank}, price={p.price}, "
            f"change_pct={p.change_pct}%, amount={p.amount:.0f}, "
            f"screen_score={p.screen_score:.1f}, industry={p.industry or 'unknown'}, "
            f"concepts={p.concepts or 'unknown'}, board_heat_score={p.board_heat_score}, "
            f"signal_score={p.signal_score}, dsa_context={_format_dsa_context_for_prompt(p)}"
        )
    return (
        f"- {p.code} {p.name}: price={p.price}, change_pct={p.change_pct}%, "
        f"amount={p.amount:.0f}, turnover={p.turnover_rate}, volume_ratio={p.volume_ratio}, "
        f"total_mv={p.total_mv}, PE={p.pe_ratio}, PB={p.pb_ratio}, "
        f"industry={p.industry or 'unknown'}, concepts={p.concepts or 'unknown'}, "
        f"industry_rank={p.industry_rank}, industry_change_pct={p.industry_change_pct}, "
        f"board_heat_score={p.board_heat_score}, board_heat_summary={p.board_heat_summary or 'unknown'}, "
        f"board_heat_latest_score={p.board_heat_latest_score}, "
        f"board_heat_trend_score={p.board_heat_trend_score}, "
        f"board_heat_persistence_score={p.board_heat_persistence_score}, "
        f"board_heat_cooling_score={p.board_heat_cooling_score}, "
        f"board_heat_observations={p.board_heat_observations}, "
        f"board_heat_state={p.board_heat_state or 'unknown'}, "
        f"change_60d={p.change_60d}, signal_score={p.signal_score}, "
        f"macd={p.macd_status}, rsi={p.rsi_status}, "
        f"breakout_20d_pct={p.breakout_20d_pct}, range_20d_pct={p.range_20d_pct}, "
        f"volume_ratio_20d={p.volume_ratio_20d}, body_pct={p.body_pct}, "
        f"pullback_to_ma20_pct={p.pullback_to_ma20_pct}, "
        f"consolidation_days_20d={p.consolidation_days_20d}, "
        f"screen_score={p.screen_score:.1f}, factor_scores={p.factor_scores}, "
        f"dsa_context={_format_dsa_context_for_prompt(p)}"
    )


def _fit_candidate_prompt_lines(
    candidates: list[Pick],
    budget: int,
    trimmed: list[str],
) -> str:
    marker = f"...{_PROMPT_TRIM_MARKER}:candidate_details"
    full_text = "\n".join(_format_candidate_for_prompt(p) for p in candidates)
    if len(full_text) <= budget:
        return full_text

    available = max(int(budget) - len(marker) - 1, 0)
    if available <= 0:
        trimmed.append("candidate_details")
        return marker[:budget]

    identity_lines = [_format_candidate_for_prompt(p, detail="identity") for p in candidates]
    lines: list[str] = []
    used = 0
    omitted = 0
    for line in identity_lines:
        extra = len(line) + (1 if lines else 0)
        if used + extra > available:
            omitted += 1
            continue
        lines.append(line)
        used += extra

    if omitted == 0:
        for idx, pick in enumerate(candidates):
            for detail in ("full", "compact"):
                replacement = _format_candidate_for_prompt(pick, detail=detail)
                delta = len(replacement) - len(lines[idx])
                if used + delta <= available:
                    lines[idx] = replacement
                    used += delta
                    break

    if omitted:
        trimmed.append("candidate_omitted")
        lines.append(f"...{_PROMPT_TRIM_MARKER}:candidate_omitted={omitted}")
    else:
        trimmed.append("candidate_details")
        lines.append(marker)
    return "\n".join(lines)


def _truncate_prompt_text(text: str, limit: int, label: str, trimmed: list[str]) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    marker = f"\n...{_PROMPT_TRIM_MARKER}:{label}"
    trimmed.append(label)
    if limit <= len(marker) + 8:
        return marker[:limit]
    return text[: max(limit - len(marker), 0)].rstrip() + marker


def _format_dsa_context_for_prompt(p: Pick) -> str:
    parts: list[str] = []
    if p.dsa_analysis_summary:
        parts.append(f"summary={_truncate_text(p.dsa_analysis_summary, 240)}")

    context = p.dsa_context if isinstance(p.dsa_context, dict) else {}
    quote = context.get("quote") if isinstance(context.get("quote"), dict) else {}
    if quote:
        parts.append(
            "quote="
            f"price:{quote.get('price')},change_pct:{quote.get('change_pct')},"
            f"amount:{quote.get('amount')}"
        )

    fundamentals = context.get("fundamentals") if isinstance(context.get("fundamentals"), dict) else {}
    coverage = fundamentals.get("coverage") if isinstance(fundamentals.get("coverage"), dict) else {}
    if coverage:
        available = [
            str(key)
            for key, value in coverage.items()
            if str(value).lower() in {"available", "partial"}
        ]
        if available:
            parts.append(f"fundamental_coverage={','.join(available[:5])}")

    news_items = p.dsa_news
    if not news_items:
        news_payload = context.get("news") if isinstance(context.get("news"), dict) else {}
        raw_results = news_payload.get("results") if isinstance(news_payload, dict) else []
        if isinstance(raw_results, list):
            news_items = [item for item in raw_results if isinstance(item, dict)]
    titles = [
        _truncate_text(str(item.get("title") or "").strip(), 80)
        for item in news_items[:3]
        if isinstance(item, dict) and item.get("title")
    ]
    if titles:
        parts.append(f"news_titles={';'.join(titles)}")

    warnings = context.get("warnings") if isinstance(context.get("warnings"), list) else []
    warning_text = [str(item) for item in warnings[:3] if item]
    if warning_text:
        parts.append(f"warnings={';'.join(warning_text)}")

    return "; ".join(parts) if parts else "none"


def _truncate_text(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)] + "…"


def _call_llm_with_metadata(
    prompt: str,
    api_key: str,
    model: str,
    base_url: str,
    *,
    fallback_models: list[str] | None = None,
    temperature: float = 0.2,
    json_mode: bool = True,
    silent: bool = True,
    channels: list[dict[str, object]] | None = None,
    config_path: str = "",
    timeout_sec: float = 60.0,
    max_tokens: int | None = 2048,
    reasoning_effort: str | None = None,
    validator: Callable[[str], Any] | None = None,
) -> tuple[str, str]:
    """Try configured OpenAI-compatible endpoints and return (content, used_model)."""
    if error := configuration_error(channels or [], config_path):
        raise LLMClientError(error)

    attempts = build_attempts(
        model,
        api_key=api_key,
        base_url=base_url,
        channels=channels or [],
        fallback_models=fallback_models or [],
    )
    if not attempts:
        raise RuntimeError("No LLM model configured")

    messages = [{"role": "user", "content": prompt}]
    response_format = {"type": "json_object"} if json_mode else None
    formats = (response_format, None) if json_mode else (None,)
    last_error: LLMClientError | None = None

    for attempt in attempts:
        for requested_format in formats:
            try:
                text = complete(
                    attempt,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=requested_format,
                    reasoning_effort=reasoning_effort,
                    timeout=timeout_sec,
                    silent=silent,
                )
            except LLMClientError as exc:
                last_error = exc
                if exc.timed_out:
                    # Do not blindly retry the SAME endpoint without response_format
                    # after a timeout, but fall through to remaining fallback models/channels.
                    break
                if requested_format is not None and exc.json_mode_rejected:
                    continue
                break
            if validator is not None:
                try:
                    validator(text)
                except (ValueError, KeyError, TypeError) as exc:
                    last_error = LLMClientError(f"Invalid LLM structured output: {exc}")
                    break
            return text, attempt.model

    if last_error is not None:
        raise last_error
    raise RuntimeError("No LLM model configured")


def _call_llm(
    prompt: str,
    api_key: str,
    model: str,
    base_url: str,
    *,
    fallback_models: list[str] | None = None,
    temperature: float = 0.2,
    json_mode: bool = True,
    silent: bool = True,
    channels: list[dict[str, object]] | None = None,
    config_path: str = "",
    timeout_sec: float = 60.0,
    max_tokens: int | None = 2048,
) -> str:
    """Try configured OpenAI-compatible endpoints for one LLM prompt."""
    text, _ = _call_llm_with_metadata(
        prompt,
        api_key,
        model,
        base_url,
        fallback_models=fallback_models,
        temperature=temperature,
        json_mode=json_mode,
        silent=silent,
        channels=channels,
        config_path=config_path,
        timeout_sec=timeout_sec,
        max_tokens=max_tokens,
    )
    return text


def _parse_ranking_response(response: str, candidates: list[Pick]) -> list[Pick]:
    """Parse LLM response and reorder candidates."""
    return _parse_ranking_response_detail(response, candidates).picks


def _parse_ranking_response_detail(response: str, candidates: list[Pick]) -> RankingParseResult:
    """Parse LLM response and return diagnostics."""
    errors: list[str] = []
    if not response or not response.strip():
        errors.append("empty_response")
        logger.warning("Empty LLM ranking response")
        return RankingParseResult(candidates, 0.0, errors, matched_codes=set(), matched_count=0)

    parsed = _extract_ranking_json(response, errors)
    if parsed is None:
        errors.append("no_json_found")
        logger.warning("No JSON object or array found in LLM response")
        return RankingParseResult(candidates, 0.0, errors, matched_codes=set(), matched_count=0)
    if isinstance(parsed, dict):
        items = parsed.get("ranked", [])
        market_view = _safe_str(parsed.get("market_view"), max_len=260)
        selection_logic = _safe_str(parsed.get("selection_logic"), max_len=360)
        portfolio_risk = _safe_str(parsed.get("portfolio_risk"), max_len=360)
    else:
        items = parsed
        market_view = ""
        selection_logic = ""
        portfolio_risk = ""
    if not isinstance(items, list):
        errors.append("ranked_not_list")
        logger.warning("LLM ranking JSON has no ranked list")
        return RankingParseResult(candidates, 0.0, errors, matched_codes=set(), matched_count=0)

    code_to_pick = {_normalize_code(p.code): p for p in candidates if _normalize_code(p.code)}

    ranked = []
    matched = 0
    seen_codes = set()
    for item in items:
        if not isinstance(item, dict):
            errors.append("non_object_item")
            continue
        code = _normalize_code(item.get("code", ""))
        if code in seen_codes:
            errors.append(f"duplicate_code:{code}")
            continue
        seen_codes.add(code)
        if code in code_to_pick:
            pick = code_to_pick.pop(code)
            pick.ranking_reason = _safe_str(item.get("reason"), max_len=180)
            pick.risk_summary = _safe_str(item.get("risk"), max_len=180)
            pick.llm_score = _bounded_float(item.get("llm_score"), low=0, high=100)
            pick.llm_confidence = _bounded_float(item.get("confidence"), low=0, high=1)
            pick.llm_sector = _safe_str(
                item.get("sector") or item.get("industry") or item.get("sector_label"),
                max_len=40,
            )
            pick.llm_theme = _safe_str(item.get("theme"), max_len=100)
            pick.llm_thesis = _safe_str(item.get("thesis"), max_len=220)
            pick.llm_catalysts = _safe_string_list(item.get("catalysts"))
            pick.llm_invalidators = _safe_string_list(item.get("invalidators"))
            pick.llm_style_fit = _safe_str(item.get("style_fit"), max_len=120)
            pick.llm_watch_items = _safe_string_list(item.get("watch_items"))
            pick.llm_risks = _safe_string_list(item.get("risk_flags"))
            pick.llm_tags = _safe_string_list(item.get("tags"))
            if pick.llm_sector:
                pick.llm_tags = _dedupe([*pick.llm_tags, f"sector:{pick.llm_sector}"])
            if pick.llm_theme:
                pick.llm_tags = _dedupe([*pick.llm_tags, f"theme:{pick.llm_theme}"])
            if pick.llm_style_fit:
                pick.llm_tags = _dedupe([*pick.llm_tags, f"style_fit:{pick.llm_style_fit}"])
            ranked.append(pick)
            matched += 1
        elif code:
            errors.append(f"unknown_code:{code}")

    # Append any candidates not mentioned by LLM, preserving which codes were actually matched.
    matched_codes = {_normalize_code(p.code) for p in ranked if _normalize_code(p.code)}
    ranked.extend(code_to_pick.values())
    coverage = matched / max(len(candidates), 1)
    return RankingParseResult(
        ranked,
        coverage,
        errors,
        market_view=market_view,
        selection_logic=selection_logic,
        portfolio_risk=portfolio_risk,
        matched_codes=matched_codes,
        matched_count=matched,
    )


def _safe_str(value, *, max_len: int) -> str:
    return safe_text(value, max_len=max_len)


def _try_parse_json_lenient(raw: str, errors: list[str]):
    """Attempt to parse LLM JSON output, tolerating common formatting drift.

    Steps applied in order: strict parse → strip trailing commas → balance
    truncated brackets → return None if all fail. Any repair that succeeds is
    recorded in ``errors`` for diagnostics.
    """
    import re

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        first_error = exc

    # Repair 1: remove trailing commas before } or ].
    repaired = re.sub(r",(\s*[}\]])", r"\1", raw)
    if repaired != raw:
        try:
            result = json.loads(repaired)
            errors.append("json_repaired:trailing_comma")
            return result
        except json.JSONDecodeError:
            pass

    # Repair 2: close unbalanced brackets caused by truncated output.
    open_curly = repaired.count("{") - repaired.count("}")
    open_square = repaired.count("[") - repaired.count("]")
    if open_curly > 0 or open_square > 0:
        patched = repaired + ("]" * max(open_square, 0)) + ("}" * max(open_curly, 0))
        try:
            result = json.loads(patched)
            errors.append("json_repaired:closed_brackets")
            return result
        except json.JSONDecodeError:
            pass

    errors.append(f"json_decode_error:{first_error}")
    logger.warning("Failed to parse LLM ranking JSON: %s", first_error)
    return None


def _extract_ranking_json(response: str, errors: list[str]):
    """Extract ranking JSON from common LLM response shapes."""
    for raw in _iter_json_payloads(response):
        parsed = _try_parse_json_lenient(raw, errors)
        if _looks_like_ranking_payload(parsed):
            return parsed

    partial = _extract_partial_ranking_array(response, errors)
    if partial is not None:
        return partial
    return None


def _looks_like_ranking_payload(value: object) -> bool:
    if isinstance(value, dict):
        return isinstance(value.get("ranked"), list)
    if isinstance(value, list):
        return any(isinstance(item, dict) and "code" in item for item in value)
    return False


def _iter_json_payloads(response: str):
    """Yield likely JSON payload substrings in priority order."""
    import re

    yielded: set[str] = set()
    fence_pattern = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)
    for match in fence_pattern.finditer(response):
        payload = match.group(1).strip()
        if payload and payload not in yielded:
            yielded.add(payload)
            yield payload

    cleaned = fence_pattern.sub(lambda match: match.group(1), response)
    for payload in _balanced_json_values(cleaned):
        if payload not in yielded:
            yielded.add(payload)
            yield payload


def _balanced_json_values(text: str) -> list[str]:
    """Return balanced top-level JSON object/array substrings."""
    values: list[str] = []
    stack: list[str] = []
    start: int | None = None
    in_string = False
    escaped = False
    pairs = {"{": "}", "[": "]"}

    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char in pairs:
            if not stack:
                start = index
            stack.append(pairs[char])
            continue
        if char in ("}", "]") and stack:
            expected = stack.pop()
            if char != expected:
                stack.clear()
                start = None
                continue
            if not stack and start is not None:
                values.append(text[start : index + 1])
                start = None
    return values


def _extract_partial_ranking_array(response: str, errors: list[str]):
    """Recover a ranked list from multiple JSON objects in a noisy response."""
    items = []
    item_errors: list[str] = []
    for raw in _balanced_json_values(response):
        parsed = _try_parse_json_lenient(raw, item_errors)
        if isinstance(parsed, dict) and "code" in parsed:
            items.append(parsed)
    if not items:
        return None
    errors.append("json_repaired:partial_array")
    return {"ranked": items}


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        key = str(item).strip()
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result
