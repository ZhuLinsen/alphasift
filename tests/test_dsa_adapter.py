from alphasift import dsa_adapter
from alphasift.models import Pick, ScreenResult, StrategyInfo


def test_list_strategies_returns_stable_shape(monkeypatch):
    monkeypatch.setattr(
        dsa_adapter,
        "load_strategies",
        lambda: [
            StrategyInfo(
                name="dual_low",
                display_name="Dual Low",
                description="Low valuation strategy",
                version="1",
                category="value",
                tags=["value"],
                market_scope=["cn"],
            )
        ],
    )

    assert dsa_adapter.list_strategies() == [
        {
            "id": "dual_low",
            "name": "Dual Low",
            "description": "Low valuation strategy",
            "version": "1",
            "category": "value",
            "tags": ["value"],
            "market_scope": ["cn"],
        }
    ]


def test_screen_returns_stable_dsa_contract(monkeypatch):
    calls = []

    monkeypatch.setattr(
        dsa_adapter,
        "run_screen",
        lambda *args, **kwargs: calls.append((args, kwargs)) or ScreenResult(
            strategy="dual_low",
            market="cn",
            strategy_version="1",
            strategy_category="value",
            snapshot_count=100,
            after_filter_count=3,
            run_id="run123",
            llm_ranked=True,
            llm_coverage=1.0,
            llm_market_view="market ok",
            picks=[
                Pick(
                    rank=1,
                    code="600519",
                    name="Kweichow Moutai",
                    final_score=88.5,
                    screen_score=80.0,
                    llm_score=90.0,
                    llm_thesis="LLM likes the setup",
                    ranking_reason="",
                    risk_level="medium",
                    risk_flags=["valuation"],
                    price=1688.0,
                    industry="Baijiu",
                    factor_scores={"value": 88.0, "liquidity": 72.0},
                    dsa_context={
                        "enriched": True,
                        "quote": {"price": 1688.0},
                        "news": {"results": [{"title": "贵州茅台公告"}]},
                    },
                    dsa_news=[{"title": "贵州茅台公告"}],
                    dsa_analysis_summary="DSA新闻: 贵州茅台公告",
                    sentiment_available=True,
                    sentiment_score=68.0,
                    sentiment_label="positive",
                    sentiment_confidence=0.72,
                    sentiment_source_count=2,
                    sentiment_positive_events=["回购增持"],
                    sentiment_evidence=[{"source": "announcement", "category": "回购增持"}],
                    sentiment_score_delta=1.3,
                    post_analysis_summaries={"scorecard": "Local scorecard: value_quality"},
                )
            ],
            degradation=["fallback used"],
            source_errors=["source timeout"],
        ),
    )

    context = {"dsa": {"contract_version": "1"}}
    payload = dsa_adapter.screen("dual_low", market="cn", max_results=5, context=context)

    assert calls[0][1]["use_llm"] is True
    assert calls[0][1]["context"] is context
    assert payload["contract_version"] == "1"
    assert payload["run_id"] == "run123"
    assert payload["llm_ranked"] is True
    assert payload["llm_coverage"] == 1.0
    assert payload["candidate_count"] == 1
    assert payload["warnings"] == ["fallback used"]
    assert payload["source_errors"] == ["source timeout"]
    assert payload["candidates"][0]["code"] == "600519"
    assert payload["candidates"][0]["score"] == 88.5
    assert payload["candidates"][0]["risk_flags"] == ["valuation"]
    assert payload["candidates"][0]["llm_score"] == 90.0
    assert payload["candidates"][0]["llm_thesis"] == "LLM likes the setup"
    assert payload["candidates"][0]["reason"] == "LLM likes the setup"
    assert payload["candidates"][0]["price"] == 1688.0
    assert payload["candidates"][0]["industry"] == "Baijiu"
    assert payload["candidates"][0]["dsa_context"]["enriched"] is True
    assert payload["candidates"][0]["dsa_news"][0]["title"] == "贵州茅台公告"
    assert payload["candidates"][0]["dsa_analysis_summary"] == "DSA新闻: 贵州茅台公告"
    assert payload["candidates"][0]["sentiment_available"] is True
    assert payload["candidates"][0]["sentiment_score"] == 68.0
    assert payload["candidates"][0]["sentiment_label"] == "positive"
    assert payload["candidates"][0]["sentiment_positive_events"] == ["回购增持"]


def test_status_is_fail_open(monkeypatch):
    monkeypatch.setattr(dsa_adapter, "list_strategies", lambda context=None: (_ for _ in ()).throw(RuntimeError("boom")))

    payload = dsa_adapter.get_status()

    assert payload["available"] is False
    assert payload["contract_version"] == "1"
    assert "boom" in payload["error"]
