# AlphaSift

AlphaSift 是为 AI Agent 设计的全市场候选发现与横向排序引擎。它按 YAML 策略筛选、评分、排序股票候选，并把运行结果保存下来，方便后续做 T+N 评估。

> English README: [README.md](README.md)

## 免责声明

- 本项目仅用于学习、研究与工程实验，不构成任何投资建议、收益承诺或买卖指引。
- 项目输出依赖第三方行情数据、外部模型与策略参数，可能存在延迟、缺失、错误或不符合实际交易条件的情况。
- LLM 生成的排序理由、风险摘要等内容仅供参考，不能替代人工研究、合规审查与独立投资判断。
- 使用者应自行评估策略风险、交易成本、流动性、公告时点与市场环境，并对自己的决策与结果负责。

## 快速开始

```bash
# 安装
pip install -e .

# 配置（LLM 排序可复用 daily_stock_analysis 的 LiteLLM 配置）
cp .env.example .env
# 编辑 .env，填入 GEMINI_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY
# 或使用 LITELLM_MODEL、LLM_CHANNELS、LITELLM_CONFIG

# 列出可用策略
alphasift strategies

# UI/agent 总览：策略分组、数据源健康、最近运行
alphasift overview --explain

# 本地只读 JSON API，供 dashboard / agent 消费
alphasift serve --host 127.0.0.1 --port 8765

# 一键演示（无 API key）
alphasift quickstart

# 执行选股（不使用 LLM 排序）
alphasift screen dual_low --no-llm

# 执行选股（使用 LLM 排序，需要配置 LLM_API_KEY）
alphasift screen dual_low

# 复用其他项目的 LLM 配置文件
alphasift --env-file /home/ubuntu/daily_ai_assistant/.env screen balanced_alpha

# 带市场/主题上下文的 LLM 排序
alphasift screen balanced_alpha --context "今日券商板块放量，低估值金融获得资金回流"

# 带候选级新闻/公告/资金流上下文的 LLM 排序
alphasift screen balanced_alpha --candidate-context-file candidate_context.csv

# 默认会运行本地 L3 scorecard 后置评分器
alphasift screen balanced_alpha --explain

# 追加 DSA 作为可选 L3 后置分析器之一（需要配置 DSA_API_URL）
alphasift screen dual_low --post-analyzer dsa

# 显式关闭 L3 后置评分/分析
alphasift screen dual_low --no-post-analysis

# 项目/策略自检
alphasift audit

# 刷新行业/概念/板块热度映射缓存，并写 metadata 和 history sidecar
alphasift industry-cache --output data/industry_map.csv --explain
alphasift screen balanced_alpha --industry-map-file data/industry_map.csv

# 保存运行，之后用最新快照做 T+N 评估
alphasift screen dual_low --no-llm --save-run
alphasift runs
alphasift runs --json
alphasift report <run_id> --output data/reports/dual_low.md
alphasift evaluate <run_id> --explain
alphasift evaluate-batch --limit 20 --explain
# 如需更完整复盘，可额外抓取日 K 路径，输出最大回撤/最大浮盈
alphasift evaluate <run_id> --with-price-path --explain

# Python 调用
from alphasift import evaluate_saved_run, evaluate_saved_runs, screen
result = screen("dual_low", use_llm=False)
for p in result.picks:
    print(f"{p.rank}. {p.code} {p.name} score={p.final_score:.1f}")
```

## 选股输出示例

下面是 2026-04-12（周六，非交易时段）的一组真实无 LLM 记录，数据来自上一交易日 2026-04-10 收盘快照。示例只说明引擎输出形态，不构成任何推荐。

```text
$ alphasift screen dual_low --no-llm
全市场 5190 只 -> 硬筛后 337 只 -> 输出 Top 5
排名  代码    名称      得分   价格    涨跌幅   PE     PB
1     002039  黔源电力  72.7   20.72   -2.49%   14.76  1.99
2     002444  巨星科技  71.0   30.82   +0.29%   14.59  1.95
3     002128  电投能源  70.9   31.60   -2.41%   14.00  1.90
```

