from pathlib import Path

from alphasift.config import Config
from alphasift.daily_report import IM_CARD_MAX_CHARS
from alphasift.market_digest import (
    _top_picks_for_market,
    build_markets_digest,
    load_multi_market_runs,
    render_market_digest_im_card,
)
from alphasift.models import Pick, ScreenResult
from alphasift.store import save_screen_result


def _make_run(
    *,
    run_id: str,
    strategy: str,
    market: str,
    track: str = "rules",
    created_at: str = "2026-11-20T22:00:00Z",
    picks: list[Pick] | None = None,
) -> ScreenResult:
    return ScreenResult(
        strategy=strategy,
        market=market,
        run_id=run_id,
        track=track,
        llm_ranked=(track == "ai"),
        created_at=created_at,
        snapshot_count=500,
        after_filter_count=20,
        picks=picks or [],
    )


def test_load_multi_market_runs_dedup_corrupted_empty_and_missing_created_at(tmp_path: Path) -> None:
    cfg = Config(data_dir=tmp_path)

    # Non-existent runs dir returns empty lists preserving deduplicated market order
    assert load_multi_market_runs(cfg, markets=["us", "US", "hk"]) == {"us": [], "hk": []}

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    # Corrupted JSON is silently ignored
    (runs_dir / "broken.json").write_text("{not valid json", encoding="utf-8")

    # Earlier and later run for same (strategy, track) on same settled US session (2026-11-20)
    save_screen_result(
        _make_run(
            run_id="r_old",
            strategy="us_momentum_quality",
            market="us",
            track="rules",
            created_at="2026-11-20T21:30:00Z",
            picks=[Pick(rank=1, code="OLD1", name="OldCorp", final_score=70.0, screen_score=70.0)],
        ),
        data_dir=cfg.data_dir,
    )
    save_screen_result(
        _make_run(
            run_id="r_new",
            strategy="us_momentum_quality",
            market="us",
            track="rules",
            created_at="2026-11-20T22:15:00Z",
            picks=[Pick(rank=1, code="AAPL", name="Apple", final_score=91.0, screen_score=91.0)],
        ),
        data_dir=cfg.data_dir,
    )
    # AI track on same date kept alongside rules track (sorted rules before ai)
    save_screen_result(
        _make_run(
            run_id="r_ai",
            strategy="us_momentum_quality",
            market="us",
            track="ai",
            created_at="2026-11-20T22:20:00Z",
            picks=[Pick(rank=1, code="AAPL", name="Apple", final_score=93.0, screen_score=91.0)],
        ),
        data_dir=cfg.data_dir,
    )
    # Previous day run excluded when latest is 2026-11-20, included when filtered to 2026-11-19
    save_screen_result(
        _make_run(
            run_id="r_prev",
            strategy="global_value",
            market="us",
            track="rules",
            created_at="2026-11-19T22:00:00Z",
            picks=[Pick(rank=1, code="MSFT", name="Microsoft", final_score=85.0, screen_score=85.0)],
        ),
        data_dir=cfg.data_dir,
    )
    # Missing created_at does not raise ValueError: max() arg is an empty sequence
    save_screen_result(
        _make_run(
            run_id="r_empty_ts",
            strategy="global_value",
            market="hk",
            track="rules",
            created_at="",
            picks=[Pick(rank=1, code="00700", name="Tencent", final_score=88.0, screen_score=88.0)],
        ),
        data_dir=cfg.data_dir,
    )

    loaded = load_multi_market_runs(cfg, markets=["us", "US", "hk"])
    assert list(loaded.keys()) == ["us", "hk"]
    assert [(r.run_id, r.track) for r in loaded["us"]] == [("r_new", "rules"), ("r_ai", "ai")]
    assert [r.run_id for r in loaded["hk"]] == ["r_empty_ts"]

    filtered = load_multi_market_runs(cfg, markets=["us"], trade_date="2026-11-19")
    assert [r.run_id for r in filtered["us"]] == ["r_prev"]


