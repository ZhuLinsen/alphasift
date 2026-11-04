import pandas as pd
import pytest

import alphasift.snapshot as snapshot
from alphasift.filter import apply_hard_filters
from alphasift.markets import get_market, has_foreign_yahoo_suffix, supported_markets
from alphasift.models import HardFilterConfig
from alphasift.normalize import normalize_code
from alphasift.snapshot_yahoo import YAHOO_SECTORS, fetch_yahoo_snapshot


def test_registry_lists_markets_and_rejects_unknown():
    assert supported_markets() == ["cn", "us", "hk", "jp", "kr", "tw", "in"]
    assert get_market("HK").currency == "HKD"
    with pytest.raises(ValueError, match="Unsupported market"):
        get_market("eu")


@pytest.mark.parametrize(
    "code, expected",
    [
        ("005930.KS", "005930.KS"),
        ("0700.HK", "0700.HK"),
        ("7203.T", "7203.T"),
        ("2330.TWO", "2330.TWO"),
        ("RELIANCE.NS", "RELIANCE.NS"),
        ("AAPL", "AAPL"),
        # A-share suffixes still collapse to the 6-digit code.
        ("600519.SS", "600519"),
        ("000001.SZ", "000001"),
        ("sh600519", "600519"),
    ],
)
def test_normalize_code_keeps_foreign_suffixes(code, expected):
    assert normalize_code(code, allow_ticker=True) == expected


def test_foreign_suffix_detection():
    assert has_foreign_yahoo_suffix("0700.HK")
    assert not has_foreign_yahoo_suffix("600519.SS")
    assert not has_foreign_yahoo_suffix("BRK-B")


def test_exclude_st_only_applies_to_cjk_names():
    df = pd.DataFrame(
        {
            "code": ["000001", "000002", "COST", "STE", "600003"],
            "name": ["平安银行", "*ST金泰", "COST", "STERIS plc", "退市海润"],
            "price": [10.0] * 5,
        }
    )

    result = apply_hard_filters(df, HardFilterConfig(exclude_st=True))

    assert result["code"].tolist() == ["000001", "COST", "STE"]


def _quote(symbol, cap, **extra):
    quote = {
        "symbol": symbol,
        "longName": f"{symbol} Corp",
        "quoteType": "EQUITY",
        "regularMarketPrice": 100.0,
        "regularMarketChangePercent": 1.5,
        "regularMarketVolume": 2_000_000,
        "averageDailyVolume10Day": 1_000_000,
        "sharesOutstanding": 100_000_000,
        "marketCap": cap,
        "trailingPE": 12.0,
        "priceToBook": 1.5,
        "currency": "HKD",
    }
    quote.update(extra)
    return quote


def test_fetch_yahoo_snapshot_tags_sector_pages_and_derives_fields():
    calls = []

    def fake_screen(query, size, offset, sortField, sortAsc):
        sector = [op for op in query.operands if op.operands[0] == "sector"][0].operands[1]
        calls.append((sector, offset))
        if sector == "Financial Services":
            if offset == 0:
                return {"total": 3, "quotes": [_quote("0005.HK", 9e11), _quote("1398.HK", 5e11)]}
            return {"total": 3, "quotes": [_quote("0939.HK", 4e11, trailingPE=None, epsTrailingTwelveMonths=20.0)]}
        if sector == "Technology":
            return {
                "total": 2,
                "quotes": [
                    _quote("0700.HK", 3e12),
                    {"symbol": "2800.HK", "quoteType": "ETF", "regularMarketPrice": 20.0},
                ],
            }
        return {"total": 0, "quotes": []}

    df = fetch_yahoo_snapshot("hk", screen=fake_screen)

    assert df["code"].tolist() == ["0700.HK", "0005.HK", "1398.HK", "0939.HK"]
    assert set(df["industry"]) == {"Technology", "Financial Services"}
    assert ("Financial Services", 2) in calls
    assert len({sector for sector, _ in calls}) == len(YAHOO_SECTORS)
    row = df.set_index("code").loc["0939.HK"]
    assert row["pe_ratio"] == pytest.approx(5.0)  # derived from price / EPS
    assert row["volume_ratio"] == pytest.approx(2.0)
    assert row["turnover_rate"] == pytest.approx(2.0)
    assert row["amount"] == pytest.approx(200_000_000)
    assert df.attrs["snapshot_source"] == "yahoo_screener"
    assert df.attrs["currency"] == "HKD"


