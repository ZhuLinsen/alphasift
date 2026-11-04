# -*- coding: utf-8 -*-
"""PE/PB for South Korean listings from Naver Finance.

The Yahoo screener (and Yahoo's per-ticker quote) carries no PE, PB, EPS or
book value for .KS/.KQ symbols, so valuation strategies could not run on KR.
Naver's mobile stock API reports trailing PER/PBR per listing and is
reachable from overseas servers. It is an unofficial endpoint: failures only
leave PE/PB empty and are reported in ``source_errors``.

Set ``ALPHASIFT_KR_VALUATION=0`` to skip it.
"""

from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_NAVER_INTEGRATION_URL = "https://m.stock.naver.com/api/stock/{code}/integration"
_HEADERS = {"User-Agent": "Mozilla/5.0 (alphasift)"}
# Naver display values: "9.68배", "1,234.5배", "-12.30배", "N/A".
_NUMBER_RE = re.compile(r"^\s*(-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?)\s*배?\s*$")
_DEFAULT_WORKERS = 8
_REQUEST_TIMEOUT = (5, 10)


def kr_valuation_enabled() -> bool:
    return os.getenv("ALPHASIFT_KR_VALUATION", "1").strip().lower() not in {"0", "false", "off", "no"}


def enrich_kr_valuation(
    df: pd.DataFrame,
    *,
    budget_seconds: float | None = 60.0,
    fetch=None,
    max_workers: int = _DEFAULT_WORKERS,
) -> tuple[pd.DataFrame, list[str]]:
    """Fill missing ``pe_ratio`` / ``pb_ratio`` on KR rows. Returns (frame, errors)."""
    if df.empty or "code" not in df.columns:
        return df, []
    session = None
    if fetch is None:
        # One pooled session: a cold KR snapshot makes ~250 requests.
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_maxsize=max(1, int(max_workers)))
        session.mount("https://", adapter)

        def fetch(code: str) -> dict[str, float | None]:
            return fetch_naver_valuation(code, session=session)

    result = df.copy()
    for column in ("pe_ratio", "pb_ratio"):
        if column not in result.columns:
            result[column] = None
    missing = result["pe_ratio"].isna() | result["pb_ratio"].isna()
    codes = [str(code) for code in result.loc[missing, "code"]]
    if not codes:
        result.attrs["valuation_coverage"] = 1.0
        return result, []

    values: dict[str, dict[str, float | None]] = {}
    failures: list[str] = []
    timed_out = 0
    pool = ThreadPoolExecutor(max_workers=max(1, int(max_workers)))
    futures = {pool.submit(fetch, _naver_code(code)): code for code in codes}
    try:
        for future in as_completed(futures, timeout=budget_seconds):
            code = futures[future]
            try:
                values[code] = future.result()
            except Exception as exc:  # noqa: BLE001 - one listing failing is fine
                failures.append(f"{code}: {exc}")
    except FuturesTimeout:
        timed_out = sum(1 for future in futures if not future.done())
    finally:
        # Queued requests are dropped; in-flight ones finish in the background
        # (bounded by the request timeout) without holding up the snapshot.
        pool.shutdown(wait=False, cancel_futures=True)
        if session is not None:
            session.close()

    filled = 0
    for idx in result.index[missing]:
        item = values.get(str(result.at[idx, "code"]))
        if not item:
            continue
        for column, key in (("pe_ratio", "per"), ("pb_ratio", "pbr")):
            if pd.isna(result.at[idx, column]) and item.get(key) is not None:
                result.at[idx, column] = item[key]
                filled += 1

    # Coverage counts listings that got a usable ratio, not HTTP successes:
    # a changed payload returning N/A everywhere must not look complete.
    # PBR is present for nearly every listing; PER is absent for losses.
    usable = sum(
        1 for item in values.values() if item and (item.get("per") is not None or item.get("pbr") is not None)
    )
    result.attrs["valuation_coverage"] = round(usable / len(codes), 4)

    errors: list[str] = []
    if failures:
        errors.append(
            f"naver_valuation failed for {len(failures)}/{len(codes)} KR listings: "
            + "; ".join(failures[:3])
        )
    if values and not usable:
        errors.append(f"naver_valuation: no PER/PBR in {len(values)} responses (payload format changed?)")
    if timed_out:
        errors.append(f"naver_valuation exceeded {budget_seconds:.0f}s budget; {timed_out} listings left without PE/PB")
    logger.info("Naver valuation: %d/%d KR listings, %d fields filled", len(values), len(codes), filled)
    return result, errors


def fetch_naver_valuation(code: str, *, session: requests.Session | None = None) -> dict[str, float | None]:
    """Trailing PER / PBR for one KRX code (``005930``)."""
    client = session or requests
    response = client.get(
        _NAVER_INTEGRATION_URL.format(code=code), headers=_HEADERS, timeout=_REQUEST_TIMEOUT
    )
    response.raise_for_status()
    payload = response.json()
    infos = payload.get("totalInfos") if isinstance(payload, dict) else None
    if not isinstance(infos, list):
        raise ValueError(f"unexpected Naver payload: {str(payload)[:80]}")
    by_code = {str(item.get("code")): item.get("value") for item in infos if isinstance(item, dict)}
    return {"per": parse_naver_number(by_code.get("per")), "pbr": parse_naver_number(by_code.get("pbr"))}


def parse_naver_number(value: object) -> float | None:
    """Parse Naver display values like ``9.68배`` or ``1,234.5배``.

    N/A, dashes, anything else and an exact 0 (no ratio) -> None.
    """
    match = _NUMBER_RE.match(str(value or ""))
    if not match:
        return None
    number = float(match.group(1).replace(",", ""))
    return number if number != 0 else None


def _naver_code(symbol: str) -> str:
    return str(symbol).split(".", 1)[0].strip().upper()
