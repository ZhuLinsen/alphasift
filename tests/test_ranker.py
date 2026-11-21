import json
from unittest.mock import Mock

import pytest
import requests

from alphasift.config import Config
from alphasift.llm_client import LLMClientError
from alphasift.models import Pick
from alphasift.ranker import (
    _build_ranking_prompt,
    _call_llm,
    _parse_ranking_response,
    _parse_ranking_response_detail,
    rank_candidates,
    rank_candidates_with_metadata,
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


def _chat_response(content: str, status: int = 200) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    body = {"choices": [{"message": {"content": content}}]} if status == 200 else {"error": {"message": content}}
    response._content = json.dumps(body).encode()
    return response


def test_call_llm_sends_chat_completion_with_generation_bounds(monkeypatch):
    post = Mock(return_value=_chat_response('{"ranked": []}'))
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)

    response = _call_llm(
        "prompt",
        api_key="key",
        model="openai/local-model",
        base_url="http://localhost:8000/v1/",
        temperature=0.3,
        timeout_sec=7,
        max_tokens=321,
    )

    assert response == '{"ranked": []}'
    post.assert_called_once_with(
        "http://localhost:8000/v1/chat/completions",
        headers={"Authorization": "Bearer key"},
        json={
            "model": "local-model",
            "messages": [{"role": "user", "content": "prompt"}],
            "temperature": 0.3,
            "max_tokens": 321,
            "response_format": {"type": "json_object"},
        },
        timeout=7,
        allow_redirects=False,
    )


@pytest.mark.parametrize("fail_after_json_retry", [False, True])
def test_call_llm_does_not_retry_same_attempt_without_json_mode_on_timeout(monkeypatch, fail_after_json_retry):
    responses = [_chat_response("unsupported response_format", 400)] if fail_after_json_retry else []
    post = Mock(side_effect=[*responses, requests.Timeout("Request timed out")])
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)

    with pytest.raises(LLMClientError, match="timed out") as error:
        _call_llm(
            "prompt",
            api_key="key",
            model="openai/local-model",
            base_url="http://localhost:8000/v1",
            json_mode=True,
        )

    assert error.value.timed_out
    assert post.call_count == len(responses) + 1
    assert post.call_args_list[0].kwargs["json"]["response_format"] == {"type": "json_object"}


def test_call_llm_retries_same_attempt_without_json_mode(monkeypatch):
    post = Mock(
        side_effect=[
            _chat_response("unsupported response_format json_object", 400),
            _chat_response('{"ranked": []}'),
        ]
    )
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)

    result = _call_llm(
        "prompt",
        api_key="key",
        model="openai/local-model",
        base_url="http://localhost:8000/v1",
        fallback_models=["openai/backup"],
        max_tokens=None,
    )

    first, second = post.call_args_list
    assert result == '{"ranked": []}'
    assert first.args == second.args
    first_payload = first.kwargs.pop("json")
    second_payload = second.kwargs.pop("json")
    assert first.kwargs == second.kwargs
    assert first_payload.pop("response_format") == {"type": "json_object"}
    assert first_payload == second_payload
    assert "max_tokens" not in second_payload


@pytest.mark.parametrize("retries", [0, 1])
def test_ranker_retries_low_coverage_up_to_configured_limit(monkeypatch, retries):
    post = Mock(
        side_effect=[
            _chat_response('{"ranked": []}'),
            _chat_response('{"ranked": [{"code": "000001"}]}'),
        ]
    )
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)
    monkeypatch.setenv("LLM_MAX_RETRIES", str(retries))
    picks = [Pick(rank=1, code="000001", name="平安银行", screen_score=80, final_score=80)]
    result = rank_candidates_with_metadata(
        picks,
        "",
        "key",
        "openai/test",
        "https://gateway.test/v1",
        max_retries=Config.from_env().llm_max_retries,
        json_mode=False,
    )

    assert result.ranked is bool(retries)
    assert post.call_count == retries + 1
    assert all("response_format" not in call.kwargs["json"] for call in post.call_args_list)


