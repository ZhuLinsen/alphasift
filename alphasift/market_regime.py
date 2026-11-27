# -*- coding: utf-8 -*-
"""Objective CN market-breadth, limit-up ladder, and regime-stage statistics.

All metrics and stage labels here are reporting and evaluation-slicing metadata
only; they never alter strategy scoring or weights.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
import re
from typing import Any

import numpy as np
import pandas as pd

from alphasift.jsonutil import finite_float, json_safe, safe_int
from alphasift.normalize import normalize_code
from alphasift.pack import DailyPack

_ST_PREFIXES = ("ST", "*ST", "SST", "S*ST")
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_COMPACT_DATE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")

REGIME_STAGE_LABELS: dict[str, str] = {
    "freezing": "冰点",
    "startup": "启动",
    "main_up": "主升",
    "divergence": "分歧",
    "ebb": "退潮",
    "neutral": "震荡",
}
REGIME_STAGE_ORDER: tuple[str, ...] = (
    "freezing",
    "startup",
    "main_up",
    "divergence",
    "ebb",
    "neutral",
)


@dataclass
class MarketRegimeSnapshot:
    """Single-session CN market breadth, limit-up ladder, and stage snapshot."""

    trade_date: str
    traded_count: int
    advancing_count: int
    declining_count: int
    flat_count: int
    advance_ratio_pct: float
    limit_up_count: int
    non_st_limit_up_count: int
    one_price_limit_up_count: int
    broken_board_count: int
    non_st_broken_board_count: int
    seal_rate_pct: float | None
    limit_down_count: int
    non_st_limit_down_count: int
    one_price_limit_down_count: int
    max_consecutive_limit_up: int
    consecutive_board_ladder: dict[int, int]
    prev_limit_up_count: int
    prev_limit_up_avg_return_pct: float | None
    prev_limit_up_open_premium_pct: float | None
    prev_limit_up_win_rate_pct: float | None
    prev_limit_up_promoted_count: int
    prev_limit_up_promotion_rate_pct: float | None
    total_amount_yi: float | None
    amount_is_proxy: bool
    regime_stage: str
    regime_stage_label: str
    regime_reasons: list[str]
    usage_policy: str = "reporting_and_slice_only"
    median_return_pct: float | None = None
    return_distribution: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["consecutive_board_ladder"] = {
            str(k): safe_int(v, default=0) for k, v in self.consecutive_board_ladder.items()
        }
        return json_safe(payload)


def cn_price_limit_pct(code: str, *, is_st: bool = False, name: str = "") -> float:
    """Return CN daily price-limit ratio (0.10, 0.20, 0.30, or main-board ST 0.05)."""
    norm = normalize_code(code, allow_ticker=False) or str(code or "").strip()
    if norm.startswith(("300", "301", "688", "689")):
        return 0.20
    if norm.startswith(("4", "8", "920")):
        return 0.30
    upper_name = str(name or "").strip().upper()
    if is_st or upper_name.startswith(_ST_PREFIXES):
        return 0.05
    return 0.10


def round_cn_tick(values: np.ndarray | float) -> np.ndarray | float:
    """Vectorized half-up rounding to CN tick size (0.01 yuan)."""
    return np.floor(np.asarray(values, dtype=np.float64) * 100.0 + 0.5 + 1e-9) / 100.0


def _normalize_date_str(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "<na>"}:
        return None
    if _ISO_DATE_RE.match(text):
        return text
    match = _COMPACT_DATE_RE.match(text)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def _aligned_meta(pack: DailyPack) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Align is_st, limit_pct, and normalized list_date arrays to ``pack.codes``."""
    n = len(pack.codes)
    codes = np.asarray([normalize_code(c, allow_ticker=False) or str(c) for c in pack.codes], dtype=str)
    st_map: dict[str, bool] = {}
    name_map: dict[str, str] = {}
    list_map: dict[str, str] = {}

    if pack.meta is not None and not pack.meta.empty and "code" in pack.meta.columns:
        for row in pack.meta.itertuples(index=False):
            raw_code = getattr(row, "code", "")
            code = normalize_code(raw_code, allow_ticker=False) or str(raw_code).strip()
            if not code:
                continue
            name_val = getattr(row, "name", "")
            name_str = "" if name_val is None or pd.isna(name_val) else str(name_val).strip()
            name_map[code] = name_str
            is_st_val = getattr(row, "is_st", False)
            is_st_flag = bool(False if pd.isna(is_st_val) else is_st_val)
            if name_str.upper().startswith(_ST_PREFIXES):
                is_st_flag = True
            st_map[code] = is_st_flag
            list_norm = _normalize_date_str(getattr(row, "list_date", None))
            if list_norm:
                list_map[code] = list_norm

    is_st = np.zeros(n, dtype=bool)
    limit_pct = np.empty(n, dtype=np.float64)
    list_dates = np.empty(n, dtype=object)
    for j, code in enumerate(codes):
        st_flag = st_map.get(code, False)
        name_str = name_map.get(code, "")
        is_st[j] = st_flag
        limit_pct[j] = cn_price_limit_pct(code, is_st=st_flag, name=name_str)
        list_dates[j] = list_map.get(code)
    return is_st, limit_pct, list_dates


