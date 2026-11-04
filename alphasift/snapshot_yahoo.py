# -*- coding: utf-8 -*-
"""Region-wide equity snapshot from the Yahoo Finance screener.

One query per sector tags every row with its sector, which portfolio
diversity control needs. A region above the market's universe floor is
typically 5-30 pages of 250 rows at ~0.3s each.

Field notes:
- ``amount`` is price x volume, an estimate of traded value.
- ``volume_ratio`` is today's volume over the 10-day average. During the
  session it reflects a partial day, like the A-share intraday volume ratio.
- ``circ_mv`` is total market cap; Yahoo has no free-float cap here.
- PE/PB are derived from trailing EPS and book value per share when Yahoo
  omits the ratios. South Korea has neither; KR PE/PB come from Naver
  Finance instead (``alphasift.valuation_kr``).
- Preferred shares are dropped. PB below 0.1 on a listing whose reporting
  currency differs from its trading currency (some ADRs) is cleared as an
  unconverted-currency artifact.
"""

from __future__ import annotations

import logging
import os
import re
import time

import pandas as pd

from alphasift.markets import MarketSpec, get_market
from alphasift.source_guard import parse_source_timeout_seconds
from alphasift.valuation_kr import enrich_kr_valuation, kr_valuation_enabled

logger = logging.getLogger(__name__)

YAHOO_SECTORS = (
    "Basic Materials",
    "Communication Services",
    "Consumer Cyclical",
    "Consumer Defensive",
    "Energy",
    "Financial Services",
    "Healthcare",
    "Industrials",
    "Real Estate",
    "Technology",
    "Utilities",
)
_PREFERRED_SYMBOL_RE = re.compile(r"-P[A-Z]{0,2}$")
_CROSS_CURRENCY_MIN_PB = 0.1
_PAGE_SIZE = 250
_PAGE_PAUSE_SECONDS = 0.2
_DEFAULT_MAX_ROWS = 4000
_DEFAULT_BUDGET_SECONDS = 90.0
_MIN_VALUATION_COVERAGE = 0.8


def fetch_yahoo_snapshot(
    market: str,
    *,
    min_market_cap: float | None = None,
    max_rows: int | None = None,
    screen=None,
) -> pd.DataFrame:
    """Return the standard snapshot schema for a Yahoo-screener market."""
    spec = get_market(market)
    if not spec.yahoo_region:
        raise ValueError(f"Market {spec.id!r} is not served by the Yahoo screener")
    if screen is None:
        import yfinance as yf

        screen = yf.screen

    floor = spec.universe_min_market_cap if min_market_cap is None else float(min_market_cap)
    limit = max_rows if max_rows is not None else _int_env("ALPHASIFT_YAHOO_MAX_ROWS", _DEFAULT_MAX_ROWS)
    budget = parse_source_timeout_seconds(
        "ALPHASIFT_YAHOO_SNAPSHOT_BUDGET_SEC", default=_DEFAULT_BUDGET_SECONDS
    )
    started = time.monotonic()

    rows: dict[str, dict[str, object]] = {}
    errors: list[str] = []
    timed_out = False
    for sector_index, sector in enumerate(YAHOO_SECTORS):
        # Each sector is paged by market cap, up to ``limit`` rows of its own.
        # The global top-``limit`` is then cut after all sectors are in, so a
        # large early sector cannot crowd out Technology or Utilities.
        offset = 0
        while offset < limit:
            if budget is not None and time.monotonic() - started > budget:
                # Keep what was fetched, marked partial: the caller then uses
                # it without replacing the complete last-good cache, instead of
                # dropping it and switching to a different universe.
                skipped = ", ".join(YAHOO_SECTORS[sector_index:])
                errors.append(
                    f"budget {budget:.0f}s exceeded after {len(rows)} rows; not fetched: {skipped}"
                )
                timed_out = True
                break
            try:
                payload = screen(
                    _sector_query(spec, sector, floor),
                    size=_PAGE_SIZE,
                    offset=offset,
                    sortField="intradaymarketcap",
                    sortAsc=False,
                )
            except Exception as exc:  # noqa: BLE001 - one sector failing should not drop the rest
                errors.append(f"{sector}: {exc}")
                break
            quotes = (payload or {}).get("quotes") or []
            for quote in quotes:
                row = _quote_to_row(quote, sector)
                if row is not None:
                    rows.setdefault(str(row["code"]), row)
            offset += len(quotes)
            total = int((payload or {}).get("total") or 0)
            if not quotes or offset >= total:
                break
            time.sleep(_PAGE_PAUSE_SECONDS)
        if timed_out:
            break

    if not rows:
        detail = "; ".join(errors[:3]) or "no rows above the universe floor"
        raise RuntimeError(f"yahoo_screener returned no data for market {spec.id}: {detail}")

    df = pd.DataFrame(list(rows.values()))
    df = df.sort_values("total_mv", ascending=False, na_position="last").head(limit).reset_index(drop=True)
    valuation_errors: list[str] = []
    valuation_incomplete = False
    if spec.id == "kr" and kr_valuation_enabled():
        # Yahoo has no PE/PB for Korean listings; Naver fills them within
        # what is left of the snapshot budget (at most 60s).
        remaining = 60.0 if budget is None else min(60.0, budget - (time.monotonic() - started))
        if remaining <= 0:
            # The snapshot budget is spent; do not run past it.
            valuation_errors = ["naver_valuation skipped: snapshot budget exhausted"]
            valuation_incomplete = True
        else:
            df, valuation_errors = enrich_kr_valuation(df, budget_seconds=remaining)
            # A mostly unvalued frame must not replace a valued last-good cache.
            valuation_incomplete = float(df.attrs.get("valuation_coverage", 1.0)) < _MIN_VALUATION_COVERAGE
    df.attrs["snapshot_source"] = "yahoo_screener"
    df.attrs["market"] = spec.id
    df.attrs["currency"] = spec.currency
    df.attrs["source_errors"] = [
        *(f"yahoo_screener sector {item}" for item in errors),
        *valuation_errors,
    ]
    df.attrs["partial"] = bool(errors) or valuation_incomplete
    logger.info("Yahoo screener snapshot for %s: %d rows", spec.id, len(df))
    return df


