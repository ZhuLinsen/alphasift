# -*- coding: utf-8 -*-
"""Market registry: what AlphaSift needs to know about each supported market.

China A-shares keep their dedicated source chain (sina / efinance / akshare /
EastMoney / Tushare). Every other market is served by the Yahoo Finance
screener, which works from overseas servers and CI runners and returns price,
market cap, PE/PB and currency for a whole region in a few requests.

Codes for non-CN markets are Yahoo symbols (``AAPL``, ``0700.HK``,
``7203.T``, ``005930.KS``). They are already unique across markets, so no
extra namespace prefix is needed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketSpec:
    id: str
    name: str
    currency: str
    timezone: str
    # Yahoo screener region code; None means the market has its own chain.
    yahoo_region: str | None = None
    # Yahoo symbol suffixes used by this market's listings.
    yahoo_suffixes: tuple[str, ...] = ()
    # Universe floor in local currency, roughly USD 1B. It keeps the screener
    # pull small and liquid; strategies can filter further.
    universe_min_market_cap: float = 0.0
    # A-share conventions (ST names, limit-up boards, EastMoney industries).
    cn_rules: bool = False


MARKETS: dict[str, MarketSpec] = {
    spec.id: spec
    for spec in (
        MarketSpec("cn", "China A-shares", "CNY", "Asia/Shanghai", cn_rules=True),
        MarketSpec("us", "United States", "USD", "America/New_York", "us", (), 1e9),
        MarketSpec("hk", "Hong Kong", "HKD", "Asia/Hong_Kong", "hk", ("HK",), 8e9),
        MarketSpec("jp", "Japan", "JPY", "Asia/Tokyo", "jp", ("T",), 1.5e11),
        MarketSpec("kr", "South Korea", "KRW", "Asia/Seoul", "kr", ("KS", "KQ"), 1.4e12),
        MarketSpec("tw", "Taiwan", "TWD", "Asia/Taipei", "tw", ("TW", "TWO"), 3e10),
        MarketSpec("in", "India", "INR", "Asia/Kolkata", "in", ("NS", "BO"), 8.5e10),
    )
}

# Suffixes that mark a non-CN Yahoo listing. A-share Yahoo/vendor suffixes
# (.SS/.SH/.SZ/.BJ) are deliberately absent so they still normalize to 6 digits.
FOREIGN_YAHOO_SUFFIXES: frozenset[str] = frozenset(
    suffix for spec in MARKETS.values() for suffix in spec.yahoo_suffixes
)


def supported_markets() -> list[str]:
    return list(MARKETS)


def get_market(market: str) -> MarketSpec:
    key = (market or "").strip().lower()
    try:
        return MARKETS[key]
    except KeyError:
        raise ValueError(
            f"Unsupported market: {market!r} (supported: {', '.join(MARKETS)})"
        ) from None


def has_foreign_yahoo_suffix(code: str) -> bool:
    """True for symbols like ``0700.HK`` or ``005930.KS`` that must keep their suffix."""
    head, sep, suffix = (code or "").rpartition(".")
    return bool(sep and head and suffix.upper() in FOREIGN_YAHOO_SUFFIXES)
