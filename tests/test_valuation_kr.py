import pandas as pd
import pytest

import alphasift.snapshot_yahoo as snapshot_yahoo
from alphasift.valuation_kr import enrich_kr_valuation, parse_naver_number


@pytest.mark.parametrize(
    "raw, expected",
    [("9.68배", 9.68), ("1,234.5배", 1234.5), ("-12.30배", -12.3), ("N/A", None), ("-", None), (None, None)],
)
def test_parse_naver_number(raw, expected):
    assert parse_naver_number(raw) == expected


def test_enrich_fills_only_missing_values_and_reports_failures():
    df = pd.DataFrame(
        {
            "code": ["005930.KS", "247540.KQ", "000660.KS"],
            "pe_ratio": [None, None, 7.0],
            "pb_ratio": [None, None, 1.1],
        }
    )
    seen = []

    def fake_fetch(code):
        seen.append(code)
        if code == "247540":
            raise RuntimeError("HTTP 500")
        return {"per": 9.68, "pbr": 2.51}

    result, errors = enrich_kr_valuation(df, fetch=fake_fetch)

    assert sorted(seen) == ["005930", "247540"]  # 000660 already had both
    assert result.loc[0, ["pe_ratio", "pb_ratio"]].tolist() == [9.68, 2.51]
    assert result.loc[1, ["pe_ratio", "pb_ratio"]].isna().all()
    assert result.loc[2, "pe_ratio"] == 7.0
    assert len(errors) == 1 and "1/2 KR listings" in errors[0] and "HTTP 500" in errors[0]


def _kr_quote(symbol, cap):
    return {
        "symbol": symbol, "longName": symbol, "quoteType": "EQUITY", "regularMarketPrice": 1000.0,
        "regularMarketVolume": 10, "marketCap": cap, "currency": "KRW",
    }


def test_kr_snapshot_gets_naver_valuation(monkeypatch):
    def fake_screen(query, size, offset, sortField, sortAsc):
        sector = [op for op in query.operands if op.operands[0] == "sector"][0].operands[1]
        if sector == "Technology":
            return {"total": 1, "quotes": [_kr_quote("005930.KS", 1e15)]}
        return {"total": 0, "quotes": []}

    monkeypatch.setattr(
        snapshot_yahoo,
        "enrich_kr_valuation",
        lambda df: (df.assign(pe_ratio=9.68, pb_ratio=2.51), ["naver_valuation note"]),
    )

    df = snapshot_yahoo.fetch_yahoo_snapshot("kr", screen=fake_screen)

    assert df.loc[0, ["pe_ratio", "pb_ratio"]].tolist() == [9.68, 2.51]
    assert "naver_valuation note" in df.attrs["source_errors"]
    assert df.attrs["partial"] is False


def test_kr_valuation_can_be_disabled(monkeypatch):
    monkeypatch.setenv("ALPHASIFT_KR_VALUATION", "0")
    monkeypatch.setattr(
        snapshot_yahoo, "enrich_kr_valuation", lambda df: pytest.fail("must not call Naver")
    )

    df = snapshot_yahoo.fetch_yahoo_snapshot(
        "kr",
        screen=lambda *a, **k: {"total": 1, "quotes": [_kr_quote("005930.KS", 1e15)]},
    )

    assert df["pe_ratio"].isna().all()


def test_krx_preferred_shares_are_dropped():
    from alphasift.snapshot_yahoo import _quote_to_row

    assert _quote_to_row(_kr_quote("005930.KS", 1e15), "Technology") is not None
    assert _quote_to_row(_kr_quote("005935.KS", 1e14), "Technology") is None
    assert _quote_to_row(_kr_quote("00088K.KS", 1e12), "Industrials") is None
    assert _quote_to_row(_kr_quote("7203.T", 1e13), "Consumer Cyclical") is not None
