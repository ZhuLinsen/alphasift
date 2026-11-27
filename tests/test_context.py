import pandas as pd

from alphasift.context import build_llm_context, summarize_candidate_profile, summarize_event_profile


def test_summarize_candidate_profile_includes_factor_leaders():
    df = pd.DataFrame([
        {
            "code": "000001",
            "name": "平安银行",
            "screen_score": 80,
            "factor_value_score": 90,
            "factor_momentum_score": 60,
            "factor_theme_heat_score": 72,
            "industry": "银行",
            "concepts": "低估值,中特估",
            "board_heat_score": 72,
            "board_heat_trend_score": 8,
            "board_heat_persistence_score": 100,
            "board_heat_cooling_score": 0,
            "board_heat_state": "warming",
            "board_heat_summary": "银行:+1.20%:rank=3",
        },
        {
            "code": "600000",
            "name": "浦发银行",
            "screen_score": 75,
            "factor_value_score": 70,
            "factor_momentum_score": 85,
            "factor_theme_heat_score": 55,
            "industry": "银行",
            "concepts": "低估值",
            "board_heat_score": 55,
            "board_heat_summary": "银行:+0.20%:rank=12",
        },
    ])

    summary = summarize_candidate_profile(df)

    assert "候选池结构" in summary
    assert "因子均值" in summary
    assert "价值:000001平安银行" in summary
    assert "动量:600000浦发银行" in summary
    assert "行业分布: 银行2" in summary
    assert "概念线索: 低估值2" in summary
    assert "主题热度" in summary
    assert "板块/主题热度" in summary
    assert "trend=8" in summary
    assert "persist=100" in summary
    assert "state=warming" in summary


def test_build_llm_context_contains_candidate_profile():
    df = pd.DataFrame([
        {
            "code": "000001",
            "name": "平安银行",
            "change_pct": 1.0,
            "amount": 100_000_000,
            "screen_score": 80,
            "factor_value_score": 90,
        }
    ])

    context = build_llm_context(snapshot_df=df, candidate_df=df, max_chars=2000)

    assert "全市场快照" in context
    assert "候选池结构" in context


def test_build_llm_context_includes_strategy_event_profile():
    context = build_llm_context(
        event_profile={
            "preferred_event_tags": ["回购增持", "订单经营"],
            "avoided_event_tags": ["风险:监管"],
            "preferred_announcement_categories": ["业绩"],
            "source_weights": {"announcement": 1.2, "news": 0.5},
        },
        max_chars=2000,
    )

    assert "策略事件偏好" in context
    assert "偏好事件标签: 回购增持，订单经营" in context
    assert "规避事件标签: 风险:监管" in context
    assert "偏好公告类别: 业绩" in context
    assert "来源权重: announcement=1.20" in context


def test_summarize_event_profile_ignores_empty_profile():
    assert summarize_event_profile({}) == ""


def test_build_llm_context_aligns_candidate_context_file_by_code(tmp_path):
    candidate_df = pd.DataFrame([
        {"code": 1.0, "name": "平安银行", "screen_score": 80},
    ])
    context_file = tmp_path / "candidate_context.csv"
    context_file.write_text(
        "code,name,news,fund_flow\n"
        "000001,平安银行,北向资金连续增持,主力净流入\n"
        "600000,浦发银行,不应进入上下文,不应进入上下文\n",
        encoding="utf-8",
    )

    context = build_llm_context(
        candidate_df=candidate_df,
        candidate_context_files=[context_file],
        max_chars=2000,
    )

    assert "候选外部线索" in context
    assert "000001 平安银行" in context
    assert "新闻:北向资金连续增持" in context
    assert "资金流:主力净流入" in context
    assert "600000" not in context


def test_build_llm_context_accepts_collected_candidate_context_rows():
    candidate_df = pd.DataFrame([
        {"code": "000001", "name": "平安银行", "screen_score": 80},
    ])

    context = build_llm_context(
        candidate_df=candidate_df,
        candidate_context_rows=[
            {"code": "000001", "news": "公告落地", "fund_flow": "主力净流入"},
            {"code": "600000", "news": "不相关"},
        ],
        max_chars=2000,
    )

    assert "候选抓取线索" in context
    assert "公告落地" in context
    assert "主力净流入" in context
    assert "600000" not in context


def test_candidate_context_includes_source_confidence_fields():
    candidate_df = pd.DataFrame([
        {"code": "000001", "name": "平安银行", "screen_score": 80},
    ])

    context = build_llm_context(
        candidate_df=candidate_df,
        candidate_context_rows=[
            {
                "code": "000001",
                "context_summary": "新闻:公告落地；资金流:主力净流入",
                "source_count": 2,
                "source_confidence": 0.67,
                "source_weight_score": 0.7,
                "event_tags": ["回购增持"],
                "announcement_categories": ["业绩"],
                "negative_event_flags": ["监管"],
            }
        ],
        max_chars=2000,
    )

    assert "压缩摘要:新闻:公告落地" in context
    assert "来源数:2" in context
    assert "来源置信度:0.67" in context
    assert "来源权重分:0.7" in context
    assert "事件标签:回购增持" in context
    assert "公告类别:业绩" in context
    assert "负面风险:监管" in context


