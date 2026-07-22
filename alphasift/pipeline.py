# -*- coding: utf-8 -*-
"""Main pipeline — orchestrates L1 → L2 → result."""

import logging
import uuid
from pathlib import Path

import pandas as pd

from alphasift.config import Config
from alphasift.candidate_context import collect_candidate_context
from alphasift.context import build_llm_context
from alphasift.daily import enrich_daily_features
from alphasift.dsa_provider import apply_dsa_provider_context
from alphasift.filter import (
    apply_hard_filters,
    hard_filter_rejection_summary,
    hard_filter_waterfall,
    requires_daily_features,
    without_daily_filters,
)
from alphasift.industry import enrich_industry_concepts
from alphasift.models import Pick, ScreenResult
from alphasift.normalize import (
    normalize_code,
    safe_bool as _safe_bool,
    safe_float as _safe_float,
    safe_int as _safe_int,
    safe_string_list as _safe_string_list,
    safe_text,
)
from alphasift.post_analysis import normalize_post_analyzers, run_post_analyzers
from alphasift.ranker import rank_candidates_with_metadata
from alphasift.risk import apply_portfolio_overlay, apply_risk_overlay
from alphasift.scorer import compute_screen_scores, factor_score_columns
from alphasift.sentiment import apply_sentiment_overlay
from alphasift.snapshot import fetch_snapshot_with_fallback
from alphasift.strategy import load_all_strategies

logger = logging.getLogger(__name__)


