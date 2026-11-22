<div align="center">

<a href="https://zhulinsen.github.io/alphasift/?lang=zh">
  <img src="docs/assets/alphasift-logo.svg" alt="AlphaSift Logo" width="480">
</a>

简体中文 | [English](README.en.md) | [日本語](README.ja.md)

# 🔎 AlphaSift

**AI 量化选股引擎**

*A股 / 美股 / 港股 / 日韩台印全市场多因子筛选 → AI 情报复核与排雷 → 公开 T+N 纸面跟踪验证*

[![GitHub stars](https://img.shields.io/github/stars/ZhuLinsen/alphasift?style=social)](https://github.com/ZhuLinsen/alphasift/stargazers)
[![Live Dashboard](https://img.shields.io/badge/Live%20Dashboard-GitHub%20Pages-0ea5e9.svg)](https://zhulinsen.github.io/alphasift/?lang=zh)
[![MCP Ready](https://img.shields.io/badge/MCP-STDIO%20Ready-8b5cf6.svg)](docs/ecosystem.md)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3b82f6.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-10b981.svg)](LICENSE)

[**在线看板**](https://zhulinsen.github.io/alphasift/?lang=zh) · [**核心亮点**](#-为什么用-alphasift) · [**30 秒上手**](#-30-秒极速上手) · [**硬核实证**](#-硬核实证与系统架构) · [**量化铁三角**](#-quant-trio-开源量化铁三角) · [**Agent Skill**](SKILL.md)

</div>

> [!TIP]
> 🚀 **与 [daily_stock_analysis（73.6k★）](https://github.com/ZhuLinsen/daily_stock_analysis) 同源配套**：**AlphaSift** 负责每天盘后从全市场 `5,000+` 标的中初筛高共识候选并公开跟踪 `T+N` 胜率；**DSA** 负责单股深度研报与操作决策；[**AlphaEvo**](https://github.com/ZhuLinsen/alphaevo) 负责进化式因子挖掘与验伪。

---

## 🖥️ 无需安装，在线直看今日选股与公开纸面战绩

👉 **[点击打开公开在线看板（zhulinsen.github.io/alphasift）](https://zhulinsen.github.io/alphasift/?lang=zh)** — 每交易日盘后自动更新 7 大市场多策略共识精选、`T+5 / T+10 / T+20` 收益榜，以及可选 **AI 复核 vs 纯规则** 同日对照赛道。

<p align="center">
  <a href="https://zhulinsen.github.io/alphasift/?lang=zh">
    <img src="docs/assets/dashboard-preview.gif" alt="AlphaSift 在线看板交互演示（深/浅主题与多语言实时切换）" width="840">
  </a>
  <br><sub>点击动图直达在线看板 · 支持 Dark / Light 主题及 <code>中 | EN | 日</code> 一键切换</sub>
</p>

<details>
<summary><strong>查看更多静态高清截图与可打印独立盘后研报（<code>alphasift daily-report --output-html</code>）</strong></summary>

<table>
  <tr>
    <td width="50%" align="center">
      <a href="https://zhulinsen.github.io/alphasift/?lang=zh&theme=dark">
        <img src="docs/assets/dashboard-zh.png" alt="AlphaSift 在线看板（暗色 · 中文）" width="100%">
      </a>
      <br><sub><b>Obsidian Dark 终端</b> — 跨策略共识精选、A 股宽度与 7 市场领跑榜</sub>
    </td>
    <td width="50%" align="center">
      <a href="https://zhulinsen.github.io/alphasift/?lang=en&theme=light">
        <img src="docs/assets/dashboard-light.png" alt="AlphaSift 在线看板（亮色 · 多语言）" width="100%">
      </a>
      <br><sub><b>Editorial Paper Light</b> — 中/英/日实时切换与审计账本</sub>
    </td>
  </tr>
  <tr>
    <td colspan="2" align="center">
      <a href="docs/usage.md">
        <img src="docs/assets/daily-report.png" alt="AlphaSift 独立可打印盘后投研日报" width="88%">
      </a>
      <br><sub><b>可打印独立盘后研报</b>（<code>alphasift daily-report --output-html</code>）— 盘后综述、7 档涨跌分布、公告排雷与 20 日迷你 K 线</sub>
    </td>
  </tr>
</table>

</details>

---

## ✨ 为什么用 AlphaSift

多数 AI 选股工具只能“针对几只自选股聊天分析”，或拿美化后的历史片段截图讲故事，既难跨全市场扫雷，也没人敢公开事后账本。**AlphaSift 把全市场筛选、情报排雷与事后验真做成了一个公开透明的闭环：**

1. **全市场自动挑股（零 API Key 也能跑）**：覆盖 A股、美股、港股、日本、韩国、台湾、印度 7 大市场，内置 12 套公开可读的 YAML 量化策略与行业分散约束，每天几十秒跑完 `5,000+` 标的。
2. **不吹票、代码级硬排雷、每天公开验真**：接入大模型时（默认 `gemini/gemini-3.8-flash` + `gemini/gemini-4-hydrogen` 自动兜底），先注入实时公告、新闻与资金流上下文，遇未消除重大利空在 Python 代码层面硬封顶 **`<= 35` 分**；所有入选标的记录至公开 [`track-record`](https://github.com/ZhuLinsen/alphasift/tree/track-record) 账本，按 `next_open` 扣除一字涨停核算 `T+5 / T+10 / T+20` 超额收益，同日实测 AI 到底有没有跑赢纯规则。
3. **零成本定时运行 + 一句话接 AI 助手**：支持免费 GitHub Actions 每天盘后跑并推送到飞书/企微/Telegram/Discord/邮件等 12 个渠道（Fork 后默认只推送不发布重复网页）；内置零依赖 STDIO **MCP Server**（`alphasift mcp`）和本机 **Web 工作台**（`alphasift serve` → `/ui`）。

---

## ⚡ 30 秒极速上手

### 1. 接入 Claude Code / OpenClaw / Cursor / Codex（原生 MCP）

安装 AlphaSift 后，在客户端 MCP 配置加入 5 行 JSON 即可让 AI 助手直接调用 `10` 个只读量化工具（默认不触发外发推送）：

```json
{
  "mcpServers": {
    "alphasift": { "command": "alphasift", "args": ["mcp"] }
  }
}
```

> *上方为 Claude Code / Cursor JSON 写法；Codex（`mcp_servers` TOML）与 OpenClaw（`mcp.servers`）写法见 [docs/ecosystem.md](docs/ecosystem.md)。*

**接好后直接用自然语言提问：**
- *“用 AlphaSift 跑一遍今天低估且没有公告利空的 A 股 `dual_low` 策略，给出前 5 只及入选理由”*
- *“对比 `dual_low` 和 `quality_value` 的筛选条件与权重偏向，我更适合震荡市还是趋势市？”*
- *“用 `global_value` 扫描港股和日股无 LLM 初筛结果，按行业分组列出来”*

---

### 2. 本机命令行、交互式 Web 工作台 & Docker

可直接从 [`v0.3.0` Release](https://github.com/ZhuLinsen/alphasift/releases/tag/v0.3.0) 安装独立 wheel 包，或源码可编辑安装：

```bash
# 方式 A：直接安装 v0.3.0 Release Wheel
pip install https://github.com/ZhuLinsen/alphasift/releases/download/v0.3.0/alphasift-0.3.0-py3-none-any.whl

# 方式 B：源码克隆安装
git clone https://github.com/ZhuLinsen/alphasift.git && cd alphasift
pip install -e .
```

**无 API Key 立即出结果：**
```bash
alphasift quickstart                            # 30 秒端到端演示
alphasift screen dual_low --no-llm              # 跑 A 股双低纯规则筛选
alphasift screen global_value --market hk --no-llm   # 扫描港股低估值
alphasift serve --host 127.0.0.1 --port 8765    # 打开本机交互式 Web 工作台 (/ui)
# 或用 Docker Compose 在同一回环端口启动：
docker compose up --build -d
```

**可选开启 AI 情报复核、250 日回放与可打印研报：**
```bash
cp .env.example .env                            # 填入 GEMINI_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY
alphasift pack build --days 250                 # 首次构建本地 A 股日线包
alphasift screen dual_low --save-run
alphasift evaluate-strategies --window 5,10,20 --explain
alphasift daily-report --pack-dir ./data/pack/cn --output-html daily_report.html --push
```

---

### 3. 免费云端每日自动选股与推送（Fork 防撞车）

1. **Fork 本仓库**并启用 **GitHub Actions**。
2. 在 *Settings → Secrets and variables → Actions → Secrets* 按需添加可选密钥：
   - `GEMINI_API_KEY`（或 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`）：开启每日 AI 对照赛道与盘后综述；不填则静默跑纯规则赛道。
   - `NOTIFY_URLS`：一行接入 12 种原生推送通道（无配置自动跳过）。
3. **Plan A Fork 安全护栏**：他人 Fork 后默认**只跑每日筛选与推送，跳过重复官网构建**，避免一 Fork 就挂出一份一模一样的站点；如确实要在 Fork 发布独立网页，在 *Variables* 设置 `ALPHASIFT_ENABLE_PAGES=true` 并开启 *Settings → Pages → GitHub Actions*。详细步骤见 [部署与镜像指南](docs/deployment.md)。

---

## 📊 硬核实证与系统架构

| 维度 | 传统条件选股（东财 / TradingView） | 单股 AI 研报（`daily_stock_analysis`） | **AlphaSift** |
|---|---|---|---|
| **覆盖范围** | 单市场人工点选指标 | 聚焦已给定的自选股池 | **7 大市场全量初筛（A股 / 美 / 港 / 日 / 韩 / 台 / 印）** |
| **规则与分散度** | 封闭黑盒或人工拼指标 | 偏重个股长文叙事 | **透明 YAML DSL + 8 行业桶硬上限正交分散** |
| **AI 幻觉约束** | 无 | 偏叙事分析 | **公告/资讯/资金流上下文 + 重大利空 `<= 35` 硬封顶** |
| **事后真实性** | 无持续记录 | 需人工回看 | **公开 `track-record` 账本（`next_open` 扣除一字涨停）** |

- **策略正交分散实证**：A 股 10 套策略经 8 行业桶硬上限重构后（`hard_cap` / `max_same_bucket: 1`），250 日 3 时点回测策略两两平均重合度由 **8.0%–24.9% 降至 0.9%–1.8%**（最大单对 `100% → 20%`），银行单板块占比由 **22%–31.1% 降至 4.0%–9.1%**。
- **250 日实证形态雷达（`next_open` vs 沪深 300 与 All-A 等权）**：在 `2026-02-05 .. 2026-11-06`（180 交易日、5,218 只 A 股、`next_open` 排除开盘一字涨停，共内置 **9 套**无状态形态）回放中，形态须同时满足 `T+5 样本 >= 200`、扣除 `25bp` 往返成本后相对沪深 300 与同日全 A 等权均值均为正、Bartlett Newey-West HAC 检验 `t >= 2.0`、BH-FDR 多重检验校正 `q <= 0.05` 且前/后半样本（`H1/H2 >= 15d & >= 30`）同向为正，方可晋级 `active`。当前 **`红三兵回踩确认`**、**`红三兵`** 与其余 7 套经典形态均暂列 **`experimental` 观察期**，并在日报与看板中披露净超额与检验指标；负期望观察形态在推送卡片中自动折叠对照。

```
+-------------------------------------------------------------------+
|  7 市场实时快照链路  +  私有离线日线包 DailyPack (actions/cache)  |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
|  L1 确定性底座：YAML 硬筛选规则 + 多因子打分曲线                  |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
|  L2 情报红线 AI 复核 + 候选上下文注入（重大负面 <= 35 分封顶）    |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
|  风险过滤覆盖层 + 8 行业桶硬上限分散（max_same_bucket: 1）        |
+----------------+--------------------------------+-----------------+
                 |                                |
                 v                                v
+---------------------------------+  +------------------------------+
|  L3 后置分析 (scorecard / DSA)  |  |  track-record 公开可审计账本 |
|  独立 HTML 研报 & 12 通道推送   |  |  next_open T+5/10/20 验收    |
+---------------------------------+  +------------------------------+
```

---

<details>
<summary><strong>内置 12 套 YAML 策略清单（点击展开参数与覆盖范围）</strong></summary>

| 策略名 | 适用市场 | 类型 | 核心思路 |
|---|---|---|---|
| `dual_low` | `cn` | 价值 | 中小盘双低（`50–600 亿` 市值，低 PE + 低 PB），行业桶硬上限 `1` |
| `blue_chip_income` | `cn` | 红利 | 超大盘高流动性高股息蓝筹（`≥ 500 亿` 市值） |
| `quality_value` | `cn` | GARP 成长 | 中盘稳健估值 + MA20 趋势确认（`80–1200 亿` 市值） |
| `low_volatility_quality` | `cn` | 质量防御 | 基于日 K 20 日波动率、最大回撤与 ATR 的低波防线 |
| `balanced_alpha` | `cn` | 均衡框架 | 跨因子综合发现，强制行业正交分散 |
| `momentum_quality` | `cn` | 趋势质量 | 60 日中期趋势确认 + 基本面质量硬过滤 |
| `shrink_pullback` | `cn` | 回踩趋势 | 上升趋势中缩量回踩支撑位（需日 K） |
| `capital_heat` | `cn` | 资金动量 | 换手与量比活跃但剔除短期过热追高 |
| `oversold_reversal` | `cn` | 超跌修复 | 短期超跌 + 回撤受控的均值回复候选 |
| `volume_breakout` | `cn` | 放量突破 | 成交量显著放大并突破关键压力区间 |
| `global_value` | `us, hk, jp, kr, tw, in` | 多市场价值 | 去除币种绝对阈值的 `dual_low` 跨市场版本 |
| `us_momentum_quality` | `us` | 美股趋势 | 美股大盘动量 + 质量精选（`>= $2B`） |

</details>

<details>
<summary><strong>一行 <code>NOTIFY_URLS</code> 12 种原生推送通道 & Atom RSS 订阅</strong></summary>

无需额外推送依赖，用一个逗号/换行分隔的 `NOTIFY_URLS` 变量即可同时触发多个渠道（完全兼容传统独立环境变量，报错与日志自动脱敏 Token，共享 `(trade_date, channel)` 文件双锁防重复推送）：

```bash
NOTIFY_URLS="pushplus://TOKEN,sct://SENDKEY,bark://api.day.app/KEY,mailto://sender@qq.com:auth@qq.com?to=a@qq.com,https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
```

| 通道 | 一行 `NOTIFY_URLS` 写法 | 独立环境变量（兼容） |
|---|---|---|
| **PushPlus** | `pushplus://TOKEN[/TOPIC]` | `PUSHPLUS_TOKEN`, `PUSHPLUS_TOPIC` |
| **Server酱 / Server酱3** | `sct://SENDKEY`（兼容 `SCT...` 与 `sctp123t...`） | `SERVERCHAN_SENDKEY` |
| **Bark** | `bark://KEY` 或 `bark://host/KEY` | `BARK_URL` |
| **Email 邮件** | `mailto://user:pass@host[:port]?to=a,b` | `EMAIL_SENDER`, `EMAIL_PASSWORD`, `EMAIL_RECEIVERS` |
| **企业微信** | `wecom://KEY` 或完整 Webhook URL | `WECOM_WEBHOOK_URL` |
| **飞书** | `feishu://TOKEN[#secret=SEC]` 或完整 URL | `FEISHU_WEBHOOK_URL`, `FEISHU_WEBHOOK_SECRET` |
| **钉钉** | `dingtalk://TOKEN[#secret=SEC]` 或完整 URL | `DINGTALK_WEBHOOK_URL`, `DINGTALK_WEBHOOK_SECRET` |
| **Telegram** | `tgram://BOT_TOKEN/CHAT_ID` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| **Discord** | `discord://ID/TOKEN` 或完整 URL | `DISCORD_WEBHOOK_URL` |
| **Slack** | `slack://T.../B.../...` 或 Webhook URL | `SLACK_WEBHOOK_URL` |
| **ntfy** | `ntfy://topic` 或 `https://ntfy.sh/topic` | `NTFY_URL` |
| **自定义 Webhook / Apprise** | `custom://https://...` 或任意 Apprise Scheme | `CUSTOM_WEBHOOK_URL`, `CUSTOM_WEBHOOK_TOKEN` |

公开看板页脚同时输出 Atom 1.0 RSS：[`site/feed.xml`](https://zhulinsen.github.io/alphasift/site/feed.xml)。本地可通过 `alphasift notify status` 与 `alphasift notify test --dry-run` 检查配置。

</details>

<details>
<summary><strong>7 市场数据源链路、独立示例输出与关键环境变量</strong></summary>

| 市场 ID | 数据源链路 | 说明 |
|---|---|---|
| `cn` | `em_datacenter → sina → efinance → akshare_em`（配置 `TUSHARE_TOKEN` 时优先 `tushare`） | A 股全市场 + 东财行业补全 + 公告排雷 + 私有离线包 |
| `us, hk, jp, tw, in` | Yahoo Finance 筛选器 + `yfinance` | 海外服务器直连可用，仅依赖单一非官方接口 |
| `kr` | Yahoo Finance + Naver Finance | 从 Naver 补充韩股 PE/PB（`ALPHASIFT_KR_VALUATION=0` 可关闭） |

- **2026-11-20 `--no-llm` 离线样本示例**：A 股 `dual_low`（5,215 → 205 → 5 行业 Top 5：`601997` 贵阳银行、`601117` 中国化学、`600741` 华域汽车、`603799` 华友钴业、`601233` 桐昆股份）；港股 `global_value --market hk`（`0267.HK`、`0001.HK`、`1339.HK`、`1398.HK`、`0358.HK`）；日股 `global_value --market jp`（`9501.T`、`5401.T`、`1605.T`、`9104.T`、`9022.T`）。
- **核心环境变量**：`LITELLM_MODEL`（默认 `gemini/gemini-3.8-flash`）、`LITELLM_FALLBACK_MODELS`（`gemini/gemini-4-hydrogen`）、`GEMINI_API_KEY` / `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`、`LLM_CANDIDATE_CONTEXT_ENABLED=true`（CI Actions 默认开启；本地默认关闭）、`NOTIFY_URLS`、`ALPHASIFT_ENABLE_PAGES=true`（Fork 启用网页开关）、`DSA_API_URL`。详情见 [docs/configuration.md](docs/configuration.md)。
- **口径说明**：AlphaSift 为研究初筛与后验审计引擎，不构成投资建议或自动交易系统；公开账本在 `ALPHASIFT_NEXT_OPEN_SWITCH_DATE`（`2026-11-21`）前采用 `close` 入场口径，切换日起采用 `next_open` 并严格计量开盘一字涨停不可成交比例。

</details>

---

## 🔗 Quant Trio — 开源量化铁三角

| 项目 | 在链路中的定位 | 协同方式 |
|---|---|---|
| **[AlphaEvo](https://github.com/ZhuLinsen/alphaevo)** | 研究与因子挖掘 | 进化式发现与样本外检验 α 因子后，沉淀为 AlphaSift YAML 策略规则 |
| **[AlphaSift](https://github.com/ZhuLinsen/alphasift)** | **全市场筛选与公开验真** | 盘后从 7 市场 `5,000+` 标的精选高共识候选并公开跟踪 `T+5 / 10 / 20` |
| **[daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis)** | L3 个股深度精研 | 通过 `DSA_API_URL` 或 `alphasift mcp` 接收初筛名单，输出深度基本面与操作计划 |

更多架构说明、MCP Schema 与 Docker 教程见 [docs/ecosystem.md](docs/ecosystem.md)。

---

## 免责声明、文档索引与开源协议

> 本项目仅用于量化研究、开源工程验证与个人学习，不构成任何投资建议、收益承诺或买卖指令。行情源、大模型输出与形态统计均可能存在延迟或偏差。

[使用指南](docs/usage.md) · [配置参考](docs/configuration.md) · [生态与 MCP](docs/ecosystem.md) · [部署与镜像](docs/deployment.md) · [策略指南](docs/strategy-guide.md) · [评分体系](docs/scoring.md) · [输出契约](docs/result-schema.md) · [参考资料](docs/reference.md) · [参与贡献](CONTRIBUTING.md) · [安全策略](SECURITY.md) · [更新记录](docs/CHANGELOG.md) · [SKILL.md](SKILL.md)

基于 [Apache License 2.0](LICENSE) 开源。