### 双低选股（dual_low）

全市场 5190 只 -> 硬筛后 337 只 -> 输出 Top 5

| 排名 | 代码 | 名称 | 得分 | 价格 | 涨跌幅 | PE | PB |
|------|------|------|------|------|--------|-----|-----|
| 1 | 002039 | 黔源电力 | 72.7 | 20.72 | -2.49% | 14.76 | 1.99 |
| 2 | 002444 | 巨星科技 | 71.0 | 30.82 | +0.29% | 14.59 | 1.95 |
| 3 | 002128 | 电投能源 | 70.9 | 31.60 | -2.41% | 14.00 | 1.90 |
| 4 | 002236 | 大华股份 | 70.8 | 17.43 | +1.04% | 14.86 | 1.50 |
| 5 | 600583 | 海油工程 | 68.9 | 7.02 | +4.15% | 14.89 | 1.17 |

### 放量突破（volume_breakout）

全市场 5190 只 -> 硬筛后 126 只 -> 输出 Top 5

| 排名 | 代码 | 名称 | 得分 | 价格 | 涨跌幅 |
|------|------|------|------|------|--------|
| 1 | 002837 | 英维克 | 74.0 | 99.05 | +6.40% |
| 2 | 688183 | 生益电子 | 73.8 | 95.30 | +7.09% |
| 3 | 300803 | 指南针 | 73.3 | 101.68 | +3.07% |
| 4 | 002384 | 东山精密 | 73.0 | 143.55 | +8.83% |
| 5 | 300277 | 汽轮科技 | 73.0 | 19.74 | +5.73% |

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
| `LLM_CONTEXT` | 否 | 传给 LLM 的市场/新闻/主题上下文 | - |
| `LLM_TEMPERATURE` | 否 | LLM 排序温度，默认偏确定性 | `0.2` |
| `LLM_JSON_MODE` | 否 | 是否请求 JSON response_format，不支持时自动降级 | `true` |
| `LLM_SILENT` | 否 | 是否抑制 LiteLLM 调用日志，避免污染 CLI JSON/摘要输出 | `true` |
| `LLM_RANK_WEIGHT` | 否 | LLM 排序对最终分数的权重 | `0.40` |
| `LLM_CANDIDATE_MULTIPLIER` | 否 | 送入 LLM 的候选倍数（相对 max_output） | `6` |
| `LLM_MAX_CANDIDATES` | 否 | 单次最多送入 LLM 的候选数 | `30` |
| `LLM_MAX_RETRIES` | 否 | LLM 结构化输出不合格时的重试次数 | `1` |
| `LLM_MIN_COVERAGE` | 否 | LLM 输出必须覆盖候选池的最低比例 | `0.60` |
| `LLM_CONTEXT_MAX_CHARS` | 否 | 拼接后传给 LLM 的上下文最大长度 | `4000` |
| `LLM_CANDIDATE_CONTEXT_ENABLED` | 否 | 是否默认对 LLM Top K 候选抓取新闻/公告/资金流线索 | `false` |
| `LLM_CANDIDATE_CONTEXT_MAX_CANDIDATES` | 否 | 候选级上下文最多抓取前 N 只 | `8` |
| `LLM_CANDIDATE_CONTEXT_PROVIDERS` | 否 | 候选级抓取来源，逗号分隔：`news,fund_flow,announcement,quote` | `news,fund_flow,announcement,quote` |
| `LLM_CANDIDATE_CONTEXT_CACHE_ENABLED` | 否 | 是否缓存候选级抓取上下文 | `true` |
| `LLM_CANDIDATE_CONTEXT_CACHE_TTL_HOURS` | 否 | 候选上下文缓存有效小时数 | `24` |
| `INDUSTRY_MAP_FILES` | 否 | 本地 code->industry/concepts/board_heat 映射 CSV/JSON/JSONL，逗号分隔 | - |
| `INDUSTRY_PROVIDER` | 否 | 可选行业/概念/板块热度 provider，如 `akshare`；默认关闭 | `none` |
| `INDUSTRY_PROVIDER_MAX_BOARDS` | 否 | provider 模式最多反查板块数 | `80` |
| `SNAPSHOT_SOURCE_PRIORITY` | 否 | 数据源优先级（逗号分隔）；不设置时若配置了 Tushare token 会优先 `tushare` | 无 token: `sina,efinance,akshare_em,em_datacenter` |
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
| `DAILY_SOURCE` | 否 | 日 K 数据源：`auto`、`tencent`、`sina`、`akshare`、`baostock` 或 `tushare`；有 Tushare token 时 `auto` 使用 `tushare,tencent,sina,akshare,baostock`，否则使用 `tencent,sina,akshare,baostock` | `auto` |
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

