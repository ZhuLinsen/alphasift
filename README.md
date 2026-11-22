<div align="center">

<a href="https://zhulinsen.github.io/alphasift/?lang=en">
  <img src="docs/assets/alphasift-logo.svg" alt="AlphaSift Logo" width="680">
</a>

# 🔎 AlphaSift

**AI Quantitative Stock Screener**

*7 global markets (CN / US / HK / JP / KR / TW / IN) -> Multi-factor YAML screening -> Red-flag AI re-ranking -> Public T+N benchmark*

[![GitHub stars](https://img.shields.io/github/stars/ZhuLinsen/alphasift?style=social)](https://github.com/ZhuLinsen/alphasift/stargazers)
[![CI](https://github.com/ZhuLinsen/alphasift/actions/workflows/ci.yml/badge.svg)](https://github.com/ZhuLinsen/alphasift/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3b82f6.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-10b981.svg)](LICENSE)
[![Live Dashboard](https://img.shields.io/badge/Live%20Dashboard-GitHub%20Pages-0ea5e9.svg)](https://zhulinsen.github.io/alphasift/?lang=en)
[![7 Markets](https://img.shields.io/badge/Markets-CN%20%7C%20US%20%7C%20HK%20%7C%20JP%20%7C%20KR%20%7C%20TW%20%7C%20IN-6366f1.svg)](https://zhulinsen.github.io/alphasift/?lang=en)
[![Agent Skill](https://img.shields.io/badge/Agent%20Skill-OpenClaw%20%7C%20Claude%20Code-10b981.svg)](SKILL.md)
[![MCP Ready](https://img.shields.io/badge/MCP-STDIO%20Ready-8b5cf6.svg)](docs/ecosystem.md)
[![Docker Ready](https://img.shields.io/badge/Docker-Ready-0284c7.svg)](Dockerfile)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/ZhuLinsen/alphasift/pulls)

[**Live Dashboard**](https://zhulinsen.github.io/alphasift/?lang=en) · [**Why AlphaSift**](#-why-alphasift) · [**4 Ways to Start**](#-4-zero-friction-ways-to-start) · [**12-Channel Push**](#-1-line-12-channel-push-notify_urls) · [**track-record Ledger**](https://github.com/ZhuLinsen/alphasift/tree/track-record) · [**Agent Skill**](SKILL.md)

[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md)

</div>

---

## ✨ Why AlphaSift

Most open-source stock tools stop at static indicator filters, one-shot LLM chat prompts, or unverified picks that silently vanish after bad weeks. **AlphaSift treats full-market discovery and post-trade falsification as one unified, inspectable pipeline:**

1. **Deterministic Zero-Key Base & Orthogonal Strategies**: L1 hard filters, multi-factor curves, risk overlay, and 8-bucket hard sector diversity (`portfolio_profile.mode: hard_cap`, `max_same_bucket: 1`) run deterministically with zero API keys. Across 3 local 250-day snapshots (`2026-09-21`, `10-20`, `11-20`), orthogonalizing all 10 CN strategies cut mean pairwise overlap from **8.0%–24.9% -> 0.9%–1.8%** (`max` **100% -> 20%**) and bank concentration from **22%–31.1% -> 4.0%–9.1%**.
2. **Empirically Audited 250-Day Pattern Radar**: Stateless chart patterns must pass a 250-day `next_open` replay (`N >= 200` and positive T+5 excess vs CSI 300) before graduating to `active`; 2 verified patterns are `active`, while 5 classic patterns stay muted `experimental`.
3. **Intelligence-First Red-Flag AI Track**: Instead of guessing on ticker fame, L2 AI injects live filings, news, and fund-flow context (Top-12 in CI Actions workflows; local `Config` defaults to disabled / `8` candidates until `LLM_CANDIDATE_CONTEXT_ENABLED=true` is set), enforces a hard red-flag ceiling (`llm_score <= 35` for unresolved adverse filings), bans brand/familiarity bias, and logs paired same-day CN `rules` vs `ai` alpha (`gemini/gemini-3.8-flash` default with `gemini/gemini-4-hydrogen` fallback, plus DeepSeek / OpenAI / Ollama).
4. **Public `next_open` T+N Ledger, 1-Line 12-Channel Push & Fork Safety**: Every session is committed to `track-record` and graded at `T+5 / T+10 / T+20` with untradable limit-up accounting. Dispatch `<1,200`-char alert briefs via a single `NOTIFY_URLS` variable across **12 native zero-dep channels**, while a **Plan A Fork Guard** prevents forked repos from publishing duplicate websites unless `ALPHASIFT_ENABLE_PAGES=true` is explicitly set.

<table>
  <tr>
    <td width="50%" align="center">
      <a href="https://zhulinsen.github.io/alphasift/?lang=en&theme=dark">
        <img src="docs/assets/dashboard-dark.png" alt="AlphaSift Live Dashboard (Dark)" width="100%">
      </a>
      <br><sub><b>Obsidian Dark Terminal</b> — Consensus Signals, CN Microstructure Breadth &amp; 7-Market T+N Leaderboard</sub>
    </td>
    <td width="50%" align="center">
      <a href="https://zhulinsen.github.io/alphasift/?lang=en&theme=light">
        <img src="docs/assets/dashboard-light.png" alt="AlphaSift Live Dashboard (Light)" width="100%">
      </a>
      <br><sub><b>Editorial Paper Light</b> — Multilingual UI Switcher (<code>ZH | EN | JA</code>) &amp; Audited Track Record</sub>
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

---

## ⚡ 4 Zero-Friction Ways to Start

### 1. 30-Second Zero-Key Full-Market Discovery
```bash
git clone https://github.com/ZhuLinsen/alphasift.git && cd alphasift
pip install -e .

alphasift quickstart
alphasift screen dual_low --no-llm
alphasift screen global_value --market hk --no-llm
```

### 2. Optional Red-Flag AI Ranking, Local CN Pack, 250D Replay & Printable Brief
```bash
cp .env.example .env   # add GEMINI_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY
alphasift pack build --days 250   # build local CN daily pack once before replay/daily-report
alphasift screen dual_low --save-run
alphasift patterns replay --pack-dir ./data/pack/cn --output-md replay.md
alphasift daily-report --pack-dir ./data/pack/cn --output-html daily_report.html --push
```

### 3. Connect to Claude Code, Cursor, Codex, or OpenClaw (`alphasift mcp` + Workbench UI / Docker)
Register the read-only STDIO MCP server (`10` tools, `2` resources; runs `scorecard` post-analysis without outbound notifications), or run either the local Web Workbench UI (`http://127.0.0.1:8765/ui`) or Docker container (both use host port `8765`):
```json
{
  "mcpServers": {
    "alphasift": { "command": "alphasift", "args": ["mcp"] }
  }
}
```
> *Claude Code / Cursor JSON shown above; for Codex (`mcp_servers` TOML) or OpenClaw (`mcp.servers`), see [docs/ecosystem.md](docs/ecosystem.md).*
```bash
alphasift serve --host 127.0.0.1 --port 8765   # Interactive Workbench UI (/ui) & read-only JSON API
# Or containerized on the same loopback port:
docker compose up --build -d
```

### 4. Free Cloud Daily Screening & 1-Line Push via GitHub Actions
1. Fork this repository and enable **GitHub Actions**.
2. Add optional **Repository Secrets** under *Settings -> Secrets and variables -> Actions*:
   - `GEMINI_API_KEY` (or `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`) to activate paired **AI Track** ranking and `--ai-brief auto`.
   - `NOTIFY_URLS` for 1-line push alerts across 12 native channels (see [Notifications](#-1-line-12-channel-push-notify_urls)).
3. **Plan A Fork Guard:** Forked repositories automatically run daily screening, AI ranking, and push notifications while **skipping duplicate website builds**. If you want your own GitHub Pages site on a fork, set repository Variable `ALPHASIFT_ENABLE_PAGES=true` and enable *Settings -> Pages -> GitHub Actions*.

---

## 🧭 Why AlphaSift vs. Alternatives

| Dimension | Static Screeners (`EastMoney` / `TradingView`) | Single-Stock AI (`daily_stock_analysis`) | **AlphaSift** |
|---|---|---|---|
| **Scope & Universe** | Manual UI filters on 1 market at a time | Deep-dive on a pre-picked watchlist | **Full-market discovery across 7 markets (`cn/us/hk/jp/kr/tw/in`)** |
| **Determinism & Diversity** | Opaque UI presets | Prompt-driven per ticker | **Auditable YAML DSL + 8-bucket `hard_cap` orthogonality** |
| **AI Guardrails** | None | Single-ticker sentiment narrative | **Filings/fund-flow context, `<= 35` red-flag cap, anti-fame bias** |
| **Post-Trade Audit** | None | Manual review | **Public `track-record` ledger (`next_open` T+5/10/20 + limit-up blocks)** |
| **Ecosystem Fit** | Standalone UI | **Complementary downstream L3 analyzer** | **Upstream discovery (`alphasift mcp` / `DSA_API_URL`) + `NOTIFY_URLS` 12-channel push** |

---

## 🏗️ Architecture

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
|  L3 Analyzers (scorecard / DSA) |  |  Immutable track-record Log  |
|  Printable HTML & NOTIFY_URLS   |  |  next_open T+5/10/20 Audit   |
+---------------------------------+  +------------------------------+
```

| Capability | Engineering Design |
|---|---|
| **Self-Healing Sources & Pack Storage** | Health-ordered CN snapshot chain (`em_datacenter -> sina -> efinance -> akshare_em`, or `tushare` first with token). Raw `daily.npz` / `meta.csv.gz` matrices stay local or in CI Actions cache and are never redistributed via public GitHub Releases; fork ledger branches inherit fork repo visibility. |
| **Paired Rules vs AI Attribution** | Runs deterministic `rules` and context-grounded `ai` tracks side by side on identical market dates to measure net added/dropped stock alpha honestly. |
| **Low-Noise Idempotent Delivery** | File-locked `(trade_date, channel)` deduplication prevents repeat group pings and blocks stale packs unless `--force-push` is passed. |

---

## 📊 Verified Pattern Radar Benchmark (`250d next_open` vs CSI 300)

Evaluated locally over **`2026-02-05 .. 2026-11-06`** (`180` trading sessions, `5,218` A-share stocks, `next_open` entry excluding one-price limit-ups, benchmark `sh000300`):

| Pattern | Signals | T+5 Matched | T+5 Excess | T+10 Excess | Status |
|---|---:|---:|---:|---:|---|
| **20D Shrink Pullback** (`ma20_shrink_pullback` v2.0) | 2,295 | 2,293 | **+0.158%** | **+0.905%** | `active` |
| **Steady Trend Breakout** (`steady_trend_breakout` v1.0) | 460 | 460 | **+0.271%** | **+0.560%** | `active` |
| 5 Classic Patterns (`single_yang_hold`, `box_breakout`, etc.) | 992–9,233 | 988–9,221 | -1.185% .. -0.175% | -1.207% .. -0.619% | `experimental` |

---

## 🔔 1-Line 12-Channel Push (`NOTIFY_URLS`)

Configure **one comma/newline-separated `NOTIFY_URLS` variable** (or standalone channel env vars) with zero extra dependencies:

```bash
NOTIFY_URLS="pushplus://TOKEN,sct://SENDKEY,bark://api.day.app/KEY,mailto://sender@qq.com:auth@qq.com?to=a@qq.com,b@qq.com,https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
```

| Channel | `NOTIFY_URLS` URI / URL | Standalone Env Vars |
|---|---|---|
| **PushPlus** (`pushplus`) | `pushplus://TOKEN[/TOPIC]` | `PUSHPLUS_TOKEN`, `PUSHPLUS_TOPIC` |
| **ServerChan / ServerChan3** (`serverchan`) | `sct://SENDKEY` (`SCT...` & `sctp123t...`) | `SERVERCHAN_SENDKEY` |
| **Bark** (`bark`) | `bark://KEY` or `bark://host/KEY` | `BARK_URL` |
| **Email SMTP** (`email`) | `mailto://user:pass@host[:port]?to=a,b` | `EMAIL_SENDER`, `EMAIL_PASSWORD`, `EMAIL_RECEIVERS` |
| **WeCom** (`wecom`) | `wecom://KEY` or full webhook URL | `WECOM_WEBHOOK_URL` |
| **Feishu** (`feishu`) | `feishu://TOKEN[#secret=SEC]` or full URL | `FEISHU_WEBHOOK_URL`, `FEISHU_WEBHOOK_SECRET` |
| **DingTalk** (`dingtalk`) | `dingtalk://TOKEN[#secret=SEC]` or full URL | `DINGTALK_WEBHOOK_URL`, `DINGTALK_WEBHOOK_SECRET` |
| **Telegram** (`telegram`) | `tgram://BOT_TOKEN/CHAT_ID` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| **Discord** (`discord`) | `discord://ID/TOKEN` or webhook URL | `DISCORD_WEBHOOK_URL` |
| **Slack** (`slack`) | `slack://T.../B.../...` or webhook URL | `SLACK_WEBHOOK_URL` |
| **ntfy** (`ntfy`) | `ntfy://topic` or `https://ntfy.sh/topic` | `NTFY_URL` |
| **Custom JSON** (`custom`) | `custom://https://...` or HTTPS URL | `CUSTOM_WEBHOOK_URL`, `CUSTOM_WEBHOOK_TOKEN` |
| **Apprise (optional)** | Any Apprise scheme when `apprise` installed | `NOTIFY_URLS` |

> Secrets and tokens in `NOTIFY_URLS` are redacted from all logs/errors, and every target shares an `flock`-protected `(trade_date, channel)` idempotency ledger. Verify locally via `alphasift notify status` and `alphasift notify test --dry-run`. A low-profile Atom 1.0 RSS feed is also emitted at [`site/feed.xml`](https://zhulinsen.github.io/alphasift/site/feed.xml).

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
<summary><strong>Real Sample Output (Standalone Local 2026-11-20 Run, Deterministic <code>--no-llm</code>)</strong></summary>

**China A-Shares (`dual_low` v1.1 standalone snapshot run; live daily runs appear on `track-record`):** 5,215 stocks -> 205 filtered -> Top 5 across 5 distinct industries (`hard_cap: 1`):

| # | Code | Security | Industry | PE | PB |
|---:|---|---|---|---:|---:|
| 1 | `601997` | Bank of Guiyang | Banks | 4.4 | 0.32 |
| 2 | `601117` | China National Chemical | Construction | 6.6 | 0.61 |
| 3 | `600741` | HASCO | Auto Parts | 7.7 | 0.77 |
| 4 | `603799` | Huayou Cobalt | Rare Metals | 8.7 | 1.07 |
| 5 | `601233` | Tongkun Group | Chemical Fibers | 6.8 | 1.11 |

**Hong Kong (`global_value --market hk` on 2026-11-20):** 567 stocks -> 236 filtered: `0267.HK` CITIC Limited · `0001.HK` CK Hutchison · `1339.HK` PICC Group · `1398.HK` ICBC · `0358.HK` Jiangxi Copper.

**Japan (`global_value --market jp` on 2026-11-20):** 748 stocks -> 311 filtered: `9501.T` TEPCO · `5401.T` Nippon Steel · `1605.T` INPEX · `9104.T` Mitsui O.S.K. Lines · `9022.T` Central Japan Railway.

*Research examples only — never investment advice.*

</details>

<details>
<summary><strong>Supported Markets, Key Configuration & Known Limitations</strong></summary>

| Market | Snapshot & Daily Source | Scope Notes |
|---|---|---|
| `cn` | `em_datacenter -> sina -> efinance -> akshare_em` (`tushare` first with token); private `DailyPack` / `tencent` / `sina` / `akshare` / `baostock` | Full A-share universe, EastMoney sector backfill, optional announcements & hotspots |
| `us`, `hk`, `jp`, `tw`, `in` | Yahoo Finance screener + `yfinance` | Large/mid-cap floor (`>= ~$1B` / `HK$8B` / `JPY 150B`), single unofficial endpoint |
| `kr` | Yahoo Finance screener + Naver Finance mobile API | Naver supplies PE/PB (`ALPHASIFT_KR_VALUATION=0` disables); `~10s` extra |

Key env vars (`ALPHASIFT_*` or standard names — see [docs/configuration.md](docs/configuration.md) and [.env.example](.env.example)): `LITELLM_MODEL` (default `gemini/gemini-3.8-flash`), `LITELLM_FALLBACK_MODELS` (`gemini/gemini-4-hydrogen`), `GEMINI_API_KEY` / `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`, `LLM_CANDIDATE_CONTEXT_ENABLED=true`, `NOTIFY_URLS`, `ALPHASIFT_ENABLE_PAGES=true` (required on forks to publish GitHub Pages), `TUSHARE_TOKEN`, `ALPHASIFT_PACK_DIR`, and `DSA_API_URL`.

**Known limitations:** AlphaSift is a screening & post-trade audit engine, not an execution broker or full dividend-adjusted portfolio simulator. Prior to `ALPHASIFT_NEXT_OPEN_SWITCH_DATE` (`2026-11-21`), historical `track-record` runs used `close` entry (untradable share marked unassessed); from `2026-11-21` onward, CN track-record uses `next_open` with raw limit-up block accounting.

</details>

---

## 🔗 Related Projects — Quant Trio

| Project | Role in Stack | How It Connects |
|---|---|---|
| **[AlphaEvo](https://github.com/ZhuLinsen/alphaevo)** | Research & Factor Mining | Discovers & stress-tests alpha genomes before distilling them into AlphaSift YAML rules |
| **[AlphaSift](https://github.com/ZhuLinsen/alphasift)** | **Multi-Market Funnel & Benchmark** | Screens `5,000+` symbols → `3–5` picks across 7 markets & verifies `T+5 / 10 / 20` on `track-record` |
| **[daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis)** | L3 Single-Stock Deep Dive | Consumes shortlisted picks via `DSA_API_URL` or MCP for granular fundamentals, news & action plans |

See [docs/ecosystem.md](docs/ecosystem.md) for architecture diagrams, STDIO MCP schemas, and Docker setup.

---

## Disclaimer, Docs & License

> This repository is built purely for research, engineering verification, and educational experiments — never investment advice or buy/sell recommendations. Market data, LLM rankings, and pattern signals can be incomplete or delayed.

[Usage](docs/usage.md) · [Configuration](docs/configuration.md) · [Ecosystem & MCP](docs/ecosystem.md) · [Deployment & Mirror](docs/deployment.md) · [Strategy Guide](docs/strategy-guide.md) · [Scoring](docs/scoring.md) · [Result Schema](docs/result-schema.md) · [Reference](docs/reference.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Changelog](docs/CHANGELOG.md) · [SKILL.md](SKILL.md)

Licensed under the [Apache License 2.0](LICENSE).
