from pathlib import Path

import pandas as pd

from alphasift.config import Config
from alphasift.pipeline import _daily_source_health_notes, _sort_screened_candidates, screen
from alphasift.strategy import ScreeningConfig


def test_pipeline_enriches_daily_features_for_daily_strategy(monkeypatch):
    df = pd.DataFrame(
        [
            {
                "code": "000001",
                "name": "平安银行",
                "price": 10.0,
                "change_pct": -0.5,
                "amount": 200_000_000,
                "turnover_rate": 2.0,
                "volume_ratio": 1.2,
                "pe_ratio": 8.0,
                "pb_ratio": 0.8,
                "total_mv": 100_000_000_000,
            },
            {
                "code": "600000",
                "name": "浦发银行",
                "price": 11.0,
                "change_pct": -0.8,
                "amount": 190_000_000,
                "turnover_rate": 2.0,
                "volume_ratio": 1.1,
                "pe_ratio": 9.0,
                "pb_ratio": 0.9,
                "total_mv": 90_000_000_000,
            },
        ]
    )
    df.attrs["snapshot_source"] = "test"

    def fake_enrich(frame, **kwargs):
        enriched = frame.copy()
        for idx, row in enriched.iterrows():
            is_target = row["code"] == "000001"
            enriched.loc[idx, "ma_bullish"] = is_target
            enriched.loc[idx, "price_above_ma20"] = True
            enriched.loc[idx, "signal_score"] = 72 if is_target else 80
            enriched.loc[idx, "change_60d"] = 12 if is_target else 10
            enriched.loc[idx, "macd_status"] = "bullish"
            enriched.loc[idx, "rsi_status"] = "neutral"
            enriched.loc[idx, "volume_ratio_20d"] = 1.0 if is_target else 1.8
            enriched.loc[idx, "pullback_to_ma20_pct"] = 4 if is_target else 12
            enriched.loc[idx, "volatility_20d_pct"] = 25 if is_target else 60
            enriched.loc[idx, "max_drawdown_20d_pct"] = -5 if is_target else -18
            enriched.loc[idx, "atr_20_pct"] = 3 if is_target else 9
            enriched.loc[idx, "daily_quality_score"] = 100 if is_target else 70
            enriched.loc[idx, "daily_quality_flags"] = "" if is_target else "fallback_errors"
            enriched.loc[idx, "daily_source"] = "tencent"
        enriched.attrs["daily_success_count"] = len(enriched)
        enriched.attrs["daily_source_counts"] = {"tencent": 2}
        enriched.attrs["daily_quality_flag_counts"] = {"fallback_errors": 1}
        enriched.attrs["daily_source_order_notes"] = ["daily source order adjusted by health: tencent,sina"]
        enriched.attrs["daily_source_health"] = {
            "sina": {"failures": 0.0, "total_failures": 1.0, "last_rows": 30.0, "disabled": False},
            "tencent": {"failures": 2.0, "total_failures": 2.0, "last_rows": 0.0, "disabled": True},
        }
        return enriched

    monkeypatch.setattr("alphasift.pipeline.fetch_snapshot_with_fallback", lambda sources, **kwargs: df)
    monkeypatch.setattr("alphasift.pipeline.enrich_daily_features", fake_enrich)

    result = screen(
        "shrink_pullback",
        use_llm=False,
        explain_filters=True,
        config=Config(
            llm_api_key="",
            snapshot_source_priority=["test"],
            strategies_dir=Path("strategies"),
            risk_enabled=False,
        ),
    )

    assert result.daily_enriched is True
    assert result.after_filter_count == 1
    assert result.picks[0].code == "000001"
    assert result.picks[0].ma_bullish is True
    assert result.picks[0].volatility_20d_pct == 25
    assert result.picks[0].max_drawdown_20d_pct == -5
    assert result.picks[0].atr_20_pct == 3
    assert result.picks[0].daily_quality_score == 100
    assert result.picks[0].daily_quality_flags == ""
    assert result.picks[0].daily_source == "tencent"
    assert any("Daily K-line enrichment attempted 2 candidates" in item for item in result.degradation)
    assert "Daily K-line sources: tencent=2" in result.degradation
    assert "Daily K-line quality flags: fallback_errors=1" in result.degradation
    assert "Daily K-line source ordering: daily source order adjusted by health: tencent,sina" in result.degradation
    assert any("Daily K-line source health:" in item for item in result.degradation)
    assert any("tencent disabled,failures=2" in item for item in result.degradation)
    assert any("sina total_failures=1,last_rows=30" in item for item in result.degradation)
    assert any("Daily hard-filter rejections:" in item for item in result.degradation)
    assert any("require_ma_bullish removed 1" in item for item in result.degradation)
    assert any("Snapshot hard-filter waterfall:" in item for item in result.degradation)
    assert any("Daily hard-filter waterfall:" in item for item in result.degradation)


