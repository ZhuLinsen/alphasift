from alphasift.models import Pick
from alphasift.sentiment import apply_sentiment_overlay, assess_pick_sentiment


def _pick(code: str = "000001", *, final_score: float = 80.0) -> Pick:
    return Pick(
        rank=1,
        code=code,
        name="示例股份",
        final_score=final_score,
        screen_score=final_score,
    )


def test_sentiment_combines_announcement_and_fund_flow_evidence():
    assessment = assess_pick_sentiment(
        _pick(),
        context_row={
            "announcement": "2026-07-21 公司公告回购方案并披露业绩预增",
            "fund_flow": "2026-07-22 主力净流入-净额=1200万，主力净流入-净占比=3.5%",
        },
    )

    assert assessment["available"] is True
    assert assessment["score"] > 50
    assert assessment["source_count"] == 2
    assert assessment["confidence"] > 0.6
    assert "回购增持" in assessment["positive_events"]
    assert "主力净流入" in assessment["positive_events"]
    assert assessment["as_of"] == "2026-07-22"


def test_sentiment_ignores_negated_negative_keywords():
    assessment = assess_pick_sentiment(
        _pick(),
        context_row={
            "announcement": "公司承诺不减持，未受到监管处罚，相关调查传闻不属实",
        },
    )

    assert assessment["available"] is False
    assert assessment["score"] is None
    assert assessment["negative_events"] == []


def test_sentiment_detects_negative_events_and_outflow():
    assessment = assess_pick_sentiment(
        _pick(),
        context_row={
            "announcement": "2026-07-22 股东拟减持，公司收到监管问询函",
            "fund_flow": "主力净流入-净额=-800万，主力净流入-净占比=-2.4%",
        },
    )

    assert assessment["available"] is True
    assert assessment["score"] < 50
    assert "减持" in assessment["negative_events"]
    assert "监管" in assessment["negative_events"]
    assert "主力净流出" in assessment["negative_events"]


def test_sentiment_reads_dsa_news_capital_flow_and_quote():
    pick = _pick()
    pick.dsa_context = {
        "news": {
            "results": [
                {
                    "title": "公司获得重大订单",
                    "snippet": "净利润增长超预期",
                    "published_date": "2026-07-22",
                }
            ]
        },
        "fundamentals": {
            "capital_flow": {
                "status": "available",
                "data": {"main_net_inflow": 20000000},
            }
        },
        "quote": {"change_pct": 3.2},
    }

    assessment = assess_pick_sentiment(pick)

    assert assessment["available"] is True
    assert assessment["source_count"] == 3
    assert assessment["score"] > 50
    assert "订单催化" in assessment["positive_events"]


def test_sentiment_overlay_preserves_technical_score_and_applies_bounded_delta():
    positive = _pick("000001", final_score=80.0)
    negative = _pick("000002", final_score=81.0)
    rows = [
        {
            "code": "000001",
            "announcement": "公司公告回购并披露业绩预增",
            "fund_flow": "主力净流入-净额=1200万",
        },
        {
            "code": "000002",
            "announcement": "股东拟减持并收到监管问询函",
            "fund_flow": "主力净流入-净额=-1200万",
        },
    ]

    picks, notes = apply_sentiment_overlay(
        [negative, positive],
        context_rows=rows,
        weight=0.1,
        min_confidence=0.45,
        max_delta=3.0,
    )

    assert positive.screen_score == 80.0
    assert negative.screen_score == 81.0
    assert 0 < positive.sentiment_score_delta <= 3.0
    assert -3.0 <= negative.sentiment_score_delta < 0
    assert picks[0].code == "000001"
    assert [pick.rank for pick in picks] == [1, 2]
    assert "applied=2" in notes[0]


def test_sentiment_overlay_does_not_score_missing_evidence():
    pick = _pick()

    picks, _ = apply_sentiment_overlay([pick], weight=0.1)

    assert picks[0].sentiment_available is False
    assert picks[0].sentiment_score is None
    assert picks[0].sentiment_score_delta == 0.0
    assert picks[0].final_score == 80.0
