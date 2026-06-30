# 项目参考

这份文档收纳 README 中不适合放在首页的细节：项目结构、数据源边界、限制、路线图和历史实测记录。

## 项目结构

```text
alphasift/
├── SKILL.md                # Skill 描述，给 AI Agent 读取
├── strategies/             # 选股策略 YAML
├── docs/
│   ├── configuration.md    # 配置参考
│   ├── design.md           # 设计原则
│   ├── positioning.md      # 项目定位
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
    ├── snapshot.py         # 全市场快照，4 种数据源 + 自动降级
    ├── filter.py           # L1 硬筛
    ├── scorer.py           # 评分计算
    ├── ranker.py           # L2 LLM 排序
    ├── risk.py             # 独立风险层
    ├── post_analysis.py    # L3 可插拔后置分析器
    ├── dsa.py              # 可选 DSA 接入
    ├── store.py            # 运行结果持久化
    ├── evaluate.py         # T+N 后验评估与批量评估聚合
    ├── pipeline.py         # 主流程编排
    └── strategy.py         # 策略 YAML 加载
```

## 与 daily_stock_analysis 的关系

- README、代码和环境变量中提到的 `DSA`，指的是外部单股深度分析服务 `daily_stock_analysis`。
- `alphasift` 负责全市场候选发现、硬筛、横向评分和 LLM 候选排序。
- `daily_stock_analysis` 负责单只股票的深度分析，默认通过 `POST /api/v1/analysis/analyze` 提供服务。
- 两者通过 `DSA_API_URL` 解耦部署；`daily_stock_analysis` 不属于本仓库，但可以作为本仓库的 L3 分析后端。
- 为控制成本，`alphasift` 只会在最终入围候选上调用 DSA；DSA 返回的结构化结果会在最后阶段影响 `final_score`、风险判断和最终名次。
- 默认使用内置 `scorecard`；也可以追加 DSA，或接入 `external_http` 形式的自定义评分工具。

## 数据源边界

支持五种 A 股全市场快照数据源，自动按优先级降级。未显式设置 `SNAPSHOT_SOURCE_PRIORITY` 时，无 Tushare token 默认链路是 `sina` -> `efinance` -> `akshare_em` -> `em_datacenter`；有 token 默认链路是 `tushare` -> `sina` -> `efinance` -> `akshare_em` -> `em_datacenter`。

| 数据源 | 接口 | 特点 |
|--------|------|------|
| `sina` | vip.stock.finance.sina.com.cn | 直连全市场源，含 PE/PB/换手率/市值字段 |
| `efinance` | push2.eastmoney.com | 实时推送，交易时段最快 |
| `akshare_em` | 82.push2.eastmoney.com | 实时推送，备选 |
| `em_datacenter` | data.eastmoney.com | 选股器 API，非交易时段可用 |
| `tushare` | Tushare Pro `daily` + `daily_basic` | 最近交易日数据，需 `TUSHARE_TOKEN`，非实时 |

周末或节假日 push2 接口不可用时，会自动降级到 `em_datacenter`。如果某个数据源超时、不可用或缺少当前策略必需字段，例如 PB，系统会跳过该源继续尝试后续来源。AlphaSift 对 efinance、AkShare、Baostock、Tushare、yfinance 这类 wrapper 源增加 caller-side timeout，并继续通过 source-health 熔断、daily history cache 和 snapshot last-good cache 暴露 `fallback_used/stale/stale_age_hours/source_errors` 等质量语义；如设置 `SNAPSHOT_FALLBACK_MAX_AGE_HOURS`，超过该年龄的缓存不会被使用。

## 参考项目取舍

