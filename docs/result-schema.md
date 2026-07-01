# AlphaSift result schema and DSA readiness

AlphaSift's core screening output is a `ScreenResult`. The stable machine-readable schema metadata is available from Python:

```python
from alphasift.result_schema import screen_result_schema

schema = screen_result_schema()
```

The current schema version is `1`.

## Stable top-level fields

Consumers should treat these top-level fields as stable integration points:

- `strategy`, `market`, `strategy_version`, `strategy_category`
- `snapshot_count`, `after_filter_count`, `picks`, `run_id`, `created_at`
- `llm_ranked`, `llm_coverage`, `llm_parse_errors`
- `degradation`, `snapshot_source`, `source_errors`
- `deep_analysis_requested`, `post_analyzers`
- `daily_enriched`, `daily_enrich_count`
- `risk_enabled`, `portfolio_diversity_enabled`, `portfolio_concentration_notes`

## Stable pick fields

Important UI/API fields on each pick include:

- identity: `rank`, `code`, `name`, `final_score`, `screen_score`
- factor diagnostics: `factor_scores`, `ranking_reason`
- risk: `risk_summary`, `risk_score`, `risk_level`, `risk_flags`, `portfolio_penalty`, `portfolio_flags`
- topic/source context: `industry`, `concepts`, `board_heat_score`, `board_heat_summary`
- daily quality: `daily_quality_score`, `daily_quality_flags`, `daily_source`
- post-analysis: `post_analysis_status`, `post_analysis_summaries`, `post_analysis_score_deltas`, `post_analysis_tags`
- optional DSA context: `dsa_context`, `dsa_news`, `dsa_analysis_summary`
- optional DSA deep analysis: `deep_analysis_status`, `deep_analysis_query_id`, `deep_analysis_summary`, `deep_analysis_error`, `deep_analysis_signal_score`, `deep_analysis_sentiment_score`, `deep_analysis_operation_advice`, `deep_analysis_trend_prediction`, `deep_analysis_risk_flags`

## Compact UI card groups

For upstream UI / DSA / agent integrations, use these field groups:

- source health: `snapshot_source`, `source_errors`, `daily_source`, `daily_quality_flags`
- filter/source degradation: `degradation`
- risk flags: `risk_level`, `risk_flags`, `portfolio_flags`, `risk_summary`
- watch items / invalidators: `llm_watch_items`, `llm_invalidators`, `deep_analysis_operation_advice`
- post-analysis: `post_analysis_status`, `post_analysis_summaries`, `post_analysis_tags`

## RunReport payload

Saved runs can be rendered into a Markdown report or exported as a JSON payload:

```bash
alphasift report <run_id> --output data/reports/<run_id>.md
alphasift report <run_id> --json
```

The current `RunReport` schema version is `1`. Stable top-level fields:

- `run`: run identity, strategy/version/category, counts, LLM/post-analysis metadata.
- `summary_cards`: compact metric cards with `label`, `value`, and `status`.
- `source_health`: snapshot source, source errors, degradation notes, daily enrichment status.
- `top_picks`: UI-ready pick cards with identity, scores, risk, topic, daily quality, and post-analysis fields.
- `evaluation`: optional T+N evaluation summary and evaluated pick cards when `--evaluate` is used.

## Run index metadata

Use `alphasift runs --json` for a lightweight saved-run index without loading full run payloads. Current sidecar metadata schema version is `3`.

Stable fields include:

- identity: `run_id`, `strategy`, `market`, `strategy_version`, `strategy_category`, `created_at`
- counts: `picks`, `snapshot_count`, `after_filter_count`
- source status: `snapshot_source`, `source_error_count`, `source_errors`, `degradation_count`, `degradation`
- enrichment status: `llm_ranked`, `llm_coverage`, `daily_enriched`, `daily_enrich_count`, `post_analyzers`
- paths: `path`, `report_path`

## Strategy run summary payload

`GET /strategy-run-summary` summarizes saved-run sidecar metadata without loading full run payloads or evaluating against live quotes:

- `summary`: global counts such as runs with source errors, runs with degradation, capped source-error/degradation samples, LLM-ranked runs, daily-enriched runs, total picks, and latest run.
- `strategies`: one row per strategy with run count, latest run/report, total and average picks, snapshot sources, source-error/degradation counts and samples, LLM/daily-enrichment coverage, post-analyzers, and recent compact run cards.
- Query params: `strategy` filters to one strategy and `limit` caps how many recent run metadata records are scanned.

`GET /data-source-history` summarizes the same sidecar metadata by snapshot source, without live checks:

- `summary`: recent run count, source-error/degradation/fallback rates, stability status/score, capped source-error/degradation samples, next actions, daily-enriched run count, source names, and latest compact run.
- `snapshot_sources`: one row per snapshot source with run count, strategy coverage, latest run, total/average picks, source-error and degradation rates and samples, fallback rate/count, stability status/score, next actions, daily enrichment counts, and recent compact run cards.
- `watchlist`: sources with any error, degradation, or last-good fallback usage, sorted by impact and carrying stability status, score, issue samples, and next actions.
- Query params: `strategy` filters to one strategy and `limit` caps scanned metadata records.

