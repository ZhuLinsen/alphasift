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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_NAVER_INTEGRATION_URL = "https://m.stock.naver.com/api/stock/{code}/integration"
_HEADERS = {"User-Agent": "Mozilla/5.0 (alphasift)"}
_NUMBER_RE = re.compile(r"-?[\d,]+(?:\.\d+)?")
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
    fetch = fetch or fetch_naver_valuation
    result = df.copy()
    for column in ("pe_ratio", "pb_ratio"):
        if column not in result.columns:
            result[column] = None
    missing = result["pe_ratio"].isna() | result["pb_ratio"].isna()
    codes = [str(code) for code in result.loc[missing, "code"]]
    if not codes:
        return result, []

    started = time.monotonic()
    values: dict[str, dict[str, float | None]] = {}
    failures: list[str] = []
    timed_out = 0
    with ThreadPoolExecutor(max_workers=max(1, int(max_workers))) as pool:
        futures = {pool.submit(fetch, _naver_code(code)): code for code in codes}
        for future in as_completed(futures):
            code = futures[future]
            if budget_seconds is not None and time.monotonic() - started > budget_seconds:
                timed_out += 1
                future.cancel()
                continue
            try:
                values[code] = future.result()
            except Exception as exc:  # noqa: BLE001 - one listing failing is fine
                failures.append(f"{code}: {exc}")

    filled = 0
    for idx in result.index[missing]:
        item = values.get(str(result.at[idx, "code"]))
        if not item:
            continue
        for column, key in (("pe_ratio", "per"), ("pb_ratio", "pbr")):
            if pd.isna(result.at[idx, column]) and item.get(key) is not None:
                result.at[idx, column] = item[key]
                filled += 1

    errors: list[str] = []
    if failures:
        errors.append(
            f"naver_valuation failed for {len(failures)}/{len(codes)} KR listings: "
            + "; ".join(failures[:3])
        )
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
    """Parse Naver display values like ``9.68배`` or ``1,234.5배``; N/A and dashes -> None."""
    match = _NUMBER_RE.search(str(value or ""))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _naver_code(symbol: str) -> str:
    return str(symbol).split(".", 1)[0].strip().upper()