@pytest.mark.parametrize("timeout", [False, True])
def test_ranker_degrades_on_http_error_or_timeout_without_leaking_keys(monkeypatch, caplog, timeout):
    key = "private-example-api-key"
    upstream = "sk-different-private-upstream-key"
    if timeout:
        post = Mock(side_effect=requests.Timeout(f"Request for {key} and {upstream} timed out"))
    else:
        post = Mock(return_value=_chat_response(f"Bad bearer {key} for upstream {upstream}", 401))
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)
    picks = [Pick(rank=1, code="000001", name="平安银行", screen_score=80, final_score=80)]
    result = rank_candidates_with_metadata(picks, "", key, "openai/test", "https://gateway.test/v1")

    assert result.picks == picks
    assert not result.ranked
    assert picks[0].llm_score is None
    assert result.errors == [
        "LLM request timed out" if timeout else "LLM HTTP 401 Unauthorized: Bad *** for upstream ***"
    ]
    assert "falling back to screen_score" in caplog.text
    for secret in (key, upstream):
        assert secret not in caplog.text
        assert secret not in str(result.errors)
    assert post.call_count == 1


def test_ranker_discards_partial_ranking_when_coverage_retry_times_out(monkeypatch):
    post = Mock(
        side_effect=[
            _chat_response('{"ranked": [{"code": "000001", "llm_score": 99}]}'),
            requests.ReadTimeout(),
        ]
    )
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)
    picks = [
        Pick(rank=1, code="000001", name="平安银行", screen_score=80, final_score=80),
        Pick(rank=2, code="600000", name="浦发银行", screen_score=70, final_score=70),
    ]

    result = rank_candidates_with_metadata(picks, "", "key", "openai/test", "https://gateway.test/v1")

    assert not result.ranked
    assert result.picks is picks
    assert [pick.llm_score for pick in result.picks] == [None, None]
    assert result.errors == ["LLM request timed out"]


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


def test_rank_candidates_enforces_red_flag_cap_retry_isolation_and_omitted_picks(monkeypatch) -> None:
    from alphasift.ranker import rank_candidates_with_metadata

    # 1. Code enforces llm_score <= 35 when unresolved adverse filing flags appear
    p_bad = Pick(rank=1, code="600001", name="Example", final_score=80.0, screen_score=80.0)
    monkeypatch.setattr(
        "alphasift.ranker._call_llm",
        lambda *_a, **_kw: json.dumps(
            {
                "ranked": [
                    {
                        "code": "600001",
                        "llm_score": 95,
                        "risk_flags": ["unresolved adverse filing"],
                    }
                ]
            }
        ),
    )
    capped = rank_candidates_with_metadata([p_bad], "", "k", "fake/model")
    assert capped.ranked is True
    assert capped.picks[0].llm_score == 35.0
    assert "red_flag_capped" in capped.picks[0].risk_flags

    # 2. Failed low-coverage attempt never mutates fallback picks' llm_score
    picks_fail = [
        Pick(rank=1, code="000001", name="A", final_score=80.0, screen_score=80.0),
        Pick(rank=2, code="000002", name="B", final_score=75.0, screen_score=75.0),
    ]
    call_idx = {"n": 0}

    def low_cov_then_crash(*_a, **_kw):
        call_idx["n"] += 1
        if call_idx["n"] == 1:
            return json.dumps({"ranked": [{"code": "000001", "llm_score": 90}]})
        raise RuntimeError("boom")

    monkeypatch.setattr("alphasift.ranker._call_llm", low_cov_then_crash)
    failed = rank_candidates_with_metadata(picks_fail, "", "k", "fake/model", max_retries=1, min_coverage=0.8)
    assert failed.ranked is False
    assert all(p.llm_score is None for p in failed.picks)

    # 3. Omitted picks never receive synthetic LLM scores
    picks_partial = [
        Pick(rank=1, code="000001", name="A", final_score=80.0, screen_score=80.0),
        Pick(rank=2, code="000002", name="B", final_score=75.0, screen_score=75.0),
        Pick(rank=3, code="000003", name="C", final_score=70.0, screen_score=70.0),
    ]
    monkeypatch.setattr(
        "alphasift.ranker._call_llm",
        lambda *_a, **_kw: json.dumps(
            {
                "ranked": [
                    {"code": "000001", "llm_score": 88},
                    {"code": "000002", "llm_score": 82},
                ]
            }
        ),
    )
    partial = rank_candidates_with_metadata(picks_partial, "", "k", "fake/model", min_coverage=0.6)
    by_code = {p.code: p for p in partial.picks}
    assert by_code["000003"].llm_score is None
    assert by_code["000003"].final_score == 70.0
    assert "llm_omitted" in by_code["000003"].risk_flags


