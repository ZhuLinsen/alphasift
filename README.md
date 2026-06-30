# AlphaSift

AlphaSift is an agent-friendly stock discovery and ranking engine. It scans a broad market universe, applies auditable YAML strategies, enriches candidates with optional market context, ranks them with deterministic factors and optional LLM judgment, and saves runs for later T+N evaluation.

> This README is the default English version. A Chinese version is available at [README.zh-CN.md](README.zh-CN.md).

## Disclaimer

- This project is for learning, research, and engineering experiments only.
- It is not investment advice, a return guarantee, or a buy/sell instruction.
- Outputs depend on third-party market data, optional LLM providers, local configuration, and strategy parameters. They can be delayed, incomplete, wrong, or unsuitable for real trading.
- Users are responsible for independent research, compliance checks, transaction costs, liquidity risks, announcement timing, and all resulting decisions.

## What AlphaSift does

- **L1 deterministic screening**: hard filters and factor scoring over the full market snapshot.
- **L2 optional LLM ranking**: structured cross-candidate reasoning, theses, catalysts, risks, confidence, and portfolio risk buckets.
- **L3 pluggable post-analysis**: local scorecard by default, with optional DSA or external HTTP analyzers.
- **Hotspot discovery**: topic/sector heat ranking, hotspot detail resolution, leader stock fallbacks, cache quality metadata, and history sidecars.
- **Daily feature enrichment**: optional candidate-level daily K-line features such as moving averages, MACD/RSI, breakout strength, volume ratio, pullback distance, and platform duration.
- **Evaluation loop**: save runs, evaluate later using newer snapshots, deduct transaction cost, tag follow-through / failed-breakout outcomes, and optionally fetch price paths for max drawdown / max favorable excursion.
- **Agent-native interface**: `SKILL.md` describes capabilities and callable interfaces for AI agents.

## Quick start

```bash
# Install in editable mode
pip install -e .

# Copy configuration template
cp .env.example .env
# Edit .env if you want LLM ranking:
# GEMINI_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY
# or LITELLM_MODEL / LLM_CHANNELS / LITELLM_CONFIG

# List built-in strategies
alphasift strategies

# Run the no-key demo
alphasift quickstart

# Screen without LLM ranking
alphasift screen dual_low --no-llm

# Screen with LLM ranking, if a provider key is configured
alphasift screen dual_low

# Reuse another project's environment file
alphasift --env-file /home/ubuntu/daily_ai_assistant/.env screen balanced_alpha

# Add market or theme context to the LLM prompt
alphasift screen balanced_alpha --context "Brokerage names are seeing volume expansion today."

# Add candidate-level news / announcement / fund-flow context
alphasift screen balanced_alpha --candidate-context-file candidate_context.csv

# Show local L3 scorecard explanations
alphasift screen balanced_alpha --explain

# Add DSA as an optional L3 analyzer; requires DSA_API_URL
alphasift screen dual_low --post-analyzer dsa

# Disable L3 post-analysis explicitly
alphasift screen dual_low --no-post-analysis

# Audit project and strategy configuration
alphasift audit
```

Example output shape:

```text
$ alphasift screen dual_low --no-llm
Universe 5190 -> filtered 337 -> output Top 5
rank  code    name       score  price   change   pe     pb
1     002039  黔源电力   72.7   20.72   -2.49%   14.76  1.99
2     002444  巨星科技   71.0   30.82   +0.29%   14.59  1.95
3     002128  电投能源   70.9   31.60   -2.41%   14.00  1.90
```

## Screening examples

The following recorded examples were run on April 12, 2026, using the previous trading day's A-share close data from April 10, 2026. LLM ranking was disabled with `--no-llm`; these rows are examples of engine output, not recommendations.

### Dual Low

Full market 5190 stocks -> 337 after hard filters -> Top 5 output.

| Rank | Code | Name | Score | Price | Change | PE | PB |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | 002039 | 黔源电力 | 72.7 | 20.72 | -2.49% | 14.76 | 1.99 |
| 2 | 002444 | 巨星科技 | 71.0 | 30.82 | +0.29% | 14.59 | 1.95 |
| 3 | 002128 | 电投能源 | 70.9 | 31.60 | -2.41% | 14.00 | 1.90 |
| 4 | 002236 | 大华股份 | 70.8 | 17.43 | +1.04% | 14.86 | 1.50 |
| 5 | 600583 | 海油工程 | 68.9 | 7.02 | +4.15% | 14.89 | 1.17 |

### Volume Breakout

Full market 5190 stocks -> 126 after hard filters -> Top 5 output.

