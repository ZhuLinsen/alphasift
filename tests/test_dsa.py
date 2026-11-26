from alphasift.dsa import (
    apply_dsa_overlay,
    analyze_picks_with_dsa,
    build_dsa_analyze_url,
    check_dsa_readiness,
    extract_deep_analysis_summary,
)
from alphasift.models import Pick


def test_build_dsa_analyze_url_accepts_base_or_full_endpoint():
    assert build_dsa_analyze_url("http://localhost:8000") == (
        "http://localhost:8000/api/v1/analysis/analyze"
    )
    assert build_dsa_analyze_url("http://localhost:8000/api/v1/analysis/analyze") == (
        "http://localhost:8000/api/v1/analysis/analyze"
    )


def test_check_dsa_readiness_reports_missing_url_without_network(monkeypatch):
    def fail_get(*_args, **_kwargs):
        raise AssertionError("network should not be called")

    monkeypatch.setattr("alphasift.dsa.requests.get", fail_get)

    status = check_dsa_readiness("")

    assert status["available"] is False
    assert status["status"] == "missing_url"
    assert status["endpoint"] == ""


def test_check_dsa_readiness_classifies_http_status_without_live_network(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code
            self.text = ""

    def fake_get(url, timeout):
        calls.append((url, timeout))
        return FakeResponse(405)

    monkeypatch.setattr("alphasift.dsa.requests.get", fake_get)

    status = check_dsa_readiness("http://localhost:8000", timeout_sec=1.5)

    assert calls == [("http://localhost:8000/api/v1/analysis/analyze", 1.5)]
    assert status["available"] is True
    assert status["status"] == "route_present"


def test_check_dsa_readiness_reports_auth_and_missing_route(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code
            self.text = "nope"

    monkeypatch.setattr("alphasift.dsa.requests.get", lambda *_args, **_kwargs: FakeResponse(401))
    unauthorized = check_dsa_readiness("http://localhost:8000")
    assert unauthorized["available"] is False
    assert unauthorized["status"] == "unauthorized"

    monkeypatch.setattr("alphasift.dsa.requests.get", lambda *_args, **_kwargs: FakeResponse(404))
    missing = check_dsa_readiness("http://localhost:8000")
    assert missing["available"] is False
    assert missing["status"] == "route_missing"


def test_extract_deep_analysis_summary_prefers_analysis_summary_over_operation_advice():
    result = {
        "query_id": "q1",
        "report": {
            "summary": {
                "analysis_summary": "这是更完整的分析摘要",
                "operation_advice": "继续观察，等待更好的风险收益比"
            }
        },
    }

    assert extract_deep_analysis_summary(result) == "这是更完整的分析摘要"


def test_analyze_picks_with_dsa_attaches_results(monkeypatch):
    picks = [
        Pick(rank=1, code="600519", name="贵州茅台", final_score=90, screen_score=90),
        Pick(rank=2, code="000858", name="五粮液", final_score=88, screen_score=88),
    ]

    def fake_call(endpoint, **kwargs):
        return {
            "query_id": f"query-{kwargs['stock_code']}",
            "report": {"summary": {"operation_advice": f"关注 {kwargs['stock_code']}"}},
        }

    monkeypatch.setattr("alphasift.dsa.call_dsa_analysis", fake_call)

    analyzed, degradation = analyze_picks_with_dsa(
        picks,
        run_id="run123",
        api_url="http://localhost:8000",
        max_picks=1,
    )

    assert degradation == []
    assert analyzed[0].deep_analysis_status == "completed"
    assert analyzed[0].deep_analysis_query_id == "query-600519"
    assert analyzed[0].deep_analysis_summary == "关注 600519"
    assert analyzed[0].deep_analysis_operation_advice == "关注 600519"
    assert analyzed[1].deep_analysis_status == "skipped"


def test_apply_dsa_overlay_uses_structured_scores_for_final_rerank():
    picks = [
        Pick(rank=1, code="AAA", name="A", final_score=80, screen_score=80),
        Pick(rank=2, code="BBB", name="B", final_score=82, screen_score=82),
    ]

    picks[0].deep_analysis_status = "completed"
    picks[0].deep_analysis_signal_score = 82
    picks[0].deep_analysis_sentiment_score = 88
    picks[0].deep_analysis_operation_advice = "买入"
    picks[0].deep_analysis_trend_prediction = "看多"

    picks[1].deep_analysis_status = "completed"
    picks[1].deep_analysis_signal_score = 40
    picks[1].deep_analysis_sentiment_score = 38
    picks[1].deep_analysis_operation_advice = "观望"
    picks[1].deep_analysis_trend_prediction = "震荡"
    picks[1].deep_analysis_risk_flags = ["乖离率过高"]

    reranked = apply_dsa_overlay(picks)

    assert reranked[0].code == "AAA"
    assert reranked[0].rank == 1
    assert reranked[1].code == "BBB"
    assert reranked[1].rank == 2
    assert reranked[0].final_score > reranked[1].final_score


def test_dsa_overlay_and_extractors_scrub_nan_inf_and_bool_scores(monkeypatch):
    import math
    from alphasift.dsa import analyze_picks_with_dsa

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "query_id": "q-inf",
                "report": {
                    "summary": {
                        "sentiment_score": float("inf"),
                        "operation_advice": "买入",
                        "trend_prediction": "看多",
                    },
                    "details": {
                        "context_snapshot": {
                            "trend_result": {
                                "signal_score": True,
                                "risk_factors": [],
                            }
                        }
                    },
                },
            }

    monkeypatch.setattr("alphasift.dsa.requests.post", lambda *a, **kw: FakeResp())

    p1 = Pick(rank=1, code="600519", name="贵州茅台", final_score=float("nan"), screen_score=80.0)
    p2 = Pick(rank=2, code="000858", name="五粮液", final_score=50.0, screen_score=50.0)

    analyzed, deg = analyze_picks_with_dsa(
        [p1, p2],
        run_id="r71",
        api_url="http://example.test",
        max_picks=1,
    )
    assert deg == []
    assert analyzed[0].deep_analysis_signal_score is None
    assert analyzed[0].deep_analysis_sentiment_score is None

    reranked = apply_dsa_overlay(analyzed)
    assert [p.code for p in reranked] == ["000858", "600519"]
    assert all(math.isfinite(float(p.final_score)) for p in reranked)
    # p1 starts at scrubbed 0.0 + 8.0 ("买入") + 4.0 ("看多") == 12.0 without bool signal_score penalty (-9.8)
    assert reranked[1].final_score == 12.0
