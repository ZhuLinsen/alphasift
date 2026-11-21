import json
import sys
import types

from alphasift.models import Pick
from alphasift.ranker import (
    _build_litellm_attempts,
    _build_ranking_prompt,
    _call_llm,
    _parse_ranking_response,
    _parse_ranking_response_detail,
    rank_candidates,
)


def test_parse_structured_llm_ranking_attaches_insight_fields():
    picks = [
        Pick(rank=1, code="000001", name="平安银行", final_score=70, screen_score=70),
        Pick(rank=2, code="600000", name="浦发银行", final_score=68, screen_score=68),
    ]
    response = json.dumps(
        {
            "ranked": [
                {
                    "code": "600000",
                    "llm_score": 88,
                    "confidence": 0.72,
                    "sector": "银行",
                    "theme": "低估值修复",
                    "reason": "估值与修复弹性更匹配策略",
                    "risk": "银行板块整体弹性有限",
                    "catalysts": ["低估值修复"],
                    "risk_flags": ["板块贝塔弱"],
                    "invalidators": ["地产链继续走弱"],
                    "tags": ["价值", "修复"],
                    "style_fit": "低估值修复",
                }
            ]
        },
        ensure_ascii=False,
    )

    ranked = _parse_ranking_response(response, picks)

    assert ranked[0].code == "600000"
    assert ranked[0].llm_score == 88
    assert ranked[0].llm_confidence == 0.72
    assert ranked[0].llm_sector == "银行"
    assert ranked[0].llm_theme == "低估值修复"
    assert ranked[0].llm_catalysts == ["低估值修复"]
    assert ranked[0].llm_risks == ["板块贝塔弱"]
    assert ranked[0].llm_invalidators == ["地产链继续走弱"]
    assert ranked[0].llm_style_fit == "低估值修复"
    assert ranked[0].llm_tags == [
        "价值",
        "修复",
        "sector:银行",
        "theme:低估值修复",
        "style_fit:低估值修复",
    ]
    assert ranked[1].code == "000001"


def test_parse_llm_ranking_normalizes_suffixed_codes():
    picks = [
        Pick(rank=1, code="SZ000001", name="平安银行", final_score=70, screen_score=70),
    ]
    response = json.dumps({"ranked": [{"code": "000001", "llm_score": 88}]})

    result = _parse_ranking_response_detail(response, picks)

    assert result.coverage == 1.0
    assert result.picks[0].llm_score == 88


def test_parse_llm_ranking_attaches_global_research_metadata():
    picks = [
        Pick(rank=1, code="000001", name="平安银行", final_score=70, screen_score=70),
    ]
    response = json.dumps(
        {
            "market_view": "候选池偏低估值修复，适合防守反击",
            "selection_logic": "优先低估值、稳定性和催化可解释性",
            "portfolio_risk": "银行板块集中度较高",
            "ranked": [
                {
                    "code": "000001",
                    "llm_score": 80,
                    "thesis": "估值低且修复逻辑清晰",
                    "reason": "低估值修复",
                    "risk": "板块弹性有限",
                    "watch_items": ["成交额能否延续"],
                }
            ],
        },
        ensure_ascii=False,
    )

    result = _parse_ranking_response_detail(response, picks)

    assert result.market_view == "候选池偏低估值修复，适合防守反击"
    assert result.selection_logic == "优先低估值、稳定性和催化可解释性"
    assert result.portfolio_risk == "银行板块集中度较高"
    assert result.picks[0].llm_thesis == "估值低且修复逻辑清晰"
    assert result.picks[0].llm_watch_items == ["成交额能否延续"]


def test_parse_llm_ranking_extracts_fenced_json_with_surrounding_text():
    picks = [
        Pick(rank=1, code="000001", name="平安银行", final_score=70, screen_score=70),
    ]
    response = """这里是排序结果：

```json
{
  "market_view": "低估值候选为主",
  "ranked": [
    {"code": "000001", "llm_score": 82, "reason": "估值修复", "risk": "弹性有限"}
  ]
}
```

请参考。"""

    result = _parse_ranking_response_detail(response, picks)

    assert result.coverage == 1.0
    assert result.market_view == "低估值候选为主"
    assert result.picks[0].llm_score == 82
    assert result.picks[0].ranking_reason == "估值修复"