| Rank | Code | Name | Score | Price | Change |
|---:|---|---|---:|---:|---:|
| 1 | 002837 | 英维克 | 74.0 | 99.05 | +6.40% |
| 2 | 688183 | 生益电子 | 73.8 | 95.30 | +7.09% |
| 3 | 300803 | 指南针 | 73.3 | 101.68 | +3.07% |
| 4 | 002384 | 东山精密 | 73.0 | 143.55 | +8.83% |
| 5 | 300277 | 汽轮科技 | 73.0 | 19.74 | +5.73% |

## Hotspot workflow

AlphaSift can discover current market hotspots and resolve a specific topic into a detail payload with raw timeline evidence, compact display-ready route events, leader stocks, source confidence, stale/fallback metadata, and quality diagnostics.

```bash
# Discover hotspot topics and write schema_version=2 cache/history sidecars
alphasift hotspots --provider akshare --top 12 --output data/hotspots.json --history data/hotspot.history.jsonl --explain

# Inspect a single hotspot topic
alphasift hotspot "AI compute" --top-stocks 10 --timeline --fallback-cache data/hotspots.json --explain

# Safe offline/no-network check
alphasift hotspots --provider none --explain
```

Hotspot cache files include:

- `schema_version`: currently `2`
- `generated_at`
- `metadata`: provider, row count, source errors, stale/fallback state
- `hotspots`: normalized topic rows
- sidecars such as `*.meta.json` and JSONL history when requested

Leader stock fallbacks are intentionally explicit. When live constituent APIs fail and AlphaSift uses last-good/cache leaders, returned stocks carry fields such as `source="last_good_cache.leader_stocks"`, `source_confidence`, and `fallback_used=true` instead of pretending to be live provider data.

Hotspot details keep the raw `timeline` for auditability and also expose a compact `route` list for applications. `route` is grouped by day, newest first, trimmed for UI display, and falls back to a short current heat/stage/leader summary when no timeline evidence is available.

## Python API

```python
from alphasift import screen

result = screen("dual_low", use_llm=False)
for pick in result.picks:
    print(f"{pick.rank}. {pick.code} {pick.name} score={pick.final_score:.1f}")
```

Saved-run evaluation helpers are also exported:

```python
from alphasift import evaluate_saved_run, evaluate_saved_runs
```

## Configuration

AlphaSift is designed to reuse LiteLLM-style configuration used by `daily_stock_analysis` and similar projects.

| Variable | Required | Description | Default |
|---|---:|---|---|
| `LITELLM_MODEL` | Recommended | Main model in `provider/model` format | `gemini/gemini-2.5-flash` |
| `LITELLM_FALLBACK_MODELS` | No | Comma-separated fallback models | - |
| `LLM_CHANNELS` | No | Multi-channel provider config using `LLM_{NAME}_*` | - |
| `LITELLM_CONFIG` | No | LiteLLM Router YAML file | - |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` | For LLM ranking | Provider API key | - |
| `OPENAI_BASE_URL` / `OLLAMA_API_BASE` | No | OpenAI-compatible or Ollama endpoint | - |
| `LLM_MAX_TOKENS` | No | Max tokens requested from LLM ranking; keeps local servers from generating unbounded output after client timeout | `2048` |
| `LLM_CONTEXT` | No | Extra market/theme context for LLM ranking | - |
| `LLM_CANDIDATE_CONTEXT_ENABLED` | No | Fetch candidate news/announcements/fund-flow context by default | `false` |
| `INDUSTRY_MAP_FILES` | No | Local code-to-industry/concepts/board-heat files | - |
| `INDUSTRY_PROVIDER` | No | Optional board/industry provider such as `akshare` | `none` |
| `SNAPSHOT_SOURCE_PRIORITY` | No | Snapshot source order | Depends on Tushare token |
| `SNAPSHOT_FALLBACK_MAX_AGE_HOURS` | No | Max acceptable age for last-good snapshot fallback; empty disables the guard | - |
| `ALPHASIFT_SOURCE_CALL_TIMEOUT_SEC` | No | Global caller-side timeout for third-party wrapper data-source calls; `0`/`off` disables | - |
| `ALPHASIFT_SNAPSHOT_CALL_TIMEOUT_SEC` | No | Snapshot wrapper timeout for `efinance`/`akshare_em`/`tushare` | `60` |
| `ALPHASIFT_DAILY_CALL_TIMEOUT_SEC` | No | Daily wrapper timeout for `akshare`/`baostock`/`tushare`/`yfinance` | `20` |
| `ALPHASIFT_EASTMONEY_MIN_INTERVAL_SEC` | No | Minimum interval for direct Eastmoney HTTP calls | `1.0` |
| `ALPHASIFT_EASTMONEY_JITTER_SEC` | No | Random jitter added to the Eastmoney interval | `0.3` |
| `TUSHARE_TOKEN` / `TUSHARE_API_TOKEN` | For Tushare | Tushare Pro token | - |
| `POST_ANALYZERS` | No | L3 analyzers; set `none` to disable | `scorecard` |
| `DSA_API_URL` | For DSA analyzer | DSA service URL or full analysis endpoint | - |
| `DAILY_ENRICH_ENABLED` | No | Enable candidate-level daily K-line enrichment | `false` |
| `DAILY_SOURCE` | No | Daily K-line source: `auto`, `tencent`, `sina`, `akshare`, `baostock`, or `tushare` | `auto` |
| `ALPHASIFT_DATA_DIR` | No | Run records, caches, and evaluation results | `./data` |
| `STRATEGIES_DIR` | No | Custom strategy directory | auto-detect |

Example multi-channel LiteLLM config:

```env
LLM_CHANNELS=primary
LLM_PRIMARY_PROTOCOL=openai
LLM_PRIMARY_BASE_URL=https://api.deepseek.com/v1
LLM_PRIMARY_API_KEYS=sk-xxx,sk-yyy
LLM_PRIMARY_MODELS=deepseek-chat,deepseek-reasoner
LITELLM_MODEL=openai/deepseek-chat
LITELLM_FALLBACK_MODELS=openai/gpt-4o-mini,anthropic/claude-3-5-sonnet
```

Example single-provider config:

```env
GEMINI_API_KEY=...
LITELLM_MODEL=gemini/gemini-2.5-flash
```

You can load external `.env` files repeatedly:

```bash
alphasift --env-file /path/to/daily_stock_analysis/.env \
  --env-file /path/to/daily_ai_assistant/.env \
  screen balanced_alpha
