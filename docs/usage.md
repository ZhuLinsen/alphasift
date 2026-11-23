# 使用指南

这份文档放 README 之外的日常用法：安装、CLI 命令、Python 调用、上下文注入和评估闭环。

## 安装

```bash
# 方式 A：从 PyPI 安装（推荐，也支持 uvx alphasift）
pip install alphasift

# 方式 B：源码克隆安装（或直接下载 v0.3.1 Release Wheel）
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
alphasift serve --host 127.0.0.1 --port 8765   # 访问 http://127.0.0.1:8765/ui 交互式 Web 工作台 + JSON API
alphasift mcp                                   # 启动零依赖 STDIO MCP Server（详见 docs/ecosystem.md）
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

复用其他项目的 `.env` 模型与渠道配置（如 `daily_stock_analysis`）：

```bash
alphasift --env-file /path/to/daily_stock_analysis/.env screen balanced_alpha
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

> 离线日线包仅供研究者**在本地或 GitHub Actions 私有缓存（`actions/cache`）中自建自用**，主仓库**不提供公开下载或二次分发**。

```bash
alphasift pack build --days 250
alphasift pack info --trade-date 2026-11-18
ALPHASIFT_PACK_DIR=data/pack/sample alphasift pack build --days 250 --codes-limit 30
python3 scripts/build_pack.py backfill --days 250 --trade-date 2026-11-18
python3 scripts/build_pack.py update --days 250 --trade-date 2026-11-19
```

`info` 输出校验后的清单和 `fresh` 字段。省略 `--trade-date` 时，按 A 股收盘时间和工作日估算预期交易日，节假日可显式指定。只有当用户显式设置 `ALPHASIFT_PACK_REPO` 指向自己的私有仓库（配合 `GITHUB_TOKEN`）时，`alphasift pack pull` 才会从对应仓库拉取并校验 SHA-256；默认不指向任何公开仓库。

默认保留 250 个交易日，数据全部来自项目现有数据源。省略 `--codes-limit` 可构建全量包。

- **回填与补缺口**：按代码在 `.backfill/` 保存断点结果并支持续传。`--source auto`（默认）在 Baostock 可连时优先用它（自带交易所昨收）；否则走批量 `yfinance`（按 100 只分批取 `auto_adjust=False, actions=True`，用 `Stock Splits` 还原不复权 OHLCV，并用 `Adj Close` 比值还原除权日昨收，北交所等无 Yahoo 代码的标的回退现有日线源）。`--source daily` 强制走新浪不复权日线加腾讯前复权日线。
- **每日增量**：`update` 优先尝试现有全市场快照源（`sina`、`efinance`、`akshare_em`），拿不到开高低和昨收时自动降级到腾讯批量行情（`qt.gtimg.cn`，含当日开高低收、昨收、成交量和成交额），只适用于最近一个已收盘交易日；仍失败时再按代码从日线补齐。
- **TickPlus（可选）**：设置 `TICKPLUS_API_KEY` 后，`update` 优先用它取当日全市场日线。

批量 `yfinance` 与新浪加腾讯路径的历史成交额均留空（每日增量进来的记录带有真实成交额）；单个代码取数失败会跳过并在下次运行重试，失败超过 5% 则中止。

`daily.npz` 保存不复权价格和交易所昨收，停牌及未上市的日期留空。Python 接口 `load_pack` 读取原始矩阵，`forward_adjust` 按昨收动态计算前复权（**历史特征与形态回放先按目标日期截断再前复权，避免未来除权回改历史均值**），成交量（股）和成交额（元）保留原值。`stitch_snapshot` 仅在内存中拼接当日快照，需要代码、开高低收（收盘可用 `price`）、昨收、成交量和成交额。`sina`、`efinance`、`akshare_em` 与 `em_datacenter`（含北交所）快照均带完整 OHLCV 与 `MAX_TRADE_DATE` 日期校验并会自动映射，未成交的行不写入；`tushare` 快照缺少部分字段，会返回明确的降级错误。