def test_parse_llm_ranking_extracts_json_after_unrelated_braces():
    picks = [
        Pick(rank=1, code="600000", name="浦发银行", final_score=70, screen_score=70),
    ]
    response = (
        "我会按 {行业/估值/催化} 三类因素判断。\n"
        '{"ranked": [{"code": "600000", "llm_score": 91, "reason": "更强"}]}'
    )

    result = _parse_ranking_response_detail(response, picks)

    assert result.coverage == 1.0
    assert result.picks[0].llm_score == 91


def test_parse_llm_ranking_recovers_partial_object_sequence():
    picks = [
        Pick(rank=1, code="000001", name="平安银行", final_score=70, screen_score=70),
        Pick(rank=2, code="600000", name="浦发银行", final_score=68, screen_score=68),
    ]
    response = """
1. {"code": "600000", "llm_score": 88, "reason": "低估值"}
2. {"code": "000001", "llm_score": 77, "reason": "防守"}
"""

    result = _parse_ranking_response_detail(response, picks)

    assert result.coverage == 1.0
    assert "json_repaired:partial_array" in result.errors
    assert [p.code for p in result.picks] == ["600000", "000001"]


def test_parse_llm_ranking_reports_empty_response():
    picks = [Pick(rank=1, code="000001", name="平安银行", final_score=70, screen_score=70)]

    result = _parse_ranking_response_detail("   ", picks)

    assert result.coverage == 0.0
    assert result.errors == ["empty_response"]


def test_rank_candidates_blends_screen_and_llm_scores(monkeypatch):
    picks = [
        Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80),
        Pick(rank=2, code="600000", name="浦发银行", final_score=70, screen_score=70),
    ]

    captured = {}

    def fake_call(prompt, api_key, model, base_url, **kwargs):
        captured["timeout_sec"] = kwargs.get("timeout_sec")
        return json.dumps(
            {
                "ranked": [
                    {"code": "600000", "llm_score": 95, "reason": "更强", "risk": "波动"},
                    {"code": "000001", "llm_score": 60, "reason": "较弱", "risk": "催化不足"},
                ]
            }
        )

    monkeypatch.setattr("alphasift.ranker._call_llm", fake_call)

    ranked = rank_candidates(
        picks,
        ranking_hints="demo",
        llm_api_key="key",
        llm_model="model",
        rank_weight=0.4,
        timeout_sec=42.0,
    )

    assert captured["timeout_sec"] == 42.0
    assert [p.code for p in ranked] == ["600000", "000001"]
    assert ranked[0].final_score == 80.0
    assert ranked[1].final_score == 72.0


def test_call_llm_sets_generation_bounds_and_disables_sdk_retries(monkeypatch):
    captured = {}

    class FakeMessage:
        content = '{"ranked": []}'

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    fake_litellm = types.ModuleType("litellm")

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return FakeResponse()

    setattr(fake_litellm, "completion", fake_completion)
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    response = _call_llm(
        "prompt",
        api_key="key",
        model="openai/local-model",
        base_url="http://localhost:8000/v1",
        timeout_sec=7,
        max_tokens=321,
    )

    assert response == '{"ranked": []}'
    assert captured["timeout"] == 7
    assert captured["max_tokens"] == 321
    assert captured["num_retries"] == 0


def test_call_llm_does_not_retry_without_json_mode_on_timeout(monkeypatch):
    calls = []
    fake_litellm = types.ModuleType("litellm")

    def fake_completion(**kwargs):
        calls.append(kwargs)
        raise TimeoutError("APITimeoutError - Request timed out")

    setattr(fake_litellm, "completion", fake_completion)
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    try:
        _call_llm(
            "prompt",
            api_key="key",
            model="openai/local-model",
            base_url="http://localhost:8000/v1",
            json_mode=True,
            fallback_models=["openai/backup-model"],
        )
    except TimeoutError:
        pass

    assert len(calls) == 1
    assert calls[0]["response_format"] == {"type": "json_object"}


