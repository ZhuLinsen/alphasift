<div align="center">

<a href="https://zhulinsen.github.io/alphasift/?lang=zh">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/banner-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/banner-light.svg">
    <img alt="AlphaSift — 开源全市场量化选股与回测基准引擎" src="docs/assets/banner-dark.svg" width="100%">
  </picture>
</a>

<h3>为 AI Agent 设计的全市场选股与后验验证引擎 —— 确定性 YAML 策略、250 日实证形态雷达、策略 + AI 双轨归因与可审计 T+N 公开账本</h3>

<p>
  <a href="https://github.com/ZhuLinsen/alphasift/actions/workflows/ci.yml"><img src="https://github.com/ZhuLinsen/alphasift/actions/workflows/ci.yml/badge.svg" alt="CI Status"></a>
  <a href="https://zhulinsen.github.io/alphasift/?lang=zh"><img src="https://img.shields.io/badge/dashboard-live%20(中%20%7C%20EN%20%7C%20日)-22c55e.svg" alt="在线看板"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-3b82f6.svg" alt="Python 3.10+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-10b981.svg" alt="Apache 2.0"></a>
  <a href="https://zhulinsen.github.io/alphasift/site/feed.xml"><img src="https://img.shields.io/badge/RSS-Atom%201.0-f59e0b.svg" alt="Atom RSS"></a>
</p>

<p>
  <a href="https://zhulinsen.github.io/alphasift/?lang=zh"><strong>在线看板</strong></a> ·
  <a href="https://zhulinsen.github.io/alphasift/site/daily_report.html?lang=zh"><strong>今日盘后研报</strong></a> ·
  <a href="https://zhulinsen.github.io/alphasift/site/feed.xml"><strong>Atom RSS 订阅</strong></a> ·
  <a href="https://github.com/ZhuLinsen/alphasift/tree/track-record"><strong>track-record 原始账本</strong></a> ·
  <a href="SKILL.md"><strong>Agent Skill</strong></a>
</p>

<p>
  <a href="README.md">English</a> · <strong>简体中文</strong> · <a href="README.ja.md">日本語</a>
</p>

</div>

---

## 多语言在线终端与盘后研报

每个交易日收盘后自动运行全市场内置策略，在 **`T+5 / T+10 / T+20`** 对照所属市场基准指数客观验收收益（A 股切换日起按 `next_open` 入场并扣除一字涨停不可成交样本），看板与独立 HTML 研报原生支持 **中文 · English · 日本語** 与 **Obsidian Dark · Editorial Light** 双主题切换。

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
      <br><sub><b>Editorial Paper Light + 三语切换</b> — 顶部一键切换 <code>中 | EN | 日</code>、明暗主题与 Atom RSS</sub>
    </td>
  </tr>
  <tr>
    <td colspan="2" align="center">
      <a href="https://zhulinsen.github.io/alphasift/site/daily_report.html?lang=zh&theme=dark">
        <img src="docs/assets/daily-report.png" alt="AlphaSift 独立可打印盘后投研日报" width="88%">
      </a>
      <br><sub><b>可打印独立盘后投研日报</b>（<code>alphasift daily-report --output-html</code>）— 盘后要点综述、盘面微观全景、公告排雷与 20 日迷你 K 线</sub>
    </td>
  </tr>
</table>

---

## 系统架构与核心能力

```mermaid
flowchart LR
  M["7市场全市场快照 + 私有日线包 DailyPack"] --> L1["L1 YAML 硬筛选与多因子评分"]
  L1 --> L2["L2 可选 LLM 横向重排 (Gemini 3.8 Flash / DeepSeek / OpenAI)"]
  L2 --> RK["风险过滤 + 8 行业桶硬上限分散"]
  RK --> L3["L3 后置分析 (scorecard / DSA / HTTP) + 公告排雷"]
  L3 --> OUT["可打印 HTML 日报 + 6 通道幂等推送 + Atom RSS"]
  RK --> AUD["不可篡改 track-record 账本 + next_open T+N 后验评估"]
```

