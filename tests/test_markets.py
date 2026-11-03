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