def test_build_litellm_attempts_uses_matching_channel_keys():
    attempts = _build_litellm_attempts(
        "openai/deepseek-chat",
        api_key="fallback-key",
        base_url="https://fallback.example/v1",
        channels=[
            {
                "name": "primary",
                "protocol": "openai",
                "base_url": "https://api.deepseek.com/v1",
                "api_keys": ["key1", "key2"],
                "models": ["deepseek-chat"],
                "enabled": True,
            }
        ],
    )

    assert attempts[0]["api_key"] == "key1"
    assert attempts[0]["api_base"] == "https://api.deepseek.com/v1"
    assert attempts[1]["api_key"] == "key2"
    assert attempts[-1]["api_key"] == "fallback-key"


def test_ranking_prompt_includes_structured_industry_context():
    prompt = _build_ranking_prompt(
        [
            Pick(
                rank=1,
                code="000001",
                name="平安银行",
                final_score=70,
                screen_score=70,
                industry="银行",
                concepts="低估值,中特估",
                industry_rank=3,
                industry_change_pct=1.2,
                board_heat_score=72.5,
                board_heat_summary="银行:+1.20%:rank=3",
                breakout_20d_pct=0.8,
                range_20d_pct=18.0,
                volume_ratio_20d=1.8,
                body_pct=1.2,
                pullback_to_ma20_pct=4.0,
                consolidation_days_20d=10,
            )
        ],
        hints="demo",
    )

    assert "industry=银行" in prompt
    assert "concepts=低估值,中特估" in prompt
    assert "industry_rank=3" in prompt
    assert "board_heat_score=72.5" in prompt
    assert "银行:+1.20%" in prompt
    assert "breakout_20d_pct=0.8" in prompt
    assert "volume_ratio_20d=1.8" in prompt
    assert "consolidation_days_20d=10" in prompt
    assert "优先参考候选的 industry/concepts" in prompt


def test_ranking_prompt_includes_dsa_provider_context():
    prompt = _build_ranking_prompt(
        [
            Pick(
                rank=1,
                code="600519",
                name="贵州茅台",
                final_score=88,
                screen_score=88,
                dsa_context={
                    "enriched": True,
                    "quote": {"price": 1688.0, "change_pct": 1.2, "amount": 100_000_000.0},
                    "fundamentals": {"coverage": {"valuation": "available"}},
                    "warnings": ["stock_news_slow"],
                },
                dsa_news=[{"title": "贵州茅台最新公告"}],
                dsa_analysis_summary="DSA新闻: 贵州茅台最新公告",
            )
        ],
        hints="demo",
    )

    assert "dsa_context=" in prompt
    assert "DSA新闻: 贵州茅台最新公告" in prompt
    assert "fundamental_coverage=valuation" in prompt
    assert "news_titles=贵州茅台最新公告" in prompt
    assert "stock_news_slow" in prompt


def test_ranking_prompt_is_bounded_and_keeps_required_fields():
    picks = [
        Pick(
            rank=index + 1,
            code=f"{index + 1:06d}",
            name=f"候选{index + 1}",
            final_score=100 - index,
            screen_score=100 - index,
            price=10 + index,
            change_pct=1.5,
            amount=100_000_000 + index,
            industry="测试行业",
            concepts="测试概念,长线索",
            board_heat_score=80 - index,
            dsa_analysis_summary="DSA摘要 " * 120,
            dsa_news=[{"title": "重要新闻 " * 40}],
        )
        for index in range(12)
    ]
    degradation: list[str] = []

    prompt = _build_ranking_prompt(
        picks,
        hints="优先主评分、行业热度和事件催化。" * 120,
        context="市场上下文 " * 600,
        max_chars=5000,
        degradation=degradation,
    )

    assert len(prompt) <= 5000
    assert "000001 候选1" in prompt
    assert "rank=1" in prompt
    assert "screen_score=100.0" in prompt
    assert "000012 候选12" in prompt
    assert "prompt_trimmed" in prompt
    assert degradation
    assert degradation[0].startswith("LLM ranking prompt truncated:")


def test_ranking_prompt_includes_red_flag_and_anti_familiarity_rules() -> None:
    picks = [
        Pick(rank=1, code="000001", name="示例公司", final_score=92.0, screen_score=92.0),
    ]
    prompt = _build_ranking_prompt(picks, hints="")
    assert "<= 35" in prompt
    assert "禁止品牌/名气偏见" in prompt