def screen(
    strategy: str,
    *,
    market: str = "cn",
    max_output: int | None = None,
    use_llm: bool = True,
    llm_context: str | None = None,
    llm_context_files: list[str | Path] | None = None,
    candidate_context_files: list[str | Path] | None = None,
    collect_llm_candidate_context: bool | None = None,
    candidate_context_max_candidates: int | None = None,
    candidate_context_providers: list[str] | None = None,
    industry_map_files: list[str | Path] | None = None,
    industry_provider: str | None = None,
    post_analyzers: list[str] | None = None,
    post_analysis_max_picks: int | None = None,
    daily_enrich: bool | None = None,
    daily_enrich_max_candidates: int | None = None,
    explain_filters: bool = False,
    deep_analysis: bool = False,
    deep_analysis_max_picks: int | None = None,
    context: dict[str, object] | None = None,
    config: Config | None = None,
) -> ScreenResult:
    """Execute stock screening with the given strategy.

    Args:
        strategy: Strategy name (matches a YAML file in strategies/).
        market: Market scope, currently only "cn".
        max_output: Override max output count from strategy.
        use_llm: Whether to use LLM for L2 ranking.
        llm_context: Optional market/news/theme context supplied to the LLM ranker.
        llm_context_files: Optional text files appended to LLM context.
        candidate_context_files: Optional CSV/JSON/JSONL files keyed by code with candidate-level context.
        collect_llm_candidate_context: Whether to fetch Top-K candidate news/fund-flow context for LLM.
        candidate_context_max_candidates: Max candidates to fetch external context for.
        candidate_context_providers: Optional provider names: news, fund_flow, announcement.
        industry_map_files: Optional code->industry/concepts files used before L1/L2.
        industry_provider: Optional provider for board mapping, e.g. "akshare".
        post_analyzers: Optional L3 analyzers, e.g. ["scorecard", "dsa"].
        post_analysis_max_picks: Override max number of picks sent to post analyzers.
        daily_enrich: Whether to enrich shortlisted candidates with daily K-line features.
        daily_enrich_max_candidates: Max candidates to enrich after snapshot filtering.
        explain_filters: Whether to include sequential hard-filter waterfall diagnostics.
        deep_analysis: Backward-compatible alias for post_analyzers=["dsa"].
        deep_analysis_max_picks: Backward-compatible max-picks alias for DSA.
        context: Optional host runtime context. DSA may provide LLM settings and
            callable data providers under context["dsa"].
        config: Runtime config. Defaults to Config.from_env().

    Returns:
        ScreenResult with ranked picks.
    """
    if config is None:
        config = Config.from_env()

    if market not in ("cn", "us"):
        raise ValueError(f"Unsupported market: {market!r} (supported: cn, us)")

    run_id = uuid.uuid4().hex[:12]
    degradation: list[str] = []

    # 1. Load strategy
    strategies = load_all_strategies(config.strategies_dir)
    if strategy not in strategies:
        available = ", ".join(strategies.keys()) or "(none)"
        raise ValueError(f"Strategy '{strategy}' not found. Available: {available}")

    strat = strategies[strategy]
    screening = strat.screening
    if market not in screening.market_scope:
        raise ValueError(
            f"Strategy '{strategy}' does not support market '{market}'. "
            f"Supported: {', '.join(screening.market_scope)}"
        )
    output_count = max_output or screening.max_output
    analyzer_names = normalize_post_analyzers(
        post_analyzers if post_analyzers is not None else config.post_analyzers
    )
    if deep_analysis and "dsa" not in analyzer_names:
        analyzer_names.append("dsa")
    analyzer_max_picks = (
        post_analysis_max_picks
        or deep_analysis_max_picks
    )
    daily_needed = requires_daily_features(screening.hard_filters)
    daily_requested = config.daily_enrich_enabled if daily_enrich is None else daily_enrich
    if daily_enrich_max_candidates is not None:
        daily_limit = daily_enrich_max_candidates
    elif screening.daily_enrich_max_candidates is not None:
        daily_limit = screening.daily_enrich_max_candidates
    else:
        daily_limit = config.daily_enrich_max_candidates
    snapshot_filters = without_daily_filters(screening.hard_filters) if daily_needed else screening.hard_filters

    # 2. Fetch snapshot
    snapshot_df = fetch_snapshot_with_fallback(
        config.snapshot_source_priority,
        required_columns=_required_snapshot_columns(snapshot_filters),
        fallback_snapshot_path=config.fallback_snapshot_path,
        fallback_max_age_hours=config.snapshot_fallback_max_age_hours,
        market=market,
    )
    effective_industry_map_files = (
        list(industry_map_files)
        if industry_map_files is not None
        else list(config.industry_map_files)
    )
    effective_industry_provider = (
        industry_provider
        if industry_provider is not None
        else config.industry_provider
    )
    effective_industry_provider = str(effective_industry_provider or "none").strip().lower()
    if effective_industry_map_files or effective_industry_provider not in {"", "none", "off", "false"}:
        snapshot_df, industry_notes = enrich_industry_concepts(
            snapshot_df,
            map_files=effective_industry_map_files,
            provider=effective_industry_provider,
            max_boards=config.industry_provider_max_boards,
            provider_cache_dir=config.industry_provider_cache_dir,
            provider_cache_ttl_hours=config.industry_provider_cache_ttl_hours,
        )
        degradation.extend(f"Industry/concepts enrichment: {item}" for item in industry_notes)
    snapshot_count = len(snapshot_df)
    universe_audit = _build_universe_audit(
        snapshot_df,
        market=market,
        minimum_count=screening.universe_min_count,
    )
    if not bool(universe_audit["minimum_count_met"]):
        raise RuntimeError(
            "Snapshot universe is incomplete for this strategy: "
            f"rows={snapshot_count}, minimum_required={screening.universe_min_count}"
        )
    if screening.require_unique_codes and (
        not bool(universe_audit["codes_unique"])
        or not bool(universe_audit["codes_valid"])
    ):
        raise RuntimeError(
            "Snapshot universe contains invalid or duplicate security codes: "
            f"invalid_rows={universe_audit['invalid_code_rows']}, "
            f"duplicate_rows={universe_audit['duplicate_code_rows']}"
        )
    snapshot_source = str(snapshot_df.attrs.get("snapshot_source", ""))
    source_errors = [str(item) for item in snapshot_df.attrs.get("source_errors", [])]
    degradation.extend(f"Snapshot source fallback: {item}" for item in source_errors)
    if bool(snapshot_df.attrs.get("fallback_used")):
        stale_age = snapshot_df.attrs.get("stale_age_hours")
        if stale_age is None:
            degradation.append("Snapshot source fallback: last_good_cache stale")
        else:
            degradation.append(
                f"Snapshot source fallback: last_good_cache stale_age_hours={stale_age}"
            )

    # 3. L1 hard filter. If a strategy needs daily features, first apply only
    # snapshot-safe filters, then enrich a narrowed candidate pool.
    if explain_filters:
        snapshot_waterfall = hard_filter_waterfall(snapshot_df, snapshot_filters)
        if snapshot_waterfall:
            degradation.append(
                "Snapshot hard-filter waterfall: "
                + _format_filter_waterfall(snapshot_waterfall)
            )
    df = apply_hard_filters(snapshot_df, snapshot_filters)
    after_filter_count = len(df)
    _record_universe_stage(universe_audit, "snapshot_hard_filter", after_filter_count)

    if df.empty:
        return ScreenResult(
            strategy=strategy,
            market=market,
            snapshot_count=snapshot_count,
            after_filter_count=0,
            run_id=run_id,
            degradation=[*degradation, "No candidates after hard filter"],
            snapshot_source=snapshot_source,
            source_errors=source_errors,
            strategy_version=strat.version,
            strategy_category=strat.category,
            post_analyzers=analyzer_names,
            daily_enriched=False,
            risk_enabled=config.risk_enabled,
            portfolio_diversity_enabled=config.portfolio_diversity_enabled,
            universe_audit=_finalize_universe_audit(universe_audit, pick_codes=[]),
        )

    daily_enriched = False
    daily_enrich_count = 0
    if daily_needed or daily_requested:
        provisional = _sort_screened_candidates(compute_screen_scores(df, screening), screening)
        universe_audit["daily_coverage_target_count"] = len(provisional)
        if screening.require_full_daily_coverage and daily_limit < len(provisional):
            raise RuntimeError(
                "Strategy requires full daily K-line coverage but the configured limit is too low: "
                f"target={len(provisional)}, DAILY_ENRICH_MAX_CANDIDATES={daily_limit}"
            )
        enrich_count = min(daily_limit, len(provisional))
        universe_audit["daily_attempted_count"] = enrich_count
        daily_candidates = provisional.head(enrich_count)
        try:
            enriched = enrich_daily_features(
                daily_candidates,
                max_rows=enrich_count,
                lookback_days=config.daily_lookback_days,
                source=config.daily_source,
                fetch_retries=config.daily_fetch_retries,
                max_workers=config.daily_fetch_max_workers,
                require_adjusted=_requires_adjusted_daily(screening),
            )
            daily_enriched = True
            daily_errors = [str(item) for item in enriched.attrs.get("daily_errors", [])]
            daily_enrich_count = int(enriched.attrs.get("daily_success_count", len(enriched)))
            universe_audit["daily_success_count"] = daily_enrich_count
            target_count = int(universe_audit.get("daily_coverage_target_count") or 0)
            universe_audit["daily_coverage_ratio"] = round(
                daily_enrich_count / target_count,
                6,
            ) if target_count else 1.0
            universe_audit["daily_coverage_complete"] = (
                daily_enrich_count == target_count
            )
            if screening.require_full_daily_coverage and not bool(
                universe_audit["daily_coverage_complete"]
            ):
                raise RuntimeError(
                    "Strategy requires full daily K-line coverage but some rows failed: "
                    f"succeeded={daily_enrich_count}, target={target_count}"
                )
            daily_source_counts = dict(enriched.attrs.get("daily_source_counts", {}) or {})
            daily_quality_flag_counts = dict(enriched.attrs.get("daily_quality_flag_counts", {}) or {})
            daily_source_order_notes = [str(item) for item in enriched.attrs.get("daily_source_order_notes", [])]
            daily_source_health_notes = _daily_source_health_notes(
                dict(enriched.attrs.get("daily_source_health", {}) or {})
            )
            degradation.append(
                f"Daily K-line enrichment attempted {enrich_count} candidates, "
                f"succeeded {daily_enrich_count} of {after_filter_count} snapshot-filtered candidates"
            )
            if daily_source_counts:
                source_summary = ", ".join(
                    f"{name}={count}" for name, count in sorted(daily_source_counts.items())
                )
                degradation.append(f"Daily K-line sources: {source_summary}")
            if daily_quality_flag_counts:
                flag_summary = ", ".join(
                    f"{name}={count}" for name, count in sorted(daily_quality_flag_counts.items())
                )
                degradation.append(f"Daily K-line quality flags: {flag_summary}")
            if daily_source_order_notes:
                degradation.append("Daily K-line source ordering: " + " | ".join(daily_source_order_notes[:3]))
            if daily_source_health_notes:
                degradation.append("Daily K-line source health: " + "; ".join(daily_source_health_notes))
            if daily_errors:
                sample = " | ".join(daily_errors[:5])
                suffix = f" | +{len(daily_errors) - 5} more" if len(daily_errors) > 5 else ""
                degradation.append(f"Daily K-line enrichment row errors: {sample}{suffix}")
            if daily_needed:
                if explain_filters:
                    daily_waterfall = hard_filter_waterfall(enriched, screening.hard_filters)
                    if daily_waterfall:
                        degradation.append(
                            "Daily hard-filter waterfall: "
                            + _format_filter_waterfall(daily_waterfall)
                        )
                daily_filter_rejections = hard_filter_rejection_summary(
                    enriched,
                    screening.hard_filters,
                    limit=6,
                )
                df = apply_hard_filters(enriched, screening.hard_filters)
                after_filter_count = len(df)
                _record_universe_stage(universe_audit, "daily_hard_filter", after_filter_count)
                if daily_filter_rejections:
                    degradation.append(
                        "Daily hard-filter rejections: "
                        + "; ".join(daily_filter_rejections)
                    )
            else:
                df = enriched
        except Exception as exc:
            if daily_needed:
                raise RuntimeError(
                    "Daily K-line enrichment is required by this strategy but failed: "
                    f"{exc}"
                ) from exc
            degradation.append(f"Daily K-line enrichment skipped: {exc}")

    if df.empty:
        return ScreenResult(
            strategy=strategy,
            market=market,
            strategy_version=strat.version,
            strategy_category=strat.category,
            snapshot_count=snapshot_count,
            after_filter_count=0,
            run_id=run_id,
            degradation=[*degradation, "No candidates after daily hard filter"],
            snapshot_source=snapshot_source,
            source_errors=source_errors,
            post_analyzers=analyzer_names,
            daily_enriched=daily_enriched,
            daily_enrich_count=daily_enrich_count,
            risk_enabled=config.risk_enabled,
            portfolio_diversity_enabled=config.portfolio_diversity_enabled,
            universe_audit=_finalize_universe_audit(universe_audit, pick_codes=[]),
        )

    # 4. Compute screen_score
    df = _sort_screened_candidates(compute_screen_scores(df, screening), screening)

    # 5. Take Top K for LLM ranking
    host_candidate_minimum = _host_candidate_minimum(context)
    top_k = min(
        max(
            output_count * config.llm_candidate_multiplier,
            output_count,
            host_candidate_minimum,
        ),
        config.llm_max_candidates,
        len(df),
    )
    df_top = df.head(top_k)

    # 6. Build Pick list
    picks = _deduplicate_picks(_df_to_picks(df_top))

    # 6.5. Host-provided candidate context, e.g. DSA realtime quote,
    # fundamentals, and news. This runs before LLM ranking so L2 can use it.
    degradation.extend(apply_dsa_provider_context(picks, context))

    # 6.6. Collect external context once for both deterministic sentiment and
    # optional LLM ranking. This remains Top-K only; it never fans out across
    # the full snapshot universe.
    candidate_context_rows: list[dict[str, object]] = []
    event_source_weights = _event_source_weights(screening.event_profile)
    context_collection_setting = (
        config.llm_candidate_context_enabled
        if collect_llm_candidate_context is None
        else collect_llm_candidate_context
    )
    should_collect_candidate_context = bool(context_collection_setting) or (
        screening.sentiment_weight > 0 and collect_llm_candidate_context is not False
    )
    if should_collect_candidate_context:
        candidate_context_rows, candidate_context_errors = collect_candidate_context(
            df_top,
            max_rows=(
                candidate_context_max_candidates
                or config.llm_candidate_context_max_candidates
            ),
            providers=(
                candidate_context_providers
                if candidate_context_providers is not None
                else config.llm_candidate_context_providers
            ),
            news_limit=config.llm_candidate_context_news_limit,
            announcement_limit=config.llm_candidate_context_announcement_limit,
            cache_dir=(
                config.data_dir / "candidate_context"
                if config.llm_candidate_context_cache_enabled
                else None
            ),
            cache_ttl_hours=config.llm_candidate_context_cache_ttl_hours,
            source_weights=event_source_weights,
        )
        degradation.append(
            f"Candidate context collected rows={len(candidate_context_rows)}"
        )
        if candidate_context_errors:
            sample = " | ".join(candidate_context_errors[:5])
            suffix = (
                f" | +{len(candidate_context_errors) - 5} more"
                if len(candidate_context_errors) > 5
                else ""
            )
            degradation.append(f"Candidate context row errors: {sample}{suffix}")

    # 7. L2 LLM ranking
    llm_ranked = False
    llm_market_view = ""
    llm_selection_logic = ""
    llm_portfolio_risk = ""
    llm_coverage: float | None = None
    llm_parse_errors: list[str] = []
    if use_llm and config.has_llm_config():
        llm_context_degradation: list[str] = []
        effective_context = build_llm_context(
            base_context=llm_context if llm_context is not None else config.llm_context,
            context_files=llm_context_files,
            candidate_context_files=candidate_context_files,
            candidate_context_rows=candidate_context_rows,
            snapshot_df=snapshot_df,
            candidate_df=df_top,
            event_profile=screening.event_profile,
            max_chars=config.llm_context_max_chars,
            degradation=llm_context_degradation,
        )
        degradation.extend(llm_context_degradation)
        llm_prompt_degradation: list[str] = []
        llm_result = rank_candidates_with_metadata(
            picks,
            screening.ranking_hints,
            config.llm_api_key,
            config.llm_model,
            config.llm_base_url,
            context=effective_context,
            rank_weight=config.llm_rank_weight,
            max_retries=config.llm_max_retries,
            min_coverage=config.llm_min_coverage,
            fallback_models=config.llm_fallback_models,
            temperature=config.llm_temperature,
            json_mode=config.llm_json_mode,
            silent=config.llm_silent,
            channels=config.llm_channels,
            config_path=str(config.llm_config_path or ""),
            timeout_sec=config.llm_timeout_sec,
            max_tokens=config.llm_max_tokens,
            degradation=llm_prompt_degradation,
        )
        degradation.extend(llm_prompt_degradation)
        picks = llm_result.picks
        llm_market_view = llm_result.market_view
        llm_selection_logic = llm_result.selection_logic
        llm_portfolio_risk = llm_result.portfolio_risk
        llm_coverage = llm_result.coverage
        llm_parse_errors = llm_result.errors
        llm_ranked = any(p.llm_score is not None for p in picks)
        if not llm_ranked:
            degradation.append("LLM ranking failed: fell back to screen_score")
            for i, p in enumerate(picks):
                p.rank = i + 1
                p.final_score = p.screen_score
    else:
        if use_llm and not config.has_llm_config():
            degradation.append("LLM ranking skipped: no LLM config")
        for i, p in enumerate(picks):
            p.rank = i + 1
            p.final_score = p.screen_score

    # 7.5. Deterministic sentiment overlay. Technical and main-wave scores stay
    # unchanged; only the composite final_score receives a bounded adjustment.
    picks, sentiment_degradation = apply_sentiment_overlay(
        picks,
        context_rows=candidate_context_rows,
        weight=screening.sentiment_weight,
        min_confidence=screening.sentiment_min_confidence,
        max_delta=screening.sentiment_max_delta,
    )
    degradation.extend(sentiment_degradation)

    # 8. Independent risk overlay
    if config.risk_enabled:
        picks, risk_degradation = apply_risk_overlay(
            picks,
            max_penalty=config.risk_max_penalty,
            veto_high_risk=config.risk_veto_high,
            profile=screening.risk_profile,
        )
        degradation.extend(risk_degradation)

    # 9. LLM-driven portfolio overlay. This runs before trimming so an
    # over-crowded sector can make room for a comparable candidate elsewhere.
    portfolio_concentration_notes: list[str] = []
    if config.portfolio_diversity_enabled:
        picks, portfolio_concentration_notes = apply_portfolio_overlay(
            picks,
            max_same_sector=config.portfolio_max_same_llm_sector,
            concentration_penalty=config.portfolio_concentration_penalty,
            profile=screening.portfolio_profile,
        )

    # 10. Trim to max_output
    picks = picks[:output_count]
    _record_universe_stage(universe_audit, "output", len(picks))

    # 11. Optional L3 post-analysis, DSA is only one possible analyzer.
    if analyzer_names:
        picks, post_degradation = run_post_analyzers(
            picks,
            analyzer_names=analyzer_names,
            run_id=run_id,
            config=config,
            max_picks=analyzer_max_picks,
            scorecard_profile=screening.scorecard_profile,
        )
        degradation.extend(post_degradation)

    return ScreenResult(
        strategy=strategy,
        market=market,
        strategy_version=strat.version,
        strategy_category=strat.category,
        snapshot_count=snapshot_count,
        after_filter_count=after_filter_count,
        picks=picks,
        run_id=run_id,
        llm_ranked=llm_ranked,
        llm_market_view=llm_market_view,
        llm_selection_logic=llm_selection_logic,
        llm_portfolio_risk=llm_portfolio_risk,
        llm_coverage=llm_coverage,
        llm_parse_errors=llm_parse_errors,
        degradation=degradation,
        snapshot_source=snapshot_source,
        source_errors=source_errors,
        deep_analysis_requested=("dsa" in analyzer_names),
        post_analyzers=analyzer_names,
        daily_enriched=daily_enriched,
        daily_enrich_count=daily_enrich_count,
        risk_enabled=config.risk_enabled,
        portfolio_diversity_enabled=config.portfolio_diversity_enabled,
        portfolio_concentration_notes=portfolio_concentration_notes,
        universe_audit=_finalize_universe_audit(
            universe_audit,
            pick_codes=[pick.code for pick in picks],
        ),
    )


