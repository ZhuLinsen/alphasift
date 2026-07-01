# 评分体系

## screen_score 组成

`screen_score` 是选股专用的横向评分，用于在 L1 筛选后对候选进行排序。

| 子分数 | 说明 | 示例因子 |
|---|---|---|
| `factor_value_score` | 估值横向分 | PE、PB，低且为正更优 |
| `factor_liquidity_score` | 流动性横向分 | 成交额 |
| `factor_momentum_score` | 动量横向分 | 当日涨跌幅、60 日涨幅、signal_score、MACD |
| `factor_reversal_score` | 反转横向分 | 控制幅度下跌、RSI、60 日过热/过弱 |
| `factor_activity_score` | 资金活跃横向分 | 量比、换手率 |
| `factor_stability_score` | 稳定性横向分 | 极端波动、过热换手、负 PE、signal_score |
| `factor_size_score` | 容量横向分 | 总市值 |
| `factor_theme_heat_score` | 主题热度横向分 | `board_heat_score`、行业涨跌幅、行业排名、热度趋势 |

### 权重

当前实现优先使用策略 YAML 中的 `factor_weights`，可用因子包括：

| 因子 | 含义 |
|---|---|
| `value` | 低 PE、低 PB 的估值吸引力 |
| `liquidity` | 成交额代表的可交易性 |
| `momentum` | 建设性正向涨幅，避免极端追高 |
| `reversal` | 控制幅度下跌后的修复观察价值 |
| `activity` | 量比、换手率代表的资金活跃度 |
| `stability` | 对极端波动、过热换手、负 PE 的惩罚 |
| `size` | 总市值与容量 |
| `theme_heat` | 行业/概念/板块热度，但会惩罚过热 |

示例：

```
screen_score = Σ(factor_score × normalized_factor_weight)
```

若策略未配置 `factor_weights`，会根据 `tech_weight` 自动映射到兼容权重。

### 可配置评分曲线

因子评分有默认曲线，但不再要求所有策略共用同一套硬编码阈值。策略 YAML 可以通过 `scoring_profile` 覆盖关键参数，例如：

- `momentum_chase_start_pct`：动量分开始惩罚追高的涨幅
- `activity_ideal_volume_ratio`：活跃度分偏好的量比中心
- `activity_ideal_turnover_rate`：活跃度分偏好的换手中心
- `reversal_ideal_change_pct`：反转策略偏好的当日跌幅中心
- `stability_hot_change_pct`：稳定性分开始惩罚过热涨幅的位置
- `theme_heat_overheat_score`：主题热度分开始惩罚过热的位置
- `theme_heat_trend_min_observations`：使用板块热度趋势前要求的最少历史观测数
- `theme_heat_trend_slope` / `theme_heat_cooling_penalty_slope`：升温加分和降温扣分斜率
- `theme_heat_persistence_min_score` / `theme_heat_persistence_slope`：持续热度加分阈值和斜率
- `theme_heat_cooling_score_penalty_slope`：最新一段降温信号的扣分斜率

默认参数代表通用基线，策略 profile 表达风格差异；例如短线题材可容忍更高换手，稳健价值则应更早惩罚过热。

## 行业/概念/主题热度

`industry-cache` 和本地映射文件可以提供以下字段：

- `industry` / `concepts`：结构化行业和概念标签
- `industry_rank` / `industry_change_pct`：板块截面排名和涨跌幅
- `industry_heat_score` / `concept_heat_score` / `board_heat_score`：0-100 热度分
- `board_heat_latest_score` / `board_heat_trend_score` / `board_heat_observations`：从 history sidecar 回填的最新热度、滚动热度变化和观测数
- `board_heat_persistence_score` / `board_heat_cooling_score` / `board_heat_state`：滚动窗口内的持续热度、最新降温幅度和状态标签
- `board_heat_summary`：可读热度摘要，例如 `银行:+1.20%:rank=3`