def test_fetch_yahoo_snapshot_rejects_cn():
    with pytest.raises(ValueError, match="not served by the Yahoo screener"):
        fetch_yahoo_snapshot("cn", screen=lambda *a, **k: {})


def test_non_cn_snapshot_uses_market_cache_and_falls_back(monkeypatch, tmp_path):
    good = pd.DataFrame(
        [{"code": "7203.T", "name": "Toyota", "price": 3000.0, "industry": "Consumer Cyclical"}]
    )
    good.attrs["snapshot_source"] = "yahoo_screener"
    monkeypatch.setattr(snapshot, "fetch_yahoo_snapshot", lambda market: good.copy())
    cn_cache = tmp_path / "snapshot.last_good.json"

    live = snapshot.fetch_snapshot_with_fallback([], market="jp", fallback_snapshot_path=cn_cache)

    assert live.attrs["market"] == "jp"
    assert (tmp_path / "snapshot.jp.last_good.json").is_file()
    assert not cn_cache.exists()

    def boom(market):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(snapshot, "fetch_yahoo_snapshot", boom)
    cached = snapshot.fetch_snapshot_with_fallback([], market="jp", fallback_snapshot_path=cn_cache)

    assert cached["code"].tolist() == ["7203.T"]
    assert cached.attrs["fallback_used"] is True
    assert "yahoo_screener: rate limited" in cached.attrs["source_errors"]


def test_us_explicit_ticker_list_keeps_legacy_path(monkeypatch):
    legacy = pd.DataFrame([{"code": "AAPL", "name": "Apple", "price": 200.0}])
    monkeypatch.setenv("ALPHASIFT_US_TICKERS", "AAPL")
    monkeypatch.setattr(snapshot, "_fetch_us_legacy_snapshot", lambda: legacy.copy())
    monkeypatch.setattr(
        snapshot, "fetch_yahoo_snapshot", lambda market: pytest.fail("screener must not run")
    )

    df = snapshot.fetch_snapshot_with_fallback([], market="us", fallback_snapshot_path=None)

    assert df["code"].tolist() == ["AAPL"]


def test_yahoo_rows_drop_preferred_and_clear_adr_pb():
    from alphasift.snapshot_yahoo import _quote_to_row

    assert _quote_to_row(_quote("JPM-PC", 1e10, currency="USD"), "Financial Services") is None
    assert _quote_to_row(_quote("BRK-B", 1e12, currency="USD"), "Financial Services") is not None

    adr = _quote_to_row(
        _quote("EC", 3e10, currency="USD", financialCurrency="COP", priceToBook=0.008), "Energy"
    )
    assert adr["pb_ratio"] is None
    assert adr["pe_ratio"] == 12.0

    h_share = _quote_to_row(
        _quote("1398.HK", 2e12, currency="HKD", financialCurrency="CNY", priceToBook=0.59),
        "Financial Services",
    )
    assert h_share["pb_ratio"] == 0.59


def test_industry_map_does_not_cross_match_foreign_codes(tmp_path):
    from alphasift.industry import enrich_industry_concepts

    mapping = tmp_path / "map.csv"
    mapping.write_text("code,industry\n000700,A股行业\n0700.HK,Internet\n", encoding="utf-8")
    df = pd.DataFrame({"code": ["0700.HK", "7203.T", "000700"], "name": ["Tencent", "Toyota", "某A股"]})

    result, _ = enrich_industry_concepts(df, map_files=[mapping])

    assert result["industry"].tolist() == ["Internet", "", "A股行业"]


def test_llm_candidate_identity_keeps_non_cn_tickers():
    from alphasift.context import summarize_candidate_identity

    df = pd.DataFrame({"code": ["AAPL", "0700.HK", "600519"], "name": ["Apple", "Tencent", "贵州茅台"]})

    text = summarize_candidate_identity(df)

    assert "AAPL" in text and "0700.HK" in text and "600519" in text


def test_us_query_restricts_to_listed_exchanges():
    from alphasift.snapshot_yahoo import _sector_query

    us = _sector_query(get_market("us"), "Energy", 1e9)
    hk = _sector_query(get_market("hk"), "Energy", 8e9)

    exchange_ops = [op for op in us.operands if op.operands[0] == "exchange"]
    assert len(exchange_ops) == 1
    assert "PNK" not in exchange_ops[0].operands and "NYQ" in exchange_ops[0].operands
    assert not [op for op in hk.operands if op.operands[0] == "exchange"]
    assert get_market("hk").universe_min_market_cap == 8e9


