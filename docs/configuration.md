# 配置参考

这份文档说明 `.env`、LLM 排序、数据源和 L3 后置分析器配置。使用 `--no-llm` 可以直接按规则排序。

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
| `AGENT_LITELLM_MODEL` | 否 | 主模型的兼容变量，优先级低于 `LITELLM_MODEL` 和 `LLM_MODEL` | - |
| `LITELLM_FALLBACK_MODELS` | 否 | 备选模型，逗号分隔 | - |
| `LLM_CHANNELS` | 否 | 多渠道配置，配合 `LLM_{NAME}_*` 使用 | - |
| `GEMINI_API_KEY` / `GEMINI_API_KEYS` / `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` | 按供应商 | `GEMINI_API_KEYS` 接受逗号分隔的密钥并优先于 `GEMINI_API_KEY` | - |
| `OPENAI_BASE_URL` / `OLLAMA_API_BASE` | 否 | OpenAI 兼容接口或 Ollama 地址 | - |
| `LLM_API_KEY` | 否 | 旧版兼容 API Key，会优先覆盖供应商 key | - |
| `LLM_MODEL` | 否 | 旧版兼容模型名；`LITELLM_MODEL` 优先 | `gemini/gemini-2.5-flash` |
| `LLM_BASE_URL` | 否 | 旧版兼容自定义 API 地址 | - |
| `LLM_CONTEXT` | 否 | 传给 LLM 的市场、新闻或主题上下文 | - |
| `LLM_TEMPERATURE` | 否 | LLM 排序温度，默认偏确定性 | `0.2` |
| `LLM_JSON_MODE` | 否 | 是否请求 JSON response_format，不支持时自动降级 | `true` |
| `LLM_SILENT` | 否 | 关闭 HTTP 状态调试日志。排序失败仍记录脱敏警告 | `true` |
| `LLM_TIMEOUT_SEC` | 否 | 单次请求超时秒数。超时后回退到规则排序 | `60` |
| `LLM_MAX_TOKENS` | 否 | 单次响应的 token 上限 | `2048` |
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
| `INDUSTRY_AUTO_BACKFILL` | 否 | A 股快照缺少行业字段时，自动用东财行业映射补全（本地缓存 7 天），让组合分散度控制能够生效 | `true` |
| `INDUSTRY_PROVIDER_MAX_BOARDS` | 否 | provider 模式最多反查板块数 | `80` |
| `SNAPSHOT_SOURCE_PRIORITY` | 否 | 数据源优先级，逗号分隔；不设置时若配置了 Tushare token 会优先 `tushare` | 无 token: `sina,efinance,akshare_em,em_datacenter` |
| `SNAPSHOT_FALLBACK_MAX_AGE_HOURS` | 否 | last-good 快照缓存最大可接受年龄；为空/`none` 表示不限制 | - |
| `ALPHASIFT_SOURCE_HEALTH_PATH` | 否 | 跨运行记录快照数据源成败的文件；最近 6 小时内失败过的源会排到后面再试。设为 `off` 关闭 | `$ALPHASIFT_DATA_DIR/source_health.json` |
| `ALPHASIFT_SOURCE_CALL_TIMEOUT_SEC` | 否 | 第三方 wrapper 数据源调用的全局等待超时；`0`/`off` 表示关闭 | - |
| `ALPHASIFT_SNAPSHOT_CALL_TIMEOUT_SEC` | 否 | 单个快照源的时间预算：`efinance`/`akshare_em`/`tushare` 的调用超时，以及 `sina`/`em_datacenter` 分页拉取的总时长上限 | `60` |
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

## LLM 网关与渠道

AlphaSift 直接调用 OpenAI 兼容的 Chat Completions 接口。`LITELLM_MODEL`、`AGENT_LITELLM_MODEL` 和 `LITELLM_FALLBACK_MODELS` 的变量名仅为兼容旧配置而保留。

主模型按 `LITELLM_MODEL` → `LLM_MODEL` → `AGENT_LITELLM_MODEL` → 首个已启用渠道的首个模型解析。未指定模型且没有渠道模型时，沿用 Ollama、DeepSeek、Gemini、OpenAI、AIHubMix 的自动选择顺序。使用 Ollama 自动选择时，请同时设置 `OLLAMA_MODEL`。`LLM_API_KEY` 和 `LLM_BASE_URL` 优先于主模型的供应商默认值。

`provider/model` 中的第一个前缀用于选择网关，请求发送剩余的模型 ID。例如 `openrouter/anthropic/claude-…` 发往 OpenRouter 的模型 ID 为 `anthropic/claude-…`。自定义兼容接口可通过 `LLM_BASE_URL` 或渠道配置指定。

