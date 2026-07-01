# 策略编写指南

## 文件位置

策略文件放在 `strategies/` 目录下，文件名即策略标识（如 `dual_low.yaml`）。

## 最小示例

```yaml
name: my_strategy
display_name: 我的策略
description: 一句话描述策略目标
version: "1.0"
category: value     # trend / value / income / quality / momentum / pattern / reversal
tags: [value, custom]
style:
  risk_profile: defensive
  holding_period: watchlist
  execution_style: mean_reversion
  market_regime: [risk_off, range_bound]
  capital_profile: medium_liquidity
  ui_badge: 价值

screening:
  enabled: true
  market_scope: [cn]
  hard_filters:
    exclude_st: true
    amount_min: 50000000
  max_output: 5
```

## 完整 Schema

```yaml
name: string              # 唯一标识（英文下划线）
display_name: string      # 显示名称
description: string       # 策略说明
version: string           # 策略版本，建议每次语义变化递增
category: string          # trend / value / income / quality / momentum / pattern / reversal / framework
tags: [string]            # 可选标签，便于检索和评估分组
style:                    # 可选，面向 UI/agent 的策略风格，不参与硬筛
  risk_profile: string    # defensive / balanced / aggressive
  holding_period: string  # short_term / swing / watchlist
  execution_style: string # mean_reversion / momentum / breakout / multi_factor 等
  market_regime: [string] # risk_on / risk_off / trend / range_bound / rotation 等
  capital_profile: string # high_liquidity / medium_liquidity
  ui_badge: string        # UI 中显示的短标签

screening:
  enabled: bool            # 是否启用选股
  market_scope: [string]   # 适用市场，当前仅 [cn]

  hard_filters:            # L1 硬筛条件（全部可选，不填则不筛）
    exclude_st: bool       # 排除 ST
    price_min: float       # 最低价格
    price_max: float       # 最高价格
    amount_min: float      # 最低成交额（元）
    market_cap_min: float  # 最低总市值
    market_cap_max: float  # 最高总市值
    pe_ttm_min: float      # 最低 PE(TTM)
    pe_ttm_max: float      # 最高 PE(TTM)
    pb_min: float          # 最低 PB
    pb_max: float          # 最高 PB
    volume_ratio_min: float    # 最低量比
    turnover_rate_min: float   # 最低换手率
    change_pct_min: float      # 最低涨跌幅
    change_pct_max: float      # 最高涨跌幅
    change_60d_min: float      # 60 日最低涨幅
    change_60d_max: float      # 60 日最高涨幅
    require_ma_bullish: bool   # 要求均线多头排列
    require_price_above_ma20: bool  # 要求价格在 MA20 上方
    signal_score_min: int      # 最低信号得分
    macd_status_whitelist: [string]  # MACD 状态白名单
    rsi_status_whitelist: [string]   # RSI 状态白名单

  tech_weight: float       # 技术分数权重，0-1，默认 0.35
  factor_weights:          # 可选，多因子评分权重；配置后优先于 tech_weight
    value: float           # 估值
    liquidity: float       # 流动性
    momentum: float        # 动量
    reversal: float        # 反转
    activity: float        # 活跃度
    stability: float       # 稳定性
    size: float            # 市值容量
    theme_heat: float      # 主题/板块热度，可选软因子

  scoring_profile:         # 可选，覆盖 L1 因子评分曲线中的默认参数
    momentum_chase_start_pct: float
    activity_ideal_volume_ratio: float
    activity_ideal_turnover_rate: float
    theme_heat_overheat_score: float
    theme_heat_trend_min_observations: float
    theme_heat_trend_slope: float
    theme_heat_cooling_penalty_slope: float
    theme_heat_persistence_min_score: float
    theme_heat_persistence_slope: float
    theme_heat_cooling_score_penalty_slope: float

  risk_profile:            # 可选，覆盖风险层阈值/扣分
    chase_change_pct: float
    abnormal_volume_ratio: float
    high_turnover_rate: float
    low_daily_quality_score: float
    fetch_failed_daily_points: float

  portfolio_profile:       # 可选，覆盖 LLM 行业/主题风险桶
    max_same_bucket: int
    concentration_penalty: float
    buckets:
      金融: [券商, 银行, 保险]

  scorecard_profile:       # 可选，覆盖默认 L3 scorecard 加减分规则
    value_quality_bonus: float
    volume_spike_ratio: float

  event_profile:           # 可选，给 LLM 和候选上下文抓取使用的事件偏好
    preferred_event_tags: [string]
    avoided_event_tags: [string]
    preferred_announcement_categories: [string]
    avoided_announcement_categories: [string]
    source_weights:
      announcement: float
      news: float
      fund_flow: float

  ranking_hints: string    # 给 LLM 的排序提示（自然语言）
  max_output: int          # 最终输出数量，默认 5
```

`style` 不参与硬筛，但会进入 `alphasift strategies --json` 和策略匹配命令。例如 `alphasift strategies --risk-profile defensive --market-regime risk_off --strict --json` 会按这些字段返回带 `score`、`matched`、`missing` 的候选策略，方便 Web UI、agent 或通知流解释为什么选用某个策略。

## 策略模板

从零新增策略时，可以先用内置模板生成草稿，再按目标市场环境、数据源覆盖和风险偏好调整：

```bash
alphasift strategies --templates --explain
alphasift strategies --template defensive_value_quality > strategies/my_defensive_value_quality.yaml
alphasift strategies --template momentum_breakout_daily --json
```

当前模板：

