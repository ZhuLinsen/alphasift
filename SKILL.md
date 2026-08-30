---
name: alphasift
description: "自动选股 Skill。Use when: 用户要按策略筛选 A 股、列出可用策略、运行双低/放量突破等选股，或保存运行并做 T+N 后验评估。通过 alphasift CLI 或 Python 接口输出候选股票列表。"
---

# alphasift — 自动选股 Skill

按策略筛选、评分并排序 A 股候选股票。

定位：全市场候选发现与横向排序引擎。它站在 `daily_stock_analysis` 这类单股深度分析服务上游；DSA 只是可选 L3 后置分析器，不是主筛选依赖。

## Use When

- 用户要列出当前可用策略
- 用户要按 `dual_low`、`volume_breakout` 这类策略筛选 A 股
- 用户要拿到结构化 JSON 结果，供后续 agent 继续分析
- 用户要保存选股运行，并在之后用最新快照评估结果
- 用户第一次接触本项目，想用 `alphasift quickstart` 一键看到全市场→候选→排名的最小闭环

## Preconditions

- 默认 `market="cn"`；`market="us"` 也可用（yfinance 快照 + 日K，无 hotspot/board_heat/tushare 等 CN 专属数据源），但需使用声明了 `market_scope` 含 `us` 的策略，目前为 `us_momentum_quality`
- 需要先在仓库根目录安装包：`pip install -e .`
- 如需 LLM 排序，可设置 `LITELLM_MODEL`、`LLM_CHANNELS`、`LITELLM_CONFIG` 或旧变量 `LLM_API_KEY/LLM_MODEL/LLM_BASE_URL`
- 可直接复用 `daily_stock_analysis` 的 LiteLLM 配置字段，包括 `OPENAI_*`、`GEMINI_*`、`DEEPSEEK_API_KEY`、`OLLAMA_API_BASE`
- 策略 YAML 可通过 `scoring_profile`、`risk_profile`、`portfolio_profile`、`scorecard_profile` 覆盖默认规则
- 策略 YAML 可通过 `event_profile` 配置偏好/规避事件、公告类别和候选上下文来源权重
- LLM 会输出候选行业/主题标签；如候选提供 `industry/concepts/board_heat_score/board_heat_trend_score`，会作为 LLM、主题热度因子与组合分散层锚点；history sidecar 可回填持续性、降温和状态字段。默认组合分散层会用这些标签映射风险桶，降低同一拥挤交易重复占位
- L3 默认启用本地 `scorecard` 后置评分器，也可追加 `dsa` 或 `external_http`
- 如需 DSA 后置分析，设置 `DSA_API_URL`，默认调用 `POST /api/v1/analysis/analyze`
- 依赖日 K 的策略会在 L1 后自动对 Top N 候选做日 K 增强
- 日 K 数据源 `DAILY_SOURCE` 支持 `akshare`（默认）、`baostock` 或 `auto`，`auto` 会在 akshare 失败时自动降级到 baostock 作为免费兜底

## Operations

### 1. 列出策略

```bash
alphasift strategies
```

### 1.1 一键演示（无 API key）

```bash
alphasift quickstart
alphasift quickstart --strategy balanced_alpha --max-output 8
```

### 2. 执行选股

```bash
alphasift screen dual_low --no-llm
alphasift screen volume_breakout --max-output 10
alphasift screen balanced_alpha --no-llm
alphasift screen capital_heat
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

### 3. Python 调用

```python
from alphasift import evaluate_saved_run, evaluate_saved_runs, list_strategies, screen

list_strategies()
screen("dual_low", market="cn", use_llm=False)
evaluate_saved_run("<run_id>")
evaluate_saved_runs(limit=20)
```

## Output

返回 `ScreenResult` JSON，核心字段有：
- `strategy`
- `market`
- `strategy_version`
- `snapshot_count`
- `after_filter_count`
- `picks`
- `llm_ranked`
- `llm_market_view`
- `llm_selection_logic`
- `llm_portfolio_risk`
- `llm_coverage`
- `post_analyzers`
- `daily_enriched`
- `risk_enabled`
- `portfolio_concentration_notes`
- `degradation`
- `snapshot_source`
- `source_errors`

每个 `Pick` 包含：
- `rank`
- `code`
- `name`
- `final_score`
- `screen_score`
- `ranking_reason`
- `risk_summary`
- `price`
- `change_pct`
- `amount`
- `total_mv`
- `turnover_rate`
- `volume_ratio`
- `pe_ratio`
- `pb_ratio`
- `industry`
- `concepts`
- `board_heat_score`
- `board_heat_latest_score`
- `board_heat_trend_score`
- `board_heat_persistence_score`
- `board_heat_cooling_score`
- `board_heat_observations`
- `board_heat_state`
- `board_heat_summary`
- `change_60d`
- `signal_score`
- `macd_status`
- `rsi_status`
- `breakout_20d_pct`
- `range_20d_pct`
- `volume_ratio_20d`
- `body_pct`
- `pullback_to_ma20_pct`
- `consolidation_days_20d`
- `factor_scores`
- `llm_confidence`
- `llm_sector`
- `llm_theme`
- `llm_tags`
- `llm_catalysts`
- `llm_risks`
- `llm_thesis`
- `llm_style_fit`
- `llm_watch_items`
- `llm_invalidators`
- `risk_score`
- `risk_level`
- `risk_penalty`
- `risk_flags`
- `portfolio_penalty`
- `portfolio_flags`
- `post_analysis_status`
- `post_analysis_score_deltas`
- `deep_analysis_status`
- `deep_analysis_summary`
- `deep_analysis_result`
- `deep_analysis_signal_score`
- `deep_analysis_sentiment_score`
- `deep_analysis_operation_advice`
- `deep_analysis_trend_prediction`
- `deep_analysis_risk_flags`

## Boundaries

- 当前没有独立的远程 `get_result` 服务；本地用 `--save-run`、`runs`、`evaluate`、`evaluate-batch` 管理运行记录
- `audit` 用于自检策略 profile 覆盖、已知能力短板和下一步优先级
- `--candidate-context-file` 支持 CSV/JSON/JSONL，通过 `code` 对齐候选级新闻、公告、资金流或研究摘要，只注入当前候选池相关行；可选抓取会附带 `source_count`、`source_confidence`、`source_weight_score`、`context_summary` 和公告类别
- 候选级上下文会识别粗粒度事件标签和负面风险标签，供 LLM 横向排序参考
- `industry-cache` 会缓存行业/概念映射和板块热度字段，并写入 history sidecar；后续加载映射时可回填板块热度滚动趋势、持续性、降温和状态字段，供 LLM 上下文与 `theme_heat` 因子使用
- 组合分散层优先使用 LLM 返回的行业/主题标签，也可回退到候选 `industry` 字段；两者都缺失时不会改变规则分数
- L3 后置分析器只在最终候选上运行，不参与全市场初筛；本地 `scorecard` 默认启用，DSA 只是其中一个可追加后端
- T+N 评估基于保存价和评估时最新快照价，不等同完整复权回测；可扣减交易成本并输出突破/回踩形态后验标签；`--with-price-path` 会额外估算最大回撤和最大浮盈
