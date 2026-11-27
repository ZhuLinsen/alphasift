# -*- coding: utf-8 -*-
"""Region-wide equity snapshot from the Yahoo Finance screener.

One query per sector tags every row with its sector, which portfolio
diversity control needs. A region above the market's universe floor is
typically 5-30 pages of 250 rows at ~0.3s each.

Field notes:
- ``amount`` is price x volume, an estimate of traded value.
  ``avg_amount`` is the current price x the 10-day average volume (3-month
  when missing), an estimate whose volume part does not depend on the time
  of day; ``avg_amount_usd`` converts it at the market's
  approximate ``usd_rate`` for cross-market liquidity floors.
- ``volume_ratio`` is today's volume over the 10-day average. During the
  session it reflects a partial day, like the A-share intraday volume ratio.
- ``circ_mv`` is total market cap; Yahoo has no free-float cap here.
- PE/PB are derived from trailing EPS and book value per share when Yahoo
  omits the ratios. South Korea has neither; KR PE/PB come from Naver
  Finance instead (``alphasift.valuation_kr``).
- Preferred shares are dropped (US ``-P`` symbols, KRX codes not ending in
  0, Taiwan codes with a letter suffix). A company listed on two local
  exchanges (India: NSE and BSE) is kept once.
- PB below 0.05 (e.g. dual-class share mismatches like BRK-B dividing Class B
  price by Class A book value) or below 0.1 on a cross-currency listing (some
  ADRs) is cleared as a reporting/currency artifact.
"""

from __future__ import annotations

from datetime import datetime
import logging
import os
import re
import time
from zoneinfo import ZoneInfo

import pandas as pd

from alphasift.jsonutil import finite_float, safe_int
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
_TW_PREFERRED_RE = re.compile(r"\d{4}[A-Z]")
_MIN_PLAUSIBLE_PB = 0.05
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

    parsed_floor = finite_float(min_market_cap) if min_market_cap is not None else None
    floor = parsed_floor if (parsed_floor is not None and parsed_floor >= 0) else spec.universe_min_market_cap
    default_limit = _int_env("ALPHASIFT_YAHOO_MAX_ROWS", _DEFAULT_MAX_ROWS)
    limit = max(1, safe_int(max_rows, default=default_limit)) if max_rows is not None else default_limit
    budget = parse_source_timeout_seconds(
        "ALPHASIFT_YAHOO_SNAPSHOT_BUDGET_SEC", default=_DEFAULT_BUDGET_SECONDS
    )
    started = time.monotonic()

    # A company listed on two exchanges (India) takes two raw rows, so a
    # sector may need up to limit x suffixes rows to yield ``limit`` companies.
    sector_row_cap = limit * max(1, len(spec.yahoo_suffixes))
    rows: dict[str, dict[str, object]] = {}
    errors: list[str] = []
    timed_out = False
    max_quote_time: float | None = None
    for sector_index, sector in enumerate(YAHOO_SECTORS):
        # Each sector is paged by market cap, up to ``limit`` rows of its own.
        # The global top-``limit`` is then cut after all sectors are in, so a
        # large early sector cannot crowd out Technology or Utilities.
        offset = 0
        while offset < sector_row_cap:
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
            raw_quotes = payload.get("quotes") if isinstance(payload, dict) else None
            quotes = raw_quotes if isinstance(raw_quotes, list) else []
            for quote in quotes:
                if not isinstance(quote, dict):
                    continue
                row = _quote_to_row(quote, sector)
                if row is not None:
                    rows.setdefault(str(row["code"]), row)
                    quote_ts = _num(quote.get("regularMarketTime"))
                    if quote_ts is not None and 0 < quote_ts <= 4_102_444_800:
                        max_quote_time = quote_ts if max_quote_time is None else max(max_quote_time, quote_ts)
            offset += len(quotes)
            total = max(0, safe_int(payload.get("total"), default=0)) if isinstance(payload, dict) else 0
            if not quotes or offset >= total:
                break
            time.sleep(_PAGE_PAUSE_SECONDS)
        if timed_out:
            break

    if not rows:
        detail = "; ".join(errors[:3]) or "no rows above the universe floor"
        raise RuntimeError(f"yahoo_screener returned no data for market {spec.id}: {detail}")

    df = _drop_secondary_listings(pd.DataFrame(list(rows.values())), spec)
    df = df.sort_values("total_mv", ascending=False, na_position="last").head(limit).reset_index(drop=True)
    df["avg_amount_usd"] = (
        pd.to_numeric(df["avg_amount"], errors="coerce") / spec.usd_rate
    ).replace([float("inf"), float("-inf")], pd.NA)
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
            cov_val = finite_float(df.attrs.get("valuation_coverage"))
            valuation_incomplete = (cov_val if cov_val is not None else 1.0) < _MIN_VALUATION_COVERAGE
    df.attrs["snapshot_source"] = "yahoo_screener"
    df.attrs["market"] = spec.id
    df.attrs["currency"] = spec.currency
    if max_quote_time is not None:
        try:
            df.attrs["quote_date"] = (
                datetime.fromtimestamp(max_quote_time, tz=ZoneInfo(spec.timezone))
                .date()
                .isoformat()
            )
        except (OSError, ValueError, OverflowError):
            pass
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


