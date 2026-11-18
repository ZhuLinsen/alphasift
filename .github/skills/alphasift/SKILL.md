---
name: alphasift
description: "自动选股 Skill。Use when: 用户要按策略筛选 A 股、列出可用策略、运行双低/放量突破/均衡多因子/资金热度等选股，或保存运行并做 T+N 后验评估。通过 alphasift CLI 或 Python 接口输出候选股票列表。"
---

# alphasift — 自动选股 Skill

按策略筛选、评分并排序 A 股候选股票。

定位：全市场候选发现与横向排序引擎。它站在 `daily_stock_analysis` 这类单股深度分析服务上游；DSA 只是可选 L3 后置分析器，不是主筛选依赖。

## Use When

- 用户要列出当前可用策略
- 用户要按 `dual_low`、`volume_breakout`、`balanced_alpha`、`capital_heat` 这类策略筛选 A 股
- 用户要拿到结构化 JSON 结果，供后续 agent 继续分析
- 用户要保存选股运行，并在之后用最新快照评估结果

## Preconditions

alphasift 包已安装在当前 Python 环境中。如未安装，先执行：

```bash
pip install -e .
```

LLM 排序调用 OpenAI 兼容接口，可设置 `LITELLM_MODEL`、`LLM_CHANNELS` 或 `LLM_API_KEY`、`LLM_MODEL`、`LLM_BASE_URL`。`LITELLM_MODEL`、`AGENT_LITELLM_MODEL` 和 `LITELLM_FALLBACK_MODELS` 的变量名仅为兼容而保留。若设置了 `LITELLM_CONFIG`，请删除该变量并迁移到 `LLM_CHANNELS`。策略 YAML 可通过 `scoring_profile`、`risk_profile`、`portfolio_profile`、`scorecard_profile`、`event_profile` 覆盖默认规则、事件偏好和候选上下文来源权重。LLM 会输出候选行业/主题标签；如候选提供 `industry/concepts/board_heat_score/board_heat_trend_score`，会作为 LLM、主题热度因子与组合分散层锚点；history sidecar 可回填持续性、降温和状态字段。默认组合分散层会用这些标签映射风险桶，降低同一拥挤交易重复占位。

L3 默认启用本地 `scorecard` 后置评分器，也可追加 `dsa` 或 `external_http`。如需 DSA 后置分析，设置 `DSA_API_URL`；DSA 只作为后置增强，不参与全市场初筛。

依赖日 K 的策略会在 L1 后自动对 Top N 候选做日 K 增强。

如需 L3 深度分析，需要设置 `DSA_API_URL`。这里的 `DSA` 指外部项目 `daily_stock_analysis`，默认调用 `POST /api/v1/analysis/analyze`。

## Operations

### 1. 查看可用策略

```bash
alphasift strategies
```

### 2. 执行选股

```bash
alphasift screen dual_low --no-llm
alphasift screen balanced_alpha --no-llm
alphasift screen capital_heat
alphasift screen volume_breakout --max-output 10
alphasift screen balanced_alpha --context "今日券商板块放量，低估值金融获得资金回流"
alphasift --env-file /home/ubuntu/daily_ai_assistant/.env screen balanced_alpha
alphasift screen balanced_alpha --explain
alphasift screen balanced_alpha --candidate-context-file candidate_context.csv
alphasift screen dual_low --no-post-analysis
alphasift screen shrink_pullback --no-llm
alphasift screen dual_low --post-analyzer dsa
alphasift audit
alphasift industry-cache --output data/industry_map.csv --explain
alphasift screen dual_low --no-llm --save-run
alphasift runs
alphasift evaluate <run_id> --explain
alphasift evaluate-batch --limit 20 --explain
alphasift evaluate <run_id> --with-price-path --explain
```

### 3. 通过 Python 调用

```python
from alphasift import evaluate_saved_run, evaluate_saved_runs, screen, list_strategies

list_strategies()
screen("dual_low", market="cn", use_llm=False)
evaluate_saved_run("<run_id>")
evaluate_saved_runs(limit=20)
```

## Output

返回 `ScreenResult` JSON，核心字段有：
- `strategy`: 策略名
- `market`: 市场
- `strategy_version`: 策略版本
- `snapshot_count`: 全市场股票数
- `after_filter_count`: 硬筛后剩余数量
- `picks`: 推荐列表
- `llm_ranked`: 是否经过 LLM 排序
- `llm_market_view`: LLM 对候选池和市场环境的整体判断
- `llm_selection_logic`: LLM 本次排序采用的核心判断维度
- `llm_portfolio_risk`: LLM 识别的最终名单共同风险
- `llm_coverage`: LLM 输出覆盖候选池比例
- `post_analyzers`: 已启用的 L3 后置分析器
- `daily_enriched`: 是否做过日 K 候选增强
- `risk_enabled`: 是否启用独立风险层
- `portfolio_concentration_notes`: 组合分散覆盖层的扣分说明
- `degradation`: 降级信息
- `snapshot_source`: 实际使用的数据源
- `source_errors`: 降级前失败的数据源错误

每个 `Pick` 会包含 `factor_scores`、`industry/concepts/board_heat_score/board_heat_trend_score/board_heat_persistence_score/board_heat_cooling_score/board_heat_state/board_heat_summary`、LLM 输出的 thesis/理由/风险/催化/行业/主题/标签/风格匹配/跟踪项/失效条件、风险层字段、组合分散扣分字段，以及可选的后置分析字段。DSA 字段只在启用 `dsa` 分析器时填充。

每个 `Pick` 还可能包含：
- `deep_analysis_status`
- `deep_analysis_summary`
- `deep_analysis_result`
- `deep_analysis_signal_score`
- `deep_analysis_sentiment_score`
- `deep_analysis_operation_advice`
- `deep_analysis_trend_prediction`
- `deep_analysis_risk_flags`

## Boundaries

- 当前只支持 `market="cn"`
- 当前没有独立的远程 `get_result` 服务；本地用 `--save-run`、`runs`、`evaluate`、`evaluate-batch` 管理运行记录
- `audit` 用于自检策略 profile 覆盖、已知能力短板和下一步优先级
- `--candidate-context-file` 支持 CSV/JSON/JSONL，通过 `code` 对齐候选级新闻、公告、资金流或研究摘要，只注入当前候选池相关行；可选抓取会附带 `source_count`、`source_confidence`、`source_weight_score`、`context_summary` 和公告类别
- 候选级上下文会识别粗粒度事件标签和负面风险标签，供 LLM 横向排序参考
- `industry-cache` 会缓存行业/概念映射和板块热度字段，并写入 history sidecar；后续加载映射时可回填板块热度滚动趋势、持续性、降温和状态字段，供 LLM 上下文与 `theme_heat` 因子使用
- 组合分散层优先使用 LLM 返回的行业/主题标签，也可回退到候选 `industry` 字段；两者都缺失时不会改变规则分数
- L3 后置分析器只在最终候选上运行，不参与全市场初筛；本地 `scorecard` 默认启用，DSA 只是其中一个可追加后端
- T+N 评估基于保存价和评估时最新快照价，不等同完整复权回测；可扣减交易成本并输出突破/回踩形态后验标签；`--with-price-path` 会额外估算最大回撤和最大浮盈