### LLM 配置兼容

AlphaSift 现在兼容 `daily_stock_analysis` 的 LiteLLM 配置习惯：

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

## 项目结构

```
alphasift/
├── SKILL.md                # Skill 描述（AI Agent 读这个）
├── strategies/             # 选股策略 YAML
├── docs/
│   ├── configuration.md    # 配置参考
│   ├── design.md           # 设计原则
│   ├── positioning.md      # 项目定位
│   ├── reference.md        # 项目结构、边界和实测记录
│   ├── scoring.md          # 评分体系
│   ├── strategy-guide.md   # 策略编写指南
│   └── usage.md            # 使用指南
└── alphasift/              # Python 包
    ├── __init__.py
    ├── cli.py              # CLI 入口
    ├── config.py           # 环境配置
    ├── context.py          # LLM 上下文拼接
    ├── candidate_context.py # 候选级新闻/公告/资金流上下文
    ├── daily.py            # 候选级日 K 特征增强
    ├── industry.py         # 行业/概念/板块热度映射
    ├── models.py           # 数据模型
    ├── snapshot.py         # 全市场快照（4 种数据源 + 自动降级）
    ├── filter.py           # L1 硬筛
    ├── scorer.py           # 评分计算
    ├── ranker.py           # L2 LLM 排序
    ├── risk.py             # 独立风险层
    ├── post_analysis.py    # L3 可插拔后置分析器
    ├── dsa.py              # 可选 DSA 接入
    ├── store.py            # 运行结果持久化
    ├── overview.py         # UI/agent 总览 payload
    ├── evaluate.py         # T+N 后验评估与批量评估聚合
    ├── pipeline.py         # 主流程编排
    └── strategy.py         # 策略 YAML 加载
```

## 核心思路

