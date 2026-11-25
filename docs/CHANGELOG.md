# Changelog

## [Unreleased]

- **Purged Walk-Forward 时间边界严格隔离与回放联动**：
  - 按每条样本 `exit_date` 执行严格 Walk-Forward 截断，禁止未闭合前瞻窗口或同批退出前样本泄漏至 `H1` 实证标签与联合 OOS 评估。
  - 公开看板、盘后 HTML/Markdown 日报与 `alphasift-workbench` 同步暴露样本外时间边界、待验证标签标记与 `250D Purged Replay` 回放审计表。
- **MCP 能力扩展至 14 个只读工具与 4 个只读资源**：
  - 新增 `alphasift_markets` 工具与 `alphasift://markets` 资源，覆盖 7 个多市场目录配置与时区/基准指数查询；保持零交易、零外部下单边界。
- **HTTP `/serve`、CLI 与 Workbench UI 完善**：
  - HTTP 只读服务新增 `/markets`、`/patterns/replay`、`/daily-report`、`/daily-report.html` 与 `/markets-digest` 端点，并统一复用 `_json_safe(..., allow_nan=False)` 输出严格合法 RFC 8259 JSON（自动将 `NaN`/`Inf` 转为 `null`）。
  - CLI 新增 `alphasift markets` 子命令；Workbench UI 新增多市场注册表卡片与 `250D Purged Replay` 回放面板。

## v0.3.1 (2026-11-23)

- **Walk-Forward 市场情绪阶段门控与零前视审计（v0.4 研究基础）**：
  - 在 `alphasift/pattern_replay.py` 中新增 `_summarize_walk_forward_regime_audit`（严格按前半段 `H1` 选正超额/剔除逆风阶段，固定投影到后半段 `H2` 进行零前视样本外对照，杜绝“看全样本事后挑阶段”）并写入 `site/patterns.json` 与 `render_replay_markdown`。
  - `replay_patterns`、CLI（`alphasift patterns replay`）及 `scripts/replay_patterns.py` 新增 `--allowed-regimes` 与 `--exclude-regimes` 参数（支持阶段英文 key 与中文标签及输入校验）。
  - 新增 250 日（5,577 只 A 股 / 180 有效日）情绪分化实证研究报告 [`docs/pattern-regime-research.md`](pattern-regime-research.md)。
- **T+5 实证里程碑解锁与 LLM 鲁棒性加固**：
  - 公开跟踪站 `2026-11-23` 正式解锁 `T+5 (n=20)`：`momentum_quality`（趋势质量）`+2.86%` 净超额 / `85%` 胜率领跑规则赛道。
  - 默认 `LLM_MAX_TOKENS` 上调至 `4096`（上限 `8192`，不自动扩写），完善 OpenAI-compatible 兼容客户端与多策略去重鲁棒性，同步刷新 `2026-11-23` 看板与盘后日报可视化素材。

## v0.3.0 (2026-11-22)

- **Issue #34 P1–P7 完整闭环与离线基准**：
  - `evaluate-strategies --window 5,10,20` 多窗口评估与按窗口复盘、saved run 与 `EvaluationResult` 日线质量统计（`daily_source_counts`、`daily_quality_flag_counts` 及 `data_quality_review` 洁净 vs 降级样本相关性对比提示）、`hard_filter_waterfall(include_quantiles=True)` 阈值分位诊断、`explain_topic_alignment()` 题材归因、`summarize_portfolio_exposure()` 主题暴露与替换候选、`SCREEN_RESULT_SCHEMA` 契约夹具与回归测试，以及可复现离线性能基准脚本 `scripts/benchmark_smoke.py`。
- **生态接入、打包安全与发布工作流**：
  - 新增零依赖原生 STDIO JSON-RPC 2.0 MCP 服务器（`alphasift mcp`，10 工具 + 2 资源）、离线安全本地交互式 Web Workbench（`alphasift serve` → `/ui`，`script-src 'sha256-...'` CSP + `Accept` 内容协商）、非 root Dockerfile（`UID 10001`）与 Docker Compose、`.github/workflows/publish.yml` 手动 PyPI Trusted Publishing 工作流、PEP 639 构建元数据修复与 Quant Trio 生态文档。