def test_st_diagnostics_match_filter_for_non_cjk_names():
    from alphasift.filter import hard_filter_rejection_summary, hard_filter_waterfall

    df = pd.DataFrame(
        {"code": ["COST", "STE", "000002"], "name": ["COST", "STERIS plc", "*ST金泰"], "price": [1.0] * 3}
    )
    filters = HardFilterConfig(exclude_st=True)

    assert len(apply_hard_filters(df, filters)) == 2
    assert hard_filter_rejection_summary(df, filters) == ["exclude_st removed 1 (3->2)"]
    step = hard_filter_waterfall(df, filters)[0]
    assert (step["filter"], step["removed"]) == ("exclude_st", 1)


def test_us_ticker_env_reaches_legacy_adapter_as_env_universe(monkeypatch):
    import alphasift.snapshot_us as snapshot_us

    seen = {}

    def fake_fetch(tickers=None, *, universe_source="auto", max_workers=8):
        seen["universe"] = universe_source
        return pd.DataFrame([{"code": "AAPL", "name": "Apple", "price": 200.0}])

    monkeypatch.setenv("ALPHASIFT_US_TICKERS", "AAPL")
    monkeypatch.setattr(snapshot_us, "fetch_us_snapshot", fake_fetch)

    df = snapshot.fetch_snapshot_with_fallback([], market="us", fallback_snapshot_path=None)

    assert seen["universe"] == "env"
    assert df.attrs["snapshot_source"] == "yfinance_tickers"


def test_row_cap_keeps_largest_names_across_all_sectors():
    def fake_screen(query, size, offset, sortField, sortAsc):
        sector = [op for op in query.operands if op.operands[0] == "sector"][0].operands[1]
        if sector == "Basic Materials":
            quotes = [_quote(f"{1000 + i}.HK", 1e10 - i) for i in range(offset + 1, offset + 4)]
            return {"total": 1000, "quotes": quotes}
        if sector == "Utilities":
            return {"total": 1, "quotes": [_quote("0002.HK", 9e11)]}
        return {"total": 0, "quotes": []}

    df = fetch_yahoo_snapshot("hk", screen=fake_screen, max_rows=3)

    assert df["code"].tolist()[0] == "0002.HK"
    assert len(df) == 3


def test_partial_snapshot_does_not_replace_last_good_cache(monkeypatch, tmp_path):
    full = pd.DataFrame([{"code": c, "name": c, "price": 1.0} for c in ("0005.HK", "0700.HK")])
    monkeypatch.setattr(snapshot, "fetch_yahoo_snapshot", lambda market: full.copy())
    cn_cache = tmp_path / "snapshot.last_good.json"
    snapshot.fetch_snapshot_with_fallback([], market="hk", fallback_snapshot_path=cn_cache)
    hk_cache = tmp_path / "snapshot.hk.last_good.json"
    before = hk_cache.read_text(encoding="utf-8")

    partial = full.head(1).copy()
    partial.attrs.update(partial=True, source_errors=["yahoo_screener sector Technology: 429"])
    monkeypatch.setattr(snapshot, "fetch_yahoo_snapshot", lambda market: partial.copy())
    live = snapshot.fetch_snapshot_with_fallback([], market="hk", fallback_snapshot_path=cn_cache)

    assert live["code"].tolist() == ["0005.HK"]
    assert "yahoo_screener sector Technology: 429" in live.attrs["source_errors"]
    assert hk_cache.read_text(encoding="utf-8") == before


def test_fetch_yahoo_quotes_reads_last_close():
    from alphasift.snapshot_yahoo import fetch_yahoo_quotes

    index = pd.date_range("2026-11-02", periods=2)
    data = pd.concat(
        {
            "0700.HK": pd.DataFrame({"Close": [400.0, 410.0]}, index=index),
            "9999.HK": pd.DataFrame({"Close": [float("nan")] * 2}, index=index),
        },
        axis=1,
    )

    quotes = fetch_yahoo_quotes(["0700.hk", "9999.HK"], download=lambda *a, **k: data)

    assert quotes.to_dict("records") == [{"code": "0700.HK", "price": 410.0}]