def _df_to_picks(df: pd.DataFrame) -> list[Pick]:
    """Convert DataFrame rows to Pick objects."""
    picks = []
    factor_cols = factor_score_columns()
    for i, (_, row) in enumerate(df.iterrows()):
        factor_scores = {
            factor: _safe_float(row.get(col)) or 0.0
            for factor, col in factor_cols.items()
            if col in df.columns
        }
        picks.append(Pick(
            rank=i + 1,
            code=normalize_code(row.get("code", row.get("代码", "")), allow_ticker=True),
            name=str(row.get("name", row.get("名称", row.get("股票名称", "")))),
            screen_score=float(row.get("screen_score", 0)),
            final_score=float(row.get("screen_score", 0)),
            price=float(row.get("price", row.get("最新价", 0)) or 0),
            change_pct=float(row.get("change_pct", row.get("涨跌幅", 0)) or 0),
            amount=float(row.get("amount", row.get("成交额", 0)) or 0),
            total_mv=_safe_float(row.get("total_mv", row.get("总市值"))),
            turnover_rate=_safe_float(row.get("turnover_rate", row.get("换手率"))),
            volume_ratio=_safe_float(row.get("volume_ratio", row.get("量比"))),
            pe_ratio=_safe_float(row.get("pe_ratio", row.get("市盈率"))),
            pb_ratio=_safe_float(row.get("pb_ratio", row.get("市净率"))),
            industry=_safe_text(row.get("industry", row.get("行业", row.get("所属行业", "")))),
            concepts=_safe_text(row.get("concepts", row.get("概念", row.get("概念题材", "")))),
            industry_rank=_safe_int(row.get("industry_rank")),
            industry_change_pct=_safe_float(row.get("industry_change_pct")),
            industry_heat_score=_safe_float(row.get("industry_heat_score")),
            concept_heat_score=_safe_float(row.get("concept_heat_score")),
            board_heat_score=_safe_float(row.get("board_heat_score")),
            board_heat_latest_score=_safe_float(row.get("board_heat_latest_score")),
            board_heat_trend_score=_safe_float(row.get("board_heat_trend_score")),
            board_heat_persistence_score=_safe_float(row.get("board_heat_persistence_score")),
            board_heat_cooling_score=_safe_float(row.get("board_heat_cooling_score")),
            board_heat_observations=_safe_int(row.get("board_heat_observations")),
            board_heat_state=_safe_text(row.get("board_heat_state")),
            board_heat_summary=_safe_text(row.get("board_heat_summary")),
            change_60d=_safe_float(row.get("change_60d")),
            signal_score=_safe_float(row.get("signal_score")),
            ma_bullish=_safe_bool(row.get("ma_bullish")),
            price_above_ma20=_safe_bool(row.get("price_above_ma20")),
            macd_status=str(row.get("macd_status", "") or ""),
            rsi_status=str(row.get("rsi_status", "") or ""),
            breakout_20d_pct=_safe_float(row.get("breakout_20d_pct")),
            range_20d_pct=_safe_float(row.get("range_20d_pct")),
            volume_ratio_20d=_safe_float(row.get("volume_ratio_20d")),
            body_pct=_safe_float(row.get("body_pct")),
            pullback_to_ma20_pct=_safe_float(row.get("pullback_to_ma20_pct")),
            consolidation_days_20d=_safe_int(row.get("consolidation_days_20d")),
            volatility_20d_pct=_safe_float(row.get("volatility_20d_pct")),
            max_drawdown_20d_pct=_safe_float(row.get("max_drawdown_20d_pct")),
            atr_20_pct=_safe_float(row.get("atr_20_pct")),
            daily_quality_score=_safe_float(row.get("daily_quality_score")),
            daily_quality_flags=_safe_text(row.get("daily_quality_flags")),
            daily_source=_safe_text(row.get("daily_source")),
            daily_adjustment=_safe_text(row.get("daily_adjustment")) or "unknown",
            daily_as_of=_safe_text(row.get("daily_as_of")),
            daily_fetched_at=_safe_text(row.get("daily_fetched_at")),
            main_wave_eligible=bool(_safe_bool(row.get("main_wave_eligible"))),
            main_wave_ineligible_reasons=_safe_text(row.get("main_wave_ineligible_reasons")),
            main_wave_raw_score=_safe_float(row.get("main_wave_raw_score")),
            main_wave_raw_max_score=_safe_float(row.get("main_wave_raw_max_score")) or 50.0,
            main_wave_score=_safe_float(row.get("main_wave_score")),
            main_wave_max_score=_safe_float(row.get("main_wave_max_score")) or 100.0,
            main_wave_hit_count=_safe_int(row.get("main_wave_hit_count")) or 0,
            main_wave_rules=_safe_rule_evidence(row.get("main_wave_rules")),
            sentiment_available=bool(_safe_bool(row.get("sentiment_available"))),
            sentiment_score=_safe_float(row.get("sentiment_score")),
            sentiment_label=_safe_text(row.get("sentiment_label")) or "unavailable",
            sentiment_confidence=_safe_float(row.get("sentiment_confidence")) or 0.0,
            sentiment_source_count=_safe_int(row.get("sentiment_source_count")) or 0,
            sentiment_positive_events=_safe_string_list(row.get("sentiment_positive_events")),
            sentiment_negative_events=_safe_string_list(row.get("sentiment_negative_events")),
            sentiment_evidence=_safe_rule_evidence(row.get("sentiment_evidence")),
            sentiment_as_of=_safe_text(row.get("sentiment_as_of")),
            sentiment_score_delta=_safe_float(row.get("sentiment_score_delta")) or 0.0,
            factor_scores=factor_scores,
        ))
    return picks