def sanitize_yahoo_pb(
    pb: object,
    *,
    trading_currency: str = "",
    financial_currency: str = "",
) -> float | None:
    """Drop Yahoo P/B reporting/currency artifacts such as dual-class share mismatches."""
    value = _num(pb)
    if value is None or value <= 0 or value < _MIN_PLAUSIBLE_PB:
        return None
    if (
        value < _CROSS_CURRENCY_MIN_PB
        and financial_currency
        and trading_currency
        and financial_currency != trading_currency
    ):
        return None
    return value


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
    if _is_local_preferred(symbol):
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
        pe = _finite_ratio(price, eps) if eps else None
    pb = _num(quote.get("priceToBook"))
    if pb is None and same_currency:
        book = _num(quote.get("bookValue"))
        pb = _finite_ratio(price, book) if book and book > 0 else None
    pb = sanitize_yahoo_pb(
        pb,
        trading_currency=trading_currency,
        financial_currency=financial_currency,
    )
    dividend_yield = _num(quote.get("dividendYield"))
    return {
        "code": symbol,
        "name": str(quote.get("longName") or quote.get("shortName") or symbol).strip(),
        "price": price,
        "change_pct": _num(quote.get("regularMarketChangePercent")),
        "amount": _finite_product(price, volume),
        "avg_amount": _finite_product(price, avg_volume),
        "total_mv": market_cap,
        "circ_mv": market_cap,
        "pe_ratio": pe,
        "pb_ratio": pb,
        "volume_ratio": _finite_ratio(volume, avg_volume) if volume is not None and avg_volume else None,
        "turnover_rate": _finite_ratio(volume, shares, scale=100.0) if volume is not None and shares else None,
        "industry": sector,
        "dividend_yield": dividend_yield,
        "currency": str(quote.get("currency") or ""),
        "exchange": str(quote.get("fullExchangeName") or quote.get("exchange") or ""),
    }


def _is_local_preferred(symbol: str) -> bool:
    """Preferred shares by local code convention.

    KRX: common shares end in 0; 005935, 005387, 00088K are preferreds.
    TWSE/TPEx: common shares are 4 digits; 2881A, 2891C, 2002A are preferreds.
    """
    head, _, suffix = symbol.upper().rpartition(".")
    if suffix in {"KS", "KQ"}:
        return len(head) == 6 and head[-1] != "0"
    if suffix in {"TW", "TWO"}:
        return _TW_PREFERRED_RE.fullmatch(head) is not None
    return False


def _drop_secondary_listings(df: pd.DataFrame, spec: MarketSpec) -> pd.DataFrame:
    """Keep one listing per company when it trades on two local exchanges.

    Indian companies are listed on both NSE (RELIANCE.NS) and BSE
    (RELIANCE.BO) under the same symbol; without this every company would be
    screened, and could be picked, twice. The listing with more average
    traded value (normally NSE) is kept.

    This matches symbols, not company identity: a BSE listing under a
    numeric scrip code would not be paired. KRX (KS/KQ) and TWSE/TPEx
    (TW/TWO) codes are unique across their two boards, so nothing collapses
    there.
    """
    if len(spec.yahoo_suffixes) < 2 or df.empty:
        return df
    head = df["code"].astype(str).str.upper().str.rsplit(".", n=1).str[0]
    # Rank by 10-day average traded value: today's volume can be missing or
    # partial before the session and would keep the thin BSE listing.
    today = pd.to_numeric(df["amount"], errors="coerce")
    average = pd.to_numeric(df["avg_amount"], errors="coerce") if "avg_amount" in df.columns else today
    order = average.fillna(today).fillna(-1.0)
    keep = (
        df.assign(_head=head, _order=order)
        .sort_values("_order", ascending=False, kind="stable")
        .drop_duplicates("_head", keep="first")
        .index
    )
    return df.loc[sorted(keep)].reset_index(drop=True)


_num = finite_float


def _finite_product(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return finite_float(a * b)


def _finite_ratio(a: float | None, b: float | None, *, scale: float = 1.0) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return finite_float((a / b) * scale)


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


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
    if data is None or data.empty:
        return pd.DataFrame(columns=["code", "price"])
    rows = []
    for symbol in symbols:
        try:
            frame = data[symbol] if isinstance(data.columns, pd.MultiIndex) else data
            close = (
                pd.to_numeric(frame["Close"], errors="coerce")
                .replace([float("inf"), float("-inf")], pd.NA)
                .dropna()
            )
        except (KeyError, TypeError):
            continue
        if close.empty:
            continue
        price = finite_float(close.iloc[-1])
        if price is not None and price > 0:
            rows.append({"code": symbol, "price": price})
    return pd.DataFrame(rows, columns=["code", "price"])