def test_daily_source_health_notes_prioritize_severe_states_and_limit_noise():
    notes = _daily_source_health_notes(
        {
            "akshare": {"failures": 0, "total_failures": 1, "last_rows": 40, "disabled": False},
            "baostock": {"failures": 1, "total_failures": 3, "disabled": False},
            "sina": {"failures": 0, "total_failures": 2, "last_rows": 30, "disabled": False},
            "tencent": {"failures": 2, "total_failures": 2, "disabled": True},
            "tushare": {"failures": 0, "total_failures": 0, "disabled": False},
        },
        limit=2,
    )

    assert notes == [
        "tencent disabled,failures=2",
        "baostock failures=1",
        "+2 more",
    ]


def test_pipeline_preserves_degradation_when_hard_filter_empty(monkeypatch):
    df = pd.DataFrame([
        {
            "code": "000001",
            "name": "平安银行",
            "price": 10.0,
            "change_pct": 0.0,
            "amount": 1,
            "total_mv": 1,
            "pe_ratio": 1000.0,
            "pb_ratio": 100.0,
        }
    ])
    df.attrs["snapshot_source"] = "test"
    df.attrs["source_errors"] = ["efinance failed"]
    monkeypatch.setattr("alphasift.pipeline.fetch_snapshot_with_fallback", lambda sources, **kwargs: df)

    result = screen(
        "dual_low",
        use_llm=False,
        post_analyzers=[],
        config=Config(
            llm_api_key="",
            snapshot_source_priority=["test"],
            strategies_dir=Path("strategies"),
            risk_enabled=False,
        ),
    )

    assert result.picks == []
    assert any("Snapshot source fallback: efinance failed" in item for item in result.degradation)
    assert "No candidates after hard filter" in result.degradation


def test_pipeline_passes_industry_provider_cache_config(monkeypatch, tmp_path):
    df = pd.DataFrame([
        {
            "code": "000001",
            "name": "骞冲畨閾惰",
            "price": 10.0,
            "change_pct": 0.0,
            "amount": 100_000_000,
            "turnover_rate": 2.0,
            "volume_ratio": 1.2,
            "pe_ratio": 8.0,
            "pb_ratio": 0.8,
            "total_mv": 100_000_000_000,
        }
    ])
    df.attrs["snapshot_source"] = "test"
    calls = []

    def fake_enrich(frame, **kwargs):
        calls.append(kwargs)
        return frame, []

    monkeypatch.setattr("alphasift.pipeline.fetch_snapshot_with_fallback", lambda sources, **kwargs: df)
    monkeypatch.setattr("alphasift.pipeline.enrich_industry_concepts", fake_enrich)

    cache_dir = tmp_path / "industry-cache"
    screen(
        "dual_low",
        use_llm=False,
        post_analyzers=[],
        config=Config(
            llm_api_key="",
            snapshot_source_priority=["test"],
            strategies_dir=Path("strategies"),
            industry_provider="akshare",
            industry_provider_cache_dir=cache_dir,
            industry_provider_cache_ttl_hours=7,
            risk_enabled=False,
        ),
    )

    assert calls == [{
        "map_files": [],
        "provider": "akshare",
        "max_boards": 80,
        "provider_cache_dir": cache_dir,
        "provider_cache_ttl_hours": 7,
    }]