- **三层漏斗**：L1 代码硬筛 → L2 LLM 排序 → L3 后置分析（可选、可插拔）
- **策略即 YAML**：所有选股逻辑通过 YAML 文件定义，不写死代码
- **默认规则可覆盖**：因子评分曲线、风险阈值、组合风险桶、scorecard 规则和事件偏好都有默认值，也可在策略 YAML 中用 profile 覆盖
- **多因子候选画像**：每只候选输出价值、流动性、动量、反转、活跃度、稳定性、市值、主题热度和热度趋势等因子分
- **LLM 结构化软判断**：LLM 只在候选池内做跨股票比较，输出全局市场判断、选择逻辑、组合风险、候选 thesis、行业/主题、风险、催化、标签和信心分；若快照或外部数据提供 `industry/concepts/board_heat_score/board_heat_trend_score`，会作为 LLM 判断锚点；`--candidate-context-file` 可按 `code` 对齐候选级新闻、公告、资金流或自定义研究摘要，抓取上下文会带来源数、来源置信度、来源权重分、公告类别、事件标签和负面风险标签
- **组合分散覆盖层**：LLM 标注行业/主题后，默认按行业风险桶对重复候选做温和扣分；若 LLM 缺失行业标签但候选有 `industry`，会用结构化行业作后备锚点
- **LiteLLM 配置复用**：兼容主模型、fallback、多渠道和 Router YAML，方便复用作者其他项目配置
- **独立风险层**：在 LLM 后对过热、弱信号、低置信度等风险做统一扣分或剔除
- **候选级日 K 增强**：只对 L1 后 Top N 候选补充 MA、60 日涨幅、MACD/RSI、signal_score、20 日突破幅度、区间振幅、20 日量能比、实体强度、MA20 回踩距离和平台持续天数；`DAILY_SOURCE=auto` 且配置了 Tushare token 时会先试 `tushare`，否则优先走 `tencent`、`sina` 直连源，再降级到 `akshare`、`baostock`；低质量、拉取失败或 stale cache 行会进入最终风险扣分
- **默认 L3 评分器**：本地 `scorecard` 默认启用，作为最终候选的轻量一致性复核
- **可评估闭环**：保存运行结果，用后续最新快照做 T+N 收益、胜率、缺失报价、交易成本扣减、等权组合摘要、形态后验标签和失败样本复盘；可选抓取日 K 路径计算最大回撤和最大浮盈
- **DSA 后置增强**：DSA 只是一种可追加 L3 分析器，不参与全市场初筛，也不是默认依赖
- **为 Agent 设计**：SKILL.md 描述能力和接口，任何支持 Skill 协议的 Agent 都能调用

## 项目定位

AlphaSift 的定位是“全市场候选发现与横向排序引擎”。它负责从全市场发现值得继续研究的股票，并把结构化因子、LLM 语义判断、组合风险和后置复核整合成可审计结果。

与传统条件选股器相比，AlphaSift 的优势是 LLM 结构化横向比较、行业/主题风险桶、候选 thesis、watch items、invalidators 和后验评估闭环。与 `daily_stock_analysis` 相比，AlphaSift 站在上游做全市场发现；DSA 更适合作为最终少量候选的 L3 单股深度分析。与 `daily_ai_assistant` 相比，AlphaSift 不是通知助手，而是结构化选股引擎，但可以复用其 LLM 配置。

更多说明见 [docs/positioning.md](docs/positioning.md)。

## 与 daily_stock_analysis 的关系

- README、代码和环境变量中提到的 `DSA`，指的是外部单股深度分析服务 `daily_stock_analysis`
- `alphasift` 负责全市场候选发现、硬筛、横向评分和 LLM 候选排序
- `daily_stock_analysis` 负责单只股票的深度分析，默认通过 `POST /api/v1/analysis/analyze` 提供服务
- 两者通过 `DSA_API_URL` 解耦部署；`daily_stock_analysis` 不属于本仓库，但可以作为本仓库的 L3 分析后端
- 为控制成本，`alphasift` 只会在最终入围候选上调用 DSA；DSA 返回的结构化结果会在最后阶段影响 `final_score`、风险判断和最终名次
- 默认使用内置 `scorecard`；也可以追加 DSA，或接入 `external_http` 形式的自定义评分工具

## 数据源

支持五种 A 股全市场快照数据源，自动按优先级降级。默认未配置 Tushare token 时使用：

```text
sina → efinance → akshare_em → em_datacenter
```

若配置了 `TUSHARE_TOKEN` / `TUSHARE_API_TOKEN`，且没有手工设置 `SNAPSHOT_SOURCE_PRIORITY`，默认改为：

```text
tushare → sina → efinance → akshare_em → em_datacenter
```

