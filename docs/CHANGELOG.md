# Changelog

## Unreleased

- 多市场支持：新增市场注册表 `alphasift/markets.py`，`--market` 支持 `cn / us / hk / jp / kr / tw / in`。非 A 股通过 Yahoo 筛选器按 11 个板块拉取全市场快照（带板块、PE/PB、市值、币种），海外服务器和 CI 上可用；美股默认从 S&P 500 + 逐只请求改为筛选器，`ALPHASIFT_US_TICKERS` 仍走原逐只路径
- 新增 `global_value` 多市场低估值策略（美/港/日/台/印），不使用与币种相关的绝对金额阈值，按板块硬性分散
- 修复非 A 股代码被截断：`005930.KS` 不再被归一化为 `005930`，日 K 模块不再把 `0700.HK` 变成 `000700`
- `exclude_st` 只作用于含中文的名称，美股 COST / STERIS 等不再被误判为 ST；候选级新闻/公告/资金流上下文仅在 A 股启用
- 各市场的 last-good 快照缓存分开存放（`snapshot.<market>.last_good.json`）
- 美股快照只保留 NYSE / Nasdaq / NYSE American / Arca / Cboe 上市股票，排除 OTC 粉单（此前 4000 行里有 2141 行是 BMWKY 这类粉单）；行数上限按板块分别计算后再全局截断，不会因前面板块占满而漏掉科技、公用事业
- 部分板块拉取失败时仍使用实时数据，但不再覆盖完整的 last-good 缓存
- 非 A 股评估：跌出股票池市值下限的历史选股会单独按代码取价，不再被记为 missing 从收益统计中漏掉；`evaluate-batch --market` 不区分大小写
- 非 A 股时跳过 A 股板块提供方（akshare / eastmoney），行业映射和 LLM 候选上下文不再把 `0700.HK` 当成 `000700`、把 `AAPL` 丢掉
- `ALPHASIFT_US_TICKERS` 现在确实只用指定列表，不会在能访问 Wikipedia 时被 S&P 500 覆盖；ST 过滤的拒绝统计和瀑布图与实际过滤一致
- `sina`/`em_datacenter` 分页拉取现在受 `ALPHASIFT_SNAPSHOT_CALL_TIMEOUT_SEC`（默认 60 秒）总时长约束，每页读超时随剩余预算收缩、连接超时 5 秒；海外服务器首次运行从约 4 分钟降到约 70 秒
- 新增 `portfolio_profile.mode: hard_cap`：Top N 优先选不超过 `max_same_bucket` 的同行业股票，符合上限的候选不够时才用超出的补足，没有行业标签的股票不受限制（不是绝对上限）；`dual_low` 升级到 1.3 并启用硬上限，新增"基建"桶。实测前 5 名从 3 只银行 + 2 只建筑变为 2 只银行 + 2 只基建 + 1 只航运
- 修复 `--no-llm` 等场景下组合分散度控制静默失效：`em_datacenter` 快照现在带回行业字段；其他数据源缺行业时自动用东财行业映射补全（`INDUSTRY_AUTO_BACKFILL`，缓存 7 天）；完全没有行业标签时会在 `degradation` 中明确提示。东财行业补全整体受 `ALPHASIFT_SNAPSHOT_CALL_TIMEOUT_SEC`（默认 60 秒）约束，超时就跳过，不会拖住选股。实测 `dual_low` 前 5 名从 5 只银行变为 3 只银行 + 2 只建筑股
- 快照数据源成败会跨运行保存到 `source_health.json`，最近 6 小时内失败过的源自动排到后面；海外服务器上 `dual_low --no-llm` 从约 4 分钟降到约 10 秒
- `em_datacenter` 每页从 500 行提高到 2000 行，全市场 3 次请求即可取完
- 支持 DSA 通过 `context["dsa"]` 注入候选 provider，AlphaSift 会在 L1 初筛后、LLM 重排前补充 DSA 行情、基本面和新闻上下文
- `dsa_adapter.screen()` 现在会透传 DSA context，并在候选结果中保留 `dsa_context`、`dsa_news` 和 `dsa_analysis_summary`
- LLM ranking prompt 会读取候选上的 DSA provider context，便于排序阶段利用 DSA 已有数据能力

## 2026-04-12

- 明确说明 `DSA` 指外部项目 `daily_stock_analysis`，补充两者的职责边界与调用关系
- 更新 README、Skill 文档和设计说明，说明 DSA 只在最终入围候选上调用
- 修正文档中过期描述：移除对 `shrink_pullback` 可直接运行和“未实现 L3 deep_analysis”的错误说法
- 补充当前 DSA overlay 行为说明：结构化结果会在最后阶段影响 `final_score`、风险判断和最终排名