def compute_limit_masks(
    daily_pack: DailyPack,
    *,
    end_index: int | None = None,
) -> dict[str, np.ndarray]:
    """Compute vectorized CN price-limit, broken-board, and streak masks over ``daily_pack``."""
    total_dates = len(daily_pack.dates)
    if total_dates == 0 or len(daily_pack.codes) == 0:
        empty_bool = np.zeros((0, len(daily_pack.codes)), dtype=bool)
        empty_float = np.zeros((0, len(daily_pack.codes)), dtype=np.float64)
        return {
            "dates": np.asarray([], dtype=str),
            "active": empty_bool,
            "is_st": np.zeros(len(daily_pack.codes), dtype=bool),
            "limit_pct": np.zeros(len(daily_pack.codes), dtype=np.float64),
            "open": empty_float,
            "high": empty_float,
            "low": empty_float,
            "close": empty_float,
            "pre_close": empty_float,
            "up_limit": empty_float,
            "down_limit": empty_float,
            "has_price_limit": empty_bool,
            "is_limit_up": empty_bool,
            "is_limit_down": empty_bool,
            "is_one_price_limit_up": empty_bool,
            "is_one_price_limit_down": empty_bool,
            "is_broken_board": empty_bool,
            "consecutive_limit_up": np.zeros((0, len(daily_pack.codes)), dtype=np.int32),
            "proxy_amount": empty_float,
            "has_real_amount": empty_bool,
        }

    if end_index is None:
        end_idx = total_dates
    else:
        end_idx = end_index + 1 if end_index >= 0 else total_dates + end_index + 1
        if end_idx <= 0 or end_idx > total_dates:
            raise IndexError(f"end_index {end_index} out of range for {total_dates} sessions")

    dates = np.asarray(daily_pack.dates[:end_idx], dtype=str)
    t_len = len(dates)
    n_codes = len(daily_pack.codes)

    open_ = np.asarray(daily_pack.matrices["open"][:end_idx], dtype=np.float64)
    high = np.asarray(daily_pack.matrices["high"][:end_idx], dtype=np.float64)
    low = np.asarray(daily_pack.matrices["low"][:end_idx], dtype=np.float64)
    close = np.asarray(daily_pack.matrices["close"][:end_idx], dtype=np.float64)
    pc_raw = np.asarray(daily_pack.matrices["pre_close"][:end_idx], dtype=np.float64)
    vol = np.asarray(daily_pack.matrices["volume"][:end_idx], dtype=np.float64)
    amt = np.asarray(daily_pack.matrices["amount"][:end_idx], dtype=np.float64)

    is_st, limit_pct, list_dates = _aligned_meta(daily_pack)
    bar_valid = np.isfinite(close) & (close > 0) & (~np.isfinite(vol) | (vol > 0))

    prev_c_row = np.full((t_len, n_codes), np.nan, dtype=np.float64)
    last_close = np.full(n_codes, np.nan, dtype=np.float64)
    for t in range(t_len):
        prev_c_row[t] = last_close
        valid_t = bar_valid[t]
        if valid_t.any():
            last_close = np.where(valid_t, close[t], last_close)

    pre_close = np.where(np.isfinite(pc_raw) & (pc_raw > 0), pc_raw, prev_c_row)
    active = bar_valid & np.isfinite(pre_close) & (pre_close > 0)

    up_limit = round_cn_tick(pre_close * (1.0 + limit_pct[None, :]))
    down_limit = round_cn_tick(pre_close * (1.0 - limit_pct[None, :]))

    # Exclude no-limit IPO / resumption bars (and historical ST-transition outliers).
    out_of_band = (
        (close > up_limit + 0.02)
        | (np.isfinite(high) & (high > up_limit + 0.02))
        | (close < down_limit - 0.02)
        | (np.isfinite(low) & (low < down_limit - 0.02))
    )
    has_price_limit = active & ~out_of_band

    # When list_date falls inside or just before the pack window, exclude first-5-day
    # registration-IPO no-limit sessions (BSE: first session only).
    first_date = str(dates[0])
    cum_bars = np.cumsum(bar_valid, axis=0)
    is_bj = np.asarray(
        [(normalize_code(c, allow_ticker=False) or str(c)).startswith(("4", "8", "920")) for c in daily_pack.codes],
        dtype=bool,
    )
    for j in range(n_codes):
        ld = list_dates[j]
        if ld is not None and ld >= first_date:
            no_limit_days = 1 if is_bj[j] else 5
            on_or_after = dates >= ld
            ipo_window = on_or_after & bar_valid[:, j] & (cum_bars[:, j] <= no_limit_days)
            has_price_limit[ipo_window, j] = False

    tol = 0.00500001
    is_limit_up = has_price_limit & (close >= up_limit - tol)
    is_limit_down = has_price_limit & (close <= down_limit + tol)
    is_one_price_limit_up = (
        is_limit_up
        & np.isfinite(open_)
        & np.isfinite(low)
        & (np.abs(open_ - up_limit) <= tol)
        & (np.abs(open_ - low) <= 1e-6)
    )
    is_one_price_limit_down = (
        is_limit_down
        & np.isfinite(open_)
        & np.isfinite(high)
        & (np.abs(open_ - down_limit) <= tol)
        & (np.abs(open_ - high) <= 1e-6)
    )
    is_broken_board = has_price_limit & (~is_limit_up) & np.isfinite(high) & (high >= up_limit - tol)

    streak = np.zeros((t_len, n_codes), dtype=np.int32)
    running = np.zeros(n_codes, dtype=np.int32)
    for t in range(t_len):
        act_t = active[t]
        lu_t = is_limit_up[t]
        running = np.where(act_t, np.where(lu_t, running + 1, 0), running)
        streak[t] = np.where(act_t & lu_t, running, 0)

    has_real_amount = active & np.isfinite(amt) & (amt > 0)
    proxy_amount = np.where(
        has_real_amount,
        amt,
        np.where(active & np.isfinite(vol) & (vol > 0), close * vol, np.nan),
    )

    return {
        "dates": dates,
        "active": active,
        "is_st": is_st,
        "limit_pct": limit_pct,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "pre_close": pre_close,
        "up_limit": up_limit,
        "down_limit": down_limit,
        "has_price_limit": has_price_limit,
        "is_limit_up": is_limit_up,
        "is_limit_down": is_limit_down,
        "is_one_price_limit_up": is_one_price_limit_up,
        "is_one_price_limit_down": is_one_price_limit_down,
        "is_broken_board": is_broken_board,
        "consecutive_limit_up": streak,
        "proxy_amount": proxy_amount,
        "has_real_amount": has_real_amount,
    }