def test_evaluate_prices_picks_that_left_the_screener_universe(monkeypatch, tmp_path):
    import alphasift.evaluate as evaluate
    from alphasift.config import Config
    from alphasift.models import Pick, ScreenResult
    from alphasift.store import save_screen_result

    save_screen_result(
        ScreenResult(
            strategy="global_value",
            market="hk",
            run_id="hk1",
            picks=[
                Pick(rank=1, code="0005.HK", name="HSBC", final_score=80, screen_score=80, price=100),
                Pick(rank=2, code="1234.HK", name="Small", final_score=70, screen_score=70, price=10),
            ],
        ),
        data_dir=tmp_path,
    )
    universe = pd.DataFrame([{"code": "0005.HK", "price": 110.0}])
    requested = []

    def fake_quotes(symbols):
        requested.append(list(symbols))
        return pd.DataFrame([{"code": "1234.HK", "price": 8.0}])

    monkeypatch.setattr(evaluate, "fetch_snapshot_with_fallback", lambda *a, **k: universe.copy())
    monkeypatch.setattr(evaluate, "fetch_yahoo_quotes", fake_quotes)

    result = evaluate.evaluate_saved_runs(
        config=Config(llm_api_key="", data_dir=tmp_path),
        market="HK",
        cost_bps=0,
        with_price_path=False,
    )

    assert requested == [["1234.HK"]]
    assert result["summary"]["run_count"] == 1
    # 0005.HK +10%, 1234.HK -20% (no longer missing): average -5%.
    assert result["summary"]["average_return_pct"] == -5.0


def test_taiwan_preferred_shares_are_dropped():
    from alphasift.snapshot_yahoo import _quote_to_row

    for symbol in ("2881A.TW", "2891C.TW", "2002A.TW"):
        assert _quote_to_row(_quote(symbol, 5e11, currency="TWD"), "Financial Services") is None
    for symbol in ("2330.TW", "6488.TWO", "910322.TW"):  # common shares and a TDR stay
        assert _quote_to_row(_quote(symbol, 5e11, currency="TWD"), "Technology") is not None


def test_india_keeps_one_listing_per_company_across_nse_and_bse():
    def fake_screen(query, size, offset, sortField, sortAsc):
        sector = [op for op in query.operands if op.operands[0] == "sector"][0].operands[1]
        if sector != "Energy":
            return {"total": 0, "quotes": []}
        quotes = [
            _quote("RELIANCE.BO", 2e13, currency="INR", averageDailyVolume10Day=100_000),
            _quote("RELIANCE.NS", 2e13, currency="INR", averageDailyVolume10Day=5_000_000),
            _quote("ONGC.NS", 3e12, currency="INR", averageDailyVolume10Day=300_000),
            _quote("ONGC.BO", 3e12, currency="INR", averageDailyVolume10Day=900_000),
            # Before the open today's volume is 0 on NSE; the 10-day average decides.
            _quote("TCS.NS", 1e13, currency="INR", regularMarketVolume=0, averageDailyVolume10Day=2_000_000),
            _quote("TCS.BO", 1e13, currency="INR", regularMarketVolume=50_000, averageDailyVolume10Day=40_000),
            _quote("BSEONLY.BO", 1e12, currency="INR"),
        ]
        return {"total": len(quotes), "quotes": quotes}

    df = fetch_yahoo_snapshot("in", screen=fake_screen)

    # The listing with more average traded value is kept, whichever exchange it is on.
    assert sorted(df["code"]) == ["BSEONLY.BO", "ONGC.BO", "RELIANCE.NS", "TCS.NS"]


def test_single_suffix_markets_do_not_collapse_share_classes():
    def fake_screen(query, size, offset, sortField, sortAsc):
        sector = [op for op in query.operands if op.operands[0] == "sector"][0].operands[1]
        if sector != "Industrials":
            return {"total": 0, "quotes": []}
        return {"total": 2, "quotes": [_quote("0019.HK", 3e11), _quote("0087.HK", 5e10)]}

    df = fetch_yahoo_snapshot("hk", screen=fake_screen)

    assert sorted(df["code"]) == ["0019.HK", "0087.HK"]