def test_sort_screened_candidates_uses_strategy_factor_tie_breakers_then_code():
    df = pd.DataFrame([
        {"code": "600000", "screen_score": 80, "factor_momentum_score": 70, "factor_stability_score": 90},
        {"code": "000001", "screen_score": 80, "factor_momentum_score": 70, "factor_stability_score": 90},
        {"code": "300001", "screen_score": 80, "factor_momentum_score": 75, "factor_stability_score": 10},
        {"code": "002001", "screen_score": 81, "factor_momentum_score": 20, "factor_stability_score": 20},
    ])
    screening = ScreeningConfig(factor_weights={"momentum": 0.7, "stability": 0.3})

    sorted_df = _sort_screened_candidates(df, screening)

    assert list(sorted_df["code"]) == ["002001", "300001", "000001", "600000"]


def test_sort_screened_candidates_keeps_default_tie_breakers_without_weights():
    df = pd.DataFrame([
        {"code": "600000", "screen_score": 80, "factor_stability_score": 70, "factor_activity_score": 50},
        {"code": "000001", "screen_score": 80, "factor_stability_score": 70, "factor_activity_score": 50},
        {"code": "300001", "screen_score": 80, "factor_stability_score": 75, "factor_activity_score": 10},
    ])

    sorted_df = _sort_screened_candidates(df, ScreeningConfig())

    assert list(sorted_df["code"]) == ["300001", "000001", "600000"]


def test_screening_reuses_daily_history_only_outside_the_session(monkeypatch, tmp_path):
    from datetime import date

    import alphasift.pipeline as pipeline

    df = pd.DataFrame(
        [{"code": "000001", "name": "平安银行", "price": 10.0, "change_pct": 1.0, "amount": 5e8,
          "volume_ratio": 1.0, "turnover_rate": 1.0, "total_mv": 2e11, "circ_mv": 2e11,
          "pe_ratio": 5.0, "pb_ratio": 0.6, "industry": "银行"}]
    )
    policies = []

    def fake_enrich(frame, **kwargs):
        policies.append(kwargs["cache_policy"])
        raise RuntimeError("stop after recording the cache policy")

    monkeypatch.setattr(pipeline, "fetch_snapshot_with_fallback", lambda sources, **kwargs: df)
    monkeypatch.setattr(pipeline, "enrich_daily_features", fake_enrich)
    config = Config(
        llm_api_key="",
        snapshot_source_priority=["test"],
        strategies_dir=Path("strategies"),
        risk_enabled=False,
        daily_history_cache_dir=tmp_path,
        daily_history_cache_ttl_hours=24,
    )
    try:
        screen("shrink_pullback", use_llm=False, config=config)
    except RuntimeError:
        pass
    policy = policies[0]
    session = date(2026, 11, 4)

    # The policy is evaluated per fetch, so a batch crossing the open switches.
    monkeypatch.setattr(pipeline, "latest_settled_close", lambda market: (session, 3600.0))
    assert policy() == {"cache_dir": tmp_path, "cache_ttl_seconds": 3600.0, "cache_min_last_date": session}
    monkeypatch.setattr(pipeline, "latest_settled_close", lambda market: (session, 3 * 86400.0))
    assert policy()["cache_ttl_seconds"] == 24 * 3600.0  # capped by config
    # In session: nothing fresh is read and nothing is written; stale fallback stays possible.
    monkeypatch.setattr(pipeline, "latest_settled_close", lambda market: None)
    assert policy() == {"cache_dir": tmp_path, "cache_ttl_seconds": 0.0, "cache_write": False}


