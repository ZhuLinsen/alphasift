from alphasift.models import Pick
from alphasift.risk import (
    PORTFOLIO_DIVERSITY_SKIPPED_NOTE,
    apply_portfolio_overlay,
    apply_risk_overlay,
)


def test_risk_overlay_penalizes_and_flags_hot_candidates():
    picks = [
        Pick(
            rank=1,
            code="000001",
            name="平安银行",
            final_score=90,
            screen_score=90,
            change_pct=8.5,
            volume_ratio=7,
            turnover_rate=16,
        )
    ]

    result, degradation = apply_risk_overlay(picks, max_penalty=12, veto_high_risk=False)

    assert degradation == []
    assert result[0].final_score < 90
    assert result[0].risk_level == "high"
    assert "single_day_chase_risk" in result[0].risk_flags
    assert "abnormal_volume_ratio" in result[0].risk_flags


def test_risk_overlay_can_veto_high_risk_candidates():
    picks = [
        Pick(
            rank=1,
            code="000001",
            name="平安银行",
            final_score=90,
            screen_score=90,
            change_pct=9.0,
            volume_ratio=8,
            turnover_rate=20,
        )
    ]

    result, degradation = apply_risk_overlay(picks, max_penalty=10, veto_high_risk=True)

    assert result == []
    assert degradation


def test_risk_overlay_accepts_strategy_profile_thresholds():
    picks = [
        Pick(
            rank=1,
            code="000001",
            name="平安银行",
            final_score=90,
            screen_score=90,
            change_pct=8.5,
        )
    ]

    result, _ = apply_risk_overlay(
        picks,
        max_penalty=12,
        profile={"chase_change_pct": 9.0},
    )

    assert result[0].risk_penalty == 0
    assert "single_day_chase_risk" not in result[0].risk_flags


def test_risk_overlay_penalizes_low_quality_daily_data_and_reranks():
    picks = [
        Pick(
            rank=1,
            code="bad",
            name="低质量",
            final_score=82,
            screen_score=82,
            daily_quality_score=0,
            daily_quality_flags="fetch_failed",
        ),
        Pick(
            rank=2,
            code="clean",
            name="干净数据",
            final_score=79,
            screen_score=79,
            daily_quality_score=95,
            daily_quality_flags="",
        ),
    ]

    result, degradation = apply_risk_overlay(picks, max_penalty=12, veto_high_risk=False)

    assert degradation == []
    assert [pick.code for pick in result] == ["clean", "bad"]
    assert result[1].risk_penalty == 8
    assert result[1].risk_level == "high"
    assert "low_daily_quality" in result[1].risk_flags
    assert "daily_fetch_failed" in result[1].risk_flags


def test_risk_overlay_flags_stale_and_fallback_daily_data():
    picks = [
        Pick(
            rank=1,
            code="000001",
            name="平安银行",
            final_score=90,
            screen_score=90,
            daily_quality_score=72,
            daily_quality_flags="stale_cache;fallback_errors",
        )
    ]

    result, _ = apply_risk_overlay(picks, max_penalty=12, veto_high_risk=False)

    assert result[0].risk_penalty == 4
    assert "daily_stale_cache" in result[0].risk_flags
    assert "daily_source_fallback_errors" in result[0].risk_flags


def test_portfolio_overlay_penalizes_duplicate_llm_risk_bucket_and_reranks():
    picks = [
        Pick(
            rank=1,
            code="000001",
            name="平安银行",
            final_score=90,
            screen_score=90,
            llm_sector="银行",
        ),
        Pick(
            rank=2,
            code="000776",
            name="广发证券",
            final_score=88,
            screen_score=88,
            llm_sector="证券",
        ),
        Pick(
            rank=3,
            code="600690",
            name="海尔智家",
            final_score=86,
            screen_score=86,
            llm_sector="家电",
        ),
    ]

    result, notes = apply_portfolio_overlay(
        picks,
        max_same_sector=1,
        concentration_penalty=5,
    )

    assert [pick.code for pick in result] == ["000001", "600690", "000776"]
    assert result[2].portfolio_penalty == 5
    assert "portfolio_sector_concentration:金融" in result[2].portfolio_flags
    assert notes == ["Portfolio concentration bucket=金融: penalized=1, codes=000776:券商(-5.0)"]


def test_portfolio_overlay_ignores_missing_llm_sector():
    picks = [
        Pick(rank=1, code="000001", name="平安银行", final_score=90, screen_score=90),
        Pick(rank=2, code="600000", name="浦发银行", final_score=88, screen_score=88),
    ]

    result, notes = apply_portfolio_overlay(picks, concentration_penalty=5)

    assert [pick.final_score for pick in result] == [90, 88]
    assert notes == [PORTFOLIO_DIVERSITY_SKIPPED_NOTE]


