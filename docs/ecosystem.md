# AlphaSift Ecosystem — Quant Trio, MCP & Docker

AlphaSift serves as the **cross-market funnel & public verification engine** in an open-source quantitative trio alongside [daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) and [AlphaEvo](https://github.com/ZhuLinsen/alphaevo).

## Quant Trio Architecture

```
+-------------------------------------------------------------------+
| 1. AlphaEvo (ZhuLinsen/alphaevo)                                  |
|    Evolutionary alpha mining & LLM/AST factor genome discovery    |
+---------------------------------+---------------------------------+
                                  | distilled factors & YAML priors
                                  v
+-------------------------------------------------------------------+
| 2. AlphaSift (this repo) — L1 Hard Filters + L2 Score & Verify    |
|    - Screens 7 markets (CN/HK/US/JP/KR/TW/IN) after close         |
|    - Explains topic alignment & portfolio concentration risk      |
|    - Public T+5 / T+10 / T+20 next_open track-record ledger       |
+---------------------------------+---------------------------------+
                                  | Top 3-5 picks + MCP / JSON API
                                  v
+-------------------------------------------------------------------+
| 3. daily_stock_analysis (ZhuLinsen/daily_stock_analysis) — L3     |
|    Deep single-stock research, news sentiment & IM briefing       |
+-------------------------------------------------------------------+
```

## STDIO MCP Integration (`alphasift mcp`)

AlphaSift ships a zero-dependency JSON-RPC 2.0 STDIO MCP server (`2024-11-05`) supporting both `Content-Length` headers and newline-delimited JSON.

### Claude Code / Cursor (`mcpServers`)

```json
{
  "mcpServers": {
    "alphasift": {
      "command": "alphasift",
      "args": ["mcp"]
    }
  }
}
```
> For **OpenAI Codex CLI** (`mcp_servers` TOML / `codex mcp add alphasift -- alphasift mcp`) and **OpenClaw** (`mcp.servers`), use the respective client key mapping with the same `alphasift mcp` command.

### Exposed Tools (14) & Resources (4)

- **Strategies**: `alphasift_list_strategies`, `alphasift_get_strategy`, `alphasift_compare_strategies`
- **Screening & Patterns**: `alphasift_screen`, `alphasift_list_patterns`, `alphasift_scan_patterns`, `alphasift_replay_patterns`
- **Diagnostics, Digest & Ledger**: `alphasift_overview`, `alphasift_doctor_data_sources`, `alphasift_notify_status`, `alphasift_list_runs`, `alphasift_markets_digest`, `alphasift_daily_report`, `alphasift_markets`
- **Resources**: `alphasift://skill`, `alphasift://strategies`, `alphasift://patterns`, `alphasift://markets`

## Local Web Workbench UI (`alphasift serve`)

```bash
alphasift serve --host 127.0.0.1 --port 8765
# Open http://127.0.0.1:8765/ui (or http://127.0.0.1:8765/ in a browser)
# Read-only JSON routes include /markets, /strategies, /patterns, /daily-report, /markets-digest
# Pure JSON API index remains available via ?format=json or Accept: application/json
```

## Docker Quickstart

```bash
docker compose up --build -d
# Workbench UI: http://127.0.0.1:8765/ui
# HTTP liveness check: curl http://127.0.0.1:8765/health
```
Named volume `alphasift_data` preserves non-root (`UID 10001`) ownership on `/app/data`.