| 核心能力 | 工程实现 |
|---|---|
| **零 Key 确定性选股底座** | L1 硬筛条件、因子评分曲线、风险惩罚与 8 行业分散上限完全确定性运行，不配置任何 LLM API Key 即可跑全链路。 |
| **10 组 A 股策略正交化去重合** | 统一启用 8 行业桶 `portfolio_profile.mode: hard_cap`（`max_same_bucket: 1`），并按市值梯度、红利/GARP/动量/反转风格正交错位。经本地 250 日数据包在 `2026-09-21`、`10-20`、`11-20` 三日回测，策略两两平均重合度由 **8.0%–24.9% 降至 0.9%–1.8%**（最大单对 **100% → 20%**），银行占比由 **22%–31.1% 降至 4.0%–9.1%**。 |
| **250 日实盘口径形态雷达** | 所有无状态形态需通过 `next_open` 回放门槛（`T+5 基准匹配样本 ≥ 200` 且相对沪深 300 超额 `> 0%`）才升级 `active`，其余保持 `experimental` 置灰观察，不混水摸鱼。 |
| **策略 + AI 双赛道配对归因** | 默认主模型已升级为 **`gemini/gemini-3.8-flash`**（自动挂载 `gemini/gemini-4-hydrogen` 回退），同步兼容 DeepSeek、OpenAI 与 Ollama；支持同日运行 `rules` 与 `ai` 双赛道并归因“AI 独选 / AI 剔除”收益贡献。 |
| **数据源自愈与严格私有化日线包** | A 股快照链（`em_datacenter → sina → efinance → akshare_em`，配置 `TUSHARE_TOKEN` 时 Tushare 优先）支持熔断避障与超时预算；原始日线包（`daily.npz` / `meta.csv.gz`）**仅留存本地或 GitHub Actions 私有缓存**，绝不通过公开 Release 二次分发。 |
| **6 通道幂等推送 + 零配置 RSS** | 支持 **企业微信、飞书（HMAC 签名）、钉钉（HMAC 签名）、Telegram、Discord、自定义 Webhook（JSON + Bearer 鉴权）** 与公开看板 **`site/feed.xml` Atom 1.0 RSS**；按 `(trade_date, channel)` 文件锁严格去重，旧包默认拦截推送。 |

---

## 形态雷达 250 日实证基准（`next_open` vs 沪深 300）

基于本地 250 日数据包（评估区间 **`2026-02-05 .. 2026-11-06`**，180 交易日、5,218 只 A 股，`next_open` 入场并剔除一字涨停不可成交）：

| 形态 | 谱系 / 模式 | 总信号 | T+5 匹配样本 | T+5 超额 | T+5 超额胜率 | T+10 超额 | 毕业判定 |
|---|---|---:|---:|---:|---:|---:|---|
| **20日线低波缩量回踩** (`ma20_shrink_pullback` v2.0) | `trend_continuation · direct` | 2,295 | 2,293 | **+0.158%** | 46.45% | **+0.905%** | **`active`** |
| **低波趋势稳健突破** (`steady_trend_breakout` v1.0) | `breakout · direct` | 460 | 460 | **+0.271%** | 48.70% | **+0.560%** | **`active`** |
| `single_yang_hold` / `box_breakout` / `bottom_volume_yang` / `double_bottom_breakout` / `shooting_star_confirm` | 混合谱系 | 992–9,233 | 988–9,221 | -1.185% .. -0.175% | 38.26%–45.47% | -1.207% .. -0.619% | `experimental` |

---

## 30 秒快速开始

```bash
pip install -e .

# 1. 无 API Key 体验全市场筛选
alphasift quickstart
alphasift screen dual_low --no-llm
alphasift screen global_value --market hk --no-llm

# 2. 开启 LLM AI 重排（默认 gemini/gemini-3.8-flash + gemini-4-hydrogen 自动回退）
cp .env.example .env   # 填入 GEMINI_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY
alphasift screen dual_low --save-run

# 3. 250 日形态回放、独立 HTML 日报、与 6 通道推送校验
alphasift patterns replay --pack-dir ./data/pack/cn --output-md replay.md
alphasift daily-report --pack-dir ./data/pack/cn --output-html daily_report.html --push
alphasift notify status
alphasift notify test --dry-run
```

**Python 调用与只读 Agent HTTP 服务：**

```python
from alphasift import screen, evaluate_saved_run

res = screen("dual_low", market="cn", use_llm=False)
for pick in res.picks:
    print(pick.rank, pick.code, pick.name, pick.industry, pick.final_score)
```

```bash
alphasift serve --host 127.0.0.1 --port 8000
```

---

## 通知推送与订阅矩阵

