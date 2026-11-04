import pytest

from alphasift.config import Config
from alphasift.pipeline import screen


def test_screen_rejects_unknown_market():
    with pytest.raises(ValueError, match="Unsupported market"):
        screen("dual_low", market="xx", config=Config())


@pytest.mark.parametrize("market", ["us", "hk", "jp", "kr", "tw", "in"])
def test_screen_enforces_strategy_market_scope(market):
    # Supported markets pass the market gate, but cn-scoped strategies reject them.
    with pytest.raises(ValueError, match="does not support market"):
        screen("dual_low", market=market, config=Config())


def _hk_snapshot():
    import pandas as pd

    return pd.DataFrame(
        [
            {
                "code": code,
                "name": name,
                "price": 10.0,
                "change_pct": 0.5,
                "amount": 5e8,
                "avg_amount_usd": avg_usd,
                "total_mv": 1e11,
                "circ_mv": 1e11,
                "pe_ratio": 8.0,
                "pb_ratio": 0.8,
                "industry": "Financial Services",
            }
            for code, name, avg_usd in [
                ("0005.HK", "HSBC", 6e7),
                ("0939.HK", "CCB", 4e7),
                ("1398.HK", "ICBC", 5e7),
                ("9999.HK", "Thin", 3e5),
            ]
        ]
    )


def test_non_cn_screen_skips_a_share_industry_provider(monkeypatch):
    calls = []

    def fake_enrich(df, **kwargs):
        calls.append(kwargs)
        return df, []

    monkeypatch.setattr(
        "alphasift.pipeline.fetch_snapshot_with_fallback", lambda *a, **k: _hk_snapshot()
    )
    monkeypatch.setattr("alphasift.pipeline.enrich_industry_concepts", fake_enrich)
    monkeypatch.setattr(
        "alphasift.pipeline.enrich_daily_features", lambda df, **k: (df, [])
    )

    result = screen(
        "global_value",
        market="hk",
        use_llm=False,
        industry_provider="akshare",
        config=Config(),
    )

    assert calls == []
    assert any("Industry provider akshare skipped" in item for item in result.degradation)
    codes = {pick.code for pick in result.picks}
    assert codes and codes <= {"0005.HK", "0939.HK", "1398.HK"}
    # global_value's USD 1M average traded value floor drops the thin listing.
    assert "9999.HK" not in codes
    assert result.after_filter_count == 3