def classify_regime_stage(
    *,
    advance_ratio_pct: float,
    non_st_limit_up_count: int,
    non_st_limit_down_count: int,
    non_st_broken_board_count: int,
    seal_rate_pct: float | None,
    max_consecutive_limit_up: int,
    prev_limit_up_avg_return_pct: float | None,
) -> tuple[str, str, list[str]]:
    """Rule-based CN regime stage classification for reporting & evaluation slices only."""
    adv_ratio = finite_float(advance_ratio_pct)
    adv_ratio = 0.0 if adv_ratio is None else adv_ratio
    non_st_lu = max(0, safe_int(non_st_limit_up_count, default=0))
    non_st_ld = max(0, safe_int(non_st_limit_down_count, default=0))
    non_st_bb = max(0, safe_int(non_st_broken_board_count, default=0))
    seal = finite_float(seal_rate_pct)
    max_lu = max(0, safe_int(max_consecutive_limit_up, default=0))
    prev_ret = finite_float(prev_limit_up_avg_return_pct)

    if (
        (adv_ratio < 25.0 and non_st_ld >= 25)
        or (adv_ratio < 20.0 and non_st_lu < 35)
        or (non_st_lu < 25 and prev_ret is not None and prev_ret < -1.0)
    ):
        reasons = [
            f"上涨占比 {adv_ratio:.1f}%",
            f"非ST涨停 {non_st_lu} / 跌停 {non_st_ld}",
        ]
        if prev_ret is not None:
            reasons.append(f"昨涨停溢价 {prev_ret:+.2f}%")
        return "freezing", REGIME_STAGE_LABELS["freezing"], reasons

    if (
        (non_st_ld >= 20 and prev_ret is not None and prev_ret < -0.5)
        or (seal is not None and seal < 60.0 and adv_ratio < 40.0 and non_st_ld >= 10)
        or (prev_ret is not None and prev_ret <= -1.5 and adv_ratio < 45.0)
    ):
        reasons = [f"非ST跌停 {non_st_ld}", f"上涨占比 {adv_ratio:.1f}%"]
        if seal is not None:
            reasons.append(f"封板率 {seal:.1f}%")
        if prev_ret is not None:
            reasons.append(f"昨涨停溢价 {prev_ret:+.2f}%")
        return "ebb", REGIME_STAGE_LABELS["ebb"], reasons

    if (
        adv_ratio >= 60.0
        and non_st_lu >= 65
        and (seal is None or seal >= 72.0)
        and (prev_ret is None or prev_ret >= 1.0)
    ):
        reasons = [
            f"上涨占比 {adv_ratio:.1f}%",
            f"非ST涨停 {non_st_lu}",
        ]
        if seal is not None:
            reasons.append(f"封板率 {seal:.1f}%")
        if prev_ret is not None:
            reasons.append(f"昨涨停溢价 {prev_ret:+.2f}%")
        return "main_up", REGIME_STAGE_LABELS["main_up"], reasons

    if (
        (adv_ratio >= 58.0 and non_st_lu >= 45 and non_st_ld <= 10)
        or (adv_ratio >= 50.0 and prev_ret is not None and prev_ret >= 2.0 and non_st_lu >= 50)
    ):
        reasons = [
            f"上涨占比 {adv_ratio:.1f}%",
            f"非ST涨停 {non_st_lu}",
        ]
        if prev_ret is not None:
            reasons.append(f"昨涨停溢价 {prev_ret:+.2f}%")
        return "startup", REGIME_STAGE_LABELS["startup"], reasons

    if (
        (non_st_lu >= 45 and seal is not None and seal < 70.0)
        or (non_st_bb >= 30 and non_st_lu >= 40)
        or (max_lu >= 5 and adv_ratio < 45.0)
    ):
        reasons = [
            f"非ST涨停 {non_st_lu} / 炸板 {non_st_bb}",
            f"最高连板 {max_lu}",
        ]
        if seal is not None:
            reasons.append(f"封板率 {seal:.1f}%")
        return "divergence", REGIME_STAGE_LABELS["divergence"], reasons

    reasons = [
        f"上涨占比 {adv_ratio:.1f}%",
        f"非ST涨停 {non_st_lu} / 跌停 {non_st_ld}",
    ]
    return "neutral", REGIME_STAGE_LABELS["neutral"], reasons


