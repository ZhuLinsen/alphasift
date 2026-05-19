# -*- coding: utf-8 -*-
"""Market snapshot fetcher.

Fetches full-market real-time snapshots for screening.
This is separate from single-stock realtime quotes.
"""

import logging
import os
import re
from datetime import date, timedelta

import pandas as pd

logger = logging.getLogger(__name__)


_A_SHARE_CODE_PATTERN = re.compile(
    r'^(60[0135]|68[89]|00[0-3]|30[01]|43\d|83\d|87\d)\d{3}$'
)


def filter_a_shares_only(df: pd.DataFrame) -> pd.DataFrame:
    """Filter DataFrame to only include valid A-share stock codes.

    Keeps codes matching mainstream A-share exchanges:
    - 上交所主板: 600xxx, 601xxx, 603xxx, 605xxx
    - 科创板: 688xxx, 689xxx
    - 深交所主板: 000xxx, 001xxx, 002xxx, 003xxx
    - 创业板: 300xxx, 301xxx
    - 北交所: 43xxxx, 83xxxx, 87xxxx

    Excludes ETFs, bonds, convertible bonds, closed-end funds, LOFs, and B-shares.
    """
    if df.empty or 'code' not in df.columns:
        return df

    def _is_a_share(code) -> bool:
        if pd.isna(code):
            return False
        code_str = str(code).strip()
        if not code_str or code_str == 'nan' or code_str == 'None':
            return False
        # Pad to 6 digits if needed (handles int codes or codes with stripped zeros)
        code_str = code_str.zfill(6)
        return bool(_A_SHARE_CODE_PATTERN.match(code_str))

    mask = df['code'].apply(_is_a_share)
    return df[mask].reset_index(drop=True)


def fetch_cn_snapshot(source: str = "efinance") -> pd.DataFrame:
    """Fetch A-share full-market snapshot.

    Returns a DataFrame with columns:
        code, name, price, change_pct, amount, total_mv, circ_mv,
        pe_ratio, pb_ratio, volume_ratio, turnover_rate

    Raises RuntimeError if the source is unavailable.
    """
    if source == "efinance":
        return _fetch_efinance()
    elif source == "akshare_em":
        return _fetch_akshare_em()
    elif source == "em_datacenter":
        return _fetch_em_datacenter()
    elif source == "tushare":
        return _fetch_tushare()
    else:
        raise ValueError(f"Unknown snapshot source: {source}")