def _sector_query(spec: MarketSpec, sector: str, floor: float):
    from yfinance import EquityQuery

    clauses = [
        EquityQuery("eq", ["region", spec.yahoo_region]),
        EquityQuery("eq", ["sector", sector]),
        EquityQuery("gt", ["intradaymarketcap", floor]),
    ]
    if spec.yahoo_exchanges:
        clauses.append(EquityQuery("is-in", ["exchange", *spec.yahoo_exchanges]))
    return EquityQuery("and", clauses)


def _quote_to_row(quote: dict, sector: str) -> dict[str, object] | None:
    if str(quote.get("quoteType") or "EQUITY").upper() != "EQUITY":
        return None
    symbol = str(quote.get("symbol") or "").strip()
    price = _num(quote.get("regularMarketPrice"))
    if not symbol or price is None or price <= 0:
        return None
    if _PREFERRED_SYMBOL_RE.search(symbol):
        # JPM-PC, BAC-PB...: preferred shares are tagged EQUITY by Yahoo.
        return None
    if _is_krx_preferred(symbol):
        return None
    volume = _num(quote.get("regularMarketVolume"))
    avg_volume = _num(quote.get("averageDailyVolume10Day")) or _num(quote.get("averageDailyVolume3Month"))
    shares = _num(quote.get("sharesOutstanding"))
    market_cap = _num(quote.get("marketCap"))
    trading_currency = str(quote.get("currency") or "")
    financial_currency = str(quote.get("financialCurrency") or trading_currency)
    # EPS and book value are in the reporting currency. Dividing a USD price
    # by JPY EPS gives a meaningless (tiny) ratio that would rank first in a
    # low-PE screen, so only derive ratios when the currencies match.
    same_currency = not financial_currency or not trading_currency or financial_currency == trading_currency
    pe = _num(quote.get("trailingPE"))
    if pe is None and same_currency:
        eps = _num(quote.get("epsTrailingTwelveMonths"))
        pe = price / eps if eps else None
    pb = _num(quote.get("priceToBook"))
    if pb is None and same_currency:
        book = _num(quote.get("bookValue"))
        pb = price / book if book and book > 0 else None
    if (
        pb is not None
        and pb < _CROSS_CURRENCY_MIN_PB
        and financial_currency
        and trading_currency
        and financial_currency != trading_currency
    ):
        # Cross-currency listings (ADRs, H-shares) are usually converted
        # correctly (ICBC 1398.HK: PB 0.59), but some ADRs divide a USD price
        # by book value in the home currency (EC: PB 0.008). A PB that low
        # only happens with an unconverted currency, so drop it.
        pb = None
    dividend_yield = _num(quote.get("dividendYield"))
    return {
        "code": symbol,
        "name": str(quote.get("longName") or quote.get("shortName") or symbol).strip(),
        "price": price,
        "change_pct": _num(quote.get("regularMarketChangePercent")),
        "amount": price * volume if volume is not None else None,
        "total_mv": market_cap,
        "circ_mv": market_cap,
        "pe_ratio": pe,
        "pb_ratio": pb,
        "volume_ratio": (volume / avg_volume) if volume is not None and avg_volume else None,
        "turnover_rate": (volume / shares * 100) if volume is not None and shares else None,
        "industry": sector,
        "dividend_yield": dividend_yield,
        "currency": str(quote.get("currency") or ""),
        "exchange": str(quote.get("fullExchangeName") or quote.get("exchange") or ""),
    }


def _is_krx_preferred(symbol: str) -> bool:
    """KRX common shares have codes ending in 0; 005935, 005387, 00088K are preferreds."""
    head, _, suffix = symbol.upper().rpartition(".")
    return suffix in {"KS", "KQ"} and len(head) == 6 and head[-1] != "0"


def _num(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # drop NaN


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return max(1, int(raw)) if raw else default


def fetch_yahoo_quotes(symbols: list[str], *, download=None) -> pd.DataFrame:
    """Latest close for specific Yahoo symbols, outside the screener universe.

    Evaluation needs current prices for saved picks even after they drop
    below the market's universe floor; the screener would no longer return
    them and they would be counted as missing instead of as losses.
    """
    symbols = [str(item).strip().upper() for item in symbols if str(item).strip()]
    if not symbols:
        return pd.DataFrame(columns=["code", "price"])
    if download is None:
        import yfinance as yf

        download = yf.download
    data = download(
        symbols,
        period="5d",
        auto_adjust=False,
        group_by="ticker",
        progress=False,
        threads=True,
    )
    rows = []
    for symbol in symbols:
        try:
            frame = data[symbol] if isinstance(data.columns, pd.MultiIndex) else data
            close = pd.to_numeric(frame["Close"], errors="coerce").dropna()
        except (KeyError, TypeError):
            continue
        if not close.empty and float(close.iloc[-1]) > 0:
            rows.append({"code": symbol, "price": float(close.iloc[-1])})
    return pd.DataFrame(rows, columns=["code", "price"])
