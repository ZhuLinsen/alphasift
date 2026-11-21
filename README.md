<div align="center">

<a href="https://zhulinsen.github.io/alphasift/?lang=en">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/banner-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/banner-light.svg">
    <img alt="AlphaSift — Full-Market Quantitative Discovery & T+N Benchmark" src="docs/assets/banner-dark.svg" width="100%">
  </picture>
</a>

<h3>Full-market stock discovery for AI agents — deterministic YAML strategies, empirical 250-day pattern radar, optional dual-track LLM re-ranking, and audited T+N track record.</h3>

<p>
  <a href="https://github.com/ZhuLinsen/alphasift/actions/workflows/ci.yml"><img src="https://github.com/ZhuLinsen/alphasift/actions/workflows/ci.yml/badge.svg" alt="CI Status"></a>
  <a href="https://zhulinsen.github.io/alphasift/?lang=en"><img src="https://img.shields.io/badge/dashboard-live%20(ZH%20%7C%20EN%20%7C%20JA)-22c55e.svg" alt="Live Dashboard"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-3b82f6.svg" alt="Python 3.10+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-10b981.svg" alt="Apache 2.0"></a>
</p>

<p>
  <a href="https://zhulinsen.github.io/alphasift/?lang=en"><strong>Live Dashboard</strong></a> ·
  <a href="https://zhulinsen.github.io/alphasift/site/daily_report.html?lang=en"><strong>Daily Research Brief</strong></a> ·
  <a href="https://github.com/ZhuLinsen/alphasift/tree/track-record"><strong>track-record Ledger</strong></a> ·
  <a href="SKILL.md"><strong>Agent Skill</strong></a>
</p>

<p>
  <strong>English</strong> · <a href="README.zh-CN.md">简体中文</a> · <a href="README.ja.md">日本語</a>
</p>

</div>

---

## Live Multilingual Terminal & Research Brief

Every trading session runs all built-in strategies automatically, evaluates prior picks at **`T+5 / T+10 / T+20`** against each market's benchmark (`next_open` entry accounting for untradable limit-up blocks), and publishes an interactive dashboard supporting **English · 中文 · 日本語** and **Obsidian Dark · Editorial Light** themes.

<table>
  <tr>
    <td width="50%" align="center">
      <a href="https://zhulinsen.github.io/alphasift/?lang=en&theme=dark">
        <img src="docs/assets/dashboard-dark.png" alt="AlphaSift Live Dashboard (Dark · English)" width="100%">
      </a>
      <br><sub><b>Obsidian Dark Terminal</b> — Cross-Strategy Consensus, CN Microstructure Breadth &amp; 7-Market T+N Leaders</sub>
    </td>
    <td width="50%" align="center">
      <a href="https://zhulinsen.github.io/alphasift/?lang=en&theme=light">
        <img src="docs/assets/dashboard-light.png" alt="AlphaSift Live Dashboard (Light · English)" width="100%">
      </a>
      <br><sub><b>Editorial Paper Light</b> — Multilingual UI Switcher (<code>中 | EN | 日</code>) &amp; Audited Track Record</sub>
    </td>
  </tr>
  <tr>
    <td colspan="2" align="center">
      <a href="https://zhulinsen.github.io/alphasift/site/daily_report.html?lang=en&theme=dark">
        <img src="docs/assets/daily-report.png" alt="AlphaSift Standalone Post-Close Research Brief" width="88%">
      </a>
      <br><sub><b>Standalone Printable Research Brief</b> (<code>alphasift daily-report --output-html</code>) — Executive Summary, 7-Bucket Return Histogram, Announcement Risk Screening &amp; 20D K-Line Hits</sub>
    </td>
  </tr>
</table>

---

## Core Architecture & Design

```mermaid
flowchart LR
  M["7 Markets Snapshot & Private DailyPack"] --> L1["L1 YAML Hard Filters & Factor Scoring"]
  L1 --> L2["L2 Red-Flag Skeptic LLM + Top-12 Context (Gemini 3.8 Flash / DeepSeek / OpenAI)"]
  L2 --> RK["Risk Overlay & 8-Bucket Hard Sector Cap"]
  RK --> L3["L3 Post-Analysis (scorecard / DSA / HTTP) & Filing Check"]
  L3 --> OUT["Printable HTML Brief & 1-Line 12-Channel Push (NOTIFY_URLS)"]
  RK --> AUD["Immutable track-record Branch & next_open T+N Evaluation"]
```