当本地存在有效且新鲜的 A 股数据包时（默认 `ALPHASIFT_DAILY_PACK_ENABLED=1`），`screen` 运行 `volume_breakout`、`shrink_pullback` 等需要日 K 的 A 股策略会自动使用 `alphasift/pack_features.py` 向量化计算全部初筛候选的日线指标，不再受默认 Top-100 补日线截断限制；若包缺失、损坏或过期且无法从快照拼接，则自动回退现有逐只补日线路径并记录 `degradation`。其他 6 个市场不触发数据包路径。

## A 股盘面统计与无状态形态引擎

两项能力均**仅适用于 A 股数据包（其他 6 个市场不动）**：

```bash
# 查看盘面宽度、涨跌停/封板率、连板梯队与客观阶段标签（仅供报告和切片，不调整策略权重）
alphasift market-stats --explain
alphasift market-stats --days 10 --json

# 列出与扫描无状态形态；默认仅扫描通过 250 日门槛的 active 形态，加 --include-experimental 包含观察期形态
alphasift patterns list --include-experimental
alphasift patterns scan --include-experimental --explain

# 250 日 next_open 回放、形态 × 阶段切片、上方 10% 筹码切片及毕业判定（样本 >= 200 且 T+5 超额 > 0）
alphasift patterns replay --output-json local/pattern_replay.json --output-md local/pattern_replay.md
```

短线接力谱系仅提供盘面连板梯队与昨涨停溢价统计，不出个股买卖信号；`overhead_supply_10pct` 仅作特征输出与切片观测，不做硬筛一票否决。

## 结构化日报、IM 推送与就绪诊断

```bash
# 打包与推送就绪自检（不会打印任何 Webhook 或 Token 密钥）
alphasift doctor radar --explain

# 生成结构化 report.json、<1200 字 IM 卡片与可打印独立 HTML 研报（公告排雷预警置顶，完整候选/AI简评详见 HTML 与看板）
alphasift daily-report --expected-trade-date 2026-11-20 --allow-stale-pack --ai-brief auto --output-json local/report.json --output-card local/card.md --output-html local/daily_report.html --push --explain
```

- **数据源稳定性**：默认 A 股快照优先级调整为 `em_datacenter -> sina -> efinance -> akshare_em`（`_fetch_em_datacenter` 改用 `FREE_CAP` 映射流通市值），减少海外环境下多源超时触发的降级。
- **跨策略共识、AI 综述简报与独立 HTML 研报**：`alphasift/daily_brief.py` 计算多策略共识（`>= 2` 策略命中）、行业集中度与策略×形态共振，并在配置 LLM Key 时由 `--ai-brief auto` 生成结构化 `ai_brief`（无 Key 或调用异常时自动回退规则合成）；`alphasift/daily_report_html.py` 与 HTTP `GET /daily-report.html` 提供零外部依赖、支持打印与 PDF 导出的独立投研日报。
- **IM 渠道环境变量**：支持企业微信（`WECOM_WEBHOOK_URL`）、飞书机器人（`FEISHU_WEBHOOK_URL`，可选加签密钥 `FEISHU_WEBHOOK_SECRET`）与 Telegram（`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`），以及卡片详情跳转链接 `ALPHASIFT_DASHBOARD_URL`（或 `--detail-url`）。同一交易日同一渠道加进程/文件锁并发去重，失败自动落盘并允许下次自动重试；若 `--expected-trade-date` 检出旧包（`pack_is_stale=True`），默认跳过未强制推送（`skipped_stale_pack`）。未配置任何渠道时静默跳过。
- **CLI 与 HTTP 同源输入**：`alphasift daily-report` 与 HTTP `/daily-report` 共用 `load_daily_report_runs()`（按沪深交易时段归属日加载规则榜与 AI 榜并生成 `ai_highlights`）。
- **公告排雷**：默认对重点候选做近期公告负面关键词抽检，**卡片内优先预留公告预警篇幅并置于策略与形态概览之前**；离线或接口异常时降级写入 `degradation`，不影响日报生成。
- **公开战绩双赛道（`scripts/track_record.py`）**：保留原有规则榜（`track=rules`）；当环境配置了 LLM Key 时，会在规则 pass 完成后自动追加 A 股 `AI` 赛道（`track=ai`，默认 `--ai-track auto`，LLM 超时/降级不影响规则榜落盘，无 Key 的 fork 自动仅跑规则榜）。**规则 vs AI 严格按同一策略共同信号日配对计算差值（配对天数 < 10 隐藏差值），单列 AI 缺失率与重合度。** 若有本地日线包，会一并记录盘面 7 桶收益分布、中位数收益与形态雷达快照（含 20 日迷你 K 线）到 `site/patterns.json`。Fork 启用、GitHub Pages 与 Cloudflare Pages 镜像步骤见 [deployment.md](deployment.md)。

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

