# 使用指南

这份文档放 README 之外的日常用法：安装、CLI 命令、Python 调用、上下文注入和评估闭环。

## 安装

```bash
pip install -e .
cp .env.example .env
```

如果暂时不用 LLM 排序，运行命令时加 `--no-llm` 即可，不需要配置模型 key。

## 三步跑通

```bash
alphasift strategies

alphasift screen dual_low --no-llm --explain

alphasift screen dual_low --no-llm --save-run
alphasift runs
alphasift evaluate <run_id> --explain
```

## UI/agent 总览

`overview` 会把策略分组、策略推荐、数据源健康、策略字段覆盖、最近运行和 next actions 放到同一份 payload，适合 Web UI、通知助手或 agent 首屏使用：

```bash
alphasift overview --explain
alphasift overview --risk-profile aggressive --data-requirement daily_k --match-limit 2 --json
```

默认不会发起网络请求，只读取当前进程的 source-health 和本地 run 索引；需要真实数据源 smoke check 时加 `--live-data-check`。

策略目录也可以输出更完整的能力描述，方便 UI、agent 或外部系统选择合适策略：

```bash
alphasift strategies --explain
alphasift strategies --json
```

结构化输出包含策略分类、标签、风格属性、数据依赖、是否需要日 K、必需 snapshot/daily 字段、活跃 hard filters、因子权重和 profile 覆盖项。

也可以直接按风格/数据依赖匹配策略，给命令行、Web UI 或 agent 做策略选择：

```bash
alphasift strategies --risk-profile defensive --holding-period swing --market-regime risk_off --strict --explain
alphasift strategies --risk-profile aggressive --data-requirement daily_k --limit 2 --json
```

匹配结果包含 `score`、`matched` 和 `missing`，便于界面展示为什么推荐某个策略，以及哪些偏好没有满足。

策略迭代或新增策略前，可以对比两套策略的风格、数据依赖、必需字段、硬筛参数和因子权重：

```bash
alphasift strategies --compare dual_low low_volatility_quality --explain
alphasift strategies --compare dual_low low_volatility_quality --json
```

JSON 输出包含 `differences` 和 `summary.compatibility_notes`，适合 UI 展示参数变更、日 K 依赖变化和数据源兼容性影响。

新增策略时可以先列出模板，再把模板 YAML 输出到 `strategies/` 下改名迭代：

```bash
alphasift strategies --templates --explain
alphasift strategies --template defensive_value_quality > strategies/my_defensive_value_quality.yaml
alphasift strategies --template momentum_breakout_daily --json
```

模板 payload 包含策略风格、数据依赖、适用说明和可直接编辑的 YAML，便于 UI/agent 生成策略草稿，同时不会把模板本身混入启用策略目录。

按具体策略预检数据源字段覆盖：

```bash
alphasift doctor data-sources --strategy low_volatility_quality --no-live --explain
alphasift doctor data-sources --all-strategies --no-live --explain
```

单策略模式会列出该策略依赖的 snapshot 字段和 daily 特征字段；全策略模式会输出策略覆盖矩阵，方便 UI/API 或 agent 判断哪些策略依赖日 K、哪些字段是数据源稳定性的关键路径。去掉 `--no-live` 后会发起真实取数 smoke test，并在字段缺失、缓存过期或数据源降级时输出 `snapshot_missing`、`daily_missing`、`source_errors` 和修复建议。

JSON 输出同时包含原始 `source_health` counters、聚合后的 `health_summary` 和 live snapshot 的 `quality_summary`。`health_summary` 会把 source 分成 `healthy_sources`、`failing_sources`、`disabled_sources` 和 `never_seen_sources`，用于界面展示数据源健康度、熔断状态和最近错误；`snapshot.quality_summary` 会统计重复代码、字段缺失率、非法数字和价格/成交额/市值非正等异常，避免数据源虽然返回行数但字段质量不可用。

## 常用场景

使用 LLM 横向排序：

```bash
alphasift screen balanced_alpha
```

复用其他项目的 LiteLLM 配置文件：