def test_in_session_fetch_never_writes_but_can_fall_back_to_stale_cache(monkeypatch, tmp_path):
    import alphasift.daily as daily

    def tencent(code, *, lookback_days):
        return pd.DataFrame([{"日期": "2026-11-03", "收盘": 10.0}, {"日期": "2026-11-04", "收盘": 10.4}])

    monkeypatch.setattr(daily, "_fetch_daily_tencent", tencent)
    in_session = dict(source="tencent", retries=0, cache_dir=tmp_path, cache_ttl_seconds=0.0, cache_write=False)

    daily.fetch_daily_history("000001", **in_session)
    assert list(tmp_path.glob("*.json")) == []  # the partial-day bar was not cached

    # After the close it is cached; in the next session, with the source down,
    # that history is used and flagged stale.
    daily.fetch_daily_history("000001", source="tencent", retries=0, cache_dir=tmp_path, cache_ttl_seconds=3600)

    def down(code, *, lookback_days):
        raise RuntimeError("501")

    monkeypatch.setattr(daily, "_fetch_daily_tencent", down)
    stale = daily.fetch_daily_history("000001", **in_session)
    assert stale.attrs.get("daily_stale") is True

def test_cached_history_that_misses_the_latest_session_is_refetched(monkeypatch, tmp_path):
    from datetime import date

    import alphasift.daily as daily

    calls = []

    def fake_tencent(code, *, lookback_days):
        calls.append(code)
        last = "2026-11-04" if len(calls) > 1 else "2026-11-03"  # first fetch: vendor not published yet
        return pd.DataFrame(
            [{"日期": "2026-11-02", "收盘": 10.0}, {"日期": "2026-11-03", "收盘": 10.5}, {"日期": last, "收盘": 11.0}]
        ).drop_duplicates("日期")

    monkeypatch.setattr(daily, "_fetch_daily_tencent", fake_tencent)
    kwargs = dict(source="tencent", retries=0, cache_dir=tmp_path, cache_ttl_seconds=3600)

    daily.fetch_daily_history("000001", **kwargs, cache_min_last_date=date(2026, 11, 4))
    second = daily.fetch_daily_history("000001", **kwargs, cache_min_last_date=date(2026, 11, 4))
    third = daily.fetch_daily_history("000001", **kwargs, cache_min_last_date=date(2026, 11, 4))

    assert len(calls) == 2  # the cache lacking 11-04 was not reused; the complete one was
    assert str(second["日期"].iloc[-1]) == "2026-11-04"
    assert str(third["日期"].iloc[-1]) == "2026-11-04"


def test_clean_daily_run_without_explain_has_no_degradation(monkeypatch):
    df = pd.DataFrame(
        [
            {
                "code": "000001",
                "name": "平安银行",
                "price": 10.0,
                "change_pct": -0.5,
                "amount": 200_000_000,
                "turnover_rate": 2.0,
                "volume_ratio": 1.2,
                "pe_ratio": 8.0,
                "pb_ratio": 0.8,
                "total_mv": 100_000_000_000,
                "industry": "银行",
            },
            {
                "code": "600000",
                "name": "浦发银行",
                "price": 11.0,
                "change_pct": -0.8,
                "amount": 190_000_000,
                "turnover_rate": 2.0,
                "volume_ratio": 1.1,
                "pe_ratio": 9.0,
                "pb_ratio": 0.9,
                "total_mv": 90_000_000_000,
                "industry": "银行",
            },
        ]
    )
    df.attrs["snapshot_source"] = "test"
    success_override = {"count": 2}

    def fake_enrich(frame, **kwargs):
        enriched = frame.copy()
        for idx, row in enriched.iterrows():
            is_target = row["code"] == "000001"
            enriched.loc[idx, "ma_bullish"] = is_target
            enriched.loc[idx, "price_above_ma20"] = True
            enriched.loc[idx, "signal_score"] = 72
            enriched.loc[idx, "change_60d"] = 12
            enriched.loc[idx, "macd_status"] = "bullish"
            enriched.loc[idx, "rsi_status"] = "neutral"
            enriched.loc[idx, "volume_ratio_20d"] = 1.0
            enriched.loc[idx, "pullback_to_ma20_pct"] = 4
            enriched.loc[idx, "volatility_20d_pct"] = 25
            enriched.loc[idx, "max_drawdown_20d_pct"] = -5
            enriched.loc[idx, "atr_20_pct"] = 3
            enriched.loc[idx, "daily_quality_score"] = 100
            enriched.loc[idx, "daily_quality_flags"] = ""
            enriched.loc[idx, "daily_source"] = "tencent"
        enriched.attrs["daily_success_count"] = success_override["count"]
        enriched.attrs["daily_source_counts"] = {"tencent": success_override["count"]}
        enriched.attrs["daily_quality_flag_counts"] = {}
        enriched.attrs["daily_source_order_notes"] = []
        enriched.attrs["daily_source_health"] = {}
        return enriched

    monkeypatch.setattr("alphasift.pipeline.fetch_snapshot_with_fallback", lambda sources, **kwargs: df)
    monkeypatch.setattr("alphasift.pipeline.enrich_daily_features", fake_enrich)

    config = Config(
        llm_api_key="",
        snapshot_source_priority=["test"],
        strategies_dir=Path("strategies"),
        risk_enabled=False,
        post_analyzers=[],
    )
    clean = screen("shrink_pullback", use_llm=False, explain_filters=False, config=config)
    assert clean.degradation == []

    success_override["count"] = 1
    partial = screen("shrink_pullback", use_llm=False, explain_filters=False, config=config)
    assert len(partial.degradation) == 1
    assert "attempted 2 candidates, succeeded 1" in partial.degradation[0]


