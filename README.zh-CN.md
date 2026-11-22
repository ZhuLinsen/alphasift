<div align="center">

<a href="https://zhulinsen.github.io/alphasift/?lang=zh">
  <img src="docs/assets/alphasift-logo.svg" alt="AlphaSift Logo" width="680">
</a>

# 🔎 AlphaSift

**AI 量化选股引擎**

*A股 / 美股 / 港股 / 日韩台印全市场多因子筛选 → AI 情报复核与排雷 → 公开 T+N 实盘验证*

[![GitHub stars](https://img.shields.io/github/stars/ZhuLinsen/alphasift?style=social)](https://github.com/ZhuLinsen/alphasift/stargazers)
[![CI](https://github.com/ZhuLinsen/alphasift/actions/workflows/ci.yml/badge.svg)](https://github.com/ZhuLinsen/alphasift/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3b82f6.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-10b981.svg)](LICENSE)
[![Live Dashboard](https://img.shields.io/badge/Live%20Dashboard-GitHub%20Pages-0ea5e9.svg)](https://zhulinsen.github.io/alphasift/?lang=zh)
[![7 Markets](https://img.shields.io/badge/Markets-CN%20%7C%20US%20%7C%20HK%20%7C%20JP%20%7C%20KR%20%7C%20TW%20%7C%20IN-6366f1.svg)](https://zhulinsen.github.io/alphasift/?lang=zh)
[![Agent Skill](https://img.shields.io/badge/Agent%20Skill-OpenClaw%20%7C%20Claude%20Code-10b981.svg)](SKILL.md)
[![MCP Ready](https://img.shields.io/badge/MCP-STDIO%20Ready-8b5cf6.svg)](docs/ecosystem.md)
[![Docker Ready](https://img.shields.io/badge/Docker-Ready-0284c7.svg)](Dockerfile)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/ZhuLinsen/alphasift/pulls)

[**在线看板**](https://zhulinsen.github.io/alphasift/?lang=zh) · [**核心亮点**](#-为什么选择-alphasift) · [**4 种零门槛用法**](#-4-种零门槛上手方式) · [**12 通道一行推送**](#-一行-12-通道推送notify_urls) · [**track-record 原始账本**](https://github.com/ZhuLinsen/alphasift/tree/track-record) · [**Agent Skill**](SKILL.md)

[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md)

</div>

---

## ✨ 为什么选择 AlphaSift

市面上多数 AI 选股项目要么停留在“看几只自选股聊天”，要么只挑好看的历史片断截图，缺乏跨全市场发现与严格的后验追责。**AlphaSift 把确定性多市场选股、情报驱动 AI 复核、与公开透明的 `T+N` 验真闭环合为一体：**

1. **零 Key 确定性底座与正交化分散**：L1 硬筛选、多因子评分、风险惩罚与 8 行业桶硬上限分散（`portfolio_profile.mode: hard_cap`、`max_same_bucket: 1`）无需任何 API Key 即可确定性运行。经本地 250 日数据包在 `2026-09-21`、`10-20`、`11-20` 三日回测，10 组 A 股策略正交重构后，两两平均重合度由 **8.0%–24.9% 降至 0.9%–1.8%**（最大单对 **100% → 20%**），银行占比由 **22%–31.1% 降至 4.0%–9.1%**。
2. **250 日实盘口径形态雷达**：所有无状态 K 线形态均须经 `next_open` 基准回放检验（`T+5 匹配样本 ≥ 200` 且相对沪深 300 超额 `> 0%`），通过门槛的 2 个形态标记为 `active`，其余 5 个经典形态仅作 `experimental` 置灰观察。
3. **情报驱动 AI 红线复核赛道**：默认主模型 **`gemini/gemini-3.8-flash`**（自动挂载 `gemini/gemini-4-hydrogen` 回退，亦支持 DeepSeek / OpenAI / Ollama）。CN AI 赛道默认开启 `LLM_CANDIDATE_CONTEXT_ENABLED=true`，注入 Top 12 公告/资讯/资金流上下文，对未消除重大负面公告强制封顶 **`llm_score <= 35`** 并**禁止品牌/名气偏见**，同日与 `rules` 赛道配对对比净增量。
4. **公开 `next_open` T+N 账本、一行推送与 Fork 安全**：每日运行自动记录到 `track-record` 分支并按 `T+5 / T+10 / T+20` 扣除一字涨停不可成交样本核算超额收益；一行 **`NOTIFY_URLS`** 直连 **12 种原生推送通道**；内置 **Plan A Fork 安全护栏**，他人 Fork 后默认仅跑选股与推送，不自动发布重复官网（仅显式设置 `ALPHASIFT_ENABLE_PAGES=true` 时才部署网页）。

<table>
  <tr>
    <td width="50%" align="center">
      <a href="https://zhulinsen.github.io/alphasift/?lang=zh&theme=dark">
        <img src="docs/assets/dashboard-zh.png" alt="AlphaSift 在线看板（暗色 · 中文）" width="100%">
      </a>
      <br><sub><b>Obsidian Dark 终端</b> — 跨策略共识精选、A 股 7 档涨跌分布、连板梯队与 7 市场排行榜</sub>
    </td>
    <td width="50%" align="center">
      <a href="https://zhulinsen.github.io/alphasift/?lang=en&theme=light">
        <img src="docs/assets/dashboard-light.png" alt="AlphaSift 在线看板（亮色 · 英文多语言适配）" width="100%">
      </a>
      <br><sub><b>Editorial Paper Light + 三语切换</b> — 顶部一键切换 <code>中 | EN | 日</code>、明暗主题与公开账本</sub>
    </td>
  </tr>
  <tr>
    <td colspan="2" align="center">
      <a href="docs/usage.md">
        <img src="docs/assets/daily-report.png" alt="AlphaSift 独立可打印盘后投研日报" width="88%">
      </a>
      <br><sub><b>可打印独立盘后投研日报</b>（<code>alphasift daily-report --output-html</code>）— 盘后要点综述、盘面微观全景、公告排雷与 20 日迷你 K 线</sub>
    </td>
  </tr>
</table>

---

## ⚡ 4 种零门槛上手方式

### 1. 无 API Key 30 秒体验全市场筛选
```bash
git clone https://github.com/ZhuLinsen/alphasift.git && cd alphasift
pip install -e .

alphasift quickstart
alphasift screen dual_low --no-llm
alphasift screen global_value --market hk --no-llm
```

### 2. 开启情报红线 AI 复核、本地日线包、250 日回放与盘后研报
```bash
cp .env.example .env   # 按需填入 GEMINI_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY
alphasift pack build --days 250   # 本地离线回放或日报前，先构建 CN 日线包
alphasift screen dual_low --save-run
alphasift patterns replay --pack-dir ./data/pack/cn --output-md replay.md
alphasift daily-report --pack-dir ./data/pack/cn --output-html daily_report.html --push
```

### 3. 一键接入 Claude Code / Cursor / Codex / OpenClaw（`alphasift mcp` + 工作台 / Docker）
启动只读 STDIO MCP 服务（`10` 个工具 + `2` 个资源；默认仅运行 `scorecard` 后置评分、不触发外部推送），或按需选一在本地 `8765` 端口启动交互式工作台：
```json
{
  "mcpServers": {
    "alphasift": { "command": "alphasift", "args": ["mcp"] }
  }
}
```
> *上方为 Claude Code / Cursor JSON 写法；Codex（`mcp_servers` TOML）与 OpenClaw（`mcp.servers`）写法见 [docs/ecosystem.md](docs/ecosystem.md)。*
```bash
alphasift serve --host 127.0.0.1 --port 8765   # 本地交互工作台 (/ui) + 只读 JSON 接口 + 日报预览
# 或改用容器在同端口启动：
docker compose up --build -d
```

### 4. GitHub Actions 零服务器定时选股与 12 通道推送
1. Fork 本仓库并启用 **GitHub Actions**。
2. 在 *Settings → Secrets and variables → Actions → Secrets* 按需添加：
   - `GEMINI_API_KEY`（或 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`）：开启每日 `ai` 赛道与 `--ai-brief auto` 盘后 AI 综述。
   - `NOTIFY_URLS`：一行接入 12 种原生推送通道（详见[通知配置](#-一行-12-通道推送notify_urls)）。
3. **Plan A Fork 安全护栏**：Fork 仓库默认只执行选股扫描、AI 复核与推送通知，**自动跳过重复网页构建**。若希望 Fork 也发布独立 GitHub Pages 站点，请在 *Variables* 新增 `ALPHASIFT_ENABLE_PAGES=true` 并开启 *Settings → Pages → GitHub Actions*。

---

## 🧭 为什么选择 AlphaSift：横向对比

| 维度 | 传统条件选股（东财 / TradingView） | 单股 AI 研报（`daily_stock_analysis`） | **AlphaSift** |
|---|---|---|---|
| **选股范围** | 单市场人工点选条件 | 聚焦用户已给定的自选股池 | **A 股 / 美 / 港 / 日 / 韩 / 台 / 印 7 市场全量初筛** |
| **规则透明度与分散度** | 封闭黑盒或人工拼凑 | 偏重单股 Prompt 叙事 | **可审计 YAML DSL + 8 行业桶硬上限正交分散** |
| **AI 幻觉防护** | 无 | 偏叙事型多空分析 | **Top 12 公告/资金流注入 + 重大负面 `<= 35` 分封顶 + 严禁名气偏见** |
| **后验真实性** | 无持续跟踪 | 需人工复盘 | **公开 `track-record` 账本（`next_open` T+5/10/20 扣除涨停不可成交）** |
| **工作流衔接** | 独立工具 | **天然衔接的下游 L3 精研引擎** | **上游全市场发现底座（`alphasift mcp` / `DSA_API_URL`）+ 一行 12 通道推送** |

---

## 🏗️ 系统架构

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
|  L2 情报红线 AI 复核 + Top-12 上下文注入（重大负面 <= 35 分封顶） |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
|  风险过滤覆盖层 + 8 行业桶硬上限分散（max_same_bucket: 1）        |
+----------------+--------------------------------+-----------------+
                 |                                |
                 v                                v
+---------------------------------+  +------------------------------+
|  L3 后置分析 (scorecard / DSA)  |  |  track-record 不可篡改账本   |
|  独立 HTML 研报 & 12 通道推送   |  |  next_open T+5/10/20 验收    |
+---------------------------------+  +------------------------------+
```

| 核心设计 | 工程细节 |
|---|---|
| **自愈行情链路与数据包存储** | A 股快照链（`em_datacenter → sina → efinance → akshare_em`，配 `TUSHARE_TOKEN` 时 `tushare` 优先）支持熔断避障；`daily.npz` / `meta.csv.gz` 仅保留在本地或 CI Actions 缓存，不通过公开 Release 分发；Fork 后 `track-record` 分支可见性与 Fork 仓库一致。 |
| **策略 vs AI 同日配对归因** | 同一个交易日分别跑纯规则（`rules`）和 AI 复核（`ai`），直接统计 AI 新纳入 / AI 剔除个股的超额收益贡献。 |
| **幂等去重与防误发** | `(trade_date, channel)` 文件双锁防重复刷屏，旧数据默认阻断推送（除非 `--force-push`），日志自动脱敏所有 Token。 |

---

## 📊 形态雷达 250 日实证基准（`next_open` vs 沪深 300）

基于本地 250 日数据包（评估区间 **`2026-02-05 .. 2026-11-06`**，180 交易日、5,218 只 A 股，`next_open` 入场并剔除一字涨停不可成交）：

| 形态 | 总信号 | T+5 匹配样本 | T+5 超额 | T+10 超额 | 毕业判定 |
|---|---:|---:|---:|---:|---|
| **20日线低波缩量回踩** (`ma20_shrink_pullback` v2.0) | 2,295 | 2,293 | **+0.158%** | **+0.905%** | **`active`** |
| **低波趋势稳健突破** (`steady_trend_breakout` v1.0) | 460 | 460 | **+0.271%** | **+0.560%** | **`active`** |
| 其余 5 个传统形态 (`single_yang_hold` / `box_breakout` 等) | 992–9,233 | 988–9,221 | -1.185% .. -0.175% | -1.207% .. -0.619% | `experimental` |

---

## 🔔 一行 12 通道推送（`NOTIFY_URLS`）

推荐直接使用一行 **`NOTIFY_URLS`**（逗号或换行分隔多目标，协议自动识别），无需额外第三方推送库，同时完全保留传统单通道环境变量兼容：

```bash
NOTIFY_URLS="pushplus://TOKEN,sct://SENDKEY,bark://api.day.app/KEY,mailto://sender@qq.com:auth@qq.com?to=a@qq.com,b@qq.com,https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
```

| 通道 | 一行 `NOTIFY_URLS` 写法 | 独立环境变量（兼容） |
|---|---|---|
| **PushPlus** (`pushplus`) | `pushplus://TOKEN[/TOPIC]` | `PUSHPLUS_TOKEN`, `PUSHPLUS_TOPIC` |
| **Server酱 / Server酱3** (`serverchan`) | `sct://SENDKEY`（兼容 `SCT...` 与 `sctp123t...`） | `SERVERCHAN_SENDKEY` |
| **Bark** (`bark`) | `bark://KEY` 或 `bark://host/KEY` | `BARK_URL` |
| **Email 邮件** (`email`) | `mailto://user:pass@host[:port]?to=a,b` | `EMAIL_SENDER`, `EMAIL_PASSWORD`, `EMAIL_RECEIVERS` |
| **企业微信** (`wecom`) | `wecom://KEY` 或完整 Webhook URL | `WECOM_WEBHOOK_URL` |
| **飞书** (`feishu`) | `feishu://TOKEN[#secret=SEC]` 或完整 URL | `FEISHU_WEBHOOK_URL`, `FEISHU_WEBHOOK_SECRET` |
| **钉钉** (`dingtalk`) | `dingtalk://TOKEN[#secret=SEC]` 或完整 URL | `DINGTALK_WEBHOOK_URL`, `DINGTALK_WEBHOOK_SECRET` |
| **Telegram** (`telegram`) | `tgram://BOT_TOKEN/CHAT_ID` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| **Discord** (`discord`) | `discord://ID/TOKEN` 或完整 URL | `DISCORD_WEBHOOK_URL` |
| **Slack** (`slack`) | `slack://T.../B.../...` 或 `https://hooks.slack.com/...` | `SLACK_WEBHOOK_URL` |
| **ntfy** (`ntfy`) | `ntfy://topic` 或 `https://ntfy.sh/topic` | `NTFY_URL` |
| **自定义 Webhook** (`custom`) | `custom://https://...` 或任意 HTTPS URL | `CUSTOM_WEBHOOK_URL`, `CUSTOM_WEBHOOK_TOKEN` |
| **Apprise（可选兜底）** | 安装 `apprise` 后支持任意 Apprise Scheme | `NOTIFY_URLS` |

> 本地可用 `alphasift notify status` 和 `alphasift notify test --dry-run` 校验配置；`NOTIFY_URLS` 内全部密钥与 Token 在报错或日志中严格脱敏。公开看板页脚另低调提供 [`site/feed.xml`](https://zhulinsen.github.io/alphasift/site/feed.xml) Atom 1.0 RSS 订阅源。

---

<details>
<summary><strong>内置 YAML 策略清单（12 组策略覆盖 7 大市场）</strong></summary>

| 策略名 | 适用市场 | 类型 | 核心思路 |
|---|---|---|---|
| `dual_low` | `cn` | 价值 | 中小盘双低（50–600 亿市值，低 PE + 低 PB），行业桶硬上限 `1` |
| `blue_chip_income` | `cn` | 红利 | 超大盘高流动性高股息蓝筹（≥ 500 亿市值） |
| `quality_value` | `cn` | GARP 成长 | 中盘稳健估值 + MA20 趋势确认（`80–1200 亿`市值） |
| `low_volatility_quality` | `cn` | 质量防御 | 基于日 K 20 日波动率、最大回撤与 ATR 的低波防线 |
| `balanced_alpha` | `cn` | 均衡框架 | 跨因子综合发现，强制行业正交分散 |
| `momentum_quality` | `cn` | 趋势质量 | 60 日中期趋势确认 + 基本面质量硬过滤 |
| `shrink_pullback` | `cn` | 回踩趋势 | 上升趋势中缩量回踩支撑位（需日 K） |
| `capital_heat` | `cn` | 资金动量 | 换手与量比活跃但剔除短期过热追高 |
| `oversold_reversal` | `cn` | 超跌修复 | 短期超跌 + 回撤受控的均值回复候选 |
| `volume_breakout` | `cn` | 放量突破 | 成交量显著放大并突破关键压力区间 |
| `global_value` | `us, hk, jp, kr, tw, in` | 多市场价值 | 去除币种绝对阈值的 `dual_low` 跨市场版本 |
| `us_momentum_quality` | `us` | 美股趋势 | 美股 20 亿美元以上大盘动量 + 质量精选（`>= $2B`） |

</details>

<details>
<summary><strong>真实运行示例（独立离线 2026-11-20 快照，<code>--no-llm</code> 纯规则模式）</strong></summary>

**A 股（`dual_low` v1.1 独立快照示例；每日实盘账本以 `track-record` 分支为准）：** 5,215 只 → 205 只入围 → Top 5 来自 5 个互不重复行业（`hard_cap: 1`）：

| # | 代码 | 名称 | 行业 | PE | PB |
|---:|---|---|---|---:|---:|
| 1 | `601997` | 贵阳银行 | 银行 | 4.4 | 0.32 |
| 2 | `601117` | 中国化学 | 建筑施工 | 6.6 | 0.61 |
| 3 | `600741` | 华域汽车 | 汽车 | 7.7 | 0.77 |
| 4 | `603799` | 华友钴业 | 稀有金属 | 8.7 | 1.07 |
| 5 | `601233` | 桐昆股份 | 合成纤维及树脂 | 6.8 | 1.11 |

**港股（`global_value --market hk`，2026-11-20）：** 567 只 → 236 只入围：`0267.HK` 中信股份 · `0001.HK` 长和 · `1339.HK` 中国人保 · `1398.HK` 工商银行 · `0358.HK` 江西铜业。

**日股（`global_value --market jp`，2026-11-20）：** 748 只 → 311 只入围：`9501.T` 东京电力 · `5401.T` 新日铁 · `1605.T` INPEX · `9104.T` 商船三井 · `9022.T` JR东海。

*仅作引擎输出展示，不构成任何投资建议。*

</details>

<details>
<summary><strong>支持市场、关键环境变量与已知限制</strong></summary>

| 市场 ID | 数据源链路 | 说明 |
|---|---|---|
| `cn` | `em_datacenter → sina → efinance → akshare_em`（配置 `TUSHARE_TOKEN` 时优先 `tushare`） | A 股全市场 + 东财行业补全 + 公告排雷 + 私有离线包 |
| `us, hk, jp, tw, in` | Yahoo Finance 筛选器 + `yfinance` | 海外服务器直连可用，仅依赖单一非官方接口 |
| `kr` | Yahoo Finance + Naver Finance | 从 Naver 补充韩股 PE/PB（`ALPHASIFT_KR_VALUATION=0` 可关闭） |

详细环境变量见 [docs/configuration.md](docs/configuration.md)、[.env.example](.env.example) 与 [部署指南](docs/deployment.md)（含一行推送 `NOTIFY_URLS`、CN AI 上下文开关 `LLM_CANDIDATE_CONTEXT_ENABLED=true`，以及 Fork 启用网页所需的 `ALPHASIFT_ENABLE_PAGES=true`）。

**已知限制：** AlphaSift 定位为候选发现与后验审计引擎，并非自动交易或全复权分红组合回测器；公开账本在切换日（默认 `2026-11-21`）前为历史 `close` 口径（不可成交率标「未评估」），切换日起按 `next_open` 并严控开盘一字涨停不可成交口径。

</details>

---

## 🔗 相关项目 — 开源量化铁三角（Quant Trio）

| 项目 | 在链路中的定位 | 协同方式 |
|---|---|---|
| **[AlphaEvo](https://github.com/ZhuLinsen/alphaevo)** | 研究与因子挖掘 | 进化式发现与样本外检验 α 因子后，沉淀为 AlphaSift YAML 策略规则 |
| **[AlphaSift](https://github.com/ZhuLinsen/alphasift)** | **多市场初筛与验证底座** | 盘后从 7 市场 `5,000+` 标的精选 `3–5` 只并公开验证 `T+5 / 10 / 20` |
| **[daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis)** | L3 个股深度精研 | 通过 `DSA_API_URL` 或 `alphasift mcp` 接收初筛名单，生成个股资讯与操作建议 |

更多结构图、STDIO MCP 工具列表与 Docker 快速启动见 [docs/ecosystem.md](docs/ecosystem.md)。

---

## 免责声明、文档与开源协议

> 本项目仅用于量化研究、开源工程验证与个人学习，不构成任何投资建议、收益承诺或买卖指令。

[使用指南](docs/usage.md) · [配置参考](docs/configuration.md) · [生态与 MCP](docs/ecosystem.md) · [部署与镜像](docs/deployment.md) · [策略编写指南](docs/strategy-guide.md) · [评分体系](docs/scoring.md) · [输出契约](docs/result-schema.md) · [参考资料](docs/reference.md) · [参与贡献](CONTRIBUTING.md) · [安全策略](SECURITY.md) · [更新记录](docs/CHANGELOG.md) · [SKILL.md](SKILL.md)

基于 [Apache License 2.0](LICENSE) 开源。