def test_yahoo_snapshot_adds_average_traded_value_in_usd():
    def fake_screen(query, size, offset, sortField, sortAsc):
        sector = [op for op in query.operands if op.operands[0] == "sector"][0].operands[1]
        if sector != "Technology":
            return {"total": 0, "quotes": []}
        return {"total": 1, "quotes": [_quote("7203.T", 4e13, currency="JPY", averageDailyVolume10Day=30_000)]}

    df = fetch_yahoo_snapshot("jp", screen=fake_screen)

    row = df.iloc[0]
    assert row["avg_amount"] == pytest.approx(100.0 * 30_000)  # 10-day volume, not today's
    assert row["avg_amount_usd"] == pytest.approx(100.0 * 30_000 / get_market("jp").usd_rate)


def test_window_evaluation_prices_picks_that_left_the_screener_universe(monkeypatch, tmp_path):
    import alphasift.evaluate as evaluate
    from alphasift.config import Config
    from alphasift.models import Pick, ScreenResult
    from alphasift.store import save_screen_result

    save_screen_result(
        ScreenResult(
            strategy="global_value",
            market="hk",
            run_id="hk1",
            picks=[Pick(rank=1, code="1234.HK", name="Small", final_score=70, screen_score=70, price=10)],
        ),
        data_dir=tmp_path,
    )
    requested = []

    def fake_quotes(symbols):
        requested.append(list(symbols))
        return pd.DataFrame([{"code": "1234.HK", "price": 8.0}])

    monkeypatch.setattr(
        evaluate, "fetch_snapshot_with_fallback", lambda *a, **k: pd.DataFrame([{"code": "0005.HK", "price": 1.0}])
    )
    monkeypatch.setattr(evaluate, "fetch_yahoo_quotes", fake_quotes)
    monkeypatch.setattr(evaluate, "fetch_daily_history", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(evaluate, "_fetch_benchmark_path", lambda *a, **k: pd.DataFrame())

    evaluate.evaluate_saved_runs_by_windows(
        windows=[5, 20],
        config=Config(llm_api_key="", data_dir=tmp_path),
        market="hk",
        cost_bps=0,
    )

    # Filled once, before the windows share the prefetched snapshot.
    assert requested == [["1234.HK"]]


def test_latest_settled_close_is_none_in_session_and_counts_from_last_close():
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

    from alphasift.markets import latest_settled_close

    sh = ZoneInfo("Asia/Shanghai")
    # Wednesday 2026-11-04.
    assert latest_settled_close("cn", datetime(2026, 11, 4, 10, 0, tzinfo=sh)) is None
    assert latest_settled_close("cn", datetime(2026, 11, 4, 15, 10, tzinfo=sh)) is None  # settling
    assert latest_settled_close("cn", datetime(2026, 11, 4, 16, 30, tzinfo=sh)) == (date(2026, 11, 4), 3600.0)
    # Before Thursday's open: Wednesday's close (settled 15:30) is the latest.
    assert latest_settled_close("cn", datetime(2026, 11, 5, 8, 30, tzinfo=sh)) == (date(2026, 11, 4), 17 * 3600.0)
    # Within 15 minutes of the open a batch could run past it: no reuse.
    assert latest_settled_close("cn", datetime(2026, 11, 5, 9, 20, tzinfo=sh)) is None
    # Saturday and Monday pre-open both count from Friday's close.
    assert latest_settled_close("cn", datetime(2026, 11, 7, 15, 30, tzinfo=sh)) == (date(2026, 11, 6), 24 * 3600.0)
    assert latest_settled_close("cn", datetime(2026, 11, 9, 9, 0, tzinfo=sh)) == (date(2026, 11, 6), (2 * 24 + 17.5) * 3600.0)
    # Other markets use their own clock: 22:20 Shanghai is 09:20 New York, inside the pre-open margin.
    assert latest_settled_close("us", datetime(2026, 11, 4, 22, 20, tzinfo=sh)) is None
    assert latest_settled_close("us", datetime(2026, 11, 4, 20, 0, tzinfo=sh)) == (date(2026, 11, 3), 14.5 * 3600.0)


def test_latest_settled_close_measures_real_time_across_dst():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from alphasift.markets import latest_settled_close

    ny = ZoneInfo("America/New_York")
    # Sunday 2026-03-08 12:00 EDT; Friday 16:30 EST was 42.5 real hours earlier (clocks sprang forward).
    _, elapsed = latest_settled_close("us", datetime(2026, 3, 8, 12, 0, tzinfo=ny))
    assert elapsed == 42.5 * 3600.0