def test_pipeline_reuses_valid_snapshot_df_and_falls_back_when_incomplete(monkeypatch):
    shared = pd.DataFrame(
        [
            {
                "code": "000001",
                "name": "平安银行",
                "price": 10.0,
                "change_pct": 0.5,
                "amount": 200_000_000,
                "volume_ratio": 1.5,
                "turnover_rate": 2.0,
                "total_mv": 100_000_000_000,
                "industry": "银行",
            }
        ]
    )
    shared.attrs["snapshot_source"] = "shared_live"
    shared.attrs["source_errors"] = ["warn"]

    fetched = []

    def fake_fetch(*args, **kwargs):
        fetched.append(kwargs.get("required_columns"))
        full = shared.copy()
        full["pe_ratio"] = 6.0
        full["pb_ratio"] = 0.7
        full.attrs["snapshot_source"] = "refetched"
        return full

    monkeypatch.setattr("alphasift.pipeline.fetch_snapshot_with_fallback", fake_fetch)

    config = Config(
        llm_api_key="",
        snapshot_source_priority=["test"],
        strategies_dir=Path("strategies"),
        risk_enabled=False,
        post_analyzers=[],
    )
    # capital_heat needs price, amount, total_mv, change_pct, name -> all present in `shared`.
    before_cols = list(shared.columns)
    res_reused = screen(
        "capital_heat",
        use_llm=False,
        daily_enrich=False,
        config=config,
        snapshot_df=shared,
    )
    assert fetched == []
    assert res_reused.snapshot_source == "shared_live"
    assert list(shared.columns) == before_cols

    # dual_low requires pe_ratio / pb_ratio -> falls back to fetch_snapshot_with_fallback.
    res_fallback = screen(
        "dual_low",
        use_llm=False,
        daily_enrich=False,
        config=config,
        snapshot_df=shared,
    )
    assert len(fetched) == 1
    assert res_fallback.snapshot_source == "refetched"

    import pytest

    cn_tagged = shared.copy()
    cn_tagged.attrs["market"] = "cn"
    with pytest.raises(ValueError, match="does not match requested market"):
        screen(
            "global_value",
            market="us",
            use_llm=False,
            daily_enrich=False,
            config=config,
            snapshot_df=cn_tagged,
        )