这些字段不会成为默认硬筛条件。它们进入 `theme_heat` 因子、候选池结构摘要和 LLM prompt，用于区分“有板块扩散支撑”“持续升温”“持续热但边际降温”和“单日孤立脉冲”。短线策略可以给 `theme_heat` 更高权重；价值/防守策略可以不给权重，仅让 LLM 作为软信息参考。

`alphasift industry-cache` 除了主 CSV/JSON，还会写：

- `*.meta.json`：刷新时间、provider、抓取板块数、错误说明
- `*.history.jsonl`：每次刷新时的板块热度快照；加载主映射时会自动读取同名 history sidecar，回填趋势、持续性、降温和状态字段

## 日 K 增强

默认主链只依赖全市场快照。策略声明以下字段时，或显式启用 `--daily-enrich` 时，系统会在 L1 快照硬筛后只对 Top N 候选补充日 K 特征：

- `change_60d`
- `ma_bullish`
- `price_above_ma20`
- `macd_status`
- `rsi_status`
- `signal_score`
- `breakout_20d_pct`
- `range_20d_pct`
- `volume_ratio_20d`
- `body_pct`
- `pullback_to_ma20_pct`

这些特征会参与后续 hard filter 和因子评分，但日 K 增强不是全市场历史数据扫描。

日 K 拉取按单只候选执行，并通过 `DAILY_FETCH_RETRIES` 处理临时网络抖动。单只失败会记录到 degradation 并填充缺省特征，不拖垮同批其他候选；若某个策略硬性依赖日 K，失败候选会在日 K 硬筛中自然淘汰，避免在关键形态条件不可验证时继续入选。

## L3 后置分析器

L3 是最终候选后处理层。默认启用本地 `scorecard`，因此即使不配置外部系统，也会有一层稳定、低成本的候选复核评分。当前支持：

| 分析器 | 来源 | 作用 |
|---|---|---|
| `scorecard` | 本地规则评分 | 默认启用，根据因子、LLM 置信度、催化/风险做轻量加减分 |
| `dsa` | 外部 daily_stock_analysis | 对最终候选做单股深度分析并提取建议、趋势、风险 |
| `external_http` | 自定义 HTTP 工具 | 接入其他策略、评分器或研究系统 |

默认 `scorecard` 会覆盖全部最终输出候选；`dsa` 和 `external_http` 这类高成本后端默认只处理前 `POST_ANALYSIS_MAX_PICKS` 只。

`scorecard` 的加减分阈值也支持通过 `scorecard_profile` 覆盖，例如价值质量加分、量比脉冲扣分、LLM 置信度阈值、催化/风险标签加减分上限等。

DSA 不参与 L1 全市场初筛；它只在最终入围候选上调用，并在最后阶段作为 overlay 使用：
- `screen_score` 仍决定进入最终名单前的主排序
- DSA 返回的 `signal_score`、`sentiment_score`、`operation_advice`、趋势判断和风险因子会对最终 `final_score` 做修正
- 因此 DSA 更适合作为低频、高成本的终审层，而不是高频主链评分器

当前实现中，DSA 不参与 L1 全市场初筛；它只在最终入围候选上调用，并在最后阶段作为 overlay 使用：
- `screen_score` 仍决定进入最终名单前的主排序
- DSA 返回的 `signal_score`、`sentiment_score`、`operation_advice`、趋势判断和风险因子会对最终 `final_score` 做修正
- 因此 DSA 更适合作为低频、高成本的终审层，而不是高频主链评分器

## LLM 排序 (L2)

LLM 只在 Top K 候选上做相对排序，输入为：

1. 候选的 screen_score 和关键指标
2. 策略 YAML 中的 `ranking_hints`
3. 全市场快照摘要、候选池宽度、因子均值、因子领先候选和主评分分布
4. 新闻/情报摘要（如有）
5. 候选级 CSV/JSON/JSONL 外部线索（如有），通过 `--candidate-context-file` 按 `code` 对齐，只注入当前候选池相关行
6. 可选 Top K 抓取线索，通过 `--collect-candidate-context` 或 `LLM_CANDIDATE_CONTEXT_ENABLED=true` 抓取新闻、公告、资金流摘要，并带 `source_count`、`source_confidence`、`source_weight_score`、`context_summary`、公告类别、事件标签和负面风险标签

