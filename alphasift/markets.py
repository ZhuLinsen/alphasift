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
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


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
    # Yahoo exchange codes to keep; empty means every exchange in the region.
    # The US region is half OTC pink sheets (unsponsored foreign ordinaries
    # like BMWKY), which crowd out listed names under the row cap.
    yahoo_exchanges: tuple[str, ...] = ()
    # A-share conventions (ST names, limit-up boards, EastMoney industries).
    cn_rules: bool = False
    # Local regular-session open (HH:MM). A run created before the open was
    # priced off the previous close, so that day's bar is entirely post-entry.
    session_open: str = "09:30"
    # Local regular-session close (HH:MM). Today's bar only counts as a
    # completed T+N bar once the session has closed.
    session_close: str = "15:00"
    # Index used as the T+N evaluation benchmark. CN uses Tencent's index
    # K-line (Yahoo's 000300.SS history is broken); others use Yahoo.
    benchmark: str = ""
    benchmark_name: str = ""
    # Approximate local units per USD. Only used to express liquidity floors
    # (avg_amount_usd_min) in one currency across markets; a rough rate is
    # enough for a floor, so it is not fetched live.
    usd_rate: float = 1.0


MARKETS: dict[str, MarketSpec] = {
    spec.id: spec
    for spec in (
        MarketSpec(
            "cn", "China A-shares", "CNY", "Asia/Shanghai", cn_rules=True,
            benchmark="sh000300", benchmark_name="CSI 300", usd_rate=7.2,
        ),
        MarketSpec(
            "us", "United States", "USD", "America/New_York", "us", (),
            # Nasdaq GS/GM/CM, NYSE, NYSE American, NYSE Arca, Cboe BZX.
            yahoo_exchanges=("NMS", "NGM", "NCM", "NYQ", "ASE", "PCX", "BTS"),
            universe_min_market_cap=1e9,
            session_close="16:00", benchmark="SPY", benchmark_name="S&P 500 (SPY)",
        ),
        MarketSpec(
            "hk", "Hong Kong", "HKD", "Asia/Hong_Kong", "hk", ("HK",), 8e9,
            session_close="16:00", benchmark="^HSI", benchmark_name="Hang Seng", usd_rate=7.8,
        ),
        MarketSpec(
            "jp", "Japan", "JPY", "Asia/Tokyo", "jp", ("T",), 1.5e11,
            session_open="09:00", session_close="15:30", benchmark="^N225", benchmark_name="Nikkei 225", usd_rate=150.0,
        ),
        MarketSpec(
            "kr", "South Korea", "KRW", "Asia/Seoul", "kr", ("KS", "KQ"), 1.4e12,
            session_open="09:00", session_close="15:30", benchmark="^KS11", benchmark_name="KOSPI", usd_rate=1400.0,
        ),
        MarketSpec(
            "tw", "Taiwan", "TWD", "Asia/Taipei", "tw", ("TW", "TWO"), 3e10,
            session_open="09:00", session_close="13:30", benchmark="^TWII", benchmark_name="TAIEX", usd_rate=30.0,
        ),
        MarketSpec(
            "in", "India", "INR", "Asia/Kolkata", "in", ("NS", "BO"), 8.5e10,
            session_open="09:15", session_close="15:30", benchmark="^NSEI", benchmark_name="Nifty 50", usd_rate=85.0,
        ),
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


# Daily bars are final some time after the close; vendors can lag a little.
_CLOSE_SETTLE_SECONDS = 30 * 60
# A screening batch takes minutes; stop reusing caches shortly before the open
# so candidates processed after it do not mix in pre-open data.
_PRE_OPEN_MARGIN_SECONDS = 15 * 60


def latest_settled_close(market: str, now: datetime | None = None) -> tuple[date, float] | None:
    """Latest session whose close has settled, and seconds since it settled.

    None during the session (and just before the open): today's bar is not
    final, so screening must not reuse cached histories. Weekends step back
    to Friday; exchange holidays are not known here, which only makes reuse
    stricter (a cached history must still reach the computed session date).
    """
    spec = get_market(market)
    tz = ZoneInfo(spec.timezone)
    local = (now or datetime.now(tz)).astimezone(tz)
    open_h, open_m = (int(part) for part in spec.session_open.split(":"))
    close_h, close_m = (int(part) for part in spec.session_close.split(":"))
    day = local.date()
    open_at = datetime.combine(day, time(open_h, open_m), tzinfo=tz)
    if local.weekday() < 5:
        if open_at.timestamp() - _PRE_OPEN_MARGIN_SECONDS <= local.timestamp() < datetime.combine(
            day, time(close_h, close_m), tzinfo=tz
        ).timestamp():
            return None
        if local.timestamp() < open_at.timestamp():
            day -= timedelta(days=1)
    else:
        day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    settled = datetime.combine(day, time(close_h, close_m), tzinfo=tz).timestamp() + _CLOSE_SETTLE_SECONDS
    # Epoch seconds, not wall-clock differences, so DST changes do not skew it.
    elapsed = local.timestamp() - settled
    if elapsed <= 0:
        return None
    return day, elapsed