- [`simonlin1212/a-stock-data`](https://github.com/simonlin1212/a-stock-data)：明确优先使用通达信/腾讯等低封禁源，东财只用于独有数据，并对东财直连请求做共享 session、串行限流、随机抖动和重试。AlphaSift 已采用直接 HTTP 源优先、wrapper 超时、东财共享重试会话与 `ALPHASIFT_EASTMONEY_*` 限流参数。
- [`akfamily/akshare`](https://github.com/akfamily/akshare)：覆盖面广、调用简单，但官方说明强调数据风险和接口可能变动。AlphaSift 保留 AkShare 作为备源或可选 provider，不再让它成为唯一关键路径。
- [`microsoft/qlib`](https://github.com/microsoft/qlib)：强调本地数据准备、数据健康检查和可重复研究 workflow。AlphaSift 对应补上 `doctor data-sources`、source-health JSON、daily quality flags、saved-run/evaluate 闭环。
- [`ricequant/rqalpha`](https://github.com/ricequant/rqalpha) 与 [`zvtvz/zvt`](https://github.com/zvtvz/zvt)：都把数据层/策略层解耦，支持扩展 provider 或本地持久化后再选股。AlphaSift 保持策略 YAML、数据源 fallback、last-good cache 与上层 DSA/API 解耦，而不是把某个免费源写死成强依赖。

## 已知限制

- 依赖日 K 的策略只对 L1 后 Top N 候选做增强；这不是完整历史数据库或全市场回测系统。
- `dsa` 后置分析器依赖外部 `daily_stock_analysis` 服务，当前按同步 REST 请求逐只调用，更适合最终名单的低频深度分析。
- L1/L2 主评分仍以快照横截面数据为主；任意 L3 后置分析器都只在最终阶段做覆盖和分数修正，不参与全市场初筛。
- `tushare` 兜底源依赖用户自己的 Pro token、接口积分和权限；当前取最近交易日收盘数据，不提供实时盘口。
- T+N 评估基于保存时价格与评估时最新快照价格，不等同严谨事件回测；可扣减交易成本、标记突破/回踩后验形态，并可选抓取日 K 路径估算最大回撤/最大浮盈，但暂不处理分红、停牌和调仓约束。
- 仓库内同时保留 `strategies/` 与 `alphasift/strategies/` 两份策略镜像用于开发态和安装态；内置策略文件需保持一致，但 `strategies/` 允许新增自定义 YAML。

## 改进路线

对照同类智能投研项目，AlphaSift 后续优先补这些能力：

- **数据可靠性**：已补 `tushare` 兜底、wrapper 调用超时、source-health 熔断与 last-good/stale fallback；下一步做多源字段对账、数据新鲜度标记、异常值报告和缓存命中可视化。
- **事件归因闭环**：把新闻、公告、资金流的事件标签纳入 `evaluate-batch` 统计，区分哪些事件真的改善后验表现。
- **回测边界**：在现有 T+N 评估上继续补持仓约束、调仓周期、逐日权益曲线和复权处理；完整量化研究可对接 Qlib 或 Backtrader。
- **Agent 产物**：把一次选股运行输出为稳定的 Markdown/JSON 报告包，便于被通知助手、Web UI 或 MCP/HTTP 服务消费。
- **策略研发**：增加策略 profile 模板、参数版本对比和失败样本复盘，让 YAML 策略迭代更可控。

## 实测记录

### 2026-04-12（周六，非交易时段）

测试环境：Python 3.12，数据来源为上一交易日（2026-04-10）收盘数据。

- efinance / akshare 实时推送接口在非交易时段不可用，当时自动降级到 `em_datacenter`（东方财富选股器 API）。
- 当前默认链路支持 Tushare；配置 token 且未手工指定 `SNAPSHOT_SOURCE_PRIORITY` 时会优先使用 Tushare。本次记录未配置 Tushare token，未触发该源。
- 未启用 LLM 排序（`--no-llm`）。

#### 双低选股（dual_low）

全市场 5190 只 -> 硬筛后 337 只 -> 输出 Top 5

| 排名 | 代码 | 名称 | 得分 | 价格 | 涨跌幅 | PE | PB |
|------|------|------|------|------|--------|-----|-----|
| 1 | 002039 | 黔源电力 | 72.7 | 20.72 | -2.49% | 14.76 | 1.99 |
| 2 | 002444 | 巨星科技 | 71.0 | 30.82 | +0.29% | 14.59 | 1.95 |
| 3 | 002128 | 电投能源 | 70.9 | 31.60 | -2.41% | 14.00 | 1.90 |
| 4 | 002236 | 大华股份 | 70.8 | 17.43 | +1.04% | 14.86 | 1.50 |
| 5 | 600583 | 海油工程 | 68.9 | 7.02 | +4.15% | 14.89 | 1.17 |

#### 放量突破（volume_breakout）

全市场 5190 只 -> 硬筛后 126 只 -> 输出 Top 5

| 排名 | 代码 | 名称 | 得分 | 价格 | 涨跌幅 |
|------|------|------|------|------|--------|
| 1 | 002837 | 英维克 | 74.0 | 99.05 | +6.40% |
| 2 | 688183 | 生益电子 | 73.8 | 95.30 | +7.09% |
| 3 | 300803 | 指南针 | 73.3 | 101.68 | +3.07% |
| 4 | 002384 | 东山精密 | 73.0 | 143.55 | +8.83% |
| 5 | 300277 | 汽轮科技 | 73.0 | 19.74 | +5.73% |

#### 数据源降级验证

| 数据源 | 状态 | 说明 |
|--------|------|------|
| efinance（push2.eastmoney.com） | 不可用 | 实时推送接口，非交易时段返回空响应 |
| akshare_em（82.push2.eastmoney.com） | 不可用 | 同上 |
| em_datacenter（data.eastmoney.com） | 可用 | 选股器 API，周末仍返回最近交易日数据 |
| tushare（Tushare Pro） | 未触发 | 当前已支持，需 `TUSHARE_TOKEN` |

降级链路验证通过：`efinance` -> `akshare_em` -> `em_datacenter`，自动切换到可用数据源。