| Capability | Engineering Design |
|---|---|
| **Zero-Key Deterministic Engine** | L1 hard filters, multi-factor curves, risk overlay, and 8-bucket sector diversity (`portfolio_profile.mode: hard_cap`) execute deterministically with zero external LLM keys required. |
| **Orthogonalized 10-CN Strategies** | All 10 CN strategies separate cleanly by market cap (`blue_chip_income` ≥ ¥50B vs `dual_low` ¥5B–¥60B), style, and sector cap (`max_same_bucket: 1`). Across 3 local pack dates (`2026-09-21`, `10-20`, `11-20`), mean pairwise overlap fell from **8.0%–24.9% → 0.9%–1.8%** (`max` **100% → 20%**) and bank concentration dropped from **22%–31.1% → 4.0%–9.1%**. |
| **Empirically Audited Pattern Radar** | Stateless technical patterns are gated via 250-day `next_open` replay (`N ≥ 200` and positive T+5 excess vs CSI 300). Only 2 verified patterns are `active`; 5 classic patterns remain muted `experimental`. |
| **Intelligence-First AI Track** | Configure `GEMINI_API_KEY` (defaults to `gemini/gemini-3.8-flash` with `gemini/gemini-4-hydrogen` fallback), `DEEPSEEK_API_KEY`, or `OPENAI_API_KEY`. The CN AI track automatically enables `LLM_CANDIDATE_CONTEXT_ENABLED=true` to inject Top-12 filings/news/fund-flow context, caps unresolved adverse filings (`llm_score <= 35`), bans brand/familiarity bias, and tracks paired `rules` vs `ai` alpha. |
| **Self-Healing Sources & Fork Guard** | Health-ordered CN snapshot chain (`em_datacenter → sina → efinance → akshare_em`, or `tushare` first with token). Raw daily packs stay strictly private (`actions/cache`). **Plan A Fork Guard:** forked repos run screening & push notifications while skipping duplicate GitHub Pages builds unless `ALPHASIFT_ENABLE_PAGES=true`. |
| **1-Line 12-Channel Push (`NOTIFY_URLS`)** | Auto-sniffs URI/URLs for **PushPlus, Server酱/³, Bark, Email (SMTP), WeCom, Feishu, DingTalk, Telegram, Discord, Slack, ntfy, Custom JSON** (zero extra deps, optional `apprise` fallback) with `(trade_date, channel)` idempotency locks, plus low-profile `site/feed.xml` Atom RSS. |

---

## Verified Pattern Radar Benchmark (`250d next_open` vs CSI 300)

Evaluated locally over **`2026-02-05 .. 2026-11-06`** (`180` trading sessions, `5,218` A-share stocks, `next_open` entry excluding one-price limit-ups, benchmark `sh000300`):

| Pattern | Family · Mode | Signals | T+5 Matched | T+5 Excess | T+5 Excess Win | T+10 Excess | Status |
|---|---|---:|---:|---:|---:|---:|---|
| **20D Low-Vol Shrink Pullback** (`ma20_shrink_pullback` v2.0) | `trend_continuation · direct` | 2,295 | 2,293 | **+0.158%** | 46.45% | **+0.905%** | `active` |
| **Steady Trend Breakout** (`steady_trend_breakout` v1.0) | `breakout · direct` | 460 | 460 | **+0.271%** | 48.70% | **+0.560%** | `active` |
| `single_yang_hold` / `box_breakout` / `bottom_volume_yang` / `double_bottom_breakout` / `shooting_star_confirm` | mixed | 992–9,233 | 988–9,221 | -1.185% .. -0.175% | 38.26%–45.47% | -1.207% .. -0.619% | `experimental` |

---

## Quick Start (30 Seconds)

```bash
pip install -e .

# 1. Zero-key A-share & global discovery
alphasift quickstart
alphasift screen dual_low --no-llm
alphasift screen global_value --market hk --no-llm

# 2. Optional AI dual-track ranking (defaults to gemini/gemini-3.8-flash + gemini-4-hydrogen fallback)
cp .env.example .env   # set GEMINI_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY
alphasift screen dual_low --save-run

# 3. Pattern radar replay, standalone HTML brief & push connectivity check
alphasift patterns replay --pack-dir ./data/pack/cn --output-md replay.md
alphasift daily-report --pack-dir ./data/pack/cn --output-html daily_report.html --push
alphasift notify status
alphasift notify test --dry-run
```

**Python API & HTTP Agent Server:**

```python
from alphasift import screen, evaluate_saved_run

res = screen("dual_low", market="cn", use_llm=False)
for pick in res.picks:
    print(pick.rank, pick.code, pick.name, pick.industry, pick.final_score)
```

```bash
alphasift serve --host 127.0.0.1 --port 8000   # Read-only JSON API for AI agents & orchestrators
```

---

## Notifications & 1-Line 12-Channel Push

