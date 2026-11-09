# AlphaSift

**Full-market stock discovery for AI agents.** AlphaSift scans every A-share (or the larger listings of six other markets), screens them with auditable YAML strategies, optionally lets an LLM rank the shortlist, keeps the final picks diversified across sectors, and saves every run so you can check later whether the picks worked.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
![Markets](https://img.shields.io/badge/markets-CN%20%7C%20US%20%7C%20HK%20%7C%20JP%20%7C%20KR%20%7C%20TW%20%7C%20IN-orange)

English | [中文](README.zh-CN.md) | [日本語](README.ja.md)

```text
full market ──► L1 hard filters + factor scores ──► L2 LLM ranking (optional)
  (5,000+ names)    (YAML strategy, no API key)        (cross-candidate reasoning)
                                                              │
saved run ◄── L3 post-analysis ◄── risk overlay + sector diversity cap
   │          (scorecard / DSA / HTTP)
   └──► T+N evaluation: returns, win rate, failure review
```

## Why AlphaSift

- **A-shares first, six more markets in beta.** China A-shares go through a dedicated multi-source chain. US, Hong Kong, Japan, South Korea, Taiwan and India go through the Yahoo Finance screener, which also works from overseas servers and CI runners; they have one unofficial data source and fewer fields (see Known limitations).
- **Runs without an API key.** L1 screening, scoring, risk and diversity control are deterministic. An LLM only re-ranks the shortlist when you configure one.
- **Strategies are YAML, not code.** Filters, factor weights, scoring curves, risk thresholds and sector buckets live in readable files that you can diff and review.
- **Picks don't all come from one sector.** Every row carries an industry or sector label. `portfolio_profile.mode: hard_cap` keeps at most N picks per sector in the Top N.
- **Data sources heal themselves.** Source outcomes persist across runs, so dead sources are tried last. Each source has a time budget. A last-good snapshot is used, marked as stale, when every live source fails.
- **Every run is checkable.** Save runs and evaluate them later with transaction costs, win rates, failure samples and optional price paths (max drawdown / run-up).
- **Built for agents.** [SKILL.md](SKILL.md) describes the callable interface. `alphasift serve` exposes a read-only JSON API for dashboards and orchestrators.

## Quick start

```bash
pip install -e .

# A-shares, no API key needed
alphasift screen dual_low --no-llm

# Other markets: us, hk, jp, kr, tw, in
alphasift screen global_value --market hk --no-llm

# Add LLM ranking: set GEMINI_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY
# (or LITELLM_MODEL / LLM_CHANNELS) in .env first
cp .env.example .env
alphasift screen dual_low

# Save a run, then evaluate it a few days later
alphasift screen dual_low --no-llm --save-run
alphasift evaluate <run_id> --with-price-path --explain
```

Run `alphasift quickstart` for a guided no-key demo, and `alphasift strategies` to list the strategies.

## Example output

Real runs on 2026-11-03 with `--no-llm`. **They show what the engine outputs; they are not recommendations.**

**China A-shares** (`dual_low`): 5,218 stocks, 284 after filters, Top 5 capped at 2 per sector

| # | Code | Name | Industry | PE | PB |
|---:|---|---|---|---:|---:|
| 1 | 601169 | 北京银行 | Banks | 5.8 | 0.43 |
| 2 | 600016 | 民生银行 | Banks | 5.7 | 0.26 |
| 3 | 601668 | 中国建筑 | Construction | 6.6 | 0.39 |
| 4 | 601186 | 中国铁建 | Infrastructure | 6.3 | 0.29 |
| 5 | 601919 | 中远海控 | Shipping | 7.9 | 1.12 |

**Hong Kong** (`global_value --market hk`): 581 stocks, 275 after filters

| # | Code | Name | Sector | PE | PB |
|---:|---|---|---|---:|---:|
| 1 | 0998.HK | China CITIC Bank | Financial Services | 5.8 | 0.43 |
| 2 | 0267.HK | CITIC Limited | Industrials | 5.3 | 0.38 |
| 3 | 1398.HK | ICBC | Financial Services | 6.5 | 0.59 |
| 4 | 0001.HK | CK Hutchison | Industrials | 6.9 | 0.45 |
| 5 | 0358.HK | Jiangxi Copper | Basic Materials | 5.7 | 0.77 |

**Japan** (`global_value --market jp`): 773 stocks, 408 after filters

| # | Code | Name | Sector | PE | PB |
|---:|---|---|---|---:|---:|
| 1 | 9501.T | Tokyo Electric Power | Utilities | 2.6 | 0.21 |
| 2 | 9022.T | Central Japan Railway | Industrials | 7.2 | 0.71 |
| 3 | 9502.T | Chubu Electric Power | Utilities | 10.6 | 0.66 |
| 4 | 1911.T | Sumitomo Forestry | Consumer Cyclical | 9.0 | 0.70 |
| 5 | 7203.T | Toyota Motor | Consumer Cyclical | 8.7 | 0.97 |

On an overseas server, the A-share run takes about 10 seconds once source health is warm. Each Yahoo market takes 2–10 seconds.

## Supported markets

| `--market` | Market | Snapshot source | Notes |
|---|---|---|---|
| `cn` | China A-shares | sina → efinance → akshare_em → em_datacenter (Tushare first when a token is set) | Health-aware ordering; EastMoney industry backfill |
| `us` | United States | Yahoo screener (NYSE / Nasdaq listings ≥ $1B, including ADRs) | `ALPHASIFT_US_TICKERS` uses an explicit ticker list instead |
| `hk` | Hong Kong | Yahoo screener | Universe floor ≈ HK$8B |
| `jp` | Japan | Yahoo screener | Universe floor ≈ ¥150B |
| `kr` | South Korea | Yahoo screener + Naver Finance | Yahoo has no KR PE/PB; they come from Naver's (unofficial) mobile API, about 10s extra. `ALPHASIFT_KR_VALUATION=0` turns it off |
| `tw` | Taiwan | Yahoo screener | TWSE and TPEx listings |
| `in` | India | Yahoo screener | NSE and BSE listings |

Non-CN codes are Yahoo symbols (`AAPL`, `0700.HK`, `7203.T`, `005930.KS`). Daily K-line enrichment and T+N evaluation use yfinance for these markets. Candidate-level news, announcement and fund-flow context is A-share only.

## Built-in strategies

| Strategy | Markets | Type | Idea |
|---|---|---|---|
| `dual_low` | cn | Value | Low PE + low PB, activity and stability confirmation, hard cap per sector |
| `quality_value` | cn | Value | Reasonable valuation with liquidity and controlled volatility |
| `blue_chip_income` | cn | Income | Liquid blue chips with dividend quality |
| `low_volatility_quality` | cn | Quality | Defensive screen using daily volatility, drawdown and ATR |
| `volume_breakout` | cn | Trend | Volume expansion through resistance |
| `shrink_pullback` | cn | Trend | Pullback into support within an uptrend (daily K-line) |
| `capital_heat` | cn | Momentum | Active capital flow without extreme overheating |
| `oversold_reversal` | cn | Reversal | Repair candidates with controlled drawdown |
| `balanced_alpha` | cn | Framework | General multi-factor discovery |
| `momentum_quality` | cn | Framework | Trend confirmation plus quality filters |
| `global_value` | us, hk, jp, kr, tw, in | Value | `dual_low` for other markets, with no currency-dependent thresholds |
| `us_momentum_quality` | us | Trend | Momentum and quality for US large caps |

Write your own in `strategies/`. See the [strategy guide](docs/strategy-guide.md).

## Configuration

Copy `.env.example` to `.env`. AlphaSift reads LiteLLM-style settings, so it can reuse the configuration of [daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis). The most common settings:

| Variable | Purpose | Default |
|---|---|---|
| `LITELLM_MODEL` | Main model, `provider/model` | `gemini/gemini-2.5-flash` |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` | Provider key for LLM ranking | - |
| `LLM_CHANNELS` / `LITELLM_CONFIG` | Multi-channel or LiteLLM Router config | - |
| `TUSHARE_TOKEN` | Puts Tushare first in the A-share chain | - |
| `SNAPSHOT_SOURCE_PRIORITY` | Override the A-share source order | depends on token |
| `ALPHASIFT_SNAPSHOT_CALL_TIMEOUT_SEC` | Time budget per snapshot source | `60` |
| `INDUSTRY_AUTO_BACKFILL` | Fill missing A-share industry labels | `true` |
| `ALPHASIFT_DATA_DIR` | Runs, caches and source health | `./data` |
| `DSA_API_URL` | Enable the optional DSA deep-analysis step | - |

The full list is in [docs/configuration.md](docs/configuration.md).

## More features

- **Python API**: `from alphasift import screen, evaluate_saved_run`, then `screen("dual_low", use_llm=False, market="cn")`.
- **LLM context**: `--context "..."` adds market notes, and `--candidate-context-file` adds per-stock research.
- **Post-analysis (L3)**: the local `scorecard` runs by default. `--post-analyzer dsa` sends the final shortlist to [daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) for single-stock deep analysis.
- **Hotspots**: `alphasift hotspots` and `alphasift hotspot "<topic>"` rank A-share themes and resolve leader stocks with cache and fallback metadata.
- **Agent and UI payloads**: `alphasift overview --json`, `alphasift serve`, and `alphasift doctor data-sources --all-strategies --explain`. Endpoints are listed in the [usage guide](docs/usage.md).

## Known limitations

- AlphaSift is a discovery and ranking engine, not a backtester or an execution system. T+N evaluation compares saved prices with later prices and does not model dividends, suspensions or position constraints.
- `evaluate-strategies --window 5,10,20` measures true T+N: each pick's return at the close of the Nth trading bar after entry, against the market benchmark (CSI 300, S&P 500, Hang Seng, Nikkei 225, KOSPI, TAIEX, Nifty 50) over the same bars. Picks whose window has not elapsed are reported as pending. `evaluate` and `evaluate-batch` without a window still measure return to the latest price.
- Entry is placed in exchange time: a run saved before the session open enters at the previous close; a run saved during or after the session does not count that day's bar toward run-up or drawdown. Exchange holidays are not modeled beyond the bars the data source returns.
- Yahoo-screener markets are not the whole market: the universe is listings above a market-cap floor (about USD 1B), one query per Yahoo sector, capped at 4000 rows. They depend on a single unofficial endpoint, estimate traded value as price × volume, and use total market cap as float cap. Korean PE/PB come from Naver Finance (another unofficial endpoint); loss-making companies have no PE. PE/PB are only derived from EPS and book value when the trading and reporting currencies match.
- Daily K-line strategies enrich only the L1 shortlist, not the whole market.
- `strategies/` and `alphasift/strategies/` mirror each other (development vs installed package) and must stay in sync.

## Disclaimer

This project is for learning, research and engineering experiments. It is not investment advice, a return guarantee or a buy/sell instruction. Market data, LLM output and strategy parameters can be delayed, incomplete or wrong. You are responsible for your own research, compliance, costs and decisions.

## Documentation

[Usage](docs/usage.md) · [Configuration](docs/configuration.md) · [Strategy guide](docs/strategy-guide.md) · [Scoring](docs/scoring.md) · [Design](docs/design.md) · [Positioning](docs/positioning.md) · [Comparison](docs/comparison.md) · [Reference](docs/reference.md) · [Changelog](docs/CHANGELOG.md) · [SKILL.md](SKILL.md)

## License

[Apache License 2.0](LICENSE)