- `defensive_value_quality`：稳健价值质量，snapshot-only，适合从 `quality_value` / `dual_low` 延伸。
- `momentum_breakout_daily`：日 K 放量突破，依赖 `daily_k` 和行业/主题上下文，上线前应先跑数据源 doctor。
- `oversold_reversal_snapshot`：超跌修复，snapshot-only，适合数据源不稳定时作为低依赖反转策略起点。

模板不放在 `strategies/*.yaml` 下，因此不会被当成已启用策略自动加载。输出到 `strategies/` 后请先改 `name`、`display_name` 和 `version`，再用 `alphasift doctor data-sources --strategy <name> --no-live --explain` 检查字段覆盖。

## 策略分类说明

| 分类 | 适用场景 | 示例 |
|---|---|---|
| `trend` | 趋势确认与趋势延续 | 缩量回踩、放量突破、多头排列 |
| `value` | 估值驱动的价值筛选 | 双低、高股息、低 PEG |
| `pattern` | 技术形态识别 | 一阳穿三阴、底部放量 |
| `reversal` | 反转信号捕捉 | 超跌反弹、底背离 |

## ranking_hints 编写建议

`ranking_hints` 是发送给 LLM 的自然语言提示，用于指导候选间的相对排序。

好的写法：
- 明确列出优先关注的维度（1、2、3）
- 描述具体的偏好（如"缩量明显"而非"量能良好"）
- 提及风险排除条件
- 提醒 LLM 识别行业/主题共性，避免最终名单都来自同一拥挤交易

避免的写法：
- 让 LLM 自行发挥选股标准
- 包含精确数值阈值（这些应放在 hard_filters 中）
- 要求 LLM 给出目标价

## factor_weights 编写建议

- 价值策略：提高 `value`、`stability`，适当保留 `liquidity`
- 动量策略：提高 `momentum`、`activity`、`liquidity`
- 资金/题材策略：可加入 `theme_heat`，让板块扩散、热度升温/降温趋势进入软评分
- 反转策略：提高 `reversal`、`stability`，避免单纯追跌
- 通用策略：分散配置多个因子，让 LLM 在 L2 解释因子冲突

## profile 编写建议

内置默认 profile 只提供开箱即用的基线。只要某个阈值明显代表策略偏好，就应放到 YAML：

- 短线热度策略可降低 `momentum_chase_start_pct`，更早惩罚追高
- 低波动价值策略可降低 `chase_change_pct`、`volume_spike_ratio`
- 高弹性题材策略可提高 `high_turnover_rate`、`abnormal_volume_ratio`
- 行业集中度偏好可用 `portfolio_profile.buckets` 调整，例如把银行、券商、保险归为金融风险桶
- 事件驱动策略可用 `event_profile` 偏好回购、订单、业绩改善，也可以提高公告相对新闻的来源权重

不要把 profile 当作回测拟合参数频繁调到极端值；它更适合表达策略风格和风险偏好。

## 日 K 条件

这些字段依赖候选级日 K 增强：

- `change_60d_min` / `change_60d_max`
- `require_ma_bullish`
- `require_price_above_ma20`
- `signal_score_min`
- `macd_status_whitelist`
- `rsi_status_whitelist`
- `breakout_20d_pct_min` / `breakout_20d_pct_max`
- `range_20d_pct_max`
- `volume_ratio_20d_min` / `volume_ratio_20d_max`
- `body_pct_min` / `body_pct_max`
- `pullback_to_ma20_pct_min` / `pullback_to_ma20_pct_max`
- `consolidation_days_20d_min` / `consolidation_days_20d_max`

如果策略配置了这些条件，pipeline 会先做快照字段硬筛，再对 Top N 候选拉取日 K 并计算特征，最后执行日 K 硬筛。这样能开放 `shrink_pullback` 这类策略，同时避免对全市场逐只拉取历史行情。

## 版本与评估

策略语义变化时建议更新 `version`，例如：

- 调整 hard filter 阈值：`1.0` → `1.1`
- 改变因子权重结构：`1.1` → `1.2`
- 改变策略目标或适用场景：`1.x` → `2.0`

提交策略变更前可用对比命令检查参数漂移：

```bash
alphasift strategies --compare dual_low low_volatility_quality --explain
alphasift strategies --compare dual_low low_volatility_quality --json
```

对比 payload 会列出风格、数据依赖、必需字段、硬筛参数、因子权重和 profile keys 的差异，并在 `summary.compatibility_notes` 中提示日 K 依赖或数据要求变化。

`alphasift screen --save-run` 会把 `strategy_version`、候选、分数、风险和后置分析结果一起保存。后续可用 `alphasift evaluate <run_id>` 做单次 T+N 后验评估，也可以用 `alphasift evaluate-batch --limit 20 --explain` 对最近保存的 runs 做策略级聚合复盘。评估会按收益、交易成本、行业/主题、LLM 催化/风险、后置分析标签、风险标签、持有期和形态后验标签聚合，并输出 `failure_review` 和 `event_signal_review`，把失败样本、共性事件信号、事件信号胜率、共性风险 flag、失败突破、严重回撤和下一步调参建议聚在一起。

## L3 后置分析器

策略 YAML 只负责 L1 筛选和基础评分偏好，不绑定具体 L3 工具。运行时用 CLI 或环境变量选择：

```bash
alphasift screen balanced_alpha
alphasift screen dual_low --post-analyzer dsa
alphasift screen capital_heat --post-analyzer external_http
alphasift screen balanced_alpha --no-post-analysis
```

可选分析器包括：

- `scorecard`：本地轻量后置评分，默认启用并覆盖全部输出候选
- `dsa`：外部 daily_stock_analysis 单股深度分析，默认只处理前 N 只
- `external_http`：自定义 HTTP 评分或研究工具