| 前缀 | 默认 Base URL | 密钥变量 | 供应商文档 |
|---|---|---|---|
| `openai` | `https://api.openai.com/v1` | `OPENAI_API_KEY` | [Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) |
| `deepseek` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` | [Your First API Call](https://api-docs.deepseek.com/) |
| `gemini` | `https://generativelanguage.googleapis.com/v1beta/openai` | `GEMINI_API_KEYS` / `GEMINI_API_KEY` | [OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai) |
| `anthropic` | `https://api.anthropic.com/v1` | `ANTHROPIC_API_KEY` | [OpenAI SDK compatibility](https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk) |
| `ollama` | `http://localhost:11434/v1` | 可不填 | [OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility) |
| `openrouter` | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` | [API Reference](https://openrouter.ai/docs/api_reference/overview) |
| `dashscope` / `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `DASHSCOPE_API_KEY` / `QWEN_API_KEY` | [Base URL overview](https://docs.modelstudio.console.alibabacloud.com/en/model-studio/base-url) |
| `zhipu` | `https://open.bigmodel.cn/api/paas/v4` | `ZHIPU_API_KEY` / `ZAI_API_KEY` | [快速开始](https://docs.bigmodel.cn/cn/guide/start/quick-start) |
| `moonshot` | `https://api.moonshot.cn/v1` | `MOONSHOT_API_KEY` | [Chat Completions](https://platform.kimi.com/docs/api/chat) |
| `aihubmix` | `https://aihubmix.com/v1` | `AIHUBMIX_KEY` / `AIHUBMIX_API_KEY` | [SDK 集成](https://api.aihubmix.com/ecosystem) |

客户端为 `OLLAMA_API_BASE` 补齐 `/v1`。`OPENAI_BASE_URL` 和 `AIHUBMIX_BASE_URL` 可覆盖相应的默认地址。跨供应商的直连备用模型使用各自的地址和密钥。

渠道和渠道内的模型、密钥均按逗号分隔的顺序尝试。客户端先试主模型匹配的渠道密钥，再试主模型的直连配置，接着尝试其余渠道模型及 `LITELLM_FALLBACK_MODELS`。`LLM_<NAME>_API_KEYS` 优先于 `LLM_<NAME>_API_KEY`，`LLM_<NAME>_ENABLED=false` 可跳过指定渠道。`LLM_<NAME>_PROTOCOL` 默认为 `openai`，也可用上表除 `anthropic` 外的前缀选择对应的兼容网关。

### 迁移 Router YAML

删除 `LITELLM_CONFIG`，将 YAML 的每个路由按原顺序写入 `LLM_CHANNELS`。把原路由的 `api_base`、`api_key` 和实际 `model` 分别填入渠道的 `BASE_URL`、`API_KEY`（多密钥用 `API_KEYS`）和 `MODELS`。如果主模型使用了 YAML 中的路由别名，请改为实际模型 ID 或由首个渠道模型确定主模型。Claude 渠道请使用 `PROTOCOL=openai` 和 `https://api.anthropic.com/v1`。

```env
LLM_CHANNELS=primary,backup
LLM_PRIMARY_PROTOCOL=openai
LLM_PRIMARY_BASE_URL=https://api.deepseek.com/v1
LLM_PRIMARY_API_KEYS=key1,key2
LLM_PRIMARY_MODELS=deepseek-chat,deepseek-reasoner
LLM_BACKUP_PROTOCOL=openai
LLM_BACKUP_BASE_URL=https://api.openai.com/v1
LLM_BACKUP_API_KEY=your_openai_key
LLM_BACKUP_MODELS=gpt-4o-mini
```

检测到 `LITELLM_CONFIG` 或原生协议的渠道时，排序会回退到规则分数并给出迁移提示。可用 `alphasift doctor data-sources --no-live` 查看提示。

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

周末或节假日 push2 接口不可用时，会自动降级到 `em_datacenter`。EastMoney 直连接口通过共享重试会话、串行限流和随机抖动访问，减少连接抖动和连续降级时的突发请求；这一点参考了 `a-stock-data` 对东财 `em_get()` 的防封建议。AlphaSift 对 efinance、AkShare、Baostock、Tushare、yfinance 这类第三方 wrapper 调用增加了 caller-side 超时；直接 HTTP 源继续使用请求级 timeout。重复失败的数据源会进入短期健康度熔断，后续运行会临时跳过该源；`doctor data-sources` 会同时输出原始 `source_health` counters 和面向 UI/agent 的 `health_summary`，按 healthy/failing/disabled/never_seen 分组展示。日 K live 源全失败时可读取过期但结构有效的 history cache，并用 `daily_stale/source_errors` 标记降级。如果某个数据源缺少当前策略必需字段，例如 PB，系统会跳过该源继续尝试后续来源。所有实时源失败时可读取 `snapshot.last_good.json`，并标记 `fallback_used/stale/stale_age_hours/source_errors`；如设置 `SNAPSHOT_FALLBACK_MAX_AGE_HOURS`，超过该年龄的缓存会被拒绝，避免长期重复使用过旧快照。

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
