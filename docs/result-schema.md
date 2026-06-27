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