`GET /strategy-performance` summarizes saved evaluation files without re-running live evaluation:

- `summary`: global evaluation count, pick/evaluated/missing counts, average and median return, win rate, average run return, run win rate, performance score, outcome, latest evaluation, and next actions.
- `strategies`: one row per strategy with latest evaluation metadata, pick counts, return/win-rate metrics, run-level metrics, source/degradation counts, performance score, outcome, next actions, and recent compact evaluation cards.
- `leaderboard`: top strategy rows sorted by performance score for first-screen comparison.
- Query params: `strategy` filters to one strategy and `limit` caps scanned evaluation files.

## Evaluation failure review payload

`alphasift evaluate-batch --json` and `alphasift evaluate-strategies --json` include `failure_review` for strategy iteration screens:

- `summary`: failure counts, shown sample count, negative-pick count, missing quote count, failed-breakout count, severe drawdown count, average negative return, and worst return.
- `failure_samples`: worst-first sample cards with run, strategy, code, rank, return, quote status, LLM tags/catalysts/risks, post-analysis tags, risk/portfolio flags, shape status/tags, path status, drawdown/runup, `event_signals`, and `failure_reasons`.
- `dimensions`: failure aggregations by strategy, sector, theme, LLM tag/catalyst/risk, post-analysis tag, combined event signal, risk flag, portfolio flag, shape status, shape tag, and failure reason.
- `recommendations`: UI-ready next actions for data coverage, breakout filters, risk thresholds, concentration rules, or drawdown controls.

Use `--failure-samples N` to control how many sample cards are retained. Aggregations and recommendations remain available even when `N=0`.

The same commands also include `event_signal_review` for success/failure attribution across event-like labels:

- `summary`: signal count, signal occurrence count, positive/negative/mixed signal counts.
- `signals`: one row per combined signal such as `tag:<label>`, `catalyst:<label>`, `risk:<label>`, or `post:<label>`, with sample count, evaluated count, average/median/best/worst returns, win rate, failure count/rate, sample codes, and an `action` of `prefer`, `avoid`, `watch`, or `insufficient_data`.
- `strategy_patch_suggestions`: per-strategy review items that convert positive/negative signal evidence into reviewable `screening.event_profile.preferred_event_tags` and `avoided_event_tags` append suggestions. Each item includes `field_changes`, compact `evidence`, and a YAML fragment under `yaml_patch`; the command does not modify strategy files automatically.
- `recommendations`: UI-ready next actions that suggest which signals should be reviewed as preferred or avoided event tags.

## Data-source doctor payload

`alphasift doctor data-sources --json` emits a stable diagnostic payload for UI, agent, and operations surfaces:

- `snapshot` / `daily`: status, selected source, row count, stale/fallback flags, required fields, missing fields, raw errors.
- `snapshot.quality_summary`: field-quality diagnostics for live snapshot checks, including duplicate codes, checked fields, per-field missing/invalid/non-positive counts, and anomaly tokens.
- `source_health`: raw per-source counters from in-process health guards.
- `health_summary`: UI-ready grouping by `healthy_sources`, `failing_sources`, `disabled_sources`, `never_seen_sources`, plus `last_errors`.
- `freshness_summary`: UI-ready snapshot/daily freshness and cache status with `data_state`, `cache_state`, fallback/stale/unchecked counters, warnings, and `fresh_enough`.
- `snapshot_reconciliation`: present when `--compare-snapshot-sources` is used; compares configured snapshot providers by rows, required-field coverage, quality status, failed sources, and code overlap against the first usable provider.
- `strategy_requirements` / `strategy_coverage`: required fields and coverage status for one strategy or the full strategy catalog.
- `strategy_readiness_summary`: UI-ready strategy readiness rollup with ready/attention/unchecked counts, status counts, impacted/unchecked strategy cards, missing-field impacts, and next actions.
- `recommendations`: next actions derived from live check status, fallback use, stale cache, and health guard state.

## Overview payload

`alphasift overview --json` is the preferred first-screen payload for UI/agent integrations. Current schema version is `1`.

Stable top-level fields:

- `summary`: strategy counts, daily-strategy count, data-source status, strategy-match count, recent-run count, live-check flag.
- `strategy_groups`: strategy names grouped by category, risk profile, holding period, and data requirement.
- `strategy_facets`: UI-ready strategy filter facets with values, counts, query params, and backing strategy names.
- `strategy_cards`: UI-ready strategy cards that join catalog metadata, readiness state, saved-run history, saved-evaluation performance, top factors, use-case hints, next actions, and lane groupings such as `needs_history`, `needs_evaluation`, `performance_leaders`, and `attention`.
- `strategy_matches`: optional ranked strategy recommendations with `score`, `matched`, and `missing`.
- `data_sources`: compact data-source doctor subset with `health_summary`, `freshness_summary`, `snapshot_quality`, strategy requirements, strategy coverage, and recommendations.
- `data_sources.strategy_readiness_summary`: compact readiness rollup for strategy availability panels.
- `run_history_summary`: saved-run metadata rollup by strategy for history dashboards.
- `data_source_history`: saved-run metadata rollup by snapshot source for data-stability dashboards.
- `performance_summary`: saved-evaluation rollup by strategy for performance leaderboards.
- `recent_runs`: lightweight saved-run metadata from `alphasift runs --json`.
- `next_actions`: UI-ready operational next steps.

