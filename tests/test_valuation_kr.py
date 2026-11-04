import pandas as pd
import pytest

import alphasift.snapshot_yahoo as snapshot_yahoo
from alphasift.valuation_kr import enrich_kr_valuation, parse_naver_number


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("9.68배", 9.68), ("1,234.5배", 1234.5), ("-12.30배", -12.3), ("0.00배", None),
        ("N/A", None), ("-", None), (None, None), (",", None), ("2026.03 기준 9.68배", None),
    ],
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
        lambda df, **kwargs: (df.assign(pe_ratio=9.68, pb_ratio=2.51), ["naver_valuation note"]),
    )

    df = snapshot_yahoo.fetch_yahoo_snapshot("kr", screen=fake_screen)

    assert df.loc[0, ["pe_ratio", "pb_ratio"]].tolist() == [9.68, 2.51]
    assert "naver_valuation note" in df.attrs["source_errors"]
    assert df.attrs["partial"] is False


def test_kr_valuation_can_be_disabled(monkeypatch):
    monkeypatch.setenv("ALPHASIFT_KR_VALUATION", "0")
    monkeypatch.setattr(
        snapshot_yahoo, "enrich_kr_valuation", lambda df, **kwargs: pytest.fail("must not call Naver")
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


def test_budget_bounds_slow_naver_requests():
    import threading
    import time

    release = threading.Event()

    def slow_fetch(code):
        if code == "000660":
            release.wait(5)
        return {"per": 5.0, "pbr": 0.5}

    df = pd.DataFrame({"code": ["005930.KS", "000660.KS"], "pe_ratio": [None, None], "pb_ratio": [None, None]})
    started = time.monotonic()
    try:
        result, errors = enrich_kr_valuation(df, fetch=slow_fetch, budget_seconds=0.3)
    finally:
        release.set()

    assert time.monotonic() - started < 2
    assert result.loc[0, "pe_ratio"] == 5.0
    assert pd.isna(result.loc[1, "pe_ratio"])
    assert any("budget" in item and "1 listings" in item for item in errors)


def test_low_valuation_coverage_marks_snapshot_partial(monkeypatch):
    def unvalued(df, **kwargs):
        out = df.copy()
        out.attrs["valuation_coverage"] = 0.1
        return out, ["naver_valuation failed for 9/10 KR listings"]

    monkeypatch.setattr(snapshot_yahoo, "enrich_kr_valuation", unvalued)

    df = snapshot_yahoo.fetch_yahoo_snapshot(
        "kr",
        screen=lambda *a, **k: {"total": 1, "quotes": [_kr_quote("005930.KS", 1e15)]},
    )

    assert df.attrs["partial"] is True  # keeps the valued last-good cache


def test_fetch_naver_valuation_parses_total_infos():
    from alphasift.valuation_kr import fetch_naver_valuation

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"totalInfos": [
                {"code": "per", "value": "9.68배"},
                {"code": "pbr", "value": "N/A"},
                "junk",
            ]}

    class Session:
        def get(self, url, **kwargs):
            assert url.endswith("/005930/integration")
            return Response()

    assert fetch_naver_valuation("005930", session=Session()) == {"per": 9.68, "pbr": None}

    class BadSession(Session):
        def get(self, url, **kwargs):
            response = Response()
            response.json = lambda: {"code": "StockConflict"}
            return response

    with pytest.raises(ValueError, match="unexpected Naver payload"):
        fetch_naver_valuation("999999", session=BadSession())


def test_enrich_keeps_existing_pe_when_only_pb_is_missing():
    df = pd.DataFrame({"code": ["005930.KS"], "pe_ratio": [7.0], "pb_ratio": [None]})

    result, errors = enrich_kr_valuation(df, fetch=lambda code: {"per": 9.68, "pbr": 2.51})

    assert result.loc[0, ["pe_ratio", "pb_ratio"]].tolist() == [7.0, 2.51]
    assert errors == []