def test_top_picks_for_market_consensus_ranking_and_tiebreak() -> None:
    entries = [
        {
            "strategy": "strat_b",
            "picks": [
                {"code": "NVDA", "name": "NVIDIA", "final_score": 95.0},
                {"code": "MSFT", "name": "Microsoft", "final_score": 82.0, "price": 410.0},
                {"code": "AAA", "name": "Alpha", "final_score": 82.0},
                {"code": "C1", "name": "C1", "final_score": 60.0},
                {"code": "C2", "name": "C2", "final_score": 59.0},
                {"code": "C3", "name": "C3", "final_score": 58.0},
                {"code": "C4", "name": "C4", "final_score": 57.0},
            ],
        },
        {
            "strategy": "strat_a",
            "picks": [
                {"code": "MSFT", "name": "Microsoft", "final_score": 84.0, "pe_ratio": 31.2, "ranking_reason": "Cash cow"},
                {"code": "AAA", "name": "Alpha", "final_score": 84.0},
            ],
        },
    ]
    top = _top_picks_for_market(entries, display_names={"strat_a": "A", "strat_b": "B"})
    assert len(top) == 6
    # 2-strategy consensus (AAA & MSFT) rank ahead of single-strategy 95.0 NVDA; tie broken by code ascending
    assert [row["code"] for row in top[:3]] == ["AAA", "MSFT", "NVDA"]
    assert top[1]["strategy_count"] == 2
    assert top[1]["avg_final_score"] == 83.0
    assert top[1]["price"] == 410.0
    assert top[1]["pe_ratio"] == 31.2
    assert top[1]["ranking_reason"] == "Cash cow"


def test_build_markets_digest_with_news_success_and_graceful_degradation(tmp_path: Path) -> None:
    cfg = Config(data_dir=tmp_path)
    runs_by_mkt = {
        "us": [
            _make_run(
                run_id="us1",
                strategy="us_momentum_quality",
                market="us",
                created_at="2026-11-20T22:00:00Z",
                picks=[Pick(rank=1, code="AAPL", name="Apple Inc", final_score=90.5, screen_score=90.5)],
            )
        ],
        "hk": [],
    }

    digest_ok = build_markets_digest(
        runs_by_mkt,
        markets=["us", "US", "hk"],
        detail_url="https://alphasift.zhulinsen.tech/",
        include_news=True,
        config=cfg,
        regional_news_collector=lambda mkts, limit=4: (
            [{"title": "US & HK equities close mixed ahead of macro print", "source": "StubWire"}],
            ["stub:regional"],
        ),
    )
    assert digest_ok["object"] == "MarketDigest"
    assert digest_ok["markets"] == ["us", "hk"]
    assert digest_ok["market_news"]["sources"] == ["stub:regional"]
    assert digest_ok["market_news"]["errors"] == []
    assert "**市场快讯**：US & HK equities" in digest_ok["im_card_markdown"]
    assert digest_ok["im_card_chars"] <= IM_CARD_MAX_CHARS
    assert digest_ok["degradation"] == ["No saved runs found for market=hk"]

    def _boom(*_args, **_kwargs):
        raise RuntimeError("upstream timeout")

    digest_err = build_markets_digest(
        runs_by_mkt,
        markets=["us"],
        include_news=True,
        config=cfg,
        regional_news_collector=_boom,
    )
    assert digest_err["market_news"]["items"] == []
    assert digest_err["market_news"]["errors"] == ["regional news skipped: upstream timeout"]


def test_render_market_digest_im_card_empty_sections_and_none_score() -> None:
    empty_card = render_market_digest_im_card({"trade_date": "2026-11-20", "market_sections": []})
    assert "暂无已保存的策略运行记录" in empty_card
    assert len(empty_card) <= IM_CARD_MAX_CHARS

    none_score_card = render_market_digest_im_card(
        {
            "trade_date": "2026-11-20",
            "market_sections": [
                {
                    "market": "us",
                    "market_name": "美股",
                    "trade_date": "2026-11-20",
                    "strategy_count": 1,
                    "top_picks": [{"code": "NVDA", "name": "NVIDIA", "avg_final_score": None}],
                }
            ],
        },
        max_chars=400,
    )
    assert "NVDA NVIDIA(0.0分)" in none_score_card
    assert len(none_score_card) <= 400


