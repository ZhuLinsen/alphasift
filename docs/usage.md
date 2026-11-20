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

`overview` 会把策略分组、策略筛选 facets、策略卡片、策略推荐、数据源健康、数据新鲜度/缓存状态、策略字段覆盖、数据源历史、策略表现历史、最近运行和 next actions 放到同一份 payload，适合 Web UI、通知助手或 agent 首屏使用：

```bash
alphasift overview --explain
alphasift overview --risk-profile aggressive --data-requirement daily_k --match-limit 2 --json
alphasift serve --host 127.0.0.1 --port 8765
```

默认不会发起网络请求，只读取当前进程的 source-health 和本地 run 索引；需要真实数据源 smoke check 时加 `--live-data-check`。

`alphasift serve` 会启动只读本地 JSON API，方便 UI、agent 或外部编排层直接消费稳定 payload。默认监听 `127.0.0.1:8765`，可用端点包括 `/health`、`/result-schema`、`/overview`、`/strategies`、`/strategy?name=<strategy_name>`、`/strategy-compare?base=<base>&target=<target>`、`/strategy-facets`、`/strategy-cards`、`/strategy-readiness`、`/strategy-run-summary`、`/data-source-history`、`/strategy-performance`、`/strategy-templates`、`/strategy-template?name=<template_name>`、`/runs`、`/report?run=<run_id>` 和 `/doctor/data-sources`。HTTP API 默认也不做 live 数据源检查；需要时给 `/overview?live=true`、`/strategy-cards?live=true`、`/strategy-readiness?live=true` 或 `/doctor/data-sources?live=true`。

策略目录也可以输出更完整的能力描述，方便 UI、agent 或外部系统选择合适策略：

```bash
alphasift strategies --explain
alphasift strategies --json
curl "http://127.0.0.1:8765/strategy-facets"
curl "http://127.0.0.1:8765/strategy-cards?strategy=dual_low"
curl "http://127.0.0.1:8765/data-source-history?limit=50"
curl "http://127.0.0.1:8765/strategy-performance?limit=50"
```

结构化输出包含策略分类、标签、风格属性、数据依赖、是否需要日 K、必需 snapshot/daily 字段、活跃 hard filters、因子权重和 profile 覆盖项。`/strategy-facets` 会把这些属性汇总成可直接驱动筛选控件的 `value/count/strategies` 列表，并标出对应 query 参数。`/strategy-cards` 还会输出 `lanes`，把策略分成 `needs_history`、`needs_evaluation`、`performance_leaders` 和 `attention`，方便 UI 首屏直接渲染待跑、待评估、表现领先和需要关注的策略区块。

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
curl "http://127.0.0.1:8765/strategy?name=low_volatility_quality"
curl "http://127.0.0.1:8765/strategy-compare?base=dual_low&target=low_volatility_quality"
```

JSON 输出包含 `differences` 和 `summary.compatibility_notes`，适合 UI 展示参数变更、日 K 依赖变化和数据源兼容性影响。HTTP API 返回同一份对比结构，方便前端从策略详情页直接进入 diff 审核。

新增策略时可以先列出模板，再把模板 YAML 输出到 `strategies/` 下改名迭代：

```bash
alphasift strategies --templates --explain
alphasift strategies --template defensive_value_quality > strategies/my_defensive_value_quality.yaml
alphasift strategies --template momentum_breakout_daily --json
curl "http://127.0.0.1:8765/strategy-template?name=momentum_breakout_daily"
```

模板 payload 包含策略风格、数据依赖、适用说明和可直接编辑的 YAML，便于 UI/agent 生成策略草稿，同时不会把模板本身混入启用策略目录。

按具体策略预检数据源字段覆盖：

```bash
alphasift doctor data-sources --strategy low_volatility_quality --no-live --explain
alphasift doctor data-sources --all-strategies --no-live --explain
alphasift doctor data-sources --strategy dual_low --compare-snapshot-sources --explain
curl "http://127.0.0.1:8765/strategy-readiness"
```

单策略模式会列出该策略依赖的 snapshot 字段和 daily 特征字段；全策略模式会输出策略覆盖矩阵和 `strategy_readiness_summary`，方便 UI/API 或 agent 判断哪些策略已可用、哪些尚未 live 检查、哪些字段是数据源稳定性的关键路径。去掉 `--no-live` 后会发起真实取数 smoke test，并在字段缺失、缓存过期或数据源降级时输出 `snapshot_missing`、`daily_missing`、`source_errors`、`freshness_summary` 和修复建议。加 `--compare-snapshot-sources` 会逐个检查配置里的 snapshot provider，对比行数、必需字段覆盖、字段质量、失败源和代码交集，用于发现某个源虽然可用但缺少策略关键字段。

JSON 输出同时包含原始 `source_health` counters、聚合后的 `health_summary`、`freshness_summary` 和 live snapshot 的 `quality_summary`。`health_summary` 会把 source 分成 `healthy_sources`、`failing_sources`、`disabled_sources` 和 `never_seen_sources`，用于界面展示数据源健康度、熔断状态和最近错误；`snapshot.quality_summary` 会统计重复代码、字段缺失率、非法数字和价格/成交额/市值非正等异常，避免数据源虽然返回行数但字段质量不可用。

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
alphasift performance --limit 50 --explain
alphasift report <run_id> --output data/reports/<run_id>.md
alphasift report <run_id> --json --output data/reports/<run_id>.json
curl "http://127.0.0.1:8765/strategy-run-summary?limit=50"
```

