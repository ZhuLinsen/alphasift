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