def test_rank_candidates_round6_negated_risk_dsa_news_omitted_cap_and_zero_cov(monkeypatch):
    # 1. Negated risk phrases & benign "市场调查" do NOT trigger red-flag cap
    p_clean = Pick(
        rank=1,
        code="600010",
        name="CleanCorp",
        final_score=80.0,
        screen_score=80.0,
        dsa_analysis_summary="公司公告无立案调查且已解除警示；完成年度市场调查。",
    )
    monkeypatch.setattr(
        "alphasift.ranker._call_llm",
        lambda *_a, **_kw: json.dumps({"ranked": [{"code": "600010", "llm_score": 90}]}),
    )
    res_clean = rank_candidates_with_metadata([p_clean], "", "k", "fake/model")
    assert res_clean.ranked is True
    assert res_clean.picks[0].llm_score == 90.0
    assert "red_flag_capped" not in res_clean.picks[0].risk_flags

    # 2. dsa_news adverse title triggers cap + omitted adverse pick also has final_score capped
    p_news = Pick(
        rank=1,
        code="600011",
        name="NewsRisk",
        final_score=85.0,
        screen_score=85.0,
        dsa_news=[{"title": "公司收到证监会立案调查通知书"}],
    )
    p_omit_risk = Pick(
        rank=2,
        code="600012",
        name="OmitRisk",
        final_score=92.0,
        screen_score=92.0,
        risk_flags=["大股东减持"],
    )
    monkeypatch.setattr(
        "alphasift.ranker._call_llm",
        lambda *_a, **_kw: json.dumps({"ranked": [{"code": "600011", "llm_score": 96}]}),
    )
    res_mixed = rank_candidates_with_metadata(
        [p_news, p_omit_risk],
        "",
        "k",
        "fake/model",
        rank_weight=0.40,
        min_coverage=0.5,
    )
    by_code = {p.code: p for p in res_mixed.picks}
    assert by_code["600011"].llm_score == 35.0
    assert "red_flag_capped" in by_code["600011"].risk_flags
    assert by_code["600012"].llm_score is None
    assert "llm_omitted" in by_code["600012"].risk_flags
    assert "red_flag_capped" in by_code["600012"].risk_flags
    assert by_code["600012"].final_score == 92.0 * 0.6 + 35.0 * 0.4

    # 3. Even with min_coverage=0.0, matched_count == 0 falls back safely (ranked=False)
    p_zero = Pick(rank=1, code="600013", name="ZeroCov", final_score=77.0, screen_score=77.0)
    monkeypatch.setattr(
        "alphasift.ranker._call_llm",
        lambda *_a, **_kw: json.dumps({"ranked": [{"code": "999999", "llm_score": 99}]}),
    )
    res_zero = rank_candidates_with_metadata([p_zero], "", "k", "fake/model", max_retries=0, min_coverage=0.0)
    assert res_zero.ranked is False
    assert res_zero.picks[0].llm_score is None


def test_topic_alignment_fields_do_not_bloat_ranking_prompt():
    base_pick = Pick(rank=1, code="600519", name="贵州茅台", final_score=80.0, screen_score=80.0, industry="白酒")
    enriched_pick = Pick(
        rank=1,
        code="600519",
        name="贵州茅台",
        final_score=80.0,
        screen_score=80.0,
        industry="白酒",
        topic_alignment_status="aligned",
        topic_alignment_role="direct_industry",
        topic_alignment_reason="直接行业命中热点路线: 白酒",
        matched_topics=["白酒"],
        unmatched_topics=["半导体"],
    )
    assert _build_ranking_prompt([enriched_pick], "hints", "ctx") == _build_ranking_prompt(
        [base_pick], "hints", "ctx"
    )
