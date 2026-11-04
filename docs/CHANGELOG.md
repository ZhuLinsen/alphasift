# Changelog

## Unreleased

- 韩国估值：覆盖率改为统计真正拿到 PE 或 PB 的股票数（此前只统计请求成功数，接口格式变化导致全部为 N/A 时会被当成完整，覆盖掉有估值的缓存）；快照预算已用完时跳过 Naver，不再额外多跑 5 秒；复用 HTTP 连接，实测韩国快照约 14 秒降到 6 秒
- T+N 评估：历史数据里没有入场交易日收盘价时标记为 `no_entry_close`，不再退回用保存的选股价（盘中、未复权）去比复权收盘价，否则拆股后会算出虚假的 −50%
- T+N 基准对比：只有部分选股有基准数据时，基准和超额只覆盖这些选股；新增 `benchmark_pick_count` 和同一批选股的平均收益 `average_matched_return_pct`（两者相减恒等于超额），CLI 在覆盖不全时显示 `bench_n=k/n matched_ret=...`
- T+N 评估不再依赖实时快照：快照拉取失败时照常用历史收盘价计算，只是不显示当前价，原因记在 `source_errors`
- Yahoo 快照：财报币种和交易币种不同时（部分 ADR），不再用每股收益、每股净资产自行推算 PE/PB，避免美元股价除以日元每股收益得到极低 PE、在低估值策略里排第一；拉取超过时间预算时保留已拉到的数据并标记为不完整（不覆盖完整缓存），不再丢弃后改用其他股票池
- README：其他六个市场标为测试阶段，写明股票池范围（市值下限、按板块查询、最多 4000 行、美股含 ADR）
- **印度股票不再重复**：同一家公司在 NSE（`.NS`）和 BSE（`.BO`）各有一行，此前 1236 行快照实际只有约 630 家公司，`global_value --market in` 可能同时选中同一家公司的两个上市代码。现在同一代码（去掉 .NS / .BO 后缀后相同）只保留日均成交额更高的那个（通常是 NSE）；这是按代码去重，不是按公司身份识别。实测快照 1236 → 640 行，过滤后 176 → 86 只
- 日 K 策略（`shrink_pullback`、`volume_breakout`、`low_volatility_quality` 等）选股时复用收盘后已拉取的日 K：收盘 30 分钟后到下一次开盘前，日 K 不会再变，同一台机器上后续运行直接读缓存（`daily_history/`）；盘中不读也不写缓存（是否在盘中按每只股票取数时重新判断，跨过开盘的批次也会切换）。实测 `shrink_pullback` 第二次运行从 279 秒降到 13 秒，结果相同。所有日 K 源都失败时（盘中也一样）会退回最近的缓存并标记 `stale_cache`，而不是丢掉该候选
- **印度股票不再重复**：同一家公司在 NSE（`.NS`）和 BSE（`.BO`）各有一行，此前 1236 行快照实际只有约 630 家公司，`global_value --market in` 可能同时选中同一家公司的两个上市代码。现在每家公司只保留日均成交额更高的那个（通常是 NSE）。实测快照 1236 → 640 行，过滤后 176 → 86 只
- 台湾优先股（`2881A.TW`、`2891C.TW` 这类 4 位数字加字母的代码）不再进入股票池
- 新增硬筛条件 `avg_amount_usd_min`：按 当前价 × 近 10 日平均成交量（缺失时用 3 个月均量）估算日均成交额，再按市场近似汇率折成美元；成交量部分不受盘中时点影响，可跨市场使用同一个流动性下限。Yahoo 快照新增 `avg_amount` / `avg_amount_usd` 两列。`global_value` 升级到 1.1，设为 100 万美元，主要剔除港股、台股、印度里成交清淡的标的
- `evaluate-strategies --window` 的失败复盘和事件信号复盘改为每个窗口分别输出（`window_reviews`），此前只反映第一个窗口；顶层的复盘与汇总来自最短窗口，并以 `review_window_days` 标明
- 运行和评估的时间戳带上时区（如 `2026-11-04T14:53:14+08:00`）：在一台机器创建、在另一台时区不同的机器或 CI 上评估时，入场交易日不再错位。旧文件中不带时区的时间仍按本机时区读取，新旧记录可以混合排序

- 韩国市场补上 PE/PB：Yahoo 不提供韩股估值，改由 Naver Finance 移动端接口逐只补全（272 只约 14 秒，PB 覆盖 271 只、PE 覆盖 223 只，亏损公司没有 PE），`global_value` 加入 kr；韩国优先股（代码末位非 0，如 005935）不再进入股票池。`ALPHASIFT_KR_VALUATION=0` 可关闭
- `doctor data-sources` 支持 `--market`（us / hk / jp / kr / tw / in）：非 A 股检查 Yahoo 筛选器快照和 yfinance 日 K（默认用该市场代表股，如 0700.HK、7203.T）；`--strategy global_value` 这类不支持 A 股的策略会自动选它的第一个市场。实测 jp 通过，kr 正确报出 PE/PB 全部缺失
- **修正 T+N 评估口径**：`evaluate-strategies --window 5,10,20` 之前每个窗口的收益都是"今天价格对比入场价"，三个窗口数值相同，窗口只影响拉取多少根 K 线。现在按入场后第 N 个交易日收盘计算收益，最大回撤和浮盈也只看这 N 根 K 线；未满 N 日的记为 `pending`，不计入平均
- **新增基准对比**：T+N 窗口同时计算所在市场基准指数（沪深 300、标普 500、恒生、日经 225、KOSPI、台湾加权、Nifty 50）同期收益，输出 `average_excess_return_pct` 和 `beat_benchmark_rate`。沪深 300 走腾讯指数 K 线（Yahoo 的 000300.SS 历史数据不完整）
- T+N 改为收盘到收盘：入场价取入场交易日收盘（与基准指数同一起点、同一复权口径），避免盘中价对比指数收盘价产生虚假超额、拆股后已完成的评估被改写；每只股票的超额收益按它自己的第 N 根 K 线日期对比基准（停牌时不错位）；只计入拉取时已收盘的 K 线（缓存的盘中 K 线不会在收盘后被当成收盘价）；未到期的选股不再计入失败复盘和事件信号；基准均值改为按选股加权，`ret - bench = excess` 恒成立；多窗口只拉一次实时快照；Yahoo 日 K 不再漏掉当天已收盘的 K 线；基准拉取失败的原因会显示在窗口摘要里
- **修正入场时点**：价格路径之前包含运行当天整根 K 线，盘中或收盘后保存的运行会把选股前的高低点算进最大浮盈和最大回撤。现在按交易所时区和开盘时间判断入场时点
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