```

For the full configuration reference, see [docs/configuration.md](docs/configuration.md).

## Data sources

AlphaSift supports multiple A-share market snapshot sources and automatically falls back by priority.

Default without Tushare token:

```text
sina -> efinance -> akshare_em -> em_datacenter
```

Default with `TUSHARE_TOKEN` / `TUSHARE_API_TOKEN` and no manual priority override:

```text
tushare -> sina -> efinance -> akshare_em -> em_datacenter
```

| Source | Backend | Notes |
|---|---|---|
| `sina` | Sina Finance Market Center | Direct HTTP full-market source with PE/PB/turnover/market-cap fields |
| `efinance` | Eastmoney push2 | Fast during live sessions |
| `akshare_em` | Eastmoney push endpoint via AkShare-style access | Backup live source |
| `em_datacenter` | Eastmoney Data Center | Often available outside trading hours |
| `tushare` | Tushare Pro `daily` + `daily_basic` | Requires token; previous/nearest trading day data |

Daily K-line enrichment defaults to `DAILY_SOURCE=auto`. The auto chain uses `tushare -> tencent -> sina -> akshare -> baostock` when a Tushare token is configured, otherwise `tencent -> sina -> akshare -> baostock`. Tencent is a direct HTTP K-line source with no wrapper dependency and is preferred over Eastmoney-heavy wrapper paths for candidate-level history enrichment; Sina provides a second direct HTTP fallback before wrapper sources. Repeatedly failing sources are temporarily skipped, and expired daily cache can be used as a marked stale fallback when every live daily source fails.

Source support matrix:

| Capability | Primary chain | Fields |
|---|---|---|
| Daily K-line enrichment | `tushare` when token exists, then `tencent`, `sina`, `akshare`, `baostock` with health-aware auto reordering | OHLCV, qfq where supported, technical factors, 20d volatility/ATR/drawdown controls, per-row `daily_source` provenance, `daily_quality_score`/flags, source-health stats; low-quality/fetch-failed/stale rows feed the final risk overlay |
| Full-market snapshot | `sina`, then `efinance`, `akshare_em`, `em_datacenter`; `tushare` first when token exists | price, change, amount, market cap, PE/PB, turnover |
| Candidate context | `news`, `fund_flow`, `announcement`, `quote` | news, announcements, fund flow, Tencent quote valuation/turnover |
| Last-good fallback | daily history cache and snapshot cache | marked with stale/fallback attrs when live sources fail |

If a source is unavailable, times out, or lacks fields required by a strategy, AlphaSift skips it and tries the next source. Direct HTTP sources use request timeouts; third-party wrapper calls such as efinance, AkShare, Baostock, Tushare, and yfinance also have caller-side timeouts inspired by adjacent provider-manager projects, so a stuck wrapper cannot block the whole run indefinitely. Eastmoney-only HTTP fallbacks use a shared retrying session with serial throttling and jitter, following the same anti-ban pattern documented by `a-stock-data`; tune `ALPHASIFT_EASTMONEY_MIN_INTERVAL_SEC` upward for batch runs on sensitive networks. If all live sources fail, the last-good snapshot fallback is explicitly marked as stale/fallback data; `SNAPSHOT_FALLBACK_MAX_AGE_HOURS` can reject overly old fallback cache to avoid repeating stale selections.

## Built-in strategies

| Strategy | Type | Description |
|---|---|---|
| `dual_low` | Value | Low PE + low PB defensive value screen |
| `volume_breakout` | Trend | Volume expansion and resistance breakout |
| `quality_value` | Value | Reasonable valuation, liquidity, and controlled volatility |
| `capital_heat` | Momentum | Active capital flow without extreme overheating |
| `oversold_reversal` | Reversal | Repair candidates with controlled drawdown and still-valid liquidity |
| `balanced_alpha` | Framework | General multi-factor discovery strategy |
| `momentum_quality` | Framework | Trend confirmation plus quality filters |
| `shrink_pullback` | Trend | Pullback into support during a broader uptrend; uses daily enrichment |

Add custom YAML strategies under `strategies/`. See [docs/strategy-guide.md](docs/strategy-guide.md).

## Project layout

```text
alphasift/
├── SKILL.md                 # Agent skill description and callable interface
├── README.zh-CN.md          # Chinese README
├── strategies/              # Strategy YAML files
├── docs/
│   ├── configuration.md     # Configuration reference
│   ├── design.md            # Design principles
│   ├── positioning.md       # Product positioning
│   ├── reference.md         # Structure, boundaries, observed runs
│   ├── scoring.md           # Scoring details
│   ├── strategy-guide.md    # Strategy authoring guide
│   └── usage.md             # Usage guide
└── alphasift/               # Python package
    ├── cli.py               # CLI entry point
    ├── config.py            # Environment configuration
    ├── context.py           # LLM context assembly
    ├── candidate_context.py # Candidate news/announcement/fund-flow context
    ├── daily.py             # Daily K-line feature enrichment
    ├── hotspot.py           # Hotspot discovery/detail/cache contract
    ├── industry.py          # Industry/concept/board heat mapping
    ├── models.py            # Data models
    ├── snapshot.py          # Market snapshot loading and fallback
    ├── filter.py            # L1 hard filters
    ├── scorer.py            # Factor scoring
    ├── ranker.py            # L2 LLM ranking
    ├── risk.py              # Independent risk layer
    ├── post_analysis.py     # L3 post-analysis plugins
    ├── dsa.py               # Optional DSA integration
    ├── store.py             # Run persistence
    ├── evaluate.py          # T+N evaluation
    ├── pipeline.py          # Main orchestration
    └── strategy.py          # Strategy YAML loader