def test_market_digest_ignores_nonfinite_scores_and_preserves_valid_sort(tmp_path: Path) -> None:
    import json
    from alphasift.jsonutil import dumps_strict_json

    cfg = Config(data_dir=tmp_path)
    runs_by_mkt = {
        "us": [
            _make_run(
                run_id="us_nan",
                strategy="us_momentum_quality",
                market="us",
                created_at="2026-11-20T22:00:00Z",
                picks=[
                    Pick(
                        rank=1,
                        code="NANC",
                        name="NanCorp",
                        final_score=float("nan"),
                        screen_score=50.0,
                        price=float("inf"),
                    ),
                    Pick(
                        rank=2,
                        code="AAPL",
                        name="Apple",
                        final_score=88.5,
                        screen_score=88.5,
                        price=190.0,
                    ),
                ],
            )
        ]
    }
    digest = build_markets_digest(runs_by_mkt, markets=["us"], config=cfg)
    top = digest["market_sections"][0]["top_picks"]
    assert [p["code"] for p in top] == ["AAPL", "NANC"]
    assert top[1]["avg_final_score"] == 0.0
    assert top[1]["price"] is None
    assert "nan分" not in digest["im_card_markdown"].lower()
    assert "NANC NanCorp(0.0分)" in digest["im_card_markdown"]

    def _reject_constant(token: str) -> None:
        raise AssertionError(f"Invalid JSON constant: {token}")

    json.loads(dumps_strict_json(digest), parse_constant=_reject_constant)


def test_market_digest_handles_mixed_offsets_na_strings_and_malformed_sections(tmp_path: Path) -> None:
    cfg = Config(data_dir=tmp_path)
    # Chronologically 2026-11-20T22:00:00-05:00 (= 2026-11-21T03:00:00Z) is LATER than 2026-11-20T22:30:00Z
    save_screen_result(
        _make_run(
            run_id="r_z",
            strategy="us_momentum_quality",
            market="us",
            track="rules",
            created_at="2026-11-20T22:30:00Z",
            picks=[Pick(rank=1, code="OLD", name="OlderUTC", final_score=60.0, screen_score=60.0)],
        ),
        data_dir=cfg.data_dir,
    )
    save_screen_result(
        _make_run(
            run_id="r_offset_newer",
            strategy="us_momentum_quality",
            market="us",
            track="rules",
            created_at="2026-11-20T22:00:00-05:00",
            picks=[Pick(rank=1, code="AAPL", name="Apple", final_score=92.0, screen_score=92.0)],
        ),
        data_dir=cfg.data_dir,
    )

    loaded = load_multi_market_runs(cfg, markets=[None, " us ", ""], trade_date="  ")  # type: ignore[list-item]
    assert list(loaded.keys()) == ["us"]
    assert [r.run_id for r in loaded["us"]] == ["r_offset_newer"]

    # _top_picks_for_market ignores non-dict entries and scrubs float('nan')/'NaN' strings
    top = _top_picks_for_market(
        [
            "not-a-dict",  # type: ignore[list-item]
            {
                "strategy": "strat_a",
                "picks": [
                    "bad-pick",  # type: ignore[list-item]
                    {"code": float("nan"), "name": "BadCode"},
                    {"code": "MSFT", "name": float("nan"), "industry": "nan", "ranking_reason": "null", "final_score": 80.0},
                ],
            },
            {
                "strategy": "strat_b",
                "picks": [
                    {"code": "MSFT", "name": "Microsoft", "industry": "Software", "ranking_reason": "Cloud growth", "final_score": 84.0},
                ],
            },
        ],
        display_names={"strat_a": "A", "strat_b": "B"},
    )
    assert len(top) == 1
    assert top[0]["code"] == "MSFT"
    assert top[0]["name"] == "Microsoft"
    assert top[0]["industry"] == "Software"
    assert top[0]["ranking_reason"] == "Cloud growth"

    # Malformed market_news item or empty/nan trade_date should not crash IM card rendering
    card = render_market_digest_im_card({
        "trade_date": None,
        "market_sections": [
            "bad-section",
            {
                "market": "us",
                "market_name": "美股",
                "trade_date": None,
                "strategy_count": 1,
                "top_picks": [
                    "bad-pick",
                    {"code": None, "name": "Ghost"},
                    {"code": "AAPL", "name": float("nan"), "avg_final_score": 90.0},
                ],
            },
        ],
        "market_news": {"items": ["not-a-dict"]},
    })
    assert "AlphaSift 全球市场盘后精选 (-)" in card
    assert "AAPL(90.0分)" in card
    assert "市场快讯" not in card
    assert "nan" not in card.lower()
