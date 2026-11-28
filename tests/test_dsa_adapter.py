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


def test_status_is_fail_open(monkeypatch):
    monkeypatch.setattr(dsa_adapter, "list_strategies", lambda context=None: (_ for _ in ()).throw(RuntimeError("boom")))

    payload = dsa_adapter.get_status()

    assert payload["available"] is False
    assert payload["contract_version"] == "1"
    assert "boom" in payload["error"]


def test_screen_scrubs_nonfinite_bool_and_malformed_pick_fields(monkeypatch):
    import json
    import math

    monkeypatch.setattr(
        dsa_adapter,
        "run_screen",
        lambda *args, **kwargs: ScreenResult(
            strategy="dual_low",
            market="cn",
            strategy_version="1",
            strategy_category="value",
            snapshot_count=True,
            after_filter_count=-3,
            run_id="run_bad",
            llm_ranked=False,
            llm_coverage=float("nan"),
            picks=[
                {
                    "rank": True,
                    "code": "000001",
                    "name": "PingAn",
                    "final_score": float("nan"),
                    "screen_score": 76.5,
                    "llm_score": float("inf"),
                    "llm_confidence": True,
                    "price": float("-inf"),
                    "change_pct": math.nan,
                    "amount": False,
                    "risk_flags": "not-a-list",
                    "factor_scores": {
                        "nan_f": float("nan"),
                        "inf_f": float("inf"),
                        "bool_f": True,
                        "momentum": 84.2,
                    },
                    "dsa_context": {"quote": {"price": float("nan")}},
                }
            ],
        ),
    )

    payload = dsa_adapter.screen("dual_low")
    encoded = json.dumps(payload, allow_nan=False)
    assert encoded

    assert payload["snapshot_count"] == 0
    assert payload["after_filter_count"] == 0
    assert payload["llm_coverage"] is None

    cand = payload["candidates"][0]
    assert cand["rank"] == 1
    assert cand["score"] == 76.5
    assert cand["screen_score"] == 76.5
    assert cand["llm_score"] is None
    assert cand["llm_confidence"] is None
    assert cand["price"] is None
    assert cand["change_pct"] is None
    assert cand["amount"] is None
    assert cand["risk_flags"] == []
    assert cand["factor_scores"] == {"momentum": 84.2}
    assert cand["reason"] == "Top factors: momentum 84.2"
    assert cand["dsa_context"] == {"quote": {"price": None}}


def test_dsa_adapter_scrubs_na_and_nan_scalar_strings_and_false_flags(monkeypatch):
    import json

    monkeypatch.setattr(
        dsa_adapter,
        "run_screen",
        lambda *args, **kwargs: ScreenResult(
            strategy="NA",
            market="cn",
            run_id=float("nan"),  # type: ignore[arg-type]
            llm_ranked="false",  # type: ignore[arg-type]
            llm_market_view="null",
            picks=[
                {
                    "rank": 1,
                    "code": "600519",
                    "name": float("nan"),
                    "stock_name": "RealName",
                    "final_score": 82.0,
                    "llm_thesis": float("nan"),
                    "ranking_reason": "NA",
                    "industry": float("nan"),
                    "risk_level": "null",
                    "post_analysis_summaries": {"scorecard": "NA", "dsa": "Valid summary"},
                }
            ],
        ),
    )

    payload = dsa_adapter.screen("dual_low")
    encoded = json.dumps(payload, allow_nan=False)
    assert encoded
    assert payload["strategy"] == ""
    assert payload["run_id"] == ""
    assert payload["llm_ranked"] is False
    assert payload["llm_market_view"] == ""
    cand = payload["candidates"][0]
    assert cand["name"] == "RealName"
    assert cand["industry"] == ""
    assert cand["risk_level"] == ""
    assert cand["reason"] == "Valid summary"