def test_portfolio_overlay_uses_industry_when_llm_sector_missing():
    picks = [
        Pick(rank=1, code="000001", name="平安银行", final_score=90, screen_score=90, industry="银行"),
        Pick(rank=2, code="600000", name="浦发银行", final_score=88, screen_score=88, industry="银行"),
        Pick(rank=3, code="600690", name="海尔智家", final_score=86, screen_score=86, industry="家电"),
    ]

    result, notes = apply_portfolio_overlay(picks, concentration_penalty=5)

    assert [pick.code for pick in result] == ["000001", "600690", "600000"]
    assert "portfolio_sector_concentration:金融" in result[2].portfolio_flags
    assert notes == ["Portfolio concentration bucket=金融: penalized=1, codes=600000:银行(-5.0)"]


def _bank_heavy_picks():
    rows = [
        ("601229", "上海银行", 85.0, "银行"),
        ("601169", "北京银行", 84.7, "银行"),
        ("600016", "民生银行", 84.3, "银行"),
        ("000001", "平安银行", 83.4, "银行"),
        ("600015", "华夏银行", 82.5, "银行"),
        ("601668", "中国建筑", 70.0, "建筑施工"),
        ("601186", "中国铁建", 69.0, "基础建设"),
        ("600900", "长江电力", 68.0, ""),
    ]
    return [
        Pick(rank=i, code=code, name=name, final_score=score, screen_score=score, industry=industry)
        for i, (code, name, score, industry) in enumerate(rows, start=1)
    ]


def test_soft_mode_can_leave_one_bucket_on_top():
    result, _ = apply_portfolio_overlay(
        _bank_heavy_picks(), profile={"max_same_bucket": 2, "concentration_penalty": 3.0}
    )

    assert [pick.industry for pick in result[:5]].count("银行") == 5


def test_hard_cap_limits_bucket_in_top_n_and_keeps_overflow_as_backfill():
    result, notes = apply_portfolio_overlay(
        _bank_heavy_picks(),
        profile={"mode": "hard_cap", "max_same_bucket": 2, "concentration_penalty": 3.0},
    )

    top5 = result[:5]
    assert [pick.industry for pick in top5].count("银行") == 2
    assert [pick.code for pick in top5][2:] == ["601668", "601186", "600900"]
    # Deferred banks stay in the list as backfill, flagged and ranked last.
    assert [pick.code for pick in result[5:]] == ["600016", "000001", "600015"]
    assert "portfolio_sector_cap:金融" in result[5].portfolio_flags
    assert [pick.rank for pick in result] == list(range(1, 9))
    assert any("Portfolio hard cap bucket=金融: max=2" in note for note in notes)


def test_hard_cap_backfills_when_alternatives_run_out():
    picks = _bank_heavy_picks()[:5]

    result, _ = apply_portfolio_overlay(
        picks, profile={"mode": "hard_cap", "max_same_bucket": 2, "concentration_penalty": 0}
    )

    assert len(result) == 5
    assert all(pick.industry == "银行" for pick in result)


def test_invalid_portfolio_mode_is_rejected(tmp_path):
    from pathlib import Path

    import pytest

    from alphasift.strategy import load_strategy

    source = Path("strategies/dual_low.yaml").read_text(encoding="utf-8")
    bad = tmp_path / "bad.yaml"
    bad.write_text(source.replace("mode: hard_cap", "mode: strict"), encoding="utf-8")

    with pytest.raises(ValueError, match="portfolio_profile.mode"):
        load_strategy(bad)