- **PR #54 / #56 精选融合（`0.3.0`，零 `litellm` 重依赖）**：
  - 移除 `litellm` SDK 改用轻量 `requests` OpenAI 兼容客户端（`alphasift/llm_client.py`），支持 `LLM_CHANNELS` / `GEMINI_API_KEYS` 多通道及 Origin 级密钥隔离；融合 `factor_rank_blend` 池内分位融合与美股 `us_momentum_quality` `hard_cap`，同时完整保留 CN 10 策略 `max_same_bucket: 1` 正交分散与 250 日实证基准。

- **1 行极简统一推送、Fork 防护守卫与 AI 情报排雷激活**：
  - `alphasift/notify.py` 与 `alphasift/config.py` 新增 1 行统一 `NOTIFY_URLS` 自动协议嗅探（同时保留分渠道变量），原生零额外依赖支持 **12 种通道**（企微、飞书、钉钉、PushPlus、Server酱/³、Bark、SMTP 邮件、Telegram、Discord、Slack、ntfy、自定义 Webhook）及可选 `apprise` 90+ 通道兜底；简化顶栏界面移除 RSS 按钮（保留 `<link>` 与页脚低存在感 `site/feed.xml`）。
  - `.github/workflows/track-record.yml` 落地 Fork 防护方案 A：公开网站构建、`track-record` 分支提交与 GitHub Pages 部署默认仅在上游仓库生效，Fork 仓库需显式设置 Repo Variable `ALPHASIFT_ENABLE_PAGES=true` 才部署网站。
  - `alphasift/ranker.py` 强化 AI 排雷降权准则（未消化重大利空硬压 `<= 35` 分、禁止名气偏见）；`scripts/track_record.py` 对 CN 复用单次加载的 `DailyPack` 并在 AI 赛道默认开启 Top 12 候选公告/新闻/资金流上下文收集；`alphasift/evaluate.py` 修复 `pd.to_datetime(..., format="mixed")` 消除测试告警。

- **Web 多语言国际化（`zh`/`en`/`ja`）、6 通道推送 + Atom RSS 与旗舰文档重构**：
  - `scripts/track_record_page.html` 与 `alphasift/daily_report_html.py` 全面接入中/英/日三语切换（`?lang=zh|en|ja` + `localStorage` 持久化 + 浏览器语言检测），覆盖导航、KPI、策略/形态/市场阶段标签、排行榜、图表提示、历史回看及打印版日报。
  - `alphasift/notify.py`、`alphasift/config.py` 与 `track-record.yml` 新增 **钉钉（HMAC-SHA256 签名）**、**Discord（Embed 卡片）** 与 **自定义 Webhook（结构化 JSON +可选 Bearer 鉴权）**，形成 6 通道幂等推送矩阵；新增 `alphasift notify status` / `alphasift notify test` CLI。
  - `scripts/track_record.py` 在 `build_site` 中零依赖生成公开 **Atom 1.0 RSS 订阅源**（`site/feed.xml`），并在看板导航与页脚提供一键订阅入口。
  - 新增深/浅双主题矢量 Hero Banner（`docs/assets/banner-{dark,light}.svg`）与 2× 高清多语言截图，重构 `README.md`、`README.zh-CN.md`、`README.ja.md` 并补全 `.env.example`、`docs/configuration.md`、`docs/deployment.md`、`SKILL.md`。

- **模型默认升级、策略正交化、形态毕业与私有化 CI**：
  - `alphasift/config.py` 默认主模型升级为 `gemini/gemini-3.8-flash`，未显式覆盖 `LITELLM_FALLBACK_MODELS` 时自动挂载 `gemini/gemini-4-hydrogen` 备选链路。
  - 重构 10 组 A 股内置策略（统一 8 行业硬上限 `mode: hard_cap` + `max_same_bucket: 1`），拉平超大盘红利（`blue_chip_income`）、中小盘双低（`dual_low`）、中盘 GARP 成长（`quality_value`）、中期多头趋势（`momentum_quality`）与均衡多因子（`balanced_alpha`）的风格正交性，大幅降低同质重合与银行单板块集中。
  - 校准 `ma20_shrink_pullback`（v2.0）并新增 `steady_trend_breakout`（v1.0）：经本地 250 日 `next_open` + 沪深 300 基准回放检验均为样本 ≥200 且 T+5/T+10 超额为正，正式毕业为首批 2 个 `active` 形态（其余 5 个经典形态保留 `experimental`）。
  - 看板与独立 HTML 日报重构为 Obsidian Dark / Editorial Paper Light 双主题终端 UI，修复 `track-record.yml` 跳过 `pack` 时的 Pages `deploy` 条件，全面切换 Actions 缓存私有日线包并升级至 Node 24 原生官方 Actions 版本（`checkout@v7`、`setup-python@v7`、`cache@v6`、`upload-pages-artifact@v5`、`deploy-pages@v5`）。