def _safe_rule_evidence(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _requires_adjusted_daily(screening) -> bool:
    hard_filters = screening.hard_filters
    if hard_filters.require_main_wave_eligible or hard_filters.main_wave_score_min is not None:
        return True
    return any(
        str(name).startswith("main_wave_") and (_safe_float(weight) or 0.0) > 0
        for name, weight in screening.factor_weights.items()
    )


def _host_candidate_minimum(context: dict[str, object] | None) -> int:
    """Honor a host's pre-rank context window when sizing the LLM pool."""
    if not isinstance(context, dict):
        return 0
    provider = context.get("dsa")
    if not isinstance(provider, dict):
        return 0
    try:
        return max(int(provider.get("max_candidates", 0)), 0)
    except (TypeError, ValueError):
        return 0


def _deduplicate_picks(picks: list[Pick]) -> list[Pick]:
    unique: list[Pick] = []
    seen: set[str] = set()
    for pick in picks:
        if not pick.code or pick.code in seen:
            continue
        seen.add(pick.code)
        pick.rank = len(unique) + 1
        unique.append(pick)
    return unique


def _build_universe_audit(
    frame: pd.DataFrame,
    *,
    market: str,
    minimum_count: int | None,
) -> dict[str, object]:
    code_column = next(
        (column for column in ("code", "代码", "证券代码") if column in frame.columns),
        None,
    )
    if code_column is None:
        normalized_codes = pd.Series([""] * len(frame), index=frame.index, dtype=object)
    else:
        normalized_codes = frame[code_column].map(
            lambda value: normalize_code(value, allow_ticker=market == "us")
        )
    valid_codes = normalized_codes[normalized_codes.astype(str).str.len() > 0]
    invalid_code_rows = int(len(frame) - len(valid_codes))
    duplicate_code_rows = int(len(valid_codes) - valid_codes.nunique())
    minimum_required = int(minimum_count) if minimum_count is not None else None
    minimum_met = minimum_required is None or len(frame) >= minimum_required
    return {
        "market": market,
        "snapshot_count": len(frame),
        "unique_code_count": int(valid_codes.nunique()),
        "invalid_code_rows": invalid_code_rows,
        "duplicate_code_rows": duplicate_code_rows,
        "codes_valid": invalid_code_rows == 0,
        "codes_unique": duplicate_code_rows == 0,
        "minimum_required_count": minimum_required,
        "minimum_count_met": minimum_met,
        "daily_coverage_target_count": 0,
        "daily_attempted_count": 0,
        "daily_success_count": 0,
        "daily_coverage_ratio": None,
        "daily_coverage_complete": None,
        "stages": [{"stage": "snapshot", "count": len(frame)}],
    }


def _record_universe_stage(audit: dict[str, object], stage: str, count: int) -> None:
    stages = audit.setdefault("stages", [])
    if isinstance(stages, list):
        stages.append({"stage": stage, "count": int(count)})


def _finalize_universe_audit(
    audit: dict[str, object],
    *,
    pick_codes: list[str],
) -> dict[str, object]:
    result = dict(audit)
    stages = [dict(item) for item in audit.get("stages", []) if isinstance(item, dict)]
    counts = [int(item.get("count") or 0) for item in stages]
    result["stages"] = stages
    result["counts_monotonic"] = all(
        current >= following
        for current, following in zip(counts, counts[1:])
    )
    normalized_picks = [str(code) for code in pick_codes if str(code)]
    result["candidate_codes_unique"] = len(normalized_picks) == len(set(normalized_picks))
    checks = [
        bool(result.get("minimum_count_met")),
        bool(result.get("codes_valid")),
        bool(result.get("codes_unique")),
        bool(result.get("counts_monotonic")),
        bool(result.get("candidate_codes_unique")),
    ]
    if not all(checks):
        result["status"] = "failed"
    elif result.get("daily_coverage_complete") is False:
        result["status"] = "degraded"
    else:
        result["status"] = "ok"
    return result


def _sort_screened_candidates(df: pd.DataFrame, screening=None) -> pd.DataFrame:
    """Sort scored candidates deterministically with factor-aware tie breakers."""
    factor_order = ["stability", "activity", "momentum", "value"]
    if screening is not None and screening.factor_weights:
        factor_order = [
            factor
            for factor, _weight in sorted(
                screening.factor_weights.items(),
                key=lambda item: (-float(item[1]), item[0]),
            )
        ]
    sort_columns = [
        column
        for column in ["screen_score"] + [f"factor_{factor}_score" for factor in factor_order]
        if column in df.columns
    ]
    ascending = [False] * len(sort_columns)
    if "code" in df.columns:
        sort_columns.append("code")
        ascending.append(True)
    if not sort_columns:
        return df
    return df.sort_values(sort_columns, ascending=ascending, kind="mergesort")


def _required_snapshot_columns(filters) -> list[str]:
    columns: list[str] = []
    if filters.exclude_st:
        columns.append("name")
    if filters.amount_min is not None:
        columns.append("amount")
    if filters.price_min is not None or filters.price_max is not None:
        columns.append("price")
    if filters.market_cap_min is not None or filters.market_cap_max is not None:
        columns.append("total_mv")
    if filters.pe_ttm_min is not None or filters.pe_ttm_max is not None:
        columns.append("pe_ratio")
    if filters.pb_min is not None or filters.pb_max is not None:
        columns.append("pb_ratio")
    if filters.volume_ratio_min is not None:
        columns.append("volume_ratio")
    if filters.turnover_rate_min is not None:
        columns.append("turnover_rate")
    if filters.change_pct_min is not None or filters.change_pct_max is not None:
        columns.append("change_pct")
    return list(dict.fromkeys(columns))


def _event_source_weights(event_profile: dict[str, object]) -> dict[str, float] | None:
    value = (event_profile or {}).get("source_weights")
    if not isinstance(value, dict):
        return None
    result: dict[str, float] = {}
    for key, raw in value.items():
        try:
            result[str(key)] = float(raw)
        except (TypeError, ValueError):
            continue
    return result or None


def _daily_source_health_notes(health: dict[str, object], *, limit: int = 4) -> list[str]:
    source_states: list[tuple[tuple[int, float, float, str], str, dict[object, object]]] = []
    for source, raw_state in health.items():
        if not isinstance(raw_state, dict):
            continue
        failures = _safe_float(raw_state.get("failures")) or 0.0
        total_failures = _safe_float(raw_state.get("total_failures")) or 0.0
        disabled = bool(raw_state.get("disabled"))
        if not disabled and failures <= 0 and total_failures <= 0:
            continue
        severity_key = (
            0 if disabled else 1 if failures > 0 else 2,
            -failures,
            -total_failures,
            str(source),
        )
        source_states.append((severity_key, str(source), raw_state))

    notes: list[str] = []
    for _severity_key, source, raw_state in sorted(source_states):
        failures = _safe_float(raw_state.get("failures")) or 0.0
        total_failures = _safe_float(raw_state.get("total_failures")) or 0.0
        disabled = bool(raw_state.get("disabled"))
        last_rows = _safe_float(raw_state.get("last_rows")) or 0.0
        parts: list[str] = []
        if disabled:
            parts.append("disabled")
        if failures > 0:
            parts.append(f"failures={failures:g}")
        elif total_failures > 0:
            parts.append(f"total_failures={total_failures:g}")
        if last_rows > 0:
            parts.append(f"last_rows={last_rows:g}")
        if parts:
            notes.append(f"{source} " + ",".join(parts))
        if len(notes) >= limit:
            break
    hidden_count = len(source_states) - len(notes)
    if hidden_count > 0:
        notes.append(f"+{hidden_count} more")
    return notes


def _format_filter_waterfall(steps: list[dict[str, object]], *, limit: int = 8) -> str:
    parts: list[str] = []
    for step in steps[:limit]:
        text = (
            f"{step.get('filter')} {step.get('before')}->{step.get('after')} "
            f"removed={step.get('removed')}"
        )
        samples = step.get("samples")
        if isinstance(samples, list) and samples:
            sample_names = [
                str(item.get("name") or item.get("code") or item.get("value") or "")
                for item in samples
                if isinstance(item, dict)
            ]
            sample_names = [item for item in sample_names if item]
            if sample_names:
                text += f" samples={','.join(sample_names[:3])}"
        if step.get("suggestion"):
            text += f" next={step.get('suggestion')}"
        parts.append(text)
    hidden = len(steps) - len(parts)
    if hidden > 0:
        parts.append(f"+{hidden} more")
    return "; ".join(parts)


def _safe_text(v: object) -> str:
    return safe_text(v, max_len=120)