LLM 输出：

1. 全局 `market_view`：当前候选池和市场背景是否适合该策略
2. 全局 `selection_logic`：本次排序最主要的判断维度
3. 全局 `portfolio_risk`：最终名单共同风险或集中风险
4. 重排后的排名
5. 每个候选的 `thesis`、排序理由、风险摘要、潜在催化
6. 候选 `sector` / `theme`，用于组合集中度控制和后续复盘归因
7. 候选标签、风险标签、策略风格匹配说明和置信度
8. `watch_items` 和 `invalidators`：后续跟踪项和会推翻候选逻辑的观察点

LLM 只能在候选池内重排，不能推荐候选池外股票，也不能替代硬筛条件。
LLM 输出会经过 JSON 解析、代码覆盖率校验、重复代码/未知代码检查；不满足阈值时会重试，仍失败则回退到 `screen_score`。调用层支持 LiteLLM JSON mode、fallback models、多渠道 key/base_url 解析和高级 Router YAML。

## 后验评估与形态标签

`alphasift evaluate` 和 `evaluate-batch` 会用保存时价格与最新快照价格计算 T+N 收益，可通过 `EVALUATION_COST_BPS` 扣除往返成本。对带日 K 形态字段的候选，还会输出：

- `breakout_follow_through`：突破候选达到 `EVALUATION_FOLLOW_THROUGH_PCT`
- `failed_breakout`：突破候选跌破 `EVALUATION_FAILED_BREAKOUT_PCT`
- `breakout_unconfirmed`：介于两者之间
- `pullback_rebound` / `pullback_failed`：MA20 回踩候选的后验表现

批量评估会按 `by_shape_status` 和 `by_shape_tag` 聚合，帮助发现某类形态是否反复失效。`evaluate-batch` 还会输出 `portfolio_summary` 和 `portfolio_by_strategy`，把每次 run 当作等权组合，统计组合收益、组合胜率，以及启用价格路径后的组合级平均最大回撤/最大浮盈。

`evaluate-batch` 和 `evaluate-strategies` 的 JSON payload 同时包含 `failure_review`，用于策略研发复盘：

- `summary`：失败样本数、负收益数、缺报价数、失败突破数、严重回撤数、最差收益。
- `failure_samples`：按严重程度排序的样本，包含 run、策略、代码、收益、LLM tags/catalysts/risks、后置分析标签、形态状态、风险/组合 flags、`event_signals` 和失败原因。
- `dimensions`：按策略、行业/主题、LLM 催化/风险、后置分析标签、合并事件信号、风险 flag、组合 flag、形态状态、失败原因聚合失败样本。
- `recommendations`：面向调参和数据检查的下一步建议。

可用 `--failure-samples N` 控制 explain/JSON 中保留的样本数量，`0` 表示只保留聚合和建议。

同一批量评估 payload 还会输出 `event_signal_review`，把 `llm_tags`、`llm_catalysts`、`llm_risks` 和 `post_analysis_tags` 统一成 `tag:`、`catalyst:`、`risk:`、`post:` 四类事件信号。每个信号会给出样本数、胜率、平均/中位/最优/最差收益、失败率和 `prefer` / `avoid` / `watch` 动作建议，方便把后验表现沉淀回策略的 `preferred_event_tags`、`avoided_event_tags` 或 risk profile。

`event_signal_review.strategy_patch_suggestions` 会进一步按策略汇总这些证据，生成可审阅的 `screening.event_profile` YAML 片段和 `append_unique` 字段变更建议。它只输出建议，不会自动改写策略文件；适合先在 UI/PR 中审核，再把稳定信号加入具体策略。