def _snapshot_at_index(masks: dict[str, np.ndarray], t: int) -> MarketRegimeSnapshot:
    dates = masks["dates"]
    is_st = masks["is_st"]
    non_st = ~is_st

    act = masks["active"][t]
    close_t = masks["close"][t]
    open_t = masks["open"][t]
    pc_t = masks["pre_close"][t]

    traded_count = int(act.sum())
    ret_t = np.where(act, close_t / pc_t - 1.0, np.nan)
    advancing_count = int((act & (close_t > pc_t + 1e-6)).sum())
    declining_count = int((act & (close_t < pc_t - 1e-6)).sum())
    flat_count = max(0, traded_count - advancing_count - declining_count)
    advance_ratio_pct = round((advancing_count / traded_count) * 100.0, 2) if traded_count > 0 else 0.0
    valid_pcts = ret_t[act] * 100.0
    valid_pcts = valid_pcts[np.isfinite(valid_pcts)]
    median_return_pct = round(float(np.median(valid_pcts)), 2) if valid_pcts.size > 0 else None
    return_distribution = {
        "le_neg7": int((valid_pcts <= -7.0).sum()),
        "neg7_neg3": int(((valid_pcts > -7.0) & (valid_pcts <= -3.0)).sum()),
        "neg3_0": int(((valid_pcts > -3.0) & (valid_pcts < -1e-4)).sum()),
        "flat": int((np.abs(valid_pcts) <= 1e-4).sum()),
        "pos0_3": int(((valid_pcts > 1e-4) & (valid_pcts < 3.0)).sum()),
        "pos3_7": int(((valid_pcts >= 3.0) & (valid_pcts < 7.0)).sum()),
        "ge_pos7": int((valid_pcts >= 7.0).sum()),
    }

    lu = masks["is_limit_up"][t]
    lu_non_st = lu & non_st
    ld = masks["is_limit_down"][t]
    ld_non_st = ld & non_st
    bb = masks["is_broken_board"][t]
    bb_non_st = bb & non_st
    one_lu = masks["is_one_price_limit_up"][t]
    one_ld = masks["is_one_price_limit_down"][t]

    limit_up_count = int(lu.sum())
    non_st_limit_up_count = int(lu_non_st.sum())
    one_price_limit_up_count = int(one_lu.sum())
    broken_board_count = int(bb.sum())
    non_st_broken_board_count = int(bb_non_st.sum())

    seal_den = non_st_limit_up_count + non_st_broken_board_count
    seal_rate_pct = round((non_st_limit_up_count / seal_den) * 100.0, 2) if seal_den > 0 else None

    limit_down_count = int(ld.sum())
    non_st_limit_down_count = int(ld_non_st.sum())
    one_price_limit_down_count = int(one_ld.sum())

    streak_t = masks["consecutive_limit_up"][t]
    lu_streaks = streak_t[lu_non_st]
    max_consecutive_limit_up = int(lu_streaks.max()) if lu_streaks.size > 0 else 0
    ladder: dict[int, int] = {}
    if lu_streaks.size > 0:
        unique_boards, counts = np.unique(lu_streaks, return_counts=True)
        for board_cnt, n_stocks in zip(unique_boards.tolist(), counts.tolist()):
            if int(board_cnt) >= 2:
                ladder[int(board_cnt)] = int(n_stocks)

    prev_lu_count = 0
    prev_lu_avg_ret: float | None = None
    prev_lu_open_prem: float | None = None
    prev_lu_win_rate: float | None = None
    prev_lu_promoted = 0
    prev_lu_promo_rate: float | None = None

    if t > 0:
        prev_pool = masks["is_limit_up"][t - 1] & non_st & act
        prev_lu_count = int(prev_pool.sum())
        if prev_lu_count > 0:
            prev_rets = ret_t[prev_pool] * 100.0
            prev_rets = prev_rets[np.isfinite(prev_rets)]
            if prev_rets.size > 0:
                prev_lu_avg_ret = round(float(np.mean(prev_rets)), 2)
                prev_lu_win_rate = round(float((prev_rets > 0).mean() * 100.0), 2)
            open_mask = prev_pool & np.isfinite(open_t) & (open_t > 0)
            if open_mask.any():
                open_rets = (open_t[open_mask] / pc_t[open_mask] - 1.0) * 100.0
                open_rets = open_rets[np.isfinite(open_rets)]
                if open_rets.size > 0:
                    prev_lu_open_prem = round(float(np.mean(open_rets)), 2)
            prev_lu_promoted = int((prev_pool & lu_non_st).sum())
            prev_lu_promo_rate = round((prev_lu_promoted / prev_lu_count) * 100.0, 2)

    real_amt_cnt = int(masks["has_real_amount"][t].sum())
    amount_is_proxy = real_amt_cnt < int(0.8 * max(1, traded_count))
    amt_t = masks["proxy_amount"][t]
    valid_amt = act & np.isfinite(amt_t) & (amt_t > 0)
    total_amount_yi = round(float(amt_t[valid_amt].sum() / 1e8), 2) if valid_amt.any() else None

    stage, stage_label, reasons = classify_regime_stage(
        advance_ratio_pct=advance_ratio_pct,
        non_st_limit_up_count=non_st_limit_up_count,
        non_st_limit_down_count=non_st_limit_down_count,
        non_st_broken_board_count=non_st_broken_board_count,
        seal_rate_pct=seal_rate_pct,
        max_consecutive_limit_up=max_consecutive_limit_up,
        prev_limit_up_avg_return_pct=prev_lu_avg_ret,
    )

    return MarketRegimeSnapshot(
        trade_date=str(dates[t]),
        traded_count=traded_count,
        advancing_count=advancing_count,
        declining_count=declining_count,
        flat_count=flat_count,
        advance_ratio_pct=advance_ratio_pct,
        limit_up_count=limit_up_count,
        non_st_limit_up_count=non_st_limit_up_count,
        one_price_limit_up_count=one_price_limit_up_count,
        broken_board_count=broken_board_count,
        non_st_broken_board_count=non_st_broken_board_count,
        seal_rate_pct=seal_rate_pct,
        limit_down_count=limit_down_count,
        non_st_limit_down_count=non_st_limit_down_count,
        one_price_limit_down_count=one_price_limit_down_count,
        max_consecutive_limit_up=max_consecutive_limit_up,
        consecutive_board_ladder=ladder,
        prev_limit_up_count=prev_lu_count,
        prev_limit_up_avg_return_pct=prev_lu_avg_ret,
        prev_limit_up_open_premium_pct=prev_lu_open_prem,
        prev_limit_up_win_rate_pct=prev_lu_win_rate,
        prev_limit_up_promoted_count=prev_lu_promoted,
        prev_limit_up_promotion_rate_pct=prev_lu_promo_rate,
        total_amount_yi=total_amount_yi,
        amount_is_proxy=amount_is_proxy,
        regime_stage=stage,
        regime_stage_label=stage_label,
        regime_reasons=reasons,
        median_return_pct=median_return_pct,
        return_distribution=return_distribution,
    )