| 通道 | 环境变量 | 能力说明 |
|---|---|---|
| **Atom 1.0 RSS** | 零配置（`site/feed.xml`） | 每次发布 GitHub Pages 自动更新，任意 RSS 阅读器免密钥订阅 |
| **企业微信** (`wecom`) | `WECOM_WEBHOOK_URL` | `<1200` 字公告预警优先 Markdown 群机器人卡片 |
| **飞书** (`feishu`) | `FEISHU_WEBHOOK_URL` / `FEISHU_WEBHOOK_SECRET` | 交互式蓝色标题卡片，配 secret 时自动生成 HMAC-SHA256 签名 |
| **钉钉** (`dingtalk`) | `DINGTALK_WEBHOOK_URL` / `DINGTALK_WEBHOOK_SECRET` | Markdown 消息，配 secret 时自动生成 URL query timestamp+sign 签名 |
| **Telegram** (`telegram`) | `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Bot API 紧凑简报（关闭网页预览） |
| **Discord** (`discord`) | `DISCORD_WEBHOOK_URL` | 富文本 Embed 卡片，点击标题直达在线看板 |
| **自定义 Webhook** (`custom`) | `CUSTOM_WEBHOOK_URL` / `CUSTOM_WEBHOOK_TOKEN` | POST 结构化 JSON（`event`、`trade_date`、`markdown`、`summary`），支持 Bearer Token |

> 所有通知通道共用进程/文件双锁幂等账本（按 `trade_date + channel`），旧包自动跳过不骚扰群聊，错误日志自动脱敏绝不泄露密钥或 Webhook token。

---

<details>
<summary><strong>内置 YAML 策略清单（12 组策略覆盖 7 大市场）</strong></summary>

| 策略名 | 适用市场 | 类型 | 核心思路 |
|---|---|---|---|
| `dual_low` | `cn` | 价值 | 中小盘双低（50–600 亿市值，低 PE + 低 PB），行业桶硬上限 `1` |
| `blue_chip_income` | `cn` | 红利 | 超大盘高流动性高股息蓝筹（≥ 500 亿市值） |
| `quality_value` | `cn` | GARP 成长 | 中盘稳健估值 + 波动/回撤约束（150–2000 亿） |
| `low_volatility_quality` | `cn` | 质量防御 | 基于日 K 20 日波动率、最大回撤与 ATR 的低波防线 |
| `balanced_alpha` | `cn` | 均衡框架 | 跨因子综合发现，强制行业正交分散 |
| `momentum_quality` | `cn` | 趋势质量 | 60 日中期趋势确认 + 基本面质量硬过滤 |
| `shrink_pullback` | `cn` | 回踩趋势 | 上升趋势中缩量回踩支撑位（需日 K） |
| `capital_heat` | `cn` | 资金动量 | 换手与量比活跃但剔除短期过热追高 |
| `oversold_reversal` | `cn` | 超跌修复 | 短期超跌 + 回撤受控的均值回复候选 |
| `volume_breakout` | `cn` | 放量突破 | 成交量显著放大并突破关键压力区间 |
| `global_value` | `us, hk, jp, kr, tw, in` | 多市场价值 | 去除币种绝对阈值的 `dual_low` 跨市场版本 |
| `us_momentum_quality` | `us` | 美股趋势 | 美股十亿美元以上大盘动量 + 质量精选 |

</details>

<details>
<summary><strong>真实运行示例（2026-11-20 截面，<code>--no-llm</code> 纯规则模式）</strong></summary>

**A 股（`dual_low` on 2026-11-20 pack）：** 5,215 只 → 205 只入围 → Top 5 来自 5 个互不重复行业（`hard_cap: 1`）：

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

详细环境变量见 [docs/configuration.md](docs/configuration.md)、[.env.example](.env.example) 与 [部署指南](docs/deployment.md)。

**已知限制：** AlphaSift 定位为候选发现与后验审计引擎，并非自动交易或全复权分红组合回测器；公开账本在切换日（默认 `2026-11-21`）前为历史 `close` 口径（不可成交率标「未评估」），切换日起按 `next_open` 并严控开盘一字涨停不可成交口径。

</details>

---

## 免责声明、文档与开源协议

> 本项目仅用于量化研究、开源工程验证与个人学习，不构成任何投资建议、收益承诺或买卖指令。

[使用指南](docs/usage.md) · [配置参考](docs/configuration.md) · [部署与镜像](docs/deployment.md) · [策略编写指南](docs/strategy-guide.md) · [评分体系](docs/scoring.md) · [设计原则](docs/design.md) · [项目定位](docs/positioning.md) · [横向比较](docs/comparison.md) · [参考资料](docs/reference.md) · [更新记录](docs/CHANGELOG.md) · [SKILL.md](SKILL.md)

基于 [Apache License 2.0](LICENSE) 开源。