Configure **one comma/newline-separated `NOTIFY_URLS` variable** (or individual channel env vars) — zero extra notification dependencies required:

```bash
NOTIFY_URLS="pushplus://YOUR_TOKEN,sct://YOUR_SENDKEY,bark://api.day.app/YOUR_KEY,mailto://sender@qq.com:auth_code@qq.com?to=me@qq.com,https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
```

| Channel | 1-Line `NOTIFY_URLS` URI / URL | Standalone Env Vars | Notes |
|---|---|---|---|
| **PushPlus** (`pushplus`) | `pushplus://TOKEN[/TOPIC]` | `PUSHPLUS_TOKEN`, `PUSHPLUS_TOPIC` | Direct WeChat push via PushPlus API |
| **Server酱 / ³** (`serverchan`) | `sct://SENDKEY` (supports `SCT...` & `sctp123t...`) | `SERVERCHAN_SENDKEY` | Auto-routes `sctp{num}t...` to Server酱³ endpoint |
| **Bark** (`bark`) | `bark://KEY` or `bark://host/KEY` | `BARK_URL` | iOS push via APNs |
| **Email SMTP** (`email`) | `mailto://user:pass@host[:port]?to=a,b` | `EMAIL_SENDER`, `EMAIL_PASSWORD`, `EMAIL_RECEIVERS` | Zero-dep stdlib `smtplib`; auto-infers QQ/163/Gmail/Outlook SSL/TLS |
| **WeCom** (`wecom`) | `wecom://KEY` or full webhook URL | `WECOM_WEBHOOK_URL` | `<1,200`-char alert-first Markdown card |
| **Feishu** (`feishu`) | `feishu://TOKEN[#secret=SEC]` or full URL | `FEISHU_WEBHOOK_URL`, `FEISHU_WEBHOOK_SECRET` | Interactive blue card with optional HMAC-SHA256 |
| **DingTalk** (`dingtalk`) | `dingtalk://TOKEN[#secret=SEC]` or full URL | `DINGTALK_WEBHOOK_URL`, `DINGTALK_WEBHOOK_SECRET` | Markdown payload with optional HMAC-SHA256 |
| **Telegram** (`telegram`) | `tgram://BOT_TOKEN/CHAT_ID` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Bot API (`disable_web_page_preview=true`) |
| **Discord** (`discord`) | `discord://ID/TOKEN` or webhook URL | `DISCORD_WEBHOOK_URL` | Rich Embed linking to dashboard |
| **Slack** (`slack`) | `slack://T.../B.../...` or `https://hooks.slack.com/...` | `SLACK_WEBHOOK_URL` | Block Kit / text alert |
| **ntfy** (`ntfy`) | `ntfy://topic` or `https://ntfy.sh/topic` | `NTFY_URL` | Self-hostable pub-sub push |
| **Custom JSON** (`custom`) | `custom://https://...` or unknown HTTPS URL | `CUSTOM_WEBHOOK_URL`, `CUSTOM_WEBHOOK_TOKEN` | JSON (`event`, `trade_date`, `markdown`, `summary`) + Bearer auth |
| **Apprise (optional)** | Any Apprise scheme when `apprise` is installed | `NOTIFY_URLS` | Automatic fallback to 90+ community services |