def fetch_snapshot_with_fallback(
    sources: list[str],
    *,
    required_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Try sources in order, return first source matching required schema."""
    errors = []
    for source in sources:
        try:
            df = fetch_cn_snapshot(source)
            if not df.empty:
                missing = _missing_required_columns(df, required_columns or [])
                if missing:
                    errors.append(
                        f"{source}: missing required columns {','.join(missing)}"
                    )
                    continue
                df.attrs["source_errors"] = list(errors)
                logger.info("Snapshot fetched from %s: %d rows", source, len(df))
                return df
            errors.append(f"{source}: returned empty data")
        except Exception as e:
            errors.append(f"{source}: {e}")
            logger.warning("Snapshot source %s failed: %s", source, e)
    raise RuntimeError(f"All snapshot sources failed: {'; '.join(errors)}")


def _missing_required_columns(df: pd.DataFrame, required_columns: list[str]) -> list[str]:
    missing: list[str] = []
    for col in required_columns:
        if col not in df.columns:
            missing.append(col)
            continue
        if df[col].dropna().empty:
            missing.append(col)
    return missing


def _fetch_efinance() -> pd.DataFrame:
    """Fetch via efinance."""
    import efinance as ef

    df = ef.stock.get_realtime_quotes()
    if df is None or df.empty:
        raise RuntimeError("efinance returned empty data")
    return _normalize(df, source="efinance")


def _fetch_akshare_em() -> pd.DataFrame:
    """Fetch via akshare (eastmoney)."""
    import akshare as ak

    df = ak.stock_zh_a_spot_em()
    if df is None or df.empty:
        raise RuntimeError("akshare returned empty data")
    return _normalize(df, source="akshare_em")


def _fetch_em_datacenter() -> pd.DataFrame:
    """Fetch via eastmoney datacenter xuangu API.

    This works even on weekends (returns last trading day data).
    """
    import requests

    url = "https://data.eastmoney.com/dataapi/xuangu/list"
    all_items = []
    page = 1
    page_size = 500

    while True:
        params = {
            "st": "SECURITY_CODE",
            "sr": "1",
            "ps": str(page_size),
            "p": str(page),
            "sty": "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,NEW_PRICE,"
                   "CHANGE_RATE,VOLUME_RATIO,DEAL_AMOUNT,TURNOVERRATE,"
                   "PE9,PBNEWMRQ,TOTAL_MARKET_CAP,CIRCULATION_MARKET_CAP",
            "filter": '(MARKET+in+("上交所主板","深交所主板","深交所创业板","上交所科创板","北交所"))',
            "source": "SELECT_SECURITIES",
            "client": "WEB",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://data.eastmoney.com/xuangu/",
        }

        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success"):
            raise RuntimeError(f"em_datacenter API error: {data.get('message', 'unknown')}")

        items = data["result"]["data"]
        all_items.extend(items)

        total_count = data["result"]["count"]
        if page * page_size >= total_count:
            break
        page += 1

    if not all_items:
        raise RuntimeError("em_datacenter returned no data")

    df = pd.DataFrame(all_items)
    return _normalize(df, source="em_datacenter")


def _fetch_tushare() -> pd.DataFrame:
    """Fetch latest available A-share snapshot via Tushare Pro.

    Tushare is not a real-time source here. It is used as a resilient fallback
    by joining the latest open trading day's daily quote and daily_basic data.
    """
    token = (
        os.getenv("TUSHARE_TOKEN", "").strip()
        or os.getenv("TUSHARE_API_TOKEN", "").strip()
    )
    if not token:
        raise RuntimeError("tushare requires TUSHARE_TOKEN")

    import tushare as ts

    pro = ts.pro_api(token)
    trade_date = _resolve_tushare_trade_date(pro)
    daily = pro.daily(
        trade_date=trade_date,
        fields="ts_code,trade_date,close,pct_chg,amount",
    )
    daily_basic = pro.daily_basic(
        trade_date=trade_date,
        fields="ts_code,turnover_rate,volume_ratio,pe,pb,total_mv,circ_mv",
    )
    stock_basic = pro.stock_basic(
        exchange="",
        list_status="L",
        fields="ts_code,symbol,name,industry",
    )

    if daily is None or daily.empty:
        raise RuntimeError(f"tushare daily returned empty data for {trade_date}")
    if daily_basic is None or daily_basic.empty:
        raise RuntimeError(f"tushare daily_basic returned empty data for {trade_date}")

    return _prepare_tushare_snapshot(daily, daily_basic, stock_basic)


def _resolve_tushare_trade_date(pro) -> str:
    """Return the latest open trade date for Tushare requests."""
    explicit = os.getenv("TUSHARE_TRADE_DATE", "").strip()
    if explicit:
        return explicit

    end = date.today()
    start = end - timedelta(days=30)
    calendar = pro.trade_cal(
        exchange="",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        is_open="1",
        fields="cal_date,is_open",
    )
    if calendar is None or calendar.empty or "cal_date" not in calendar.columns:
        raise RuntimeError("tushare trade_cal returned no open trading days")
    return str(calendar["cal_date"].max())


def _prepare_tushare_snapshot(
    daily: pd.DataFrame,
    daily_basic: pd.DataFrame,
    stock_basic: pd.DataFrame | None,
) -> pd.DataFrame:
    """Join and unit-normalize Tushare tables into the common snapshot schema."""
    merged = daily.merge(daily_basic, on="ts_code", how="left")
    if stock_basic is not None and not stock_basic.empty:
        merged = merged.merge(stock_basic, on="ts_code", how="left")
    if "symbol" not in merged.columns:
        merged["symbol"] = merged["ts_code"].astype(str).str.split(".").str[0]
    else:
        fallback_symbol = merged["ts_code"].astype(str).str.split(".").str[0]
        merged["symbol"] = merged["symbol"].fillna(fallback_symbol)

    # Tushare units: amount is thousand yuan; market caps are ten-thousand yuan.
    for col, multiplier in {
        "amount": 1000,
        "total_mv": 10000,
        "circ_mv": 10000,
    }.items():
        if col in merged.columns:
            merged[col] = pd.to_numeric(merged[col], errors="coerce") * multiplier

    return _normalize(merged, source="tushare")


def _normalize(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Normalize column names to a standard schema.

    Standard columns: code, name, price, change_pct, amount, total_mv,
                      circ_mv, pe_ratio, pb_ratio, volume_ratio, turnover_rate
    """
    df = df.copy()

    if source == "efinance":
        standard_cols = {
            "code": ["股票代码", "代码"],
            "name": ["股票名称", "名称"],
            "price": ["最新价"],
            "change_pct": ["涨跌幅"],
            "amount": ["成交额"],
            "total_mv": ["总市值"],
            "circ_mv": ["流通市值"],
            "pe_ratio": ["动态市盈率", "市盈率(动)"],
            "pb_ratio": ["市净率"],
            "volume_ratio": ["量比"],
            "turnover_rate": ["换手率"],
            "industry": ["行业", "所属行业", "行业板块"],
            "concepts": ["概念", "概念题材", "题材"],
        }
    elif source == "akshare_em":
        standard_cols = {
            "code": ["代码"],
            "name": ["名称"],
            "price": ["最新价"],
            "change_pct": ["涨跌幅"],
            "amount": ["成交额"],
            "total_mv": ["总市值"],
            "circ_mv": ["流通市值"],
            "pe_ratio": ["市盈率-动态", "市盈率(动)"],
            "pb_ratio": ["市净率"],
            "volume_ratio": ["量比"],
            "turnover_rate": ["换手率"],
            "industry": ["行业", "所属行业", "行业板块"],
            "concepts": ["概念", "概念题材", "题材"],
        }
    elif source == "em_datacenter":
        standard_cols = {
            "code": ["SECURITY_CODE"],
            "name": ["SECURITY_NAME_ABBR"],
            "price": ["NEW_PRICE"],
            "change_pct": ["CHANGE_RATE"],
            "amount": ["DEAL_AMOUNT"],
            "total_mv": ["TOTAL_MARKET_CAP"],
            "circ_mv": ["CIRCULATION_MARKET_CAP"],
            "pe_ratio": ["PE9"],
            "pb_ratio": ["PBNEWMRQ"],
            "volume_ratio": ["VOLUME_RATIO"],
            "turnover_rate": ["TURNOVERRATE"],
            "industry": ["INDUSTRY", "INDUSTRY_NAME", "BOARD_NAME"],
            "concepts": ["CONCEPT", "CONCEPT_NAME", "THEME_NAME"],
        }
    elif source == "tushare":
        standard_cols = {
            "code": ["symbol", "code"],
            "name": ["name"],
            "price": ["close"],
            "change_pct": ["pct_chg"],
            "amount": ["amount"],
            "total_mv": ["total_mv"],
            "circ_mv": ["circ_mv"],
            "pe_ratio": ["pe"],
            "pb_ratio": ["pb"],
            "volume_ratio": ["volume_ratio"],
            "turnover_rate": ["turnover_rate"],
            "industry": ["industry"],
            "concepts": ["concepts"],
        }
    else:
        standard_cols = {}

    df = _rename_standard_columns(df, standard_cols)

    # Coerce numeric columns
    numeric_cols = [
        "price", "change_pct", "amount", "total_mv", "circ_mv",
        "pe_ratio", "pb_ratio", "volume_ratio", "turnover_rate",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Drop rows without a valid price
    if "price" in df.columns:
        df = df.dropna(subset=["price"])
        df = df[df["price"] > 0]

    df.attrs["snapshot_source"] = source
    before_count = len(df)
    df = filter_a_shares_only(df)
    filtered_count = before_count - len(df)
    if filtered_count > 0:
        logger.info("Filtered %d non-A-share codes (ETF/bond/fund), %d A-shares remaining", filtered_count, len(df))
    return df


def _rename_standard_columns(
    df: pd.DataFrame,
    standard_cols: dict[str, list[str]],
) -> pd.DataFrame:
    """Rename the first matching source column for each standard field."""
    rename_map: dict[str, str] = {}
    for standard_name, candidates in standard_cols.items():
        for candidate in candidates:
            if candidate in df.columns:
                rename_map[candidate] = standard_name
                break
    return df.rename(columns=rename_map)
