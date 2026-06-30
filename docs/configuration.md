# 配置参考

这份文档集中说明 `.env`、LiteLLM、数据源和 L3 后置分析器配置。最小运行不需要 LLM key，只要在命令里加 `--no-llm`。

## 最小配置

```bash
cp .env.example .env
```

不用 LLM 排序：

```bash
alphasift screen dual_low --no-llm
```

使用 LLM 排序时，填入任意一个供应商 key，并按需指定模型：

```env
GEMINI_API_KEY=...
LITELLM_MODEL=gemini/gemini-2.5-flash
```

使用 Tushare 兜底数据源时，填入：

```env
TUSHARE_TOKEN=...
```

## 环境变量

| 变量 | 必须 | 说明 | 默认值 |
|------|------|------|--------|
| `LITELLM_MODEL` | 推荐 | 主模型，兼容 daily_stock_analysis，格式 `provider/model` | `gemini/gemini-2.5-flash` |
| `LITELLM_FALLBACK_MODELS` | 否 | 备选模型，逗号分隔 | - |
| `LLM_CHANNELS` | 否 | 多渠道配置，配合 `LLM_{NAME}_*` 使用 | - |
| `LITELLM_CONFIG` | 否 | 高级 LiteLLM Router YAML 配置文件路径 | - |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` | LLM 排序时至少一种 | 供应商 API Key，兼容 daily_stock_analysis 配置 | - |
| `OPENAI_BASE_URL` / `OLLAMA_API_BASE` | 否 | OpenAI 兼容接口或 Ollama 地址 | - |
| `LLM_API_KEY` | 否 | 旧版兼容 API Key，会优先覆盖供应商 key | - |
| `LLM_MODEL` | 否 | 旧版兼容模型名；`LITELLM_MODEL` 优先 | `gemini/gemini-2.5-flash` |
| `LLM_BASE_URL` | 否 | 旧版兼容自定义 API 地址 | - |
| `LLM_CONTEXT` | 否 | 传给 LLM 的市场、新闻或主题上下文 | - |
| `LLM_TEMPERATURE` | 否 | LLM 排序温度，默认偏确定性 | `0.2` |
| `LLM_JSON_MODE` | 否 | 是否请求 JSON response_format，不支持时自动降级 | `true` |
| `LLM_SILENT` | 否 | 是否抑制 LiteLLM 调用日志，避免污染 CLI JSON 或摘要输出 | `true` |
| `LLM_RANK_WEIGHT` | 否 | LLM 排序对最终分数的权重 | `0.40` |
| `LLM_CANDIDATE_MULTIPLIER` | 否 | 送入 LLM 的候选倍数，相对 max_output | `6` |
| `LLM_MAX_CANDIDATES` | 否 | 单次最多送入 LLM 的候选数 | `30` |
| `LLM_MAX_RETRIES` | 否 | LLM 结构化输出不合格时的重试次数 | `1` |
| `LLM_MIN_COVERAGE` | 否 | LLM 输出必须覆盖候选池的最低比例 | `0.60` |
| `LLM_CONTEXT_MAX_CHARS` | 否 | 拼接后传给 LLM 的上下文最大长度 | `4000` |
| `LLM_CANDIDATE_CONTEXT_ENABLED` | 否 | 是否默认对 LLM Top K 候选抓取新闻、公告、资金流线索 | `false` |
| `LLM_CANDIDATE_CONTEXT_MAX_CANDIDATES` | 否 | 候选级上下文最多抓取前 N 只 | `8` |
| `LLM_CANDIDATE_CONTEXT_PROVIDERS` | 否 | 候选级抓取来源，逗号分隔：`news,fund_flow,announcement,quote` | `news,fund_flow,announcement,quote` |
| `LLM_CANDIDATE_CONTEXT_CACHE_ENABLED` | 否 | 是否缓存候选级抓取上下文 | `true` |
| `LLM_CANDIDATE_CONTEXT_CACHE_TTL_HOURS` | 否 | 候选上下文缓存有效小时数 | `24` |
| `INDUSTRY_MAP_FILES` | 否 | 本地 code->industry/concepts/board_heat 映射 CSV/JSON/JSONL，逗号分隔 | - |
| `INDUSTRY_PROVIDER` | 否 | 可选行业、概念、板块热度 provider，如 `akshare`；默认关闭 | `none` |
| `INDUSTRY_PROVIDER_MAX_BOARDS` | 否 | provider 模式最多反查板块数 | `80` |
| `SNAPSHOT_SOURCE_PRIORITY` | 否 | 数据源优先级，逗号分隔；不设置时若配置了 Tushare token 会优先 `tushare` | 无 token: `sina,efinance,akshare_em,em_datacenter` |
| `SNAPSHOT_FALLBACK_MAX_AGE_HOURS` | 否 | last-good 快照缓存最大可接受年龄；为空/`none` 表示不限制 | - |
| `ALPHASIFT_SOURCE_CALL_TIMEOUT_SEC` | 否 | 第三方 wrapper 数据源调用的全局等待超时；`0`/`off` 表示关闭 | - |
| `ALPHASIFT_SNAPSHOT_CALL_TIMEOUT_SEC` | 否 | 快照 wrapper 源 `efinance`/`akshare_em`/`tushare` 的调用超时 | `60` |
| `ALPHASIFT_DAILY_CALL_TIMEOUT_SEC` | 否 | 日 K wrapper 源 `akshare`/`baostock`/`tushare`/`yfinance` 的调用超时 | `20` |
| `ALPHASIFT_EASTMONEY_MIN_INTERVAL_SEC` | 否 | 东财直连 HTTP 请求最小串行间隔 | `1.0` |
| `ALPHASIFT_EASTMONEY_JITTER_SEC` | 否 | 每次东财直连请求额外加入的随机抖动 | `0.3` |
| `TUSHARE_TOKEN` / `TUSHARE_API_TOKEN` | 使用 `tushare` 时必须 | Tushare Pro token，用于最近交易日日线和 daily_basic 兜底 | - |
| `TUSHARE_TRADE_DATE` | 否 | 固定 Tushare 交易日，格式 `YYYYMMDD`，便于复现实验 | 自动取最近开市日 |
| `POST_ANALYZERS` | 否 | L3 后置分析器，设为 `none` 可关闭 | `scorecard` |
| `POST_ANALYSIS_MAX_PICKS` | 否 | DSA/HTTP 等高成本 L3 分析器最多处理前 N 只；本地 scorecard 默认处理全部输出 | `3` |
| `POST_ANALYZER_URL` | `external_http` 时必须 | 外部评分工具 HTTP 地址 | - |
| `POST_ANALYZER_TIMEOUT_SEC` | 否 | 外部评分工具超时秒数 | `120` |
| `DSA_API_URL` | `dsa` 分析器时必须 | DSA 服务地址或完整分析端点 | - |
| `DSA_REPORT_TYPE` | 否 | DSA 报告类型 | `detailed` |
| `DSA_MAX_PICKS` | 否 | 最多对前 N 只候选做深度分析 | `3` |
| `DSA_TIMEOUT_SEC` | 否 | DSA 单次请求超时秒数 | `120` |
| `DSA_FORCE_REFRESH` | 否 | 是否强制 DSA 忽略缓存 | `false` |
| `DSA_NOTIFY` | 否 | 是否允许 DSA 发送外部通知 | `false` |
| `DAILY_ENRICH_ENABLED` | 否 | 是否默认对 L1 后 Top N 候选补充日 K 特征 | `false` |
| `DAILY_ENRICH_MAX_CANDIDATES` | 否 | 日 K 增强最多处理候选数 | `100` |
| `DAILY_LOOKBACK_DAYS` | 否 | 日 K 特征回看天数 | `120` |
| `DAILY_SOURCE` | 否 | 日 K 数据源：`auto`、`tencent`、`sina`、`akshare`、`baostock` 或 `tushare`；`auto` 有 Tushare token 时使用 `tushare,tencent,sina,akshare,baostock`，否则使用 `tencent,sina,akshare,baostock` | `auto` |
| `DAILY_FETCH_RETRIES` | 否 | 单只候选日 K 拉取失败后的重试次数 | `2` |
| `DAILY_FETCH_MAX_WORKERS` | 否 | 日 K 拉取并发数，网络不稳时建议 `1`，稳定后可设 `2`/`4` | `1` |
| `RISK_ENABLED` | 否 | 是否启用独立风险层 | `true` |
| `RISK_MAX_PENALTY` | 否 | 风险层最大扣分 | `12` |
| `RISK_VETO_HIGH` | 否 | 是否直接剔除高风险候选 | `false` |
| `EVALUATION_COST_BPS` | 否 | T+N 评估收益扣除的往返成本，单位 bps | `0` |
| `EVALUATION_FOLLOW_THROUGH_PCT` | 否 | 形态后验中“突破延续”的最低收益百分比 | `3` |
| `EVALUATION_FAILED_BREAKOUT_PCT` | 否 | 形态后验中“突破失败”的最高收益百分比 | `-3` |
| `EVALUATION_PRICE_PATH_ENABLED` | 否 | 评估时是否抓取日 K 路径，计算最大回撤和最大浮盈 | `false` |
| `EVALUATION_PRICE_PATH_LOOKBACK_DAYS` | 否 | 价格路径日 K 回看天数 | `90` |
| `ALPHASIFT_DATA_DIR` | 否 | 运行记录和评估结果目录 | `./data` |
| `STRATEGIES_DIR` | 否 | 策略目录路径 | 自动查找 |

## LiteLLM 配置兼容

AlphaSift 兼容 `daily_stock_analysis` 的 LiteLLM 配置习惯：

```env
LLM_CHANNELS=primary
LLM_PRIMARY_PROTOCOL=openai
LLM_PRIMARY_BASE_URL=https://api.deepseek.com/v1
LLM_PRIMARY_API_KEYS=sk-xxx,sk-yyy
LLM_PRIMARY_MODELS=deepseek-chat,deepseek-reasoner
LITELLM_MODEL=openai/deepseek-chat
LITELLM_FALLBACK_MODELS=openai/gpt-4o-mini,anthropic/claude-3-5-sonnet
```

也支持更简单的单供应商配置：

```env
GEMINI_API_KEY=...
LITELLM_MODEL=gemini/gemini-2.5-flash
```

如果已有 `daily_stock_analysis` 的 `.env`，通常可以复用其中的 `LITELLM_MODEL`、`LITELLM_FALLBACK_MODELS`、`LLM_CHANNELS`、`LLM_{NAME}_*`、`OPENAI_*`、`GEMINI_*`、`DEEPSEEK_*`、`OLLAMA_API_BASE` 等字段。

CLI 也支持显式加载外部 `.env`，可重复传入：

```bash
alphasift --env-file /path/to/daily_stock_analysis/.env \
  --env-file /path/to/daily_ai_assistant/.env \
  screen balanced_alpha