如果启用 `--with-price-path` 或 `EVALUATION_PRICE_PATH_ENABLED=true`，评估会额外抓取候选日 K 路径，并计算：

- `path_end_return_pct`：路径最后一个交易日相对保存价的收益
- `max_drawdown_pct`：路径内相对保存价的最大下探幅度
- `max_runup_pct`：路径内相对保存价的最大上冲幅度
- `path_status`：路径是否可用

这仍不是完整回测，但能补上“只看最后一天收益却不知道中途回撤”的短板。

### LLM 配置

为便于复用 `daily_stock_analysis` 的配置，AlphaSift 支持同一套 LiteLLM 环境变量：

- `LITELLM_MODEL`
- `LITELLM_FALLBACK_MODELS`
- `LLM_CHANNELS` + `LLM_{NAME}_PROTOCOL/BASE_URL/API_KEY/API_KEYS/MODELS/ENABLED`
- `LITELLM_CONFIG`
- `OPENAI_API_KEY` / `OPENAI_BASE_URL`
- `GEMINI_API_KEY` / `GEMINI_API_KEYS`
- `DEEPSEEK_API_KEY`
- `OLLAMA_API_BASE`

旧变量 `LLM_API_KEY`、`LLM_MODEL`、`LLM_BASE_URL` 仍兼容。

## 风险覆盖层

风险覆盖独立于策略因子和 LLM。当前实现会根据以下字段做 penalty，也可通过 `RISK_VETO_HIGH=true` 直接剔除高风险候选：

| 检查项 | 行为 |
|---|---|
| 单日涨幅过高或跌幅过大 | penalty / 可选 veto |
| 异常量比、高换手 | penalty / 可选 veto |
| 负 PE、高 PB | penalty |
| 日 K 信号偏弱、MACD 空头、RSI 过热 | penalty |
| 日 K 数据质量过低、拉取失败、过期缓存或 source fallback | penalty / 可选 veto |
| LLM 风险标签、低置信度 | penalty |
| DSA 或其他后置分析器风险标签 | 进入候选风险字段，DSA 自身也会影响后置分数 |

最终输出同时包含 `risk_score`、`risk_level`、`risk_penalty` 和 `risk_flags`，便于后续 agent 或人工复核。

策略 YAML 可以用 `risk_profile` 覆盖风险阈值和扣分点，例如 `chase_change_pct`、`abnormal_volume_ratio`、`high_turnover_rate`、`low_llm_confidence`、`low_daily_quality_score`、`fetch_failed_daily_points`。这避免把“8% 就算追高”“量比 6 就异常”“拉取失败扣多少分”这类市场风格和数据质量假设写死在代码里。

## 组合分散覆盖层

LLM 会为候选输出统一的 `llm_sector` 和 `llm_theme`。如果候选快照或外部数据提供 `industry/concepts`，这些字段会进入 LLM 上下文；当 LLM 行业标签缺失时，组合分散层会用 `industry` 作为后备锚点。默认配置下，AlphaSift 会把这些标签映射成组合风险桶，并在裁剪最终 Top N 前执行一次组合分散覆盖。例如银行、券商、保险会共同落到金融风险桶。

- 同一 LLM 行业/风险桶超过 `PORTFOLIO_MAX_SAME_LLM_SECTOR` 后，后续候选会被扣除 `PORTFOLIO_CONCENTRATION_PENALTY`
- 该层在 LLM 返回行业标签，或候选提供结构化 `industry` 字段时生效；两者都缺失时不改变排序
- 扣分记录写入 `portfolio_penalty`、`portfolio_flags` 和 `portfolio_concentration_notes`

这不是硬性行业配额，而是对“同一拥挤交易占满最终名单”的温和约束；如果重复行业候选优势足够明显，仍可能保留在最终结果中。

默认风险桶可以用策略 YAML 的 `portfolio_profile.buckets` 覆盖或扩展。例如周期策略可以把钢铁、煤炭、有色归为一个周期桶；AI 策略可以把算力、光模块、服务器归为同一交易桶。
