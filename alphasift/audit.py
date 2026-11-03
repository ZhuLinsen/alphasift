# -*- coding: utf-8 -*-
"""Project and strategy audit helpers."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from alphasift.config import Config
from alphasift.filter import requires_daily_features
from alphasift.strategy import load_all_strategies


def audit_project(strategies_dir: Path | None = None) -> dict[str, object]:
    """Return a structured audit of current strategy coverage and known gaps."""
    if strategies_dir is None:
        strategies_dir = Config.from_env().strategies_dir

    strategies = load_all_strategies(strategies_dir)
    strategy_items = list(strategies.values())
    categories = Counter(strategy.category for strategy in strategy_items)
    profile_fields = [
        "scoring_profile",
            "risk_profile",
            "portfolio_profile",
            "scorecard_profile",
    ]
    profile_coverage = {
        field: {
            "configured": sum(1 for strategy in strategy_items if getattr(strategy.screening, field)),
            "missing": [
                strategy.name
                for strategy in strategy_items
                if not getattr(strategy.screening, field)
            ],
        }
        for field in profile_fields
    }

    strategy_findings = []
    for strategy in strategy_items:
        strategy_findings.extend(_audit_strategy(strategy))

    project_gaps = _known_project_gaps()
    strengths = _current_strengths()
    return {
        "project": "alphasift",
        "positioning": "全市场候选发现与 LLM 横向排序引擎",
        "strategy_count": len(strategy_items),
        "categories": dict(sorted(categories.items())),
        "profile_coverage": profile_coverage,
        "strengths": strengths,
        "strategy_findings": strategy_findings,
        "project_gaps": project_gaps,
        "next_priorities": _next_priorities(strategy_findings, project_gaps),
    }


def _audit_strategy(strategy) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    screening = strategy.screening
    hard_filters = screening.hard_filters
    uses_daily = requires_daily_features(hard_filters)
    tags = {str(tag).lower() for tag in strategy.tags}
    is_shape_strategy = strategy.category in {"trend", "pattern"} or bool(
        tags & {"breakout", "pullback", "daily_k"}
    )

    if is_shape_strategy and not uses_daily:
        findings.append({
            "severity": "warn",
            "strategy": strategy.name,
            "area": "l1_shape_validation",
            "message": "趋势/形态策略尚未声明日 K 硬条件，可能只是在快照上近似形态。",
            "recommendation": "补充 require_ma_bullish、price_above_ma20、change_60d 或更严格的形态特征。",
        })

    if not screening.ranking_hints.strip():
        findings.append({
            "severity": "warn",
            "strategy": strategy.name,
            "area": "llm_ranking",
            "message": "缺少 ranking_hints，LLM 无法获得策略级取舍偏好。",
            "recommendation": "补充候选排序优先级、风险排除条件和组合分散要求。",
        })

    for field in ("scoring_profile", "risk_profile", "portfolio_profile", "scorecard_profile"):
        if not getattr(screening, field):
            findings.append({
                "severity": "info",
                "strategy": strategy.name,
                "area": "configurability",
                "message": f"未配置 {field}，将使用默认规则。",
                "recommendation": "如该策略风格与默认基线不同，应在 YAML 中显式配置。",
            })

    if screening.max_output > 10:
        findings.append({
            "severity": "info",
            "strategy": strategy.name,
            "area": "output",
            "message": "max_output 较大，L3/LLM 输出可能变成列表而不是精选候选。",
            "recommendation": "保持最终输出精简，更多候选可通过保存 run 和后续评估管理。",
        })

    return findings


def _current_strengths() -> list[dict[str, str]]:
    return [
        {
            "area": "positioning",
            "message": "定位在全市场候选发现，位于 DSA 单股深度分析和通知助手上游。",
        },
        {
            "area": "llm",
            "message": "LLM 只在候选池内做结构化横向排序，支持按 code 注入文件线索或抓取 Top K 新闻/公告/资金流，并输出 thesis、sector、theme、risk、watch_items 和 invalidators。",
        },
        {
            "area": "risk",
            "message": "风险层和组合分散层独立于 alpha 排序，扣分字段可审计。",
        },
        {
            "area": "configurability",
            "message": "策略 YAML 可覆盖评分曲线、风险阈值、组合风险桶和 scorecard 规则。",
        },
        {
            "area": "evaluation",
            "message": "支持保存运行、单次 T+N 最新快照评估、可选日 K 路径最大回撤/最大浮盈，以及按单只和等权组合维度聚合最近 runs。",
        },
        {
            "area": "daily_shape",
            "message": "日 K 增强已支持 20 日突破幅度、区间振幅、20 日量能比、实体强度、MA20 回踩距离和平台持续天数。",
        },
        {
            "area": "data",
            "message": "行业/概念锚点支持本地映射文件、可选 AkShare 板块反查、板块热度分、主题热度摘要，以及 history JSONL 滚动趋势、持续性、降温、状态回填和异常热度值过滤。",
        },
        {
            "area": "shape_validation",
            "message": "T+N 评估会对突破、MA20 回踩和平台整理候选打形态后验标签，用于发现突破延续或失败回落。",
        },
    ]


def _known_project_gaps() -> list[dict[str, str]]:
    return [
        {
            "severity": "gap",
            "area": "data",
            "message": "行业/概念和板块热度已能进入 LLM 上下文与 theme_heat 因子，industry-cache 会写 metadata/history sidecar 并回填滚动趋势、持续性和降温信号，但数据源仍偏本地/AkShare。",
            "recommendation": "补多源映射、板块层级口径归一和更完整的数据质量报告。",
        },
        {
            "severity": "gap",
            "area": "news_context",
            "message": "LLM 上下文支持候选级文件注入、Top K 抓取、缓存、基础去重、来源置信度、来源权重分、压缩摘要、公告类别和粗粒度事件/负面风险标签；策略可配置事件偏好和来源权重，但事件权重尚未进入可学习评估闭环。",
            "recommendation": "将事件类型偏好纳入 T+N 归因统计，补更细公告分类和来源质量评估。",
        },
        {
            "severity": "gap",
            "area": "backtest",
            "message": "当前 T+N 批量评估覆盖多维聚合、交易成本扣减、可选日 K 路径指标和等权组合摘要，但不是复权、持仓约束和调仓约束完整回测。",
            "recommendation": "增加持仓约束和组合层面的逐日权益曲线；完整研究后端可接 Qlib/Backtrader。",
        },
        {
            "severity": "gap",
            "area": "market_scope",
            "message": "A 股之外的美股/港股/日本/韩国/台湾/印度通过 Yahoo 筛选器接入，但还没有按交易所日历计算 T+N、没有跨币种的金额阈值，韩国缺少 PE/PB。",
            "recommendation": "引入 exchange_calendars 计算各市场交易日，为策略增加按市场覆盖的金额阈值，再考虑台湾交易所官方 OpenAPI 等更完整的数据源。",
        },
        {
            "severity": "gap",
            "area": "shape_validation",
            "message": "突破、回踩等形态策略已有平台、20 日形态特征、T+N 后验标签和可选日 K 路径指标，但还没有前高压力密集度和盘中失效条件。",
            "recommendation": "补充前高压力密集度和盘中止损约束。",
        },
    ]


def _next_priorities(strategy_findings: list[dict[str, str]], project_gaps: list[dict[str, str]]) -> list[str]:
    priorities = [
        "给行业/概念 history JSONL 增加板块层级口径归一和更完整的数据质量报告。",
        "将候选上下文事件类型偏好纳入 T+N 归因统计，补更细公告分类和来源质量评估。",
        "给批量 T+N 评估补持仓约束和组合层面的逐日权益曲线。",
    ]
    if any(item["area"] == "l1_shape_validation" for item in strategy_findings):
        priorities.insert(0, "补强趋势/形态策略的日 K 结构验证，尤其是放量突破类策略。")
    if any(item["area"] == "backtest" for item in project_gaps):
        priorities.append("后续再考虑接入 backtrader/qlib 这类完整回测框架，而不是在主链里硬塞。")
    return priorities