def test_screen_populates_topic_alignment_and_portfolio_exposure(tmp_path):
    snapshot = pd.DataFrame([
        {
            "code": "601997",
            "name": "贵阳银行",
            "price": 6.0,
            "amount": 200_000_000,
            "total_mv": 20_000_000_000,
            "pe_ratio": 5.0,
            "pb_ratio": 0.4,
            "change_pct": 1.0,
            "turnover_rate": 2.0,
            "volume_ratio": 1.2,
            "industry": "银行",
            "concepts": "高股息",
            "board_heat_summary": "银行:72.0",
        },
        {
            "code": "601117",
            "name": "中国化学",
            "price": 8.0,
            "amount": 300_000_000,
            "total_mv": 45_000_000_000,
            "pe_ratio": 7.0,
            "pb_ratio": 0.7,
            "change_pct": 1.5,
            "turnover_rate": 2.5,
            "volume_ratio": 1.3,
            "industry": "建筑施工",
            "concepts": "中字头",
            "board_heat_summary": "AI算力:88.0",
        },
        {
            "code": "600741",
            "name": "华域汽车",
            "price": 16.0,
            "amount": 250_000_000,
            "total_mv": 48_000_000_000,
            "pe_ratio": 8.0,
            "pb_ratio": 0.8,
            "change_pct": 0.8,
            "turnover_rate": 1.8,
            "volume_ratio": 1.1,
            "industry": "汽车",
            "concepts": "无人驾驶",
            "board_heat_summary": "无人驾驶:81.0",
        },
    ])
    snapshot.attrs["market"] = "cn"
    snapshot.attrs["snapshot_source"] = "test"
    cfg = Config(data_dir=tmp_path)
    res = screen("dual_low", market="cn", max_output=2, use_llm=False, daily_enrich=False, config=cfg, snapshot_df=snapshot)
    assert len(res.picks) == 2
    by_code = {p.code: p for p in res.picks}
    if "601997" in by_code:
        assert by_code["601997"].topic_alignment_status == "aligned"
        assert by_code["601997"].topic_alignment_role == "direct_industry"
    assert isinstance(res.portfolio_topic_exposure, dict)
    assert res.portfolio_topic_exposure
    assert len(res.replacement_candidates) <= 1


def test_screen_and_sort_scrub_nan_weights_missing_names_and_bad_limits(tmp_path):
    df = pd.DataFrame([
        {"code": "600000", "screen_score": 80, "factor_value_score": 70, "factor_stability_score": 80},
        {"code": "000001", "screen_score": 80, "factor_value_score": 70, "factor_stability_score": 90},
    ])
    bad_weights = {"momentum": float("nan"), "value": float("inf"), "stability": "bad"}
    sorted_df = _sort_screened_candidates(df, ScreeningConfig(factor_weights=bad_weights))  # type: ignore[arg-type]
    assert list(sorted_df["code"]) == ["000001", "600000"]

    snapshot = pd.DataFrame([
        {
            "code": "601997",
            "name": float("nan"),
            "price": 7.5,
            "amount": 180_000_000,
            "total_mv": 20_000_000_000,
            "pe_ratio": 5.0,
            "pb_ratio": 0.4,
            "change_pct": 1.0,
            "turnover_rate": 2.0,
            "volume_ratio": 1.2,
            "industry": "银行",
        },
        {
            "code": "601117",
            "name": pd.NA,
            "price": 8.0,
            "amount": 300_000_000,
            "total_mv": 45_000_000_000,
            "pe_ratio": 7.0,
            "pb_ratio": 0.7,
            "change_pct": 1.5,
            "turnover_rate": 2.5,
            "volume_ratio": 1.3,
            "industry": "建筑施工",
        },
        {
            "code": "600741",
            "name": "华域汽车",
            "price": 16.0,
            "amount": 250_000_000,
            "total_mv": 48_000_000_000,
            "pe_ratio": 8.0,
            "pb_ratio": 0.8,
            "change_pct": 0.8,
            "turnover_rate": 1.8,
            "volume_ratio": 1.1,
            "industry": "汽车",
        },
    ])
    snapshot.attrs["market"] = "cn"
    snapshot.attrs["snapshot_source"] = "test"
    cfg = Config(data_dir=tmp_path)
    res = screen(
        "dual_low",
        market="cn",
        max_output=True,  # type: ignore[arg-type]
        use_llm=False,
        daily_enrich=False,
        daily_enrich_max_candidates=float("nan"),  # type: ignore[arg-type]
        config=cfg,
        snapshot_df=snapshot,
        allow_snapshot_refetch=False,
    )
    assert len(res.picks) == 3
    by_code = {p.code: p for p in res.picks}
    assert by_code["601997"].name == ""
    assert by_code["601117"].name == ""
    assert by_code["600741"].name == "华域汽车"