```bash
alphasift --env-file /home/ubuntu/daily_ai_assistant/.env screen balanced_alpha
```

带市场、主题或新闻背景的 LLM 排序：

```bash
alphasift screen balanced_alpha --context "今日券商板块放量，低估值金融获得资金回流"
```

注入按候选代码对齐的新闻、公告、资金流或研究摘要：

```bash
alphasift screen balanced_alpha --candidate-context-file candidate_context.csv
```

默认运行本地 L3 scorecard 后置评分器：

```bash
alphasift screen balanced_alpha --explain
```

追加 DSA 作为可选 L3 后置分析器之一：

```bash
alphasift screen dual_low --post-analyzer dsa
```

显式关闭 L3 后置评分或分析：

```bash
alphasift screen dual_low --no-post-analysis
```

项目和策略自检：

```bash
alphasift audit
alphasift audit --json
```

刷新行业、概念、板块热度映射缓存：

```bash
alphasift industry-cache --output data/industry_map.csv --explain
alphasift screen balanced_alpha --industry-map-file data/industry_map.csv
```

批量评估最近保存的运行：

```bash
alphasift evaluate-batch --limit 20 --explain
alphasift evaluate-batch --limit 20 --with-price-path --failure-samples 10 --json
```

批量评估会输出 `failure_review`，把负收益、缺报价、失败突破、严重回撤等样本按策略、LLM 催化/风险、后置分析标签、合并事件信号、风险 flag、形态和失败原因聚合，并给出下一步调参或数据检查建议。也会输出 `event_signal_review`，按 `tag:`、`catalyst:`、`risk:`、`post:` 事件信号统计胜率和收益，给出 `prefer` / `avoid` / `watch` 动作建议。

为保存的运行生成复盘报告：

```bash
alphasift runs --json
alphasift runs --strategy low_volatility_quality --json
alphasift report <run_id> --output data/reports/<run_id>.md
alphasift report <run_id> --json --output data/reports/<run_id>.json
```

`runs --json` 会输出轻量运行索引，包含策略版本、类别、数据源、LLM/日 K 状态、降级计数和建议报告路径。默认报告是 Markdown，适合直接进入人工复盘、通知或日报；`report --json` 输出稳定的 `RunReport` payload，给 Web UI、agent 或外部服务消费。加 `--evaluate` 会在报告中附带最新 T+N 评估摘要。

评估时额外抓取日 K 路径，输出最大回撤和最大浮盈：

```bash
alphasift evaluate <run_id> --with-price-path --explain
```

## Python 调用

```python
from alphasift import evaluate_saved_run, evaluate_saved_runs, screen

result = screen("dual_low", use_llm=False)
for p in result.picks:
    print(f"{p.rank}. {p.code} {p.name} score={p.final_score:.1f}")
```

## 保存与评估

`alphasift screen --save-run` 会保存策略版本、数据源、降级记录、候选、分数、风险字段、后置分析结果和保存时价格。后续可用：

```bash
alphasift evaluate <run_id> --explain
alphasift evaluate-batch --limit 20 --explain
alphasift runs --strategy dual_low --json
```

评估会用保存时价格与评估时最新快照价格计算 T+N 收益、胜率、缺失报价、交易成本扣减、等权组合摘要和形态后验标签。启用 `--with-price-path` 后，会额外估算最大回撤和最大浮盈。
`evaluate-batch` / `evaluate-strategies` 还会输出 `failure_review` 和 `event_signal_review`，用于定位反复失效的策略、事件信号、风险 flag、形态状态和数据问题，并沉淀可偏好/规避的事件标签。`event_signal_review.strategy_patch_suggestions` 会把策略级事件胜率转换成可审阅的 `screening.event_profile` YAML 片段，方便后续把稳定的 prefer/avoid 结论落回策略。

## 自定义策略

在 `strategies/` 目录添加 YAML 文件即可，文件名就是策略标识。可用 `alphasift strategies --templates --explain` 查看起步模板。完整写法见 [strategy-guide.md](strategy-guide.md)，内置策略说明见 [../strategies/README.md](../strategies/README.md)。