| 数据源 | 接口 | 特点 |
|--------|------|------|
| `sina` | vip.stock.finance.sina.com.cn | 直连全市场源，含 PE/PB/换手率/市值字段 |
| `efinance` | push2.eastmoney.com | 实时推送，交易时段最快 |
| `akshare_em` | 82.push2.eastmoney.com | 实时推送，备选 |
| `em_datacenter` | data.eastmoney.com | 选股器 API，**非交易时段可用** |
| `tushare` | Tushare Pro `daily` + `daily_basic` | 最近交易日数据，需 `TUSHARE_TOKEN`，非实时 |

> 周末/节假日 push2 接口不可用，会自动降级到 em_datacenter。若某个数据源超时、不可用或缺少当前策略必需字段，例如 PB，系统会跳过该源继续尝试后续来源。直接 HTTP 源使用请求级 timeout；efinance、AkShare、Baostock、Tushare、yfinance 等第三方 wrapper 调用也有 caller-side timeout，避免库调用卡住整次筛选。东财直连请求参考 `a-stock-data` 的防封实践，统一走共享重试会话、串行间隔和随机抖动。

## 内置策略

| 策略 | 类型 | 说明 |
|------|------|------|
| `dual_low` | 价值 | 低 PE + 低 PB，适合价值投资 |
| `blue_chip_income` | 收益 | 高流动性大盘蓝筹和红利资产的防守型候选 |
| `volume_breakout` | 趋势 | 放量突破关键阻力位 |
| `quality_value` | 价值 | 估值合理、流动性充足、波动不过热 |
| `low_volatility_quality` | 质量 | 用日 K 波动、回撤、ATR 和数据质量约束做防守型质量筛选 |
| `capital_heat` | 动量 | 资金活跃、量价同步但未极端过热 |
| `oversold_reversal` | 反转 | 跌幅可控且流动性仍在的修复候选 |
| `balanced_alpha` | 框架 | 综合估值、资金、动量、稳定性的通用发现策略 |
| `momentum_quality` | 框架 | 兼顾趋势确认和基本面质量的中线候选发现 |
| `shrink_pullback` | 趋势 | 候选级日 K 增强后识别均线多头与回踩结构 |

### 自定义策略

可用 `alphasift overview --json/--explain` 获取一份 UI/agent 总览 payload，包含策略分组、策略筛选 facets、策略卡片、可选策略推荐、数据源 `health_summary`、策略覆盖、数据源历史、已保存 evaluation 表现、最近运行和 next actions。可用 `alphasift serve` 启动本地只读 JSON API，提供 `/health`、`/result-schema`、`/overview`、`/strategies`、`/strategy?name=<strategy_name>`、`/strategy-compare?base=<base>&target=<target>`、`/strategy-facets`、`/strategy-cards`、`/strategy-readiness`、`/strategy-run-summary`、`/data-source-history`、`/strategy-performance`、`/strategy-templates`、`/strategy-template?name=<template_name>`、`/runs`、`/report?run=<run_id>` 和 `/doctor/data-sources` 端点。可用 `alphasift strategies --json` 或 `alphasift strategies --explain` 查看策略风格属性、数据依赖、活跃硬筛、因子权重和 profile 覆盖项；UI 或 agent 需要推荐策略时，可追加 `--risk-profile defensive --holding-period swing --strict --json` 这类匹配条件，输出带 `score`、`matched`、`missing` 的候选策略；构建筛选控件时可用 `/strategy-facets` 获取分类、标签、风格、数据依赖和必需字段的 `value/count/strategies`；构建策略卡片时可用 `/strategy-cards` 聚合策略属性、readiness、运行历史、已保存 evaluation 表现、主要因子、next actions，以及 needs-history、needs-evaluation、performance leaders、attention 分区；构建策略可用性面板时可用 `/strategy-readiness` 获取 ready/attention/unchecked 计数和缺字段影响；构建历史复盘面板时可用 `/strategy-run-summary` 按策略聚合 saved-run 索引、错误/降级计数和样例且不会触发 live 行情；构建数据源稳定性面板时可用 `/data-source-history` 从 saved-run 元数据聚合 snapshot source 错误率、降级率、fallback 率、具体样例、稳定性状态和 next actions；构建策略表现面板时可用 `/strategy-performance` 从已保存 evaluation 聚合收益、胜率、表现分数和 leaderboard，且不会重新抓行情；评审策略参数漂移时可用 `--compare dual_low low_volatility_quality --json` 或 `/strategy-compare`；新增策略时可用 `alphasift strategies --templates --explain` 和 `alphasift strategies --template <name>` 从模板生成 YAML 草稿；可用 `alphasift doctor data-sources --all-strategies --explain` 查看跨策略数据源字段覆盖矩阵、source `health_summary` 和 live snapshot `quality_summary`。在 `strategies/` 目录添加 YAML 文件即可。参考 [docs/strategy-guide.md](docs/strategy-guide.md)。

