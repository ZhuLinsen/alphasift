from alphasift.models import Pick
from alphasift.risk import apply_portfolio_overlay, apply_risk_overlay


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
    assert notes == []


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