> Every channel shares an `flock`-protected idempotency ledger keyed by `(trade_date, channel)` and skips stale packs unless `--force-push` is passed. Secrets and tokens in `NOTIFY_URLS` are scrubbed from all errors/logs. A low-profile Atom 1.0 RSS feed is also emitted at [`site/feed.xml`](https://zhulinsen.github.io/alphasift/site/feed.xml).

---

<details>
<summary><strong>Built-in YAML Strategies (12 Strategies Across 7 Markets)</strong></summary>

| Strategy | Markets | Style | Core Focus |
|---|---|---|---|
| `dual_low` | `cn` | Value | Mid-cap low PE/PB (`¥5B–¥60B`), `hard_cap: 1` per industry bucket |
| `blue_chip_income` | `cn` | Income | Mega-cap liquid dividend leaders (`≥ ¥50B`) |
| `quality_value` | `cn` | GARP | Mid-cap growth valuation stability (`¥15B–¥200B`) |
| `low_volatility_quality` | `cn` | Defensive | Low 20D volatility, controlled drawdown & ATR (daily K-line) |
| `balanced_alpha` | `cn` | Multi-Factor | Broad balanced factor discovery with sector hard cap |
| `momentum_quality` | `cn` | Trend Quality | 60D trend confirmation + quality gates |
| `shrink_pullback` | `cn` | Pullback | Shrink-volume pullback to MA20 support within uptrend (daily K-line) |
| `capital_heat` | `cn` | Momentum | Active turnover & capital flow without extreme overheating |
| `oversold_reversal` | `cn` | Reversal | Controlled-drawdown mean-reversion candidates |
| `volume_breakout` | `cn` | Breakout | Volume expansion breaking 20D resistance |
| `global_value` | `us, hk, jp, kr, tw, in` | Value | Currency-neutral low PE/PB screener for global markets |
| `us_momentum_quality` | `us` | Trend | US large-cap (`≥ $1B`) momentum + quality |

</details>

<details>
<summary><strong>Real Sample Output (2026-11-20 Snapshot, Deterministic <code>--no-llm</code>)</strong></summary>

**China A-Shares (`dual_low` on 2026-11-20 pack snapshot):** 5,215 stocks → 205 filtered → Top 5 across 5 distinct industries (`hard_cap: 1`):

| # | Code | Name | Industry | PE | PB |
|---:|---|---|---|---:|---:|
| 1 | `601997` | 贵阳银行 | Banks | 4.4 | 0.32 |
| 2 | `601117` | 中国化学 | Construction | 6.6 | 0.61 |
| 3 | `600741` | 华域汽车 | Auto Parts | 7.7 | 0.77 |
| 4 | `603799` | 华友钴业 | Rare Metals | 8.7 | 1.07 |
| 5 | `601233` | 桐昆股份 | Chemical Fibers | 6.8 | 1.11 |

**Hong Kong (`global_value --market hk` on 2026-11-20):** 567 stocks → 236 filtered: `0267.HK` CITIC Limited · `0001.HK` CK Hutchison · `1339.HK` PICC Group · `1398.HK` ICBC · `0358.HK` Jiangxi Copper.

**Japan (`global_value --market jp` on 2026-11-20):** 748 stocks → 311 filtered: `9501.T` TEPCO · `5401.T` Nippon Steel · `1605.T` INPEX · `9104.T` Mitsui O.S.K. Lines · `9022.T` Central Japan Railway.

*Research examples only — never investment advice.*

</details>

<details>
<summary><strong>Supported Markets, Configuration & Known Limitations</strong></summary>

| Market | Snapshot & Daily Source | Scope Notes |
|---|---|---|
| `cn` | `em_datacenter → sina → efinance → akshare_em` (`tushare` first with token); private `DailyPack` / `tencent` / `sina` / `akshare` / `baostock` | Full A-share universe, EastMoney sector backfill, optional announcements & hotspots |
| `us`, `hk`, `jp`, `tw`, `in` | Yahoo Finance screener + `yfinance` | Large/mid-cap floor (`≥ ~$1B` / `HK$8B` / `¥150B`), single unofficial endpoint |
| `kr` | Yahoo Finance screener + Naver Finance mobile API | Naver supplies PE/PB (`ALPHASIFT_KR_VALUATION=0` disables); `~10s` extra |

Key env vars (`ALPHASIFT_*` or standard names — see [docs/configuration.md](docs/configuration.md) and [.env.example](.env.example)): `LITELLM_MODEL` (default `gemini/gemini-3.8-flash`), `LITELLM_FALLBACK_MODELS` (`gemini/gemini-4-hydrogen`), `GEMINI_API_KEY` / `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`, `LLM_CANDIDATE_CONTEXT_ENABLED=true`, `NOTIFY_URLS` (1-line 12-channel push), `ALPHASIFT_ENABLE_PAGES=true` (required on forks to publish GitHub Pages), `TUSHARE_TOKEN`, `ALPHASIFT_PACK_DIR`, and `DSA_API_URL`.

**Known limitations:** AlphaSift is a screening & post-trade audit engine, not an execution broker or full dividend-adjusted portfolio simulator. Prior to `ALPHASIFT_NEXT_OPEN_SWITCH_DATE` (`2026-11-21`), historical `track-record` runs used `close` entry (untradable share marked unassessed); from `2026-11-21` onward, CN track-record uses `next_open` with raw limit-up block accounting.

</details>

---

## Disclaimer, Docs & License

> This repository is built purely for research, engineering verification, and educational experiments — never investment advice or buy/sell recommendations. Market data, LLM rankings, and pattern signals can be incomplete or delayed.

[Usage](docs/usage.md) · [Configuration](docs/configuration.md) · [Deployment & Mirror](docs/deployment.md) · [Strategy Guide](docs/strategy-guide.md) · [Scoring](docs/scoring.md) · [Design](docs/design.md) · [Positioning](docs/positioning.md) · [Comparison](docs/comparison.md) · [Reference](docs/reference.md) · [Changelog](docs/CHANGELOG.md) · [SKILL.md](SKILL.md)

Licensed under the [Apache License 2.0](LICENSE).