- **成交与历史前复权口径修复**：
  - `pack_features.compute_pack_daily_features` 改在计算前先按 `trade_date` 截断矩阵再 `forward_adjust`，消除未来除权改写历史均线的偷价问题；`pipeline._attach_pack_daily_features` 当快照日期早于包尾日时传入目标日截断对齐。
  - `alphasift/evaluate.py` 与 `pack.pack_price_paths(..., include_raw=True)` 对 A 股一字涨跌停判定优先使用未复权 `raw_open / raw_previous_close / raw_high / raw_low` 原始行情；公开战绩 `scripts/track_record.py evaluate --pack-dir` 默认 `entry_mode=auto`，在 `ALPHASIFT_NEXT_OPEN_SWITCH_DATE`（默认 `2026-11-21`）之前保留历史 `close` 口径并将不可成交标为 `未评估（untradable_share_pct=null）`，切换日起显式接入 `next_open` 与一字涨停过滤。
  - `em_datacenter` 快照新增返回 `OPEN_PRICE / HIGH_PRICE / LOW_PRICE / PRE_CLOSE_PRICE / VOLUME / MAX_TRADE_DATE`，改用 `FREE_CAP` 映射流通市值并纳入北京证券交易所标的；默认快照数据源优先级调整为 `em_datacenter` 优先（减少海外环境下前置限流报错）。
- **AI 对比口径与形态 250 日回放统计增强**：
  - `track_comparison` 改为同一策略严格按**共同信号日**配对，输出 `paired_days`、`ai_missing_rate_pct`、`avg_pick_overlap_pct`、AI 独选与 AI 剔除平均超额（`paired_days < 10` 时隐藏差值），并沉淀个股级正反案例 `ai_case_studies`；`trend`（规则）与 `trend_ai`（AI）拆线分离，看板支持单独或叠加对比。
  - `pattern_replay` 修复基准匹配门槛，毕业门限（`>= 200`）改按 `excess_scored` 统计，增加全市场与流动性 >= 8000 万基准对比（`universe_baseline`）、按信号日聚合均值计算的 `daily_t_stat` 与前后半段（H1/H2）分布校验，以及腾讯指数优先、新浪指数重试兜底。
- **跨策略共识简报、独立 HTML 研报、并发锁推送与串行 Workflow**：
  - 新增 `alphasift/daily_brief.py`（跨策略共识 `cross_strategy_synthesis` 与支持 LLM / 规则双模式回退的 `generate_ai_daily_brief`）与 `alphasift/daily_report_html.py`（零依赖可打印 `daily_report.html`）；CLI 新增 `--output-html` / `--ai-brief`，HTTP 服务新增 `/daily-report.html`。
  - CLI `alphasift daily-report` 与 HTTP `/daily-report` 统一通过 `load_daily_report_runs()` 加载同交易日规则/AI 策略与 `ai_highlights`，新增 `expected_trade_date / pack_is_stale / stale_reason / detail_url`；IM 卡片置顶公告排雷预警并预留截断预算，将策略股票清单与实验形态清单下沉网页看板。
  - `alphasift/notify.py` 新增进程锁 + `fcntl.flock` 文件锁与 `pending -> sent / failed` 两阶段幂等状态机，并发防重发、失败下次自动重试，检测到旧包（`pack_is_stale`）时默认跳过未强制推送。
  - `scripts/track_record_page.html` 改版为高信息密度专业投研看板：首屏四宫格展示 A 股情绪宽度/7 档涨跌分布与中位数、涨跌停/封板率、连板高度梯队、公告预警/AI 要点；AI 配对归因与分离走势紧随其后；成绩单、形态雷达、250 日回放切片与历史明细分层折叠。
  - `data-pack.yml` 补充 `workflow_call` 接口（`type: string`），`track-record.yml` 亚洲盘改为 `pack -> record` 串行编排，并将 `daily-report` 前置到 `build` 之前产出 `site/report.json`。

