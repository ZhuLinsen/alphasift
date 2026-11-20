# -*- coding: utf-8 -*-
"""Vectorized daily technical and shape features over CN daily bar matrices."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from alphasift.daily import _DAILY_FEATURE_DEFAULTS
from alphasift.normalize import normalize_code
from alphasift.pack import DailyPack, forward_adjust

_FEATURE_COLUMNS = ["code", *list(_DAILY_FEATURE_DEFAULTS)]
_EMA12_ALPHA = 2.0 / (12.0 + 1.0)
_EMA26_ALPHA = 2.0 / (26.0 + 1.0)
_EMA9_ALPHA = 2.0 / (9.0 + 1.0)


def _normalize_pack_code(value: object) -> str:
    return normalize_code(value, allow_ticker=False)


def _round_array(values: np.ndarray, valid: np.ndarray) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for idx in np.flatnonzero(valid):
        out[int(idx)] = round(float(values[idx]), 4)
    return out


def compute_pack_daily_features(
    daily_pack: DailyPack,
    *,
    codes: Sequence[str] | None = None,
    as_of_index: int | None = None,
    trade_date: str | None = None,
) -> pd.DataFrame:
    """Slice to ``trade_date``/``as_of_index`` BEFORE ``forward_adjust``, then compute features."""
    dates = [str(d) for d in daily_pack.dates]
    total_dates = len(dates)
    if total_dates == 0 or len(daily_pack.codes) == 0:
        return pd.DataFrame(columns=_FEATURE_COLUMNS)

    if trade_date is not None:
        if trade_date not in dates:
            raise ValueError(f"trade_date {trade_date!r} not found in DailyPack ({dates[0]}..{dates[-1]})")
        end_idx = dates.index(trade_date) + 1
    elif as_of_index is not None:
        end_idx = as_of_index + 1 if as_of_index >= 0 else total_dates + as_of_index + 1
        if end_idx <= 0 or end_idx > total_dates:
            raise IndexError(f"as_of_index {as_of_index} out of range for {total_dates} sessions")
    else:
        end_idx = total_dates

    if end_idx < total_dates:
        # Slice strictly BEFORE forward_adjust so future splits never rescale past MAs.
        work_pack = DailyPack(
            dates=daily_pack.dates[:end_idx],
            codes=daily_pack.codes,
            matrices={k: v[:end_idx] for k, v in daily_pack.matrices.items()},
            meta=daily_pack.meta,
            sources=daily_pack.sources,
            manifest=daily_pack.manifest,
        )
    else:
        work_pack = daily_pack

    adjusted = forward_adjust(work_pack)
    return compute_matrix_daily_features(
        work_pack.codes,
        adjusted,
        selected_codes=codes,
        as_of_index=None,
    )


def compute_matrix_daily_features(
    codes: np.ndarray,
    matrices: dict[str, np.ndarray],
    *,
    selected_codes: Sequence[str] | None = None,
    as_of_index: int | None = None,
) -> pd.DataFrame:
    """Compute ``daily.compute_daily_features`` columns across a date-by-code matrix.

    Produces values matching ``alphasift.daily.compute_daily_features(pack.history(code))``
    while handling per-stock listing gaps and suspension ``NaN``s via right-aligned
    valid-bar compaction.
    """
    code_arr = np.asarray(codes, dtype=str)
    close_full = np.asarray(matrices["close"], dtype=np.float64)
    total_dates = close_full.shape[0]
    if total_dates == 0 or len(code_arr) == 0:
        return pd.DataFrame(columns=_FEATURE_COLUMNS)

    if as_of_index is not None:
        end_idx = as_of_index + 1 if as_of_index >= 0 else total_dates + as_of_index + 1
        if end_idx <= 0 or end_idx > total_dates:
            raise IndexError(f"as_of_index {as_of_index} out of range for {total_dates} sessions")
    else:
        end_idx = total_dates

    if selected_codes is not None:
        norm_selected = list(dict.fromkeys(_normalize_pack_code(item) for item in selected_codes if item is not None))
        col_indices: list[int] = []
        matched_codes: list[str] = []
        for item in norm_selected:
            if not item:
                continue
            pos = int(np.searchsorted(code_arr, item))
            if pos < len(code_arr) and code_arr[pos] == item:
                col_indices.append(pos)
                matched_codes.append(item)
        if not col_indices:
            return pd.DataFrame(columns=_FEATURE_COLUMNS)
        col_idx_arr = np.asarray(col_indices, dtype=np.intp)
        target_codes = np.asarray(matched_codes, dtype=str)
    else:
        col_idx_arr = np.arange(len(code_arr), dtype=np.intp)
        target_codes = code_arr

    close_raw = close_full[:end_idx, col_idx_arr]
    valid = np.isfinite(close_raw)
    counts = valid.sum(axis=0).astype(np.int64)
    active_mask = counts > 0
    if not active_mask.any():
        return pd.DataFrame(columns=_FEATURE_COLUMNS)

    active_cols = col_idx_arr[active_mask]
    active_codes = target_codes[active_mask]
    k = counts[active_mask]
    t_max = int(k.max())
    m = len(active_codes)

    valid_active = valid[:, active_mask]
    order = np.argsort(valid_active, axis=0, kind="stable")[-t_max:, :]
    close = np.take_along_axis(close_raw[:, active_mask], order, axis=0)

    row_pos = np.arange(t_max, dtype=np.int64)[:, None]
    start_row = t_max - k
    is_valid_row = row_pos >= start_row[None, :]

    def _compact_price(field: str) -> np.ndarray:
        if field not in matrices:
            return close.copy()
        arr = np.asarray(matrices[field][:end_idx, active_cols], dtype=np.float64)
        compacted = np.take_along_axis(arr, order, axis=0)
        return np.where(is_valid_row & ~np.isfinite(compacted), close, compacted)

    open_ = _compact_price("open")
    high = _compact_price("high")
    low = _compact_price("low")

    has_volume = "volume" in matrices
    if has_volume:
        vol_raw = np.asarray(matrices["volume"][:end_idx, active_cols], dtype=np.float64)
        volume = np.take_along_axis(vol_raw, order, axis=0)
    else:
        volume = np.full((t_max, m), np.nan, dtype=np.float64)

    last_close = close[-1]
    last_open = open_[-1]

    # Moving averages
    def _trailing_mean(window: int) -> tuple[np.ndarray, np.ndarray]:
        ok = k >= window
        vals = np.full(m, np.nan, dtype=np.float64)
        if t_max >= window and ok.any():
            vals[ok] = np.round(close[-window:, ok].mean(axis=0), 4)
        return vals, ok

    ma5_vals, ma5_ok = _trailing_mean(5)
    ma20_vals, ma20_ok = _trailing_mean(20)
    ma60_vals, ma60_ok = _trailing_mean(60)

    # 60-day change: base row is max(0, len - 61) per stock
    base_rows = np.maximum(start_row, t_max - 61)
    base_close = close[base_rows, np.arange(m)]
    change60_ok = np.isfinite(base_close) & (base_close > 0)
    change_60d_raw = np.full(m, np.nan, dtype=np.float64)
    change_60d_raw[change60_ok] = (last_close[change60_ok] / base_close[change60_ok] - 1.0) * 100.0

    ma_bullish = ma5_ok & ma20_ok & ma60_ok & (ma5_vals >= ma20_vals) & (ma20_vals >= ma60_vals)
    price_above_ma20 = ma20_ok & (last_close >= ma20_vals)

    # MACD (vectorized across columns with >= 35 valid bars)
    macd_status = np.full(m, "neutral", dtype=object)
    macd_mask = k >= 35
    if macd_mask.any():
        sub_c = close[:, macd_mask]
        sub_start = start_row[macd_mask]
        min_start = int(sub_start.min())
        n_macd = sub_c.shape[1]
        ema12 = np.zeros(n_macd, dtype=np.float64)
        ema26 = np.zeros(n_macd, dtype=np.float64)
        dea = np.zeros(n_macd, dtype=np.float64)
        diff = np.zeros(n_macd, dtype=np.float64)
        for t in range(min_start, t_max):
            init = sub_start == t
            step = t > sub_start
            if init.any():
                c_t = sub_c[t]
                ema12 = np.where(init, c_t, ema12)
                ema26 = np.where(init, c_t, ema26)
                dea = np.where(init, 0.0, dea)
            if step.any():
                c_t = sub_c[t]
                ema12 = np.where(step, _EMA12_ALPHA * c_t + (1.0 - _EMA12_ALPHA) * ema12, ema12)
                ema26 = np.where(step, _EMA26_ALPHA * c_t + (1.0 - _EMA26_ALPHA) * ema26, ema26)
                diff = ema12 - ema26
                dea = np.where(step, _EMA9_ALPHA * diff + (1.0 - _EMA9_ALPHA) * dea, dea)
        sub_status = np.where(
            (diff > dea) & (diff > 0),
            "bullish",
            np.where((diff < dea) & (diff < 0), "bearish", "neutral"),
        )
        macd_status[macd_mask] = sub_status

    # RSI(14)
    rsi_raw = np.full(m, np.nan, dtype=np.float64)
    rsi_status = np.full(m, "neutral", dtype=object)
    if t_max >= 15:
        rsi_elig = k > 14
        if rsi_elig.any():
            diffs = np.diff(close[-15:, rsi_elig], axis=0)
            gain = np.clip(diffs, 0.0, None).mean(axis=0)
            loss = np.clip(-diffs, 0.0, None).mean(axis=0)
            valid_loss = loss > 0
            sub_rsi = np.full(rsi_elig.sum(), np.nan, dtype=np.float64)
            sub_rsi[valid_loss] = 100.0 - (100.0 / (1.0 + gain[valid_loss] / loss[valid_loss]))
            rsi_raw[rsi_elig] = sub_rsi
            sub_status = np.where(
                np.isfinite(sub_rsi) & (sub_rsi <= 35.0),
                "oversold",
                np.where(np.isfinite(sub_rsi) & (sub_rsi >= 70.0), "overbought", "neutral"),
            )
            rsi_status[rsi_elig] = sub_status
    rsi_ok = np.isfinite(rsi_raw)

    # Signal score
    signal_score = np.full(m, 50.0, dtype=np.float64)
    signal_score += np.where(ma_bullish, 14.0, 0.0)
    signal_score += np.where(price_above_ma20, 10.0, 0.0)
    signal_score += np.where(macd_status == "bullish", 12.0, np.where(macd_status == "bearish", -12.0, 0.0))
    c60 = np.where(change60_ok, change_60d_raw, 0.0)
    signal_score += np.where(
        change60_ok & (c60 >= 0.0) & (c60 <= 35.0),
        np.minimum(c60 * 0.35, 12.0),
        np.where(
            change60_ok & (c60 > 60.0),
            -np.minimum((c60 - 60.0) * 0.20, 12.0),
            np.where(change60_ok & (c60 < -25.0), -np.minimum(np.abs(c60 + 25.0) * 0.25, 10.0), 0.0),
        ),
    )
    signal_score += np.where(rsi_status == "oversold", 4.0, np.where(rsi_status == "overbought", -6.0, 0.0))
    signal_score = np.round(np.clip(signal_score, 0.0, 100.0), 4)

    # Shape features
    prev_high_20d_raw = np.full(m, np.nan, dtype=np.float64)
    prev_ok = k >= 2
    if t_max >= 2 and prev_ok.any():
        prev_h_slice = high[max(0, t_max - 21) : t_max - 1, prev_ok]
        prev_high_20d_raw[prev_ok] = np.nanmax(prev_h_slice, axis=0)
    prev_high_ok = np.isfinite(prev_high_20d_raw)

    breakout_ok = prev_high_ok & (prev_high_20d_raw > 0)
    breakout_20d_raw = np.full(m, np.nan, dtype=np.float64)
    breakout_20d_raw[breakout_ok] = (last_close[breakout_ok] / prev_high_20d_raw[breakout_ok] - 1.0) * 100.0

    recent_h = high[-20:, :]
    recent_l = low[-20:, :]
    recent_h_max = np.nanmax(recent_h, axis=0)
    recent_l_min = np.nanmin(recent_l, axis=0)
    range_ok = np.isfinite(recent_h_max) & np.isfinite(recent_l_min) & (recent_l_min > 0)
    range_20d_raw = np.full(m, np.nan, dtype=np.float64)
    range_20d_raw[range_ok] = (recent_h_max[range_ok] / recent_l_min[range_ok] - 1.0) * 100.0

    # Volume ratio 20d
    vol_ratio_raw = np.full(m, np.nan, dtype=np.float64)
    if has_volume and t_max >= 2:
        last_vol = volume[-1]
        vol_prev = volume[max(0, t_max - 21) : t_max - 1, :]
        vol_prev_valid = np.isfinite(vol_prev)
        vol_prev_cnt = vol_prev_valid.sum(axis=0)
        vol_prev_sum = np.where(vol_prev_valid, vol_prev, 0.0).sum(axis=0)
        vol_base = np.where(vol_prev_cnt > 0, vol_prev_sum / np.maximum(vol_prev_cnt, 1), np.nan)
        vr_ok = prev_ok & np.isfinite(last_vol) & (vol_prev_cnt > 0) & (vol_base > 0)
        vol_ratio_raw[vr_ok] = last_vol[vr_ok] / vol_base[vr_ok]
    vol_ratio_ok = np.isfinite(vol_ratio_raw)

    body_ok = np.isfinite(last_open) & (last_open > 0) & np.isfinite(last_close)
    body_pct_raw = np.full(m, np.nan, dtype=np.float64)
    body_pct_raw[body_ok] = (last_close[body_ok] / last_open[body_ok] - 1.0) * 100.0

    pullback_ok = ma20_ok & (ma20_vals > 0)
    pullback_raw = np.full(m, np.nan, dtype=np.float64)
    pullback_raw[pullback_ok] = (last_close[pullback_ok] / ma20_vals[pullback_ok] - 1.0) * 100.0

    # Consolidation days (20d)
    consol_days: list[int | None] = [None] * m
    if t_max >= 2 and prev_ok.any():
        prev_len = np.minimum(k - 1, 20)
        prev_h_all = high[max(0, t_max - 21) : t_max - 1, :]
        prev_l_all = low[max(0, t_max - 21) : t_max - 1, :]
        found_days = np.zeros(m, dtype=np.int64)
        max_win = min(20, prev_h_all.shape[0])
        for d in range(max_win, 1, -1):
            elig = (found_days == 0) & (prev_len >= d)
            if not elig.any():
                continue
            win_h = prev_h_all[-d:, elig].max(axis=0)
            win_l = prev_l_all[-d:, elig].min(axis=0)
            ok_d = (win_l > 0) & (((win_h / win_l - 1.0) * 100.0) <= 12.0)
            if ok_d.any():
                elig_idx = np.flatnonzero(elig)[ok_d]
                found_days[elig_idx] = d
        for idx in np.flatnonzero(prev_ok):
            consol_days[int(idx)] = int(found_days[idx])

    # Volatility 20d (requires >= 3 close bars => >= 2 returns)
    vol20_raw = np.full(m, np.nan, dtype=np.float64)
    if t_max >= 3:
        c20 = close[-20:, :]
        ret = (c20[1:, :] / c20[:-1, :]) - 1.0
        ret_valid = np.isfinite(ret)
        ret_cnt = ret_valid.sum(axis=0)
        vol_elig = ret_cnt >= 2
        if vol_elig.any():
            sub_ret = ret[:, vol_elig]
            sub_valid = ret_valid[:, vol_elig]
            sub_cnt = ret_cnt[vol_elig]
            mean_ret = np.where(sub_valid, sub_ret, 0.0).sum(axis=0) / sub_cnt
            sq_diff = np.where(sub_valid, (sub_ret - mean_ret[None, :]) ** 2, 0.0).sum(axis=0)
            std_ret = np.sqrt(sq_diff / (sub_cnt - 1))
            vol20_raw[vol_elig] = std_ret * (252.0 ** 0.5) * 100.0
    vol20_ok = np.isfinite(vol20_raw)

    # Max drawdown 20d
    c20 = close[-20:, :]
    c20_valid = np.isfinite(c20)
    running_high = np.maximum.accumulate(np.where(c20_valid, c20, -np.inf), axis=0)
    dd20 = np.where(c20_valid & (running_high > 0), c20 / running_high - 1.0, 0.0)
    mdd_raw = np.minimum(dd20.min(axis=0) * 100.0, 0.0)
    mdd_ok = np.isfinite(mdd_raw)

    # ATR 20 pct
    prev_c_full = np.empty_like(close)
    prev_c_full[0, :] = np.nan
    if t_max > 1:
        prev_c_full[1:, :] = close[:-1, :]
    tr = np.fmax(high - low, np.fmax(np.abs(high - prev_c_full), np.abs(low - prev_c_full)))
    tr20 = tr[-20:, :]
    tr_valid = np.isfinite(tr20)
    tr_cnt = tr_valid.sum(axis=0)
    atr_ok = (tr_cnt > 0) & (last_close > 0)
    atr_raw = np.full(m, np.nan, dtype=np.float64)
    if atr_ok.any():
        atr_mean = np.where(tr_valid[:, atr_ok], tr20[:, atr_ok], 0.0).sum(axis=0) / tr_cnt[atr_ok]
        atr_raw[atr_ok] = atr_mean / last_close[atr_ok] * 100.0
    atr_ok = np.isfinite(atr_raw)

    # Quality score & flags
    q_scores = np.full(m, 100.0, dtype=np.float64)
    q_flags: list[list[str]] = [[] for _ in range(m)]
    for idx in np.flatnonzero(k < 30):
        q_scores[idx] -= 35.0
        q_flags[int(idx)].append("short_history_lt30")
    for idx in np.flatnonzero((k >= 30) & (k < 60)):
        q_scores[idx] -= 15.0
        q_flags[int(idx)].append("short_history_lt60")

    if not has_volume:
        q_scores -= 12.0
        for flags in q_flags:
            flags.append("missing_volume")
    else:
        missing_vol_ratio = (is_valid_row & ~np.isfinite(volume)).sum(axis=0) / k
        for idx in np.flatnonzero(missing_vol_ratio > 0):
            q_scores[idx] -= min(float(missing_vol_ratio[idx]) * 20.0, 10.0)
            q_flags[int(idx)].append("incomplete_volume")
        neg_vol = (is_valid_row & np.isfinite(volume) & (volume < 0)).any(axis=0)
        for idx in np.flatnonzero(neg_vol):
            q_scores[idx] -= 20.0
            q_flags[int(idx)].append("negative_volume")

    invalid_ohlc = (
        is_valid_row
        & ((high < low) | (high < open_) | (high < close) | (low > open_) | (low > close))
    ).any(axis=0)
    for idx in np.flatnonzero(invalid_ohlc):
        q_scores[idx] -= 30.0
        q_flags[int(idx)].append("invalid_ohlc")

    non_pos = (
        is_valid_row & ((open_ <= 0) | (high <= 0) | (low <= 0) | (close <= 0))
    ).any(axis=0)
    for idx in np.flatnonzero(non_pos):
        q_scores[idx] -= 35.0
        q_flags[int(idx)].append("non_positive_price")

    q_scores = np.round(np.maximum(q_scores, 0.0), 4)
    q_flag_strs = [";".join(flags) for flags in q_flags]

    return pd.DataFrame({
        "code": active_codes.tolist(),
        "daily_data_points": k.tolist(),
        "change_60d": _round_array(change_60d_raw, change60_ok),
        "ma5": [float(v) if ok else None for v, ok in zip(ma5_vals, ma5_ok)],
        "ma20": [float(v) if ok else None for v, ok in zip(ma20_vals, ma20_ok)],
        "ma60": [float(v) if ok else None for v, ok in zip(ma60_vals, ma60_ok)],
        "ma_bullish": ma_bullish.tolist(),
        "price_above_ma20": price_above_ma20.tolist(),
        "macd_status": macd_status.tolist(),
        "rsi_status": rsi_status.tolist(),
        "rsi14": _round_array(rsi_raw, rsi_ok),
        "signal_score": signal_score.tolist(),
        "prev_high_20d": _round_array(prev_high_20d_raw, prev_high_ok),
        "range_20d_pct": _round_array(range_20d_raw, range_ok),
        "breakout_20d_pct": _round_array(breakout_20d_raw, breakout_ok),
        "volume_ratio_20d": _round_array(vol_ratio_raw, vol_ratio_ok),
        "body_pct": _round_array(body_pct_raw, body_ok),
        "pullback_to_ma20_pct": _round_array(pullback_raw, pullback_ok),
        "consolidation_days_20d": consol_days,
        "volatility_20d_pct": _round_array(vol20_raw, vol20_ok),
        "max_drawdown_20d_pct": _round_array(mdd_raw, mdd_ok),
        "atr_20_pct": _round_array(atr_raw, atr_ok),
        "daily_quality_score": q_scores.tolist(),
        "daily_quality_flags": q_flag_strs,
        "daily_source": ["pack"] * m,
    })
