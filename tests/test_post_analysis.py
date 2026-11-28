from alphasift.config import Config
from alphasift.models import Pick
from alphasift.post_analysis import normalize_post_analyzers, run_post_analyzers


def test_config_defaults_to_local_scorecard_analyzer():
    assert Config().post_analyzers == ["scorecard"]


def test_normalize_post_analyzers_accepts_repeated_and_csv_names():
    assert normalize_post_analyzers(["scorecard,dsa", "scorecard"]) == ["scorecard", "dsa"]


def test_scorecard_post_analyzer_attaches_generic_fields():
    picks = [
        Pick(
            rank=1,
            code="000001",
            name="平安银行",
            final_score=70,
            screen_score=70,
            factor_scores={"value": 80, "stability": 70, "momentum": 60, "activity": 50},
            llm_confidence=0.8,
            llm_catalysts=["低估值修复"],
        )
    ]

    result, degradation = run_post_analyzers(
        picks,
        analyzer_names=["scorecard"],
        run_id="run1",
        config=Config(llm_api_key=""),
        max_picks=1,
    )

    assert degradation == []
    assert result[0].final_score > 70
    assert result[0].post_analysis_status["scorecard"] == "completed"
    assert "scorecard" in result[0].post_analysis_score_deltas


def test_scorecard_scores_all_picks_when_no_limit_is_set():
    picks = [
        Pick(
            rank=1,
            code="000001",
            name="平安银行",
            final_score=70,
            screen_score=70,
            factor_scores={"value": 80, "stability": 70},
        ),
        Pick(
            rank=2,
            code="600000",
            name="浦发银行",
            final_score=68,
            screen_score=68,
            factor_scores={"value": 79, "stability": 69},
        ),
    ]

    result, degradation = run_post_analyzers(
        picks,
        analyzer_names=["scorecard"],
        run_id="run1",
        config=Config(llm_api_key=""),
        max_picks=None,
    )

    assert degradation == []
    assert result[0].post_analysis_status["scorecard"] == "completed"
    assert result[1].post_analysis_status["scorecard"] == "completed"


def test_external_http_analyzer_normalizes_returned_codes(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ranked": [
                    {"code": "SZ000001", "score_delta": 2.0, "summary": "外部评分确认"},
                ]
            }

    def fake_post(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr("alphasift.post_analysis.requests.post", fake_post)
    picks = [Pick(rank=1, code="000001", name="平安银行", final_score=70, screen_score=70)]

    result, degradation = run_post_analyzers(
        picks,
        analyzer_names=["external_http"],
        run_id="run1",
        config=Config(llm_api_key="", post_analyzer_url="http://example.test/rank"),
        max_picks=1,
    )

    assert degradation == []
    assert result[0].final_score == 72
    assert result[0].post_analysis_status["external_http"] == "completed"


def test_post_analyzers_scrub_nan_inf_bool_deltas_factors_and_profiles(monkeypatch):
    import math

    class BadFloatResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ranked": [
                    {"code": "000001", "score_delta": float("inf"), "summary": "恶意无穷增分"},
                ]
            }

    monkeypatch.setattr("alphasift.post_analysis.requests.post", lambda *a, **kw: BadFloatResponse())

    p1 = Pick(
        rank=1,
        code="000001",
        name="平安银行",
        final_score=float("nan"),
        screen_score=70.0,
        volume_ratio=float("inf"),
        llm_confidence=True,
        factor_scores={"value": float("inf"), "stability": float("nan"), "momentum": "bad", "activity": True},
    )
    p2 = Pick(rank=2, code="600519", name="贵州茅台", final_score=75.0, screen_score=75.0)

    out, deg = run_post_analyzers(
        [p1, p2],
        analyzer_names=["scorecard", "external_http"],
        run_id="run_guard",
        config=Config(llm_api_key="", post_analyzer_url="http://example.test/rank"),
        scorecard_profile={"score_delta_cap": float("inf"), "value_quality_bonus": "bad", "catalyst_bonus": True},
    )
    assert deg == []
    assert [p.code for p in out] == ["600519", "000001"]
    assert all(math.isfinite(float(p.final_score)) for p in out)
    # p1's Inf volume_ratio & Inf external_http delta must NOT trigger volume_spike or Inf score
    assert "volume_spike" not in out[1].risk_flags
    assert out[1].final_score == 0.0
    assert out[1].post_analysis_score_deltas["external_http"] == 0.0


def test_post_analysis_guards_string_risks_na_items_timeout_and_empty_codes(monkeypatch):
    assert normalize_post_analyzers([None, float("nan"), "NA, scorecard", "dsa"]) == [  # type: ignore[list-item]
        "scorecard",
        "dsa",
    ]
    assert normalize_post_analyzers(True) == []  # type: ignore[arg-type]

    seen_timeouts: list[object] = []

    class FakeHttpResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ranked": [
                    {"code": "", "score_delta": 99.0, "summary": "should skip empty code"},
                    {"code": "000001", "score_delta": 1.5, "summary": float("nan"), "risk_flags": "macro_risk"},
                ]
            }

    def fake_post(*args, **kwargs):
        seen_timeouts.append(kwargs.get("timeout"))
        return FakeHttpResponse()

    monkeypatch.setattr("alphasift.post_analysis.requests.post", fake_post)

    blank_code_pick = Pick(
        rank=1,
        code="",
        name="无效标的",
        final_score=70.0,
        screen_score=70.0,
    )
    valid_pick = Pick(
        rank=2,
        code="000001",
        name="平安银行",
        final_score=70.0,
        screen_score=70.0,
        llm_catalysts="earnings_beat",  # type: ignore[arg-type]
        llm_risks="litigation_risk",  # type: ignore[arg-type]
        risk_flags=[None, float("nan"), "NA"],  # type: ignore[list-item]
    )

    out, deg = run_post_analyzers(
        [blank_code_pick, valid_pick],
        analyzer_names="scorecard,external_http",
        run_id="run_clean",
        config=Config(
            llm_api_key="",
            post_analyzer_url="http://example.test/rank",
            post_analyzer_timeout_sec=float("nan"),
        ),
    )

    assert deg == []
    assert seen_timeouts == [15.0]
    by_code = {p.code: p for p in out}
    # Empty-code response entry must never match blank-code pick
    assert by_code[""].post_analysis_status.get("external_http") is None
    assert by_code["000001"].post_analysis_summaries["external_http"] == ""
    # Single-string llm_catalysts/llm_risks must count as 1 item (not len("earnings_beat") chars)
    assert by_code["000001"].post_analysis_score_deltas["scorecard"] == -0.3
    assert by_code["000001"].risk_flags == ["litigation_risk", "macro_risk"]