- T+N 评估新增 `--entry-mode next_open`，按首根日 K 开盘价入场，基准匹配实际入场和退出日期。A 股单列开盘一字涨停的不可成交占比，退出遇一字跌停时顺延。默认模式和公开战绩继续使用收盘入场口径。
- A 股全市场向量化选股接入（P1-1）：新增 `alphasift/pack_features.py` 对 250 日数据包矩阵向量化计算与 `daily.py` 同口径的 23 项日线指标；`screen()` 在 A 股且存在新鲜数据包时自动对全部快照初筛候选计算日 K 特征（不再受 Top-100 截断限制），数据包缺失、损坏或过期无法拼接时自动回退原有逐只补日线路径；新增 `ALPHASIFT_DAILY_PACK_ENABLED` 配置与 `markets.py` `supports_daily_pack` 能力位，非 A 股市场零改动
- A 股离线日线包：新增支持断点续传的回填（Baostock，Baostock 不可连时自动走批量 `yfinance`，也可用 `--source daily` 走新浪加腾讯）、基于现有快照源与腾讯批量行情（`qt.gtimg.cn`）的每日增量、可选的 TickPlus 增量（`TICKPLUS_API_KEY`）、SHA-256 校验、动态前复权和快照拼接接口，提供 `alphasift pack pull/info/build` 及构建脚本。Release 自动发布工作流将在后续版本实现。
- 韩国估值：覆盖率改为统计真正拿到 PE 或 PB 的股票数（此前只统计请求成功数，接口格式变化导致全部为 N/A 时会被当成完整，覆盖掉有估值的缓存）；快照预算已用完时跳过 Naver，不再额外多跑 5 秒；复用 HTTP 连接，实测韩国快照约 14 秒降到 6 秒
- T+N 评估：历史数据里没有入场交易日收盘价时标记为 `no_entry_close`，不再退回用保存的选股价（盘中、未复权）去比复权收盘价，否则拆股后会算出虚假的 −50%
- T+N 基准对比：只有部分选股有基准数据时，基准和超额只覆盖这些选股；新增 `benchmark_pick_count` 和同一批选股的平均收益 `average_matched_return_pct`（两者相减恒等于超额），CLI 在覆盖不全时显示 `bench_n=k/n matched_ret=...`
- T+N 评估不再依赖实时快照：快照拉取失败时照常用历史收盘价计算，只是不显示当前价，原因记在 `source_errors`
- Yahoo 快照：财报币种和交易币种不同时（部分 ADR），不再用每股收益、每股净资产自行推算 PE/PB，避免美元股价除以日元每股收益得到极低 PE、在低估值策略里排第一；拉取超过时间预算时保留已拉到的数据并标记为不完整（不覆盖完整缓存），不再丢弃后改用其他股票池
- README：其他六个市场标为测试阶段，写明股票池范围（市值下限、按板块查询、最多 4000 行、美股含 ADR）
- **印度股票不再重复**：同一家公司在 NSE（`.NS`）和 BSE（`.BO`）各有一行，此前 1236 行快照实际只有约 630 家公司，`global_value --market in` 可能同时选中同一家公司的两个上市代码。现在同一代码（去掉 .NS / .BO 后缀后相同）只保留日均成交额更高的那个（通常是 NSE）；这是按代码去重，不是按公司身份识别。实测快照 1236 → 640 行，过滤后 176 → 86 只
- 日 K 策略（`shrink_pullback`、`volume_breakout`、`low_volatility_quality` 等）选股时复用收盘后已拉取的日 K：收盘 30 分钟后到下一次开盘前，日 K 不会再变，同一台机器上后续运行直接读缓存（`daily_history/`）；盘中不读也不写缓存（是否在盘中按每只股票取数时重新判断，跨过开盘的批次也会切换）。实测 `shrink_pullback` 第二次运行从 279 秒降到 13 秒，结果相同。所有日 K 源都失败时（盘中也一样）会退回最近的缓存并标记 `stale_cache`，而不是丢掉该候选
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