def test_build_llm_context_preserves_candidate_sections_under_budget():
    candidate_df = pd.DataFrame([
        {
            "code": "000001",
            "name": "平安银行",
            "screen_score": 95,
            "industry": "银行",
            "concepts": "低估值",
        },
        {
            "code": "600000",
            "name": "浦发银行",
            "screen_score": 90,
            "industry": "银行",
            "concepts": "中特估",
        },
        {
            "code": "300001",
            "name": "低优先级",
            "screen_score": 50,
            "industry": "其他",
            "concepts": "长文本",
        },
    ])
    degradation: list[str] = []

    context = build_llm_context(
        base_context="宏观背景" * 500,
        candidate_df=candidate_df,
        candidate_context_rows=[
            {
                "code": "000001",
                "context_summary": "强催化 " * 80,
                "news": "高优先级新闻 " * 80,
            },
            {
                "code": "600000",
                "context_summary": "次高优先级线索 " * 80,
            },
            {
                "code": "300001",
                "context_summary": "低优先级线索 " * 120,
            },
        ],
        max_chars=900,
        degradation=degradation,
    )

    assert len(context) <= 900
    assert "候选身份" in context
    assert "000001 平安银行" in context
    assert "screen_score=95" in context
    assert "候选抓取线索" in context
    assert "强催化" in context
    assert "context_trimmed" in context
    assert degradation
    assert degradation[0].startswith("LLM context truncated:")


def test_context_and_event_weights_scrub_nonfinite_and_bool() -> None:
    from alphasift.context import (
        summarize_candidate_identity,
        summarize_candidate_profile,
        summarize_event_profile,
        summarize_snapshot_context,
    )
    from alphasift.pipeline import _event_source_weights

    df = pd.DataFrame([
        {
            "code": "000001",
            "name": "平安银行",
            "change_pct": float("inf"),
            "amount": float("nan"),
            "volume_ratio": True,
            "factor_value_score": float("inf"),
            "screen_score": float("nan"),
            "board_heat_score": float("inf"),
            "industry": "银行",
        },
        {
            "code": "600000",
            "name": "浦发银行",
            "change_pct": 2.5,
            "amount": 5e8,
            "volume_ratio": 2.4,
            "factor_value_score": 82.0,
            "screen_score": 88.5,
            "board_heat_score": 76.0,
            "industry": "银行",
        },
    ])

    snap_txt = summarize_snapshot_context(df, title="测试全市场")
    assert "2.50%" in snap_txt and "500000000" in snap_txt and "100.0%" in snap_txt
    assert "nan" not in snap_txt.lower() and "inf" not in snap_txt.lower()

    prof_txt = summarize_candidate_profile(df)
    assert "价值82.0" in prof_txt and "88.5" in prof_txt and "600000浦发银行:76.0" in prof_txt
    assert "nan" not in prof_txt.lower() and "inf" not in prof_txt.lower()

    id_txt = summarize_candidate_identity(df, limit=True)  # type: ignore[arg-type]
    assert "000001 平安银行" in id_txt and "600000 浦发银行" in id_txt
    assert "nan" not in id_txt.lower() and "inf" not in id_txt.lower()

    ev_txt = summarize_event_profile({
        "source_weights": {"eastmoney": 1.5, "bad_nan": float("nan"), "bad_inf": float("inf"), "bad_bool": True},
    })
    assert "eastmoney=1.50" in ev_txt
    assert "bad_" not in ev_txt and "nan" not in ev_txt.lower() and "inf" not in ev_txt.lower()

    assert _event_source_weights({
        "source_weights": {"eastmoney": 1.5, "bad_nan": float("nan"), "bad_inf": float("inf"), "bad_bool": True},
    }) == {"eastmoney": 1.5}


def test_context_handles_duplicate_index_null_names_and_bad_max_chars():
    from alphasift.context import build_llm_context, summarize_candidate_profile, summarize_snapshot_context

    dup_df = pd.DataFrame(
        [
            {
                "code": "000001",
                "name": float("nan"),
                "change_pct": 1.0,
                "factor_value_score": 60.0,
                "board_heat_score": 55.0,
                "industry": "银行",
            },
            {
                "code": "600000",
                "name": pd.NA,
                "change_pct": 3.5,
                "factor_value_score": 85.0,
                "board_heat_score": 82.0,
                "industry": "银行",
            },
        ],
        index=[0, 0],
    )
    snap = summarize_snapshot_context(dup_df, title="重复索引")
    prof = summarize_candidate_profile(dup_df)
    assert "600000(3.50%)" in snap and "000001(1.00%)" in snap
    assert "600000(85.0)" in prof and "600000:82.0" in prof
    assert "nan" not in (snap + prof).lower() and "<na>" not in (snap + prof).lower()

    assert build_llm_context(base_context="市场平稳" * 20, max_chars=-5) == ""
    assert build_llm_context(base_context="市场平稳" * 20, max_chars=0) == ""
    assert "市场平稳" in build_llm_context(base_context="市场平稳" * 20, max_chars=True)  # type: ignore[arg-type]
    assert "市场平稳" in build_llm_context(base_context="市场平稳" * 20, max_chars=float("nan"))  # type: ignore[arg-type]