def compute_market_regime_series(
    daily_pack: DailyPack,
    *,
    end_index: int | None = None,
    masks: dict[str, np.ndarray] | None = None,
) -> list[MarketRegimeSnapshot]:
    """Compute objective market-regime statistics across all sessions up to ``end_index``."""
    resolved_masks = masks if masks is not None else compute_limit_masks(daily_pack, end_index=end_index)
    t_len = len(resolved_masks["dates"])
    return [_snapshot_at_index(resolved_masks, t) for t in range(t_len)]


def compute_market_regime(
    daily_pack: DailyPack,
    *,
    as_of_index: int = -1,
    trade_date: str | None = None,
) -> MarketRegimeSnapshot:
    """Compute point-in-time CN market regime statistics at ``as_of_index`` or ``trade_date``."""
    dates = [str(d) for d in daily_pack.dates]
    if not dates:
        raise ValueError("DailyPack contains no sessions")
    if trade_date is not None:
        norm_day = _normalize_date_str(trade_date)
        if not norm_day or norm_day not in dates:
            raise ValueError(f"trade_date {trade_date!r} not found in DailyPack ({dates[0]}..{dates[-1]})")
        idx = dates.index(norm_day)
    else:
        idx = as_of_index if as_of_index >= 0 else len(dates) + as_of_index
        if idx < 0 or idx >= len(dates):
            raise IndexError(f"as_of_index {as_of_index} out of range for {len(dates)} sessions")

    # Compute strictly up to ``idx`` so no future metadata or bars leak into history.
    masks = compute_limit_masks(daily_pack, end_index=idx)
    return _snapshot_at_index(masks, idx)


def summarize_regime_distribution(snapshots: list[MarketRegimeSnapshot]) -> dict[str, dict[str, Any]]:
    """Aggregate session counts and shares across the 6 regime stage buckets."""
    total = len(snapshots)
    counts = {stage: 0 for stage in REGIME_STAGE_ORDER}
    for snap in snapshots:
        counts[snap.regime_stage] = counts.get(snap.regime_stage, 0) + 1
    return {
        stage: {
            "label": REGIME_STAGE_LABELS[stage],
            "days": counts[stage],
            "share_pct": round((counts[stage] / total) * 100.0, 2) if total > 0 else 0.0,
        }
        for stage in REGIME_STAGE_ORDER
    }