```

## 数据源配置

支持五种 A 股全市场快照数据源，自动按优先级降级。默认未配置 Tushare token 时使用：

```text
sina -> efinance -> akshare_em -> em_datacenter
```

若配置了 `TUSHARE_TOKEN` / `TUSHARE_API_TOKEN`，且没有手工设置 `SNAPSHOT_SOURCE_PRIORITY`，默认链路改为：

```text
tushare -> sina -> efinance -> akshare_em -> em_datacenter
```

| 数据源 | 接口 | 特点 |
|--------|------|------|
| `sina` | vip.stock.finance.sina.com.cn | 直连全市场源，含 PE/PB/换手率/市值字段 |
| `efinance` | push2.eastmoney.com | 实时推送，交易时段最快 |
| `akshare_em` | 82.push2.eastmoney.com | 实时推送，备选 |
| `em_datacenter` | data.eastmoney.com | 选股器 API，非交易时段可用 |
| `tushare` | Tushare Pro `daily` + `daily_basic` | 最近交易日数据，需 `TUSHARE_TOKEN`，非实时 |

周末或节假日 push2 接口不可用时，会自动降级到 `em_datacenter`。EastMoney 直连接口通过共享重试会话、串行限流和随机抖动访问，减少连接抖动和连续降级时的突发请求；这一点参考了 `a-stock-data` 对东财 `em_get()` 的防封建议。AlphaSift 对 efinance、AkShare、Baostock、Tushare、yfinance 这类第三方 wrapper 调用增加了 caller-side 超时；直接 HTTP 源继续使用请求级 timeout。重复失败的数据源会进入短期健康度熔断，后续运行会临时跳过该源；日 K live 源全失败时可读取过期但结构有效的 history cache，并用 `daily_stale/source_errors` 标记降级。如果某个数据源缺少当前策略必需字段，例如 PB，系统会跳过该源继续尝试后续来源。所有实时源失败时可读取 `snapshot.last_good.json`，并标记 `fallback_used/stale/stale_age_hours/source_errors`；如设置 `SNAPSHOT_FALLBACK_MAX_AGE_HOURS`，超过该年龄的缓存会被拒绝，避免长期重复使用过旧快照。

### 数据源能力矩阵

| 能力 | 默认链路 | 主要字段 |
|------|----------|----------|
| 日 K 增强 | 有 token: `tushare,tencent,sina,akshare,baostock`；无 token: `tencent,sina,akshare,baostock`，并按 source-health 动态后移不健康源 | OHLCV、前复权（支持源）、技术指标、20日波动/ATR/回撤、逐行 `daily_source` 来源标记、`daily_quality_score`/flags（含 `fetch_failed` 行级失败标记）、source-health 统计；screen degradation 会汇总日K来源、质量 flags、异常 source-health 与 hard-filter 淘汰摘要；低质量、拉取失败或 stale cache 行会进入最终风险扣分 |
| 全市场快照 | 有 token: `tushare,sina,efinance,akshare_em,em_datacenter`；无 token: `sina,efinance,akshare_em,em_datacenter` | 价格、涨跌幅、成交额、市值、PE/PB、换手率 |
| 候选级上下文 | `news,fund_flow,announcement,quote` | 新闻、资金流、公告、腾讯行情估值/换手率 |
| 失败降级 | source health 熔断 + daily history cache + snapshot last-good cache | stale/fallback/source_errors 元数据 |

## L3 后置分析器

默认启用本地 `scorecard`，即使不配置外部系统，也会有一层稳定、低成本的候选复核评分。

可选分析器：

| 分析器 | 来源 | 作用 |
|---|---|---|
| `scorecard` | 本地规则评分 | 默认启用，根据因子、LLM 置信度、催化和风险做轻量加减分 |
| `dsa` | 外部 daily_stock_analysis | 对最终候选做单股深度分析并提取建议、趋势和风险 |
| `external_http` | 自定义 HTTP 工具 | 接入其他策略、评分器或研究系统 |

命令示例：

```bash
alphasift screen balanced_alpha
alphasift screen dual_low --post-analyzer dsa
alphasift screen capital_heat --post-analyzer external_http
alphasift screen balanced_alpha --no-post-analysis
```

`daily_stock_analysis` 不属于本仓库。AlphaSift 只通过 `DSA_API_URL` 把它作为可选 L3 后端调用，并且只处理最终入围候选，不参与全市场初筛。