`runs --json` 会输出轻量运行索引，包含策略版本、类别、数据源、LLM/日 K 状态、降级计数、少量错误/降级样例和建议报告路径。`/strategy-run-summary` 会按策略聚合这些索引，输出运行次数、最近报告、总候选数、source error/degradation 计数与样例、LLM/日 K 覆盖和最近运行卡片，不会触发 live 行情。`/data-source-history` 会按 snapshot source 聚合最近 runs，输出错误率、降级率、错误/降级样例、last-good fallback 次数、稳定性状态/分数、策略覆盖、watchlist 和 next actions，用于稳定性面板观察某个源是否反复失败以及失败原因。`performance` / `/strategy-performance` 会读取已保存的 evaluation 文件，按策略输出后验收益、胜率、表现分数、outcome、leaderboard 和 next actions，不会重新抓行情。默认报告是 Markdown，适合直接进入人工复盘、通知或日报；`report --json` 输出稳定的 `RunReport` payload，给 Web UI、agent 或外部服务消费。加 `--evaluate` 会在报告中附带最新 T+N 评估摘要。

评估时额外抓取日 K 路径，输出最大回撤和最大浮盈：

```bash
alphasift evaluate <run_id> --with-price-path --explain
```

## A 股离线日线包

```bash
alphasift pack pull
alphasift pack info --trade-date 2026-11-18
ALPHASIFT_PACK_DIR=data/pack/sample alphasift pack build --days 250 --codes-limit 30
python3 scripts/build_pack.py backfill --days 250 --trade-date 2026-11-18
python3 scripts/build_pack.py update --days 250 --trade-date 2026-11-19
```

`pull` 从 GitHub Release 拉取清单，校验 SHA-256；本地文件已与清单一致时跳过下载。`info` 输出校验后的清单和 `fresh` 字段。省略 `--trade-date` 时，按 A 股收盘时间和工作日估算预期交易日，节假日可显式指定。

默认保留 250 个交易日，数据全部来自项目现有数据源。省略 `--codes-limit` 可构建全量包。

- **回填与补缺口**：按代码在 `.backfill/` 保存断点结果并支持续传。`--source auto`（默认）在 Baostock 可连时优先用它（自带交易所昨收）；否则走批量 `yfinance`（按 100 只分批取 `auto_adjust=False, actions=True`，用 `Stock Splits` 还原不复权 OHLCV，并用 `Adj Close` 比值还原除权日昨收，北交所等无 Yahoo 代码的标的回退现有日线源）。`--source daily` 强制走新浪不复权日线加腾讯前复权日线。
- **每日增量**：`update` 优先尝试现有全市场快照源（`sina`、`efinance`、`akshare_em`），拿不到开高低和昨收时自动降级到腾讯批量行情（`qt.gtimg.cn`，含当日开高低收、昨收、成交量和成交额），只适用于最近一个已收盘交易日；仍失败时再按代码从日线补齐。
- **TickPlus（可选）**：设置 `TICKPLUS_API_KEY` 后，`update` 优先用它取当日全市场日线。

批量 `yfinance` 与新浪加腾讯路径的历史成交额均留空（每日增量进来的记录带有真实成交额）；单个代码取数失败会跳过并在下次运行重试，失败超过 5% 则中止。

`daily.npz` 保存不复权价格和交易所昨收，停牌及未上市的日期留空。Python 接口 `load_pack` 读取原始矩阵，`forward_adjust` 按昨收动态计算前复权，成交量（股）和成交额（元）保留原值。`stitch_snapshot` 仅在内存中拼接当日快照，需要代码、开高低收（收盘可用 `price`）、昨收、成交量和成交额。`sina`、`efinance`、`akshare_em` 快照自带这些字段并会自动映射，未成交的行不写入；`em_datacenter` 和 `tushare` 快照缺少这些字段，会返回明确的降级错误。

本次仅提供 A 股包、命令和接口。选股流水线接入与 Release 发布工作流在后续版本实现。

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

多窗口 T+N 基准对比（例如同时检查 T+5 / T+10 / T+20 相对于市场基准指数的超额收益）：

```bash
alphasift evaluate-strategies --market cn --window 5,10,20 --explain
alphasift evaluate-strategies --market us --window 5,10,20 --json
```

自动化公开跟踪脚本（`scripts/track_record.py`）用于批量跑完同一交易时段的全部分市场策略、执行多窗口基准评估并生成看板站点数据：

```bash
python scripts/track_record.py screen --session asia --track track
python scripts/track_record.py evaluate --markets cn,hk --track track
python scripts/track_record.py build --track track
```

## 自定义策略

在 `strategies/` 目录添加 YAML 文件即可，文件名就是策略标识。可用 `alphasift strategies --templates --explain` 查看起步模板。完整写法见 [strategy-guide.md](strategy-guide.md)，内置策略说明见 [../strategies/README.md](../strategies/README.md)。