```

## Relationship with daily_stock_analysis

`daily_stock_analysis` (DSA) is an external single-stock deep-analysis service. AlphaSift is upstream: it discovers and ranks candidates across the market. DSA is downstream: it can analyze a small final shortlist in depth.

- AlphaSift does broad discovery, deterministic scoring, LLM ranking, hotspot analysis, and saved-run evaluation.
- DSA does individual stock deep analysis through its own API, usually `POST /api/v1/analysis/analyze`.
- The integration is optional and configured through `DSA_API_URL`.
- To control cost and latency, AlphaSift only calls DSA for final selected candidates.
- The default L3 analyzer is local `scorecard`; DSA and external HTTP analyzers are optional.

## Known limitations

- Strategies that depend on daily K-line features enrich only the L1 top candidates, not the entire historical market.
- AlphaSift is not a full backtesting engine or portfolio execution system.
- DSA post-analysis is synchronous and better suited to low-frequency final-candidate review.
- Tushare fallback depends on the user's own token, point balance, and permissions.
- T+N evaluation compares saved run prices with later snapshots; it is not a rigorous event-study backtest and does not model dividends, suspensions, slippage, or rebalancing constraints.
- The repository keeps both `strategies/` and `alphasift/strategies/` mirrors for development and packaged usage; built-in strategy files should stay in sync.

## Verification

Last recorded full-suite check:

```text
$ python -m pytest -q
176 passed, 1 skipped in 1.56s
```

## Documentation

- [SKILL.md](SKILL.md) — agent skill description and function interface
- [README.zh-CN.md](README.zh-CN.md) — Chinese README
- [docs/usage.md](docs/usage.md) — usage guide
- [docs/configuration.md](docs/configuration.md) — configuration reference
- [docs/positioning.md](docs/positioning.md) — positioning and relative advantages
- [docs/comparison.md](docs/comparison.md) — comparison, gaps, and priorities
- [docs/design.md](docs/design.md) — design principles
- [docs/reference.md](docs/reference.md) — structure, data-source boundaries, observed runs
- [docs/scoring.md](docs/scoring.md) — scoring system details
- [docs/strategy-guide.md](docs/strategy-guide.md) — custom strategy guide

## License

Apache License 2.0