## 已知限制

- 依赖日 K 的策略只对 L1 后 Top N 候选做增强；这不是完整历史数据库或全市场回测系统
- `dsa` 后置分析器依赖外部 `daily_stock_analysis` 服务，当前按同步 REST 请求逐只调用，更适合最终名单的低频深度分析
- L1/L2 主评分仍以快照横截面数据为主；任意 L3 后置分析器都只在最终阶段做覆盖和分数修正，不参与全市场初筛
- `tushare` 兜底源依赖用户自己的 Pro token、接口积分和权限；当前取最近交易日收盘数据，不提供实时盘口
- T+N 评估基于保存时价格与评估时最新快照价格，不等同严谨事件回测；可扣减交易成本、标记突破/回踩后验形态，并可选抓取日 K 路径估算最大回撤/最大浮盈，但暂不处理分红、停牌和调仓约束
- 仓库内同时保留 `strategies/` 与 `alphasift/strategies/` 两份策略镜像用于开发态和安装态；内置策略文件需保持一致，但 `strategies/` 允许新增自定义 YAML

## 数据源降级实测

### 2026-04-12（周六，非交易时段）

测试环境：Python 3.12，数据来源为上一交易日（2026-04-10）收盘数据。

- efinance / akshare 实时推送接口在非交易时段不可用，自动降级到 `em_datacenter`（东方财富选股器 API）
- 当前默认链路支持 Tushare；配置 token 且未手工指定 `SNAPSHOT_SOURCE_PRIORITY` 时会优先使用 Tushare。本次记录未配置 Tushare token，未触发该源
- 未启用 LLM 排序（`--no-llm`）
- 对应选股输出已前置到 [选股输出示例](#选股输出示例)

#### 数据源降级验证

| 数据源 | 状态 | 说明 |
|--------|------|------|
| efinance（push2.eastmoney.com） | 不可用 | 实时推送接口，非交易时段返回空响应 |
| akshare_em（82.push2.eastmoney.com） | 不可用 | 同上 |
| em_datacenter（data.eastmoney.com） | 可用 | 选股器 API，周末仍返回最近交易日数据 |
| tushare（Tushare Pro） | 未触发 | 当前已支持，需 `TUSHARE_TOKEN` |

降级链路验证通过：efinance → akshare_em → em_datacenter，自动切换到可用数据源。

## 文档

- [SKILL.md](SKILL.md) — Skill 描述与函数接口
- [docs/usage.md](docs/usage.md) — 使用指南
- [docs/configuration.md](docs/configuration.md) — 配置参考
- [docs/positioning.md](docs/positioning.md) — 项目定位与相对优势
- [docs/comparison.md](docs/comparison.md) — 横向比较、短板与补齐优先级
- [docs/design.md](docs/design.md) — 设计原则
- [docs/reference.md](docs/reference.md) — 项目结构、数据源边界和实测记录
- [docs/scoring.md](docs/scoring.md) — 评分体系详解
- [docs/strategy-guide.md](docs/strategy-guide.md) — 策略编写指南

## License

Apache License 2.0