## Local HTTP API payloads

`alphasift serve` exposes read-only JSON endpoints for local UI/agent integrations without requiring a web framework dependency:

- `GET /health`: service status and schema version.
- `GET /result-schema`: same shape as `screen_result_schema()`; UI-ready field groups and non-goals for `ScreenResult` consumers.
- `GET /overview`: same shape as `alphasift overview --json`; supports query params such as `strategy`, `runs_limit`, `live`, `risk_profile`, `holding_period`, `data_requirement`, and `match_limit`.
- `GET /strategies`: strategy catalog, or ranked matches when style/data query params are present.
- `GET /strategy?name=<strategy_name>`: one strategy metadata card with style, data requirements, required fields, active filters, factor weights, and profile keys.
- `GET /strategy-compare?base=<strategy>&target=<strategy>`: same diff payload as `alphasift strategies --compare <base> <target> --json`.
- `GET /strategy-facets`: strategy filter facets for UI controls, including category, tag, style, data requirement, daily requirement, and required-field dimensions.
- `GET /strategy-cards`: joined strategy cards for dashboards; supports `strategy`, `limit`, and `live`.
- `GET /strategy-readiness`: compact strategy readiness payload; defaults to all strategies and no live data checks, supports `strategy`, `live`, `snapshot_source`, `daily_source`, `daily_code`, and `no_daily`.
- `GET /strategy-run-summary`: saved-run metadata rollup by strategy; supports `strategy` and `limit`.
- `GET /data-source-history`: saved-run metadata rollup by snapshot source; supports `strategy` and `limit`.
- `GET /strategy-performance`: saved-evaluation rollup by strategy; supports `strategy` and `limit`.
- `GET /strategy-templates`: lightweight strategy authoring template catalog without YAML bodies.
- `GET /strategy-template?name=<template_name>`: one strategy authoring template; supports `include_yaml=false`.
- `GET /runs`: saved-run metadata with optional `strategy` and `limit`.
- `GET /report?run=<run_id>`: same shape as `alphasift report <run_id> --json`; supports `max_picks`.
- `GET /doctor/data-sources`: same shape as `doctor data-sources --json`; defaults to no live checks unless `live=true`.

## Strategy compare payload

`alphasift strategies --compare <base> <target> --json` and `GET /strategy-compare?base=<base>&target=<target>` emit a stable diff payload for strategy review screens:

- `base` / `target`: compact strategy summaries with version, category, tags, style, data requirements, active filters, factor weights, and profile keys.
- `differences`: sectioned diffs for identity, tags, style, data requirements, required fields, active filters, hard-filter values, factor weights, and profile keys.
- `summary.changed_sections`: sections with meaningful differences.
- `summary.compatibility_notes`: UI-ready notes such as additional data requirements or daily-feature requirement changes.

## Strategy template payload

`alphasift strategies --templates --json` emits a lightweight catalog for strategy authoring starts:

- `name`, `display_name`, `description`, `category`, `tags`: template identity and grouping.
- `style`: UI/agent strategy-style hints using the same fields as enabled strategies.
- `data_requirements`: expected data dependency such as `snapshot`, `daily_k`, or `industry_context`.
- `notes`: authoring guidance and validation reminders.

`alphasift strategies --template <name> --json` returns the same fields plus `yaml`, a ready-to-edit strategy YAML body. The list endpoint intentionally omits `yaml` so UI catalogs do not carry large template text by default.

## DSA readiness

DSA is optional. Core screening must continue when DSA is unavailable.

Use this command to verify DSA integration before enabling DSA post-analysis:

```bash
alphasift doctor dsa-readiness --json
```

The command checks `DSA_API_URL` by default, or an explicit endpoint:

```bash
alphasift doctor dsa-readiness --api-url http://localhost:8000 --explain
```

Readiness statuses:

- `missing_url`: `DSA_API_URL` is not configured.
- `route_present`: the analyze route is reachable.
- `unauthorized`: the service is present but auth rejected the request.
- `route_missing`: the configured route is wrong or DSA is not serving the expected endpoint.
- `unreachable`: network/connection failure.
- `unexpected_status`: the endpoint returned an unclassified HTTP status.

## Non-goals

AlphaSift does not execute trades and does not implement complete portfolio accounting. It can export watchlist/review-ready screening results, but trade execution and full account bookkeeping belong outside this repository.
