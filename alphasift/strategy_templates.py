# -*- coding: utf-8 -*-
"""Reusable strategy authoring templates."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class StrategyTemplate:
    name: str
    display_name: str
    description: str
    category: str
    tags: list[str]
    style: dict[str, object]
    data_requirements: list[str]
    notes: list[str]
    yaml_text: str


_TEMPLATES: dict[str, StrategyTemplate] = {
    "defensive_value_quality": StrategyTemplate(
        name="defensive_value_quality",
        display_name="稳健价值质量",
        description="从估值、稳定性和流动性出发的防守型价值质量模板",
        category="value",
        tags=["value", "quality", "defensive"],
        style={
            "risk_profile": "defensive",
            "holding_period": "watchlist",
            "execution_style": "quality_value",
            "market_regime": ["risk_off", "range_bound"],
            "capital_profile": "medium_liquidity",
            "ui_badge": "稳健",
        },
        data_requirements=["snapshot"],
        notes=[
            "适合从 `quality_value` / `dual_low` 延伸出更保守的策略。",
            "默认不依赖日 K，先保证 snapshot 字段覆盖和低降级风险。",
        ],
        yaml_text="""# Defensive value-quality template. Rename before use.
name: my_defensive_value_quality
display_name: 我的稳健价值质量
description: 估值合理、流动性充足、波动不过热的防守型候选
version: "1.0"
category: value
tags: [value, quality, defensive]
style:
  risk_profile: defensive
  holding_period: watchlist
  execution_style: quality_value
  market_regime: [risk_off, range_bound]
  capital_profile: medium_liquidity
  ui_badge: 稳健

screening:
  enabled: true
  market_scope: [cn]
  hard_filters:
    exclude_st: true
    amount_min: 80000000
    price_min: 3
    price_max: 180
    market_cap_min: 10000000000
    pe_ttm_min: 0
    pe_ttm_max: 25
    pb_min: 0
    pb_max: 4.0
    change_pct_min: -3.5
    change_pct_max: 5.0
  tech_weight: 0.15
  factor_weights:
    value: 0.32
    stability: 0.24
    liquidity: 0.18
    momentum: 0.08
    activity: 0.08
    reversal: 0.04
    size: 0.06
  scoring_profile:
    momentum_chase_start_pct: 3.0
    activity_ideal_volume_ratio: 1.4
    activity_ideal_turnover_rate: 2.5
    stability_hot_change_pct: 4.5
  risk_profile:
    chase_change_pct: 5.5
    abnormal_volume_ratio: 4.5
    high_turnover_rate: 10.0
  scorecard_profile:
    value_quality_value_min: 72.0
    value_quality_stability_min: 68.0
    value_quality_bonus: 2.8
  ranking_hints: |
    优先关注：
    1. 估值合理且不是依赖单日情绪推动的标的
    2. 成交额足够、涨跌幅不过热
    3. 行业地位、现金流质量或经营稳定性更好
  max_output: 5
""",
    ),
    "momentum_breakout_daily": StrategyTemplate(
        name="momentum_breakout_daily",
        display_name="日K放量突破",
        description="依赖日 K 特征确认放量突破、均线结构和整理形态的进攻型模板",
        category="trend",
        tags=["momentum", "breakout", "daily_k"],
        style={
            "risk_profile": "aggressive",
            "holding_period": "short_term",
            "execution_style": "breakout",
            "market_regime": ["risk_on", "trend", "high_volume"],
            "capital_profile": "high_liquidity",
            "ui_badge": "突破",
        },
        data_requirements=["snapshot", "daily_k", "industry_context"],
        notes=[
            "适合从 `volume_breakout` 延伸，依赖 daily K-line 数据源稳定性。",
            "上线前先运行 `doctor data-sources --strategy <name> --explain` 检查字段覆盖。",
        ],
        yaml_text="""# Momentum breakout template. Rename before use.
name: my_momentum_breakout
display_name: 我的放量突破
description: 成交量放大突破关键阻力位，趋势启动信号
version: "1.0"
category: trend
tags: [momentum, volume, breakout, daily_k]
style:
  risk_profile: aggressive
  holding_period: short_term
  execution_style: breakout
  market_regime: [risk_on, trend, high_volume]
  capital_profile: high_liquidity
  ui_badge: 突破

