# AlphaSift

**为 AI Agent 设计的全市场选股引擎。** AlphaSift 扫描全部 A 股（其他六个市场为市值较大的上市股票），用可审计的 YAML 策略筛选打分，可选地让 LLM 对入围候选做横向排序，让最终结果在行业上尽量分散，并保存每次运行，方便事后检验选得准不准。

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
![Markets](https://img.shields.io/badge/markets-CN%20%7C%20US%20%7C%20HK%20%7C%20JP%20%7C%20KR%20%7C%20TW%20%7C%20IN-orange)

[English](README.md) | 中文

```text
全市场 ──► L1 硬筛 + 因子打分 ──► L2 LLM 横向排序（可选）
(5000+ 只)   (YAML 策略，无需 API key)    (候选池内跨股票比较)
                                               │
保存运行 ◄── L3 后置分析 ◄── 风险层 + 行业分散上限
   │        (scorecard / DSA / HTTP)
   └──► T+N 评估：收益、胜率、失败样本复盘
```

## 为什么用 AlphaSift

- **以 A 股为主，另有六个市场（测试阶段）**：A 股走专门的多数据源链路；美股、港股、日本、韩国、台湾、印度走 Yahoo Finance 筛选器，海外服务器和 CI 上也能用，但只有一个非官方数据源、字段也更少（见“已知限制”）。
- **不配 API key 也能跑**：L1 筛选、打分、风险和行业分散都是确定性的；配置了 LLM 才会对入围候选做重排。
- **策略是 YAML，不是代码**：硬筛条件、因子权重、评分曲线、风险阈值、行业桶都写在可读、可 diff、可审查的文件里。
- **不会一股脑全选同一个行业**：每只候选都带行业/板块标签，`portfolio_profile.mode: hard_cap` 保证 Top N 中同一行业不超过 N 只。
- **数据源自愈**：各数据源的成败跨运行保存，坏掉的源自动排到最后；每个源都有时间预算；所有实时源都失败时使用上次成功的快照，并明确标记为过期数据。
- **每次运行都能检验**：保存运行结果，之后按 T+N 评估收益、胜率、交易成本和失败样本，可选抓取日 K 路径计算最大回撤和最大浮盈。
- **为 Agent 设计**：[SKILL.md](SKILL.md) 描述可调用接口；`alphasift serve` 提供只读 JSON API，供面板和编排层使用。

## 快速开始

```bash
pip install -e .

# A 股，无需 API key
alphasift screen dual_low --no-llm

# 其他市场：us、hk、jp、kr、tw、in
alphasift screen global_value --market hk --no-llm

# 启用 LLM 排序：先在 .env 中配置 GEMINI_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY
# （或 LITELLM_MODEL / LLM_CHANNELS）
cp .env.example .env
alphasift screen dual_low

# 保存运行，几天后评估效果
alphasift screen dual_low --no-llm --save-run
alphasift evaluate <run_id> --with-price-path --explain
```

`alphasift quickstart` 是无需 key 的引导演示，`alphasift strategies` 列出全部策略。

## 输出示例

以下是 2026-11-03 使用 `--no-llm` 的真实运行结果。**只用于展示引擎输出，不构成任何推荐。**

**A 股**（`dual_low`）：全市场 5218 只，硬筛后 284 只，Top 5 每个行业最多 2 只

| # | 代码 | 名称 | 行业 | PE | PB |
|---:|---|---|---|---:|---:|
| 1 | 601169 | 北京银行 | 银行 | 5.8 | 0.43 |
| 2 | 600016 | 民生银行 | 银行 | 5.7 | 0.26 |
| 3 | 601668 | 中国建筑 | 建筑施工 | 6.6 | 0.39 |
| 4 | 601186 | 中国铁建 | 基础建设 | 6.3 | 0.29 |
| 5 | 601919 | 中远海控 | 港口航运 | 7.9 | 1.12 |

**港股**（`global_value --market hk`）：581 只，硬筛后 275 只

| # | 代码 | 名称 | 板块 | PE | PB |
|---:|---|---|---|---:|---:|
| 1 | 0998.HK | 中信银行 | Financial Services | 5.8 | 0.43 |
| 2 | 0267.HK | 中信股份 | Industrials | 5.3 | 0.38 |
| 3 | 1398.HK | 工商银行 | Financial Services | 6.5 | 0.59 |
| 4 | 0001.HK | 长和 | Industrials | 6.9 | 0.45 |
| 5 | 0358.HK | 江西铜业 | Basic Materials | 5.7 | 0.77 |

**日本**（`global_value --market jp`）：773 只，硬筛后 408 只

| # | 代码 | 名称 | 板块 | PE | PB |
|---:|---|---|---|---:|---:|
| 1 | 9501.T | 东京电力 | Utilities | 2.6 | 0.21 |
| 2 | 9022.T | JR 东海 | Industrials | 7.2 | 0.71 |
| 3 | 9502.T | 中部电力 | Utilities | 10.6 | 0.66 |
| 4 | 1911.T | 住友林业 | Consumer Cyclical | 9.0 | 0.70 |
| 5 | 7203.T | 丰田汽车 | Consumer Cyclical | 8.7 | 0.97 |

在海外服务器上，数据源健康记录生效后 A 股一次选股约 10 秒；Yahoo 市场每次 2–10 秒。

## 支持的市场

| `--market` | 市场 | 快照数据源 | 说明 |
|---|---|---|---|
| `cn` | A 股 | sina → efinance → akshare_em → em_datacenter（配置 token 时 Tushare 优先） | 按健康度排序数据源；缺行业时用东财行业映射补全 |
| `us` | 美股 | Yahoo 筛选器（NYSE / Nasdaq 上市、市值 ≥ 10 亿美元，含 ADR） | 设置 `ALPHASIFT_US_TICKERS` 时改用指定的股票列表 |
| `hk` | 港股 | Yahoo 筛选器 | 股票池市值下限约 80 亿港元 |
| `jp` | 日本 | Yahoo 筛选器 | 股票池市值下限约 1500 亿日元 |
| `kr` | 韩国 | Yahoo 筛选器 | Yahoo 不提供韩股 PE/PB，估值类策略无法运行 |
| `tw` | 台湾 | Yahoo 筛选器 | 含上市（TWSE）和上柜（TPEx） |
| `in` | 印度 | Yahoo 筛选器 | 含 NSE 和 BSE |

非 A 股代码使用 Yahoo 代码（`AAPL`、`0700.HK`、`7203.T`、`005930.KS`）。这些市场的日 K 增强和 T+N 评估使用 yfinance；候选级新闻、公告、资金流上下文目前只支持 A 股。

## 内置策略

| 策略 | 市场 | 类型 | 思路 |
|---|---|---|---|
| `dual_low` | cn | 价值 | 低 PE + 低 PB，叠加活跃度与稳定性确认，按行业硬性分散 |
| `quality_value` | cn | 价值 | 合理估值，兼顾流动性和波动控制 |
| `blue_chip_income` | cn | 红利 | 高流动性蓝筹与分红质量 |
| `low_volatility_quality` | cn | 质量 | 基于日 K 波动、回撤、ATR 的防御型筛选 |
| `volume_breakout` | cn | 趋势 | 放量突破压力位 |
| `shrink_pullback` | cn | 趋势 | 上升趋势中缩量回踩支撑（需日 K） |
| `capital_heat` | cn | 动量 | 资金活跃但不过热 |
| `oversold_reversal` | cn | 反转 | 回撤可控的修复候选 |
| `balanced_alpha` | cn | 框架 | 通用多因子发现 |
| `momentum_quality` | cn | 框架 | 趋势确认 + 质量过滤 |
| `global_value` | us, hk, jp, tw, in | 价值 | `dual_low` 的多市场版本，不使用与币种相关的绝对阈值 |
| `us_momentum_quality` | us | 趋势 | 美股大盘股动量 + 质量 |

自定义策略放在 `strategies/` 下，写法见[策略编写指南](docs/strategy-guide.md)。

## 配置

复制 `.env.example` 为 `.env`。AlphaSift 兼容 LiteLLM 风格配置，可以直接复用 [daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) 的配置。常用项：

| 变量 | 作用 | 默认值 |
|---|---|---|
| `LITELLM_MODEL` | 主模型，格式 `provider/model` | `gemini/gemini-2.5-flash` |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` | LLM 排序所用的供应商 key | - |
| `LLM_CHANNELS` / `LITELLM_CONFIG` | 多渠道或 LiteLLM Router 配置 | - |
| `TUSHARE_TOKEN` | A 股数据源链路中 Tushare 优先 | - |
| `SNAPSHOT_SOURCE_PRIORITY` | 手动指定 A 股数据源顺序 | 取决于是否配置 token |
| `ALPHASIFT_SNAPSHOT_CALL_TIMEOUT_SEC` | 单个快照源的时间预算 | `60` |
| `INDUSTRY_AUTO_BACKFILL` | 自动补全缺失的 A 股行业标签 | `true` |
| `ALPHASIFT_DATA_DIR` | 运行记录、缓存、数据源健康记录目录 | `./data` |
| `DSA_API_URL` | 启用可选的 DSA 单股深度分析 | - |

完整列表见 [docs/configuration.md](docs/configuration.md)。

## 更多功能

- **Python API**：`from alphasift import screen, evaluate_saved_run`，然后 `screen("dual_low", use_llm=False, market="cn")`。
- **LLM 上下文**：`--context "..."` 追加市场判断，`--candidate-context-file` 追加逐只候选的研究摘要。
- **L3 后置分析**：默认运行本地 `scorecard`；`--post-analyzer dsa` 会把最终名单交给 [daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) 做单股深度分析。
- **热点发现**：`alphasift hotspots` 和 `alphasift hotspot "<主题>"` 对 A 股题材做热度排序，并解析龙头股，附带缓存和降级元数据。
- **Agent / UI 接口**：`alphasift overview --json`、`alphasift serve`、`alphasift doctor data-sources --all-strategies --explain`，端点列表见[使用指南](docs/usage.md)。

## 已知限制

- AlphaSift 是候选发现与排序引擎，不是回测或交易执行系统。T+N 评估比较的是保存时价格与之后的价格，不处理分红、停牌和持仓约束。
- T+N 按自然日计算，还没有使用各交易所的交易日历。
- Yahoo 筛选器市场并不是全市场：股票池是市值约 10 亿美元以上、按 Yahoo 板块逐个查询的上市股票，最多 4000 行；只依赖一个非官方接口；成交额按 价格 × 成交量 估算，流通市值用总市值代替；韩国市场没有估值字段；只有交易币种和财报币种一致时才用每股收益、每股净资产推算 PE/PB。
- 依赖日 K 的策略只对 L1 入围候选做增强，不覆盖全市场。
- `strategies/` 与 `alphasift/strategies/` 是开发态和安装态的两份镜像，内置策略需保持一致。

## 免责声明

本项目仅用于学习、研究和工程实验，不构成任何投资建议、收益承诺或买卖指引。行情数据、LLM 输出和策略参数都可能延迟、缺失或出错。使用者需自行研究、判断合规性和交易成本，并对自己的决策负责。

## 文档

[使用指南](docs/usage.md) · [配置参考](docs/configuration.md) · [策略编写指南](docs/strategy-guide.md) · [评分体系](docs/scoring.md) · [设计原则](docs/design.md) · [项目定位](docs/positioning.md) · [横向比较](docs/comparison.md) · [参考资料](docs/reference.md) · [更新记录](docs/CHANGELOG.md) · [SKILL.md](SKILL.md)

## License

[Apache License 2.0](LICENSE)