def test_summarize_portfolio_exposure_flags_overconcentration_and_suggests_replacements():
    from alphasift.models import Pick
    from alphasift.risk import summarize_portfolio_exposure

    selected = [
        Pick(rank=1, code="601398", name="工商银行", final_score=88.0, screen_score=88.0, industry="银行"),
        Pick(rank=2, code="601997", name="贵阳银行", final_score=86.0, screen_score=86.0, industry="银行"),
        Pick(rank=3, code="600519", name="贵州茅台", final_score=82.0, screen_score=82.0, industry="白酒"),
    ]
    pool = [
        Pick(rank=4, code="600036", name="招商银行", final_score=81.0, screen_score=81.0, industry="银行"),
        Pick(rank=5, code="600030", name="中信证券", final_score=80.0, screen_score=80.0, industry="证券"),
        Pick(rank=6, code="688981", name="中芯国际", final_score=79.0, screen_score=79.0, industry="半导体"),
    ]
    exposure, over, replacements = summarize_portfolio_exposure(
        selected,
        candidate_pool=pool,
        max_same_bucket=1,
    )
    assert "金融" in exposure
    assert exposure["金融"]["count"] == 2
    assert exposure["金融"]["overconcentrated"] is True
    assert over == ["金融"]
    # Bank and broker candidates in crowded 金融 bucket are excluded; diverse candidates remain
    rep_codes = [item["code"] for item in replacements]
    assert "600036" not in rep_codes
    assert "600030" not in rep_codes
    assert rep_codes == ["688981"]

    # Overlay & summary must agree even when picks carry non-theme concepts (e.g. "半导体" on 煤炭开采)
    coal = [
        Pick(rank=1, code="601088", name="中国神华", final_score=85.0, screen_score=85.0, industry="煤炭开采"),
        Pick(
            rank=2,
            code="601225",
            name="陕西煤业",
            final_score=84.0,
            screen_score=84.0,
            industry="煤炭开采",
            concepts="半导体|高股息",
        ),
    ]
    coal_pool = [Pick(rank=3, code="601898", name="中煤能源", final_score=83.0, screen_score=83.0, industry="煤炭开采", concepts="芯片")]
    coal_exp, coal_over, coal_rep = summarize_portfolio_exposure(coal, candidate_pool=coal_pool, max_same_bucket=1)
    assert coal_over == ["煤炭开采"]
    assert coal_exp["煤炭开采"]["count"] == 2
    assert coal_rep == []

    # replacement_limit=0 returns []; empty-sector pick with unmatched concept maps to "unclassified"; full bucket (== limit) excluded
    zero_exp, _, zero_rep = summarize_portfolio_exposure(selected, candidate_pool=pool, max_same_bucket=1, replacement_limit=0)
    assert zero_exp["消费"]["count"] == 1
    assert zero_rep == []
    same_cap_pool = [Pick(rank=7, code="000858", name="五粮液", final_score=89.0, screen_score=89.0, industry="白酒")]
    _, _, cap_rep = summarize_portfolio_exposure(selected, candidate_pool=same_cap_pool, max_same_bucket=1)
    assert cap_rep == []
    uncls_exp, uncls_over, _ = summarize_portfolio_exposure(
        [Pick(rank=1, code="000002", name="测试", final_score=70.0, screen_score=70.0, industry="", concepts="高股息")],
        max_same_bucket=1,
    )
    assert "" not in uncls_exp
    assert "unclassified" in uncls_exp and uncls_over == []


def test_risk_and_portfolio_overlays_scrub_nan_inf_bool_and_malformed_inputs():
    from alphasift.models import Pick
    from alphasift.risk import apply_portfolio_overlay, apply_risk_overlay, summarize_portfolio_exposure

    p1 = Pick(
        rank=1,
        code="600519",
        name="贵州茅台",
        final_score=float("nan"),
        screen_score=80.0,
        change_pct=float("inf"),
        volume_ratio=float("inf"),
        turnover_rate=True,
        pe_ratio=False,
        pb_ratio=float("nan"),
        signal_score=True,
        llm_confidence=float("nan"),
        daily_quality_score=False,
        industry="白酒",
    )
    p2 = Pick(
        rank=2,
        code="000858",
        name="五粮液",
        final_score=78.0,
        screen_score=78.0,
        change_pct=1.5,
        industry="白酒",
    )

    kept, deg = apply_risk_overlay(
        [p1, p2],
        max_penalty=float("nan"),
        profile={"chase_points": "bad", "high_turnover_points": float("inf"), "abnormal_volume_ratio": True},
    )
    assert deg == []
    assert [p.code for p in kept] == ["000858", "600519"]
    # p1's NaN/Inf/bool metrics must NOT trigger Inf/bool risk flags or NaN scores
    assert kept[1].final_score == 0.0
    assert "abnormal_volume_ratio" not in kept[1].risk_flags
    assert "high_turnover" not in kept[1].risk_flags
    assert "negative_or_invalid_pe" not in kept[1].risk_flags
    assert "weak_daily_signal" not in kept[1].risk_flags
    assert "low_daily_quality" not in kept[1].risk_flags

    p1.portfolio_penalty = float("nan")
    ordered, notes = apply_portfolio_overlay(
        [p2, p1],
        max_same_sector=1,
        concentration_penalty=4.0,
        profile={"max_same_bucket": "bad", "concentration_penalty": float("inf")},
    )
    assert len(ordered) == 2 and notes
    assert ordered[0].code == "000858"
    assert ordered[1].portfolio_penalty == 4.0
    assert ordered[1].final_score == -4.0

    pool = [
        Pick(rank=3, code="688981", name="中芯国际", final_score=float("inf"), screen_score=70.0, industry="半导体"),
    ]
    _, _, reps = summarize_portfolio_exposure(
        ordered,
        candidate_pool=pool,
        max_same_bucket=True,
        replacement_limit="nan",
    )
    assert len(reps) == 1
    assert reps[0]["code"] == "688981"
    assert reps[0]["final_score"] == 0.0
