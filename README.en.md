<div align="center">

<a href="https://alphasift.zhulinsen.tech/?lang=en">
  <img src="docs/assets/alphasift-logo.svg" alt="AlphaSift Logo" width="480">
</a>

[简体中文](README.md) | English | [日本語](README.ja.md)

# 🔎 AlphaSift

**AI Quantitative Stock Screener**

*Full-market YAML screening across 7 markets -> Red-flag AI re-ranking -> Public `next_open` T+N paper benchmark*

[![GitHub stars](https://img.shields.io/github/stars/ZhuLinsen/alphasift?style=social)](https://github.com/ZhuLinsen/alphasift/stargazers)
[![PyPI](https://img.shields.io/pypi/v/alphasift?color=2563eb)](https://pypi.org/project/alphasift/)
[![Live Dashboard](https://img.shields.io/badge/Live%20Dashboard-GitHub%20Pages-0ea5e9.svg)](https://alphasift.zhulinsen.tech/?lang=en)
[![MCP Ready](https://img.shields.io/badge/MCP-STDIO%20Ready-8b5cf6.svg)](docs/ecosystem.md)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3b82f6.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-10b981.svg)](LICENSE)

[**Live Dashboard**](https://alphasift.zhulinsen.tech/?lang=en) · [**Why AlphaSift**](#-why-alphasift) · [**30s Quickstart**](#-30-second-quickstart) · [**Benchmarks & Architecture**](#-verified-benchmarks--architecture) · [**Quant Trio**](#-quant-trio-ecosystem) · [**Agent Skill**](SKILL.md)

</div>

> [!TIP]
> 🚀 **Companion to [daily_stock_analysis (73.6k★)](https://github.com/ZhuLinsen/daily_stock_analysis)**: **AlphaSift** runs post-close discovery across `5,000+` stocks & audits live `T+N` accuracy; **DSA** generates deep single-stock briefs; [**AlphaEvo**](https://github.com/ZhuLinsen/alphaevo) evolves and falsifies alpha rules.

---

## 🖥️ Zero-Install Live Dashboard & Public Ledger

👉 **[Open the Live Benchmark (alphasift.zhulinsen.tech)](https://alphasift.zhulinsen.tech/?lang=en)** — updated every trading day with 7-market consensus signals, `T+5 / T+10 / T+20` leaderboards, and side-by-side **AI vs Rules** paired attribution.

<p align="center">
  <a href="https://alphasift.zhulinsen.tech/?lang=en">
    <img src="docs/assets/dashboard-preview.gif" alt="AlphaSift Live Dashboard Interactive Preview" width="840">
  </a>
  <br><sub>Click the preview to explore the live terminal (Dark / Light themes + instant <code>ZH | EN | JA</code> switcher)</sub>
</p>

<details>
<summary><strong>View static dark/light captures & standalone printable daily research report (<code>alphasift daily-report --output-html</code>)</strong></summary>

<table>
  <tr>
    <td width="50%" align="center">
      <a href="https://alphasift.zhulinsen.tech/?lang=en&theme=dark">
        <img src="docs/assets/dashboard-dark.png" alt="AlphaSift Live Dashboard (Dark)" width="100%">
      </a>
      <br><sub><b>Obsidian Dark Terminal</b> — Consensus Signals, CN Microstructure Breadth &amp; 7-Market T+N Leaderboard</sub>
    </td>
    <td width="50%" align="center">
      <a href="https://alphasift.zhulinsen.tech/?lang=en&theme=light">
        <img src="docs/assets/dashboard-light.png" alt="AlphaSift Live Dashboard (Light)" width="100%">
      </a>
      <br><sub><b>Editorial Paper Light</b> — Multilingual Switcher (<code>ZH | EN | JA</code>) &amp; Audited Track Record</sub>
    </td>
  </tr>
  <tr>
    <td colspan="2" align="center">
      <a href="docs/usage.md">
        <img src="docs/assets/daily-report.png" alt="AlphaSift Standalone Printable Daily Brief" width="88%">
      </a>
      <br><sub><b>Standalone Printable Research Brief</b> (<code>alphasift daily-report --output-html</code>) — Executive Summary, 7-Bucket Return Histogram, Filing Risk Screen &amp; 20D K-Line Hits</sub>
    </td>
  </tr>
</table>

</details>

---

## ✨ Why AlphaSift

Most AI stock tools stop at chatting over a pre-picked watchlist or cherry-picking backtests. **AlphaSift treats full-market screening, red-flag AI filtering, and public post-trade falsification as one unified pipeline:**

1. **Full-Market Zero-Key Screening**: Scans CN A-Shares, US, HK, JP, KR, TW, and IN in seconds using 12 auditable YAML strategies and 8-bucket sector diversity caps — zero API keys required for deterministic rules.
2. **Code-Enforced Red Lines & Honest `T+N` Ledger**: Optional LLM re-ranking (`gemini/gemini-3.8-flash` default with `gemini/gemini-4-hydrogen` fallback) grounds candidates in live filings/news/fund-flow context, caps unresolved adverse filings at **`llm_score <= 35` in Python**, bans fame bias, and logs paired `rules` vs `ai` excess returns at `next_open` (`untradable_limit_up` excluded).
3. **Free Cloud Runs & Native Agent Stack**: Schedule daily runs on GitHub Actions with 12-channel `NOTIFY_URLS` alerts (Plan A fork guard prevents duplicate fork websites), or plug directly into Claude Code, OpenClaw, Cursor, and Codex via zero-dep STDIO **MCP** (`alphasift mcp`) and local **Web Workbench** (`alphasift serve` -> `/ui`).

---

## ⚡ 30-Second Quickstart

### 1. Connect to Claude Code, Cursor, Codex, or OpenClaw (Native STDIO MCP)

Connect directly with zero pre-install via **`uvx`** (or `pip install alphasift` first) to expose `14` read-only tools and `4` resources (runs local `scorecard` without outbound notifications):

```json
{
  "mcpServers": {
    "alphasift": { "command": "uvx", "args": ["alphasift", "mcp"] }
  }
}
```

> *Zero-install `uvx` config shown above; if you installed via `pip install alphasift`, change `"command"` to `"alphasift"`. For Codex (`mcp_servers` TOML) or OpenClaw (`mcp.servers`), see [docs/ecosystem.md](docs/ecosystem.md).*

**Try asking your AI assistant:**
- *"Screen today's CN `dual_low` strategy for top-5 undervalued picks with clean filings and explain the sector mix."*
- *"Compare `dual_low` vs `quality_value` factor weights and risk caps for a choppy market regime."*
- *"Run `global_value` on HK and JP markets with `--no-llm` and group picks by industry."*

---

### 2. Local CLI, Interactive Web Workbench (`/ui`) & Docker

Install directly from [PyPI (`alphasift`)](https://pypi.org/project/alphasift/), the [`v0.3.2` Release wheel](https://github.com/ZhuLinsen/alphasift/releases/tag/v0.3.2), or editable source checkout:

```bash
# Option A: Install from PyPI (supports pip / uvx)
pip install alphasift

# Option B: Editable source install
git clone https://github.com/ZhuLinsen/alphasift.git && cd alphasift
pip install -e .
```

**Run zero-key screening & local Workbench immediately:**
```bash
alphasift quickstart                            # 30s end-to-end sample
alphasift screen dual_low --no-llm              # CN deterministic rules track
alphasift screen global_value --market hk --no-llm
alphasift serve --host 127.0.0.1 --port 8765    # Local Workbench UI (/ui) & read-only API
# Or containerized on the same loopback port:
docker compose up --build -d
```

**Optional red-flag AI ranking, 250-day replay & printable daily report:**
```bash
cp .env.example .env                            # Add GEMINI_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY
alphasift pack build --days 250                 # Build local CN pack before replay / daily-report
alphasift screen dual_low --save-run
alphasift evaluate-strategies --window 5,10,20 --explain
alphasift daily-report --pack-dir ./data/pack/cn --output-html daily_report.html --push
```

---

### 3. Free Cloud Daily Screening & Fork Protection

1. Click **Fork** in the top-right (and **Star ⭐** the repo to follow daily benchmark & strategy updates), then open your fork's **Actions** tab and click **Enable workflows** (GitHub disables scheduled crons on forks by default).
2. Add optional **Secrets** under *Settings -> Secrets and variables -> Actions*: `GEMINI_API_KEY` (or `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`) for paired AI ranking, and `NOTIFY_URLS` for 1-line push alerts.
3. **Plan A Fork Guard:** Forked repositories run screening and notifications while skipping duplicate GitHub Pages builds unless you set Repository Variable `ALPHASIFT_ENABLE_PAGES=true` and enable *Settings -> Pages -> GitHub Actions*. See [docs/deployment.md](docs/deployment.md).

> ⭐ **Found the live next-open T+N benchmark or zero-key MCP useful?** Star this repo to follow daily scorecard updates and new strategy releases, or propose rules and share setups in [Discussions](https://github.com/ZhuLinsen/alphasift/discussions).

---

## 📊 Verified Benchmarks & Architecture

| Dimension | Static Screeners (`TradingView` / `EastMoney`) | Single-Stock AI (`daily_stock_analysis`) | **AlphaSift** |
|---|---|---|---|
| **Universe** | Manual UI filters on 1 market | Deep-dive on a pre-picked watchlist | **Full-market discovery across 7 markets (`cn/us/hk/jp/kr/tw/in`)** |
| **Determinism & Diversity** | Opaque UI presets | Prompt-driven per ticker | **Auditable YAML DSL + 8-bucket `hard_cap` orthogonality** |
| **AI Guardrails** | None | Single-ticker narrative | **Filings/fund-flow context, `<= 35` red-flag cap, anti-fame bias** |
| **Post-Trade Audit** | None | Manual review | **Public `track-record` ledger (`next_open` T+5/10/20 + limit-up blocks)** |

- **Orthogonal CN Strategy Suite**: Restructuring all 10 CN strategies with 8-bucket hard sector caps (`max_same_bucket: 1`) cut mean pairwise strategy overlap across 3 local 250D snapshots from **8.0%–24.9% -> 0.9%–1.8%** (`max` **100% -> 20%**) and bank concentration from **22%–31.1% -> 4.0%–9.1%**.
- **Empirically Audited 250D Pattern Radar**: Across `2026-02-05 .. 2026-11-06` (`180` sessions, `5,218` A-shares, `next_open` entry vs CSI 300 and All-A equal-weight, **9** stateless YAMLs), patterns graduate to `active` only when simultaneously passing matched `T+5 N >= 200`, positive net excess after `25bp` round-trip costs vs both benchmarks, Bartlett Newey-West HAC `t >= 2.0`, BH-FDR `q <= 0.05`, and same-sign positive split-half stability (`H1/H2 >= 15d & >= 30`). Currently **`three_white_soldiers_pullback`**, **`three_white_soldiers`**, **`ma20_shrink_pullback`**, **`steady_trend_breakout`**, and the remaining 5 patterns all stay in **`experimental`** observation while disclosing net excess and statistical diagnostics; negative-expectancy patterns auto-collapse in daily report cards.

```
+-------------------------------------------------------------------+
|  7 Markets Snapshot Chains  +  Private DailyPack (actions/cache)  |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
|  L1 Deterministic Engine: YAML Hard Filters & Factor Scoring      |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
|  L2 Red-Flag Skeptic LLM + Top-12 Context (<=35 Adverse Cap)      |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
|  Risk Overlay & 8-Bucket Hard Sector Cap (max_same_bucket: 1)     |
+----------------+--------------------------------+-----------------+
                 |                                |
                 v                                v
+---------------------------------+  +------------------------------+
|  L3 Analyzers (scorecard / DSA) |  |  Auditable track-record Log  |
|  Printable HTML & NOTIFY_URLS   |  |  next_open T+5/10/20 Audit   |
+---------------------------------+  +------------------------------+
```

---

<details>
<summary><strong>Built-in YAML Strategies (12 Strategies Across 7 Markets)</strong></summary>

| Strategy | Markets | Style | Core Focus |
|---|---|---|---|
| `dual_low` | `cn` | Value | Mid-cap low PE/PB (`5B–60B CNY`), `hard_cap: 1` per industry bucket |
| `blue_chip_income` | `cn` | Income | Mega-cap liquid dividend leaders (`>= 50B CNY`) |
| `quality_value` | `cn` | GARP | Mid-cap growth valuation stability (`8B–120B CNY`, `>= MA20`) |
| `low_volatility_quality` | `cn` | Defensive | Low 20D volatility, controlled drawdown & ATR (daily K-line) |
| `balanced_alpha` | `cn` | Multi-Factor | Broad balanced factor discovery with sector hard cap |
| `momentum_quality` | `cn` | Trend Quality | 60D trend confirmation + quality gates |
| `shrink_pullback` | `cn` | Pullback | Shrink-volume pullback to MA20 support within uptrend (daily K-line) |
| `capital_heat` | `cn` | Momentum | Active turnover & capital flow without extreme overheating |
| `oversold_reversal` | `cn` | Reversal | Controlled-drawdown mean-reversion candidates |
| `volume_breakout` | `cn` | Breakout | Volume expansion breaking 20D resistance |
| `global_value` | `us, hk, jp, kr, tw, in` | Value | Currency-neutral low PE/PB screener for global markets |
| `us_momentum_quality` | `us` | Trend | US large-cap (`>= $2B`) momentum + quality |

</details>

<details>
<summary><strong>1-Line 12-Channel Push (<code>NOTIFY_URLS</code>) & Atom RSS</strong></summary>

Configure **one comma/newline-separated `NOTIFY_URLS` variable** with zero extra dependencies (`flock`-protected `(trade_date, channel)` idempotency + automatic token redaction; legacy env vars remain compatible):

```bash
NOTIFY_URLS="pushplus://TOKEN,sct://SENDKEY,bark://api.day.app/KEY,mailto://sender@qq.com:auth@qq.com?to=a@qq.com,https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
```

| Channel | `NOTIFY_URLS` URI / URL | Standalone Env Vars |
|---|---|---|
| **PushPlus** | `pushplus://TOKEN[/TOPIC]` | `PUSHPLUS_TOKEN`, `PUSHPLUS_TOPIC` |
| **ServerChan / ServerChan3** | `sct://SENDKEY` (`SCT...` & `sctp123t...`) | `SERVERCHAN_SENDKEY` |
| **Bark** | `bark://KEY` or `bark://host/KEY` | `BARK_URL` |
| **Email SMTP** | `mailto://user:pass@host[:port]?to=a,b` | `EMAIL_SENDER`, `EMAIL_PASSWORD`, `EMAIL_RECEIVERS` |
| **WeCom** | `wecom://KEY` or webhook URL | `WECOM_WEBHOOK_URL` |
| **Feishu** | `feishu://TOKEN[#secret=SEC]` or webhook URL | `FEISHU_WEBHOOK_URL`, `FEISHU_WEBHOOK_SECRET` |
| **DingTalk** | `dingtalk://TOKEN[#secret=SEC]` or webhook URL | `DINGTALK_WEBHOOK_URL`, `DINGTALK_WEBHOOK_SECRET` |
| **Telegram** | `tgram://BOT_TOKEN/CHAT_ID` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| **Discord** | `discord://ID/TOKEN` or webhook URL | `DISCORD_WEBHOOK_URL` |
| **Slack** | `slack://T.../B.../...` or webhook URL | `SLACK_WEBHOOK_URL` |
| **ntfy** | `ntfy://topic` or `https://ntfy.sh/topic` | `NTFY_URL` |
| **Custom JSON / Apprise** | `custom://https://...` or Apprise scheme | `CUSTOM_WEBHOOK_URL`, `CUSTOM_WEBHOOK_TOKEN` |

Atom 1.0 RSS feed: [`site/feed.xml`](https://alphasift.zhulinsen.tech/site/feed.xml). Verify locally via `alphasift notify status` and `alphasift notify test --dry-run`.

</details>

<details>
<summary><strong>Supported Markets, Standalone Sample Run & Key Env Vars</strong></summary>

| Market | Snapshot & Daily Source | Scope Notes |
|---|---|---|
| `cn` | `em_datacenter -> sina -> efinance -> akshare_em` (`tushare` first with token); `DailyPack` / `tencent` / `sina` / `akshare` / `baostock` | Full A-share universe, EastMoney sector backfill, announcements & hotspots |
| `us, hk, jp, tw, in` | Yahoo Finance screener + `yfinance` | Large/mid-cap floor (`>= ~$1B` / `HK$8B` / `JPY 150B`), single unofficial endpoint |
| `kr` | Yahoo Finance screener + Naver Finance mobile API | Naver supplies PE/PB (`ALPHASIFT_KR_VALUATION=0` disables); `~10s` extra |

- **2026-11-20 `--no-llm` sample**: CN `dual_low` (5,215 -> 205 -> 5 distinct industries: `601997`, `601117`, `600741`, `603799`, `601233`), HK `global_value` (`0267.HK`, `0001.HK`, `1339.HK`, `1398.HK`, `0358.HK`), JP `global_value` (`9501.T`, `5401.T`, `1605.T`, `9104.T`, `9022.T`).
- **Key env vars**: `LLM_MODEL` (default `gemini/gemini-3.8-flash`), `LLM_FALLBACK_MODELS` (`gemini/gemini-4-hydrogen`), `GEMINI_API_KEY` / `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`, `LLM_CANDIDATE_CONTEXT_ENABLED=true` (enabled in CI Actions; local default off), `NOTIFY_URLS`, `ALPHASIFT_ENABLE_PAGES=true`, `TUSHARE_TOKEN`, `DSA_API_URL`. See [docs/configuration.md](docs/configuration.md).
- **Known limitations**: Research screening & audit engine only (no order routing or dividend-adjusted portfolio simulation). Pre-`2026-11-21` `track-record` runs used `close` entry; `2026-11-21+` CN uses `next_open` with raw limit-up block accounting.

</details>

---

## 🔗 Quant Trio Ecosystem

| Project | Role in Stack | How It Connects |
|---|---|---|
| **[AlphaEvo](https://github.com/ZhuLinsen/alphaevo)** | Research & Factor Mining | Discovers & stress-tests alpha genomes before distilling them into AlphaSift YAML rules |
| **[AlphaSift](https://github.com/ZhuLinsen/alphasift)** | **Multi-Market Funnel & Benchmark** | Screens `5,000+` symbols → shortlisted picks across 7 markets & audits `T+5 / 10 / 20` |
| **[daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis)** | L3 Single-Stock Deep Dive | Consumes shortlisted picks via `DSA_API_URL` or MCP for granular fundamentals, news & action plans |

See [docs/ecosystem.md](docs/ecosystem.md) for MCP tool schemas and Docker details.

---

<details>
<summary><strong>📈 Star History</strong></summary>

<p align="center">
  <a href="https://www.star-history.com/#ZhuLinsen/alphasift&Date">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=ZhuLinsen/alphasift&type=Date&theme=dark" />
      <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=ZhuLinsen/alphasift&type=Date" />
      <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=ZhuLinsen/alphasift&type=Date" width="760" />
    </picture>
  </a>
</p>

</details>

## Disclaimer, Docs & License

> This repository is built purely for research, engineering verification, and educational experiments — never investment advice or buy/sell recommendations. Market data, LLM rankings, and pattern signals can be incomplete or delayed.

[Usage](docs/usage.md) · [Configuration](docs/configuration.md) · [Regime Research](docs/pattern-regime-research.md) · [Ecosystem & MCP](docs/ecosystem.md) · [Deployment & Mirror](docs/deployment.md) · [Strategy Guide](docs/strategy-guide.md) · [Scoring](docs/scoring.md) · [Result Schema](docs/result-schema.md) · [Reference](docs/reference.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Changelog](docs/CHANGELOG.md) · [SKILL.md](SKILL.md)

Licensed under the [Apache License 2.0](LICENSE).

## Community

Thanks to the [LINUX DO](https://linux.do/) community.