未指定 `--window` 时，评估用保存时价格与最新快照价格计算收益、胜率、缺失报价、交易成本扣减、等权组合摘要和形态后验标签。启用 `--with-price-path` 后，会额外估算最大回撤和最大浮盈。
`evaluate-batch` / `evaluate-strategies` 还会输出 `failure_review` 和 `event_signal_review`，用于定位反复失效的策略、事件信号、风险 flag、形态状态和数据问题，并沉淀可偏好/规避的事件标签。`event_signal_review.strategy_patch_suggestions` 会把策略级事件胜率转换成可审阅的 `screening.event_profile` YAML 片段，方便后续把稳定的 prefer/avoid 结论落回策略。

多窗口 T+N 基准对比（例如同时检查 T+5 / T+10 / T+20 相对于市场基准指数的超额收益）：

```bash
alphasift evaluate-strategies --market cn --window 5,10,20 --explain
alphasift evaluate-strategies --market us --window 5,10,20 --entry-mode next_open --json
alphasift evaluate <run_id> --window 5 --entry-mode next_open --explain
```

`--entry-mode close` 是默认的收盘入场口径。`--entry-mode next_open` 适用于收盘后才拿到报告的场景，从入场截止日后首根可用日 K 的开盘价算起。首根日 K 计为 T+1，包含其最高和最低价，第 N 根日 K 的收盘价为计划退出价。停牌或缺日 K 时等待个股首个可用交易日入场，基准有对应的更早交易日时会标记 `entry_delayed_missing_bar`。个股缺开盘价时显示 `no_entry_open`。基准采用个股实际入场日的开盘价和退出日的收盘价，缺价时仅展示个股收益，并提示原因。

A 股开盘一字涨停的候选记为 `untradable_limit_up`，摘要单列数量和占候选总数的百分比。计划退出日一字跌停时，标记 `exit_delayed_limit_down` 并顺延到首个可退出日的收盘。未能退出或日 K 数量不足的窗口显示 `pending`。不可成交和未完成样本均不计入平均收益和胜率。

自动化公开跟踪脚本（`scripts/track_record.py`）支持分段成交口径（默认 `--entry-mode auto`，由 `ALPHASIFT_NEXT_OPEN_SWITCH_DATE` 控制，默认 `2026-11-21`，可用 `--next-open-from` 覆盖）：切换日之前的历史运行保留 `close` 口径并将不可成交比例标记为 `未评估`（`untradable_share_pct = null`）；切换日起自动按 `--entry-mode next_open` 结合 DailyPack 未复权原始价格判定 A 股一字涨跌停。脚本批量跑完同一交易时段的全部分市场策略、执行多窗口基准评估并生成看板站点数据：

```bash
python scripts/track_record.py screen --session asia --track track --pack-dir "$ALPHASIFT_PACK_DIR"
python scripts/track_record.py patterns --track track --pack-dir "$ALPHASIFT_PACK_DIR" --expected-trade-date 2026-11-20 --with-replay
python scripts/track_record.py evaluate --markets cn,hk --track track --pack-dir "$ALPHASIFT_PACK_DIR"
python scripts/track_record.py build --track track
```

## 自定义策略

在 `strategies/` 目录添加 YAML 文件即可，文件名就是策略标识。可用 `alphasift strategies --templates --explain` 查看起步模板。完整写法见 [strategy-guide.md](strategy-guide.md)，内置策略说明见 [../strategies/README.md](../strategies/README.md)。