screening:
  enabled: true
  market_scope: [cn]
  hard_filters:
    exclude_st: true
    amount_min: 100000000
    turnover_rate_min: 3.0
    volume_ratio_min: 2.0
    change_pct_min: 2.0
    change_pct_max: 9.9
    require_price_above_ma20: true
    signal_score_min: 60
    macd_status_whitelist: [bullish, neutral]
    breakout_20d_pct_min: -1.0
    range_20d_pct_max: 35.0
    volume_ratio_20d_min: 1.3
    body_pct_min: 0.5
    consolidation_days_20d_min: 8
  tech_weight: 0.6
  factor_weights:
    momentum: 0.32
    activity: 0.28
    liquidity: 0.22
    theme_heat: 0.08
    stability: 0.10
  scoring_profile:
    momentum_chase_start_pct: 7.0
    activity_ideal_volume_ratio: 3.0
    activity_high_volume_ratio: 9.0
    activity_ideal_turnover_rate: 6.0
    stability_hot_change_pct: 8.8
  risk_profile:
    chase_change_pct: 9.8
    abnormal_volume_ratio: 9.0
    high_turnover_rate: 24.0
    weak_signal_score: 45.0
  scorecard_profile:
    capital_confirmed_bonus: 2.2
    volume_spike_ratio: 9.0
    hot_money_activity_min: 96.0
    hot_money_penalty: 1.4
  ranking_hints: |
    优先关注：
    1. 突破前有明显横盘整理
    2. 量比和换手同步放大，日 K 信号仍健康
    3. 板块有联动效应更佳
  max_output: 5
""",
    ),
    "oversold_reversal_snapshot": StrategyTemplate(
        name="oversold_reversal_snapshot",
        display_name="超跌修复",
        description="只依赖 snapshot 的超跌修复模板，用于低数据依赖的反转候选",
        category="reversal",
        tags=["reversal", "oversold", "snapshot_only"],
        style={
            "risk_profile": "balanced",
            "holding_period": "short_term",
            "execution_style": "reversal",
            "market_regime": ["oversold_repair", "range_bound"],
            "capital_profile": "medium_liquidity",
            "ui_badge": "反转",
        },
        data_requirements=["snapshot"],
        notes=[
            "适合数据源不稳定时的低依赖策略起点。",
            "需要靠后续 LLM/scorecard/人工复核确认是否真的出现修复催化。",
        ],
        yaml_text="""# Oversold reversal template. Rename before use.
name: my_oversold_reversal
display_name: 我的超跌修复
description: 跌幅可控、流动性仍在、具备修复观察价值的反转候选
version: "1.0"
category: reversal
tags: [reversal, oversold, snapshot_only]
style:
  risk_profile: balanced
  holding_period: short_term
  execution_style: reversal
  market_regime: [oversold_repair, range_bound]
  capital_profile: medium_liquidity
  ui_badge: 反转

screening:
  enabled: true
  market_scope: [cn]
  hard_filters:
    exclude_st: true
    amount_min: 60000000
    price_min: 3
    price_max: 120
    pe_ttm_min: 0
    pe_ttm_max: 80
    pb_min: 0
    pb_max: 8.0
    turnover_rate_min: 1.0
    change_pct_min: -8.0
    change_pct_max: 1.5
  tech_weight: 0.35
  factor_weights:
    reversal: 0.40
    stability: 0.20
    liquidity: 0.18
    value: 0.16
    activity: 0.06
  scoring_profile:
    reversal_ideal_change_pct: -3.5
    reversal_collapse_start_pct: -8.5
    reversal_chase_start_pct: 2.0
    activity_ideal_turnover_rate: 3.0
  risk_profile:
    breakdown_change_pct: -8.5
    chase_change_pct: 4.0
    abnormal_volume_ratio: 5.5
  scorecard_profile:
    controlled_reversal_min: 72.0
    controlled_reversal_bonus: 2.0
  ranking_hints: |
    优先关注：
    1. 跌幅可控，不能是流动性枯竭的连续下跌
    2. 成交额仍然足够，后续有修复观察价值
    3. 避免基本面或监管风险明显的标的
  max_output: 5
""",
    ),
}


def list_strategy_templates() -> list[dict[str, object]]:
    """Return available authoring templates without the full YAML body."""
    return [
        _template_payload(template, include_yaml=False)
        for template in _TEMPLATES.values()
    ]


def get_strategy_template(name: str, *, include_yaml: bool = True) -> dict[str, object]:
    try:
        template = _TEMPLATES[name]
    except KeyError as exc:
        available = ", ".join(_TEMPLATES)
        raise ValueError(f"Strategy template '{name}' not found; available: {available}") from exc
    return _template_payload(template, include_yaml=include_yaml)


def render_strategy_template(name: str) -> str:
    return str(get_strategy_template(name, include_yaml=True)["yaml"])


def _template_payload(template: StrategyTemplate, *, include_yaml: bool) -> dict[str, object]:
    payload = asdict(template)
    if include_yaml:
        payload["yaml"] = payload.pop("yaml_text")
    else:
        payload.pop("yaml_text", None)
    return payload
