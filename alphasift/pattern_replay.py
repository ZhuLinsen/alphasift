# -*- coding: utf-8 -*-
"""250-day next_open CN pattern replay, regime slicing, and graduation gate."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timezone
import math
from pathlib import Path
import time as _time
from typing import Any

import numpy as np
import pandas as pd

from alphasift.daily import _fetch_daily_sina, _fetch_daily_tencent
from alphasift.jsonutil import finite_float, safe_int
from alphasift.market_regime import (
    REGIME_STAGE_LABELS,
    REGIME_STAGE_ORDER,
    compute_limit_masks,
    compute_market_regime_series,
    summarize_regime_distribution,
)
from alphasift.pack import DailyPack, forward_adjust
from alphasift.patterns import (
    PatternSpec,
    build_pattern_context,
    compute_overhead_supply_10pct_row,
    evaluate_pattern_matrix,
    list_patterns,
    load_pattern,
)

GRADUATION_MIN_SAMPLES = 200
GRADUATION_COST_BPS = 25.0
GRADUATION_BH_FDR_ALPHA = 0.05
NEWEY_WEST_MIN_LAG = 4
REGIME_SLICE_WEIGHT_READY_SAMPLES = 100
STABILITY_MIN_HALF_SAMPLES = 30
STABILITY_MIN_HALF_DAYS = 15
STABILITY_T_STAT_THRESHOLD = 1.96
WALK_FORWARD_LOW_OVERHEAD_PCT = 15.0
WALK_FORWARD_BOUNDARY_POLICY = "purged_by_exit_date"


def _classify_split_half(signal_date: str, exit_date: object, mid_date: str) -> str:
    """Classify an observation into H1/H2, purging H1 entries whose exit crosses mid_date."""
    if signal_date >= mid_date:
        return "h2"
    ex_str = "" if exit_date is None else str(exit_date).strip()
    if ex_str and ex_str >= mid_date:
        return "purged"
    return "h1"


def load_cn_benchmark(
    benchmark_csv: Path | None = None,
    *,
    lookback_days: int = 360,
    symbol: str = "sh000300",
) -> pd.DataFrame:
    """Load CN benchmark OHLC (default CSI 300 via Tencent -> Sina fallback) for open-to-close excess."""
    if benchmark_csv is not None:
        df = pd.read_csv(benchmark_csv)
    else:
        df = None
        errors: list[str] = []
        for name, fetcher in (("tencent", _fetch_daily_tencent), ("sina", _fetch_daily_sina)):
            for attempt in range(2):
                try:
                    cand = fetcher(symbol, lookback_days=lookback_days)
                    if cand is None or cand.empty:
                        raise RuntimeError(f"{name} benchmark empty for {symbol}")
                    df = cand
                    break
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{name}[{attempt + 1}]: {exc}")
                    if attempt == 0:
                        _time.sleep(0.3)
            if df is not None:
                break
        if df is None:
            raise RuntimeError("; ".join(errors))
    if not {"date", "open", "close"}.issubset(df.columns):
        raise RuntimeError("Benchmark history missing required columns: date, open, close")
    parsed_dates = _parse_benchmark_dates(df["date"])
    open_num = pd.to_numeric(df["open"], errors="coerce").replace([float("inf"), float("-inf")], float("nan"))
    close_num = pd.to_numeric(df["close"], errors="coerce").replace([float("inf"), float("-inf")], float("nan"))
    out = pd.DataFrame({
        "date": parsed_dates.dt.strftime("%Y-%m-%d"),
        "open": open_num,
        "close": close_num,
    })
    out = out[parsed_dates.notna() & (out["open"] > 0) & (out["close"] > 0)]
    out = out.dropna(subset=["date", "open", "close"]).drop_duplicates(subset=["date"], keep="last")
    return out.sort_values("date").reset_index(drop=True)


def _parse_benchmark_dates(series: pd.Series) -> pd.Series:
    try:
        return pd.to_datetime(series, format="mixed", errors="coerce")
    except (TypeError, ValueError):
        return pd.to_datetime(series, errors="coerce")


def _extract_benchmark_maps(
    benchmark_df: pd.DataFrame | None,
) -> tuple[dict[str, float], dict[str, float]]:
    if benchmark_df is None or not isinstance(benchmark_df, pd.DataFrame) or benchmark_df.empty:
        return {}, {}
    if not {"date", "open", "close"}.issubset(benchmark_df.columns):
        return {}, {}
    parsed_dates = _parse_benchmark_dates(benchmark_df["date"])
    bench_open: dict[str, float] = {}
    bench_close: dict[str, float] = {}
    for dt_val, raw_open, raw_close in zip(parsed_dates, benchmark_df["open"], benchmark_df["close"]):
        if pd.isna(dt_val):
            continue
        day_str = dt_val.strftime("%Y-%m-%d")
        op = finite_float(raw_open)
        cl = finite_float(raw_close)
        if op is not None and op > 0.0:
            bench_open[day_str] = op
        if cl is not None and cl > 0.0:
            bench_close[day_str] = cl
    return bench_open, bench_close


def _benchmark_return_pct(b_open: object, b_close: object) -> float | None:
    op = finite_float(b_open)
    cl = finite_float(b_close)
    if op is None or cl is None or op <= 0.0 or cl <= 0.0:
        return None
    ret = (cl / op - 1.0) * 100.0
    return ret if math.isfinite(ret) else None


def _mean_or_none(vals: Sequence[object]) -> float | None:
    clean = [v for x in vals if (v := finite_float(x)) is not None]
    return round(float(np.mean(clean)), 3) if clean else None


def _median_or_none(vals: Sequence[object]) -> float | None:
    clean = [v for x in vals if (v := finite_float(x)) is not None]
    return round(float(np.median(clean)), 3) if clean else None


def _win_rate_or_none(vals: Sequence[object]) -> float | None:
    clean = [v for x in vals if (v := finite_float(x)) is not None]
    if not clean:
        return None
    return round(float(sum(1 for v in clean if v > 0) / len(clean) * 100.0), 2)


def _newey_west_t_stat(
    daily_vals: Sequence[object],
    cal_indices: Sequence[int] | None = None,
    *,
    max_lag: int = NEWEY_WEST_MIN_LAG,
) -> float | None:
    """Bartlett-kernel Newey-West HAC t-statistic aligned to trading-day grid."""
    has_cal = cal_indices is not None and len(cal_indices) == len(daily_vals)
    filtered_vals: list[float] = []
    filtered_idx: list[int] = []
    for pos, raw in enumerate(daily_vals):
        val = finite_float(raw)
        if val is None:
            continue
        filtered_vals.append(val)
        if has_cal and cal_indices is not None:
            filtered_idx.append(int(cal_indices[pos]))

    m = len(filtered_vals)
    if m < 2:
        return None
    mu = float(np.mean(filtered_vals))
    residuals = [v - mu for v in filtered_vals]
    indices = filtered_idx if has_cal else list(range(m))
    min_idx = min(indices)
    max_idx = max(indices)
    span = max_idx - min_idx + 1
    u = np.zeros(span, dtype=np.float64)
    for idx, resid in zip(indices, residuals):
        u[idx - min_idx] += resid

    lag_cap = max(0, safe_int(max_lag, default=NEWEY_WEST_MIN_LAG))
    s_nw = float(np.dot(u, u))
    for lag in range(1, min(lag_cap + 1, span)):
        weight = 1.0 - lag / (lag_cap + 1.0)
        s_nw += 2.0 * weight * float(np.dot(u[:-lag], u[lag:]))
    s_nw = max(s_nw, 0.0)
    se = math.sqrt(s_nw * (m / (m - 1.0))) / m
    if not math.isfinite(se) or se <= 1e-12:
        return None
    t_stat = mu / se
    return round(t_stat, 2) if math.isfinite(t_stat) else None


def _two_sided_p_from_t(t_val: float | None) -> float | None:
    if t_val is None or not math.isfinite(t_val):
        return None
    return float(math.erfc(abs(float(t_val)) / math.sqrt(2.0)))


def _positive_gate_p_value(t_val: float | None) -> float:
    if t_val is None or not math.isfinite(t_val) or float(t_val) <= 0.0:
        return 1.0
    p = _two_sided_p_from_t(float(t_val))
    return 1.0 if p is None else p


def _benjamini_hochberg_q_values(p_values: Sequence[float | None]) -> list[float | None]:
    """Benjamini-Hochberg step-up FDR q-values preserving input ordering."""
    indexed = [(idx, float(p)) for idx, p in enumerate(p_values) if p is not None and math.isfinite(p)]
    out: list[float | None] = [None] * len(p_values)
    if not indexed:
        return out
    indexed.sort(key=lambda item: item[1])
    m = len(indexed)
    running_min = 1.0
    for rev_idx in range(m - 1, -1, -1):
        orig_idx, p_val = indexed[rev_idx]
        rank = rev_idx + 1
        q_raw = min(1.0, p_val * m / rank)
        running_min = min(running_min, q_raw)
        out[orig_idx] = round(running_min, 6)
    return out


def _naive_daily_t_stat(daily_vals: Sequence[object]) -> float | None:
    clean = [v for x in daily_vals if (v := finite_float(x)) is not None]
    if len(clean) < 2:
        return None
    d_std = float(np.std(clean, ddof=1))
    if not math.isfinite(d_std) or d_std <= 1e-12:
        return None
    t_stat = float(np.mean(clean) / (d_std / np.sqrt(len(clean))))
    return round(t_stat, 2) if math.isfinite(t_stat) else None


def _normalize_regime_filter(
    allowed_regimes: Sequence[str] | None = None,
    excluded_regimes: Sequence[str] | None = None,
) -> tuple[set[str] | None, dict[str, Any]]:
    """Parse and validate market-regime allow/exclude filters (keys or Chinese labels)."""
    label_to_key = {label: key for key, label in REGIME_STAGE_LABELS.items()}
    valid_keys = set(REGIME_STAGE_ORDER)

    def _parse(values: Sequence[str] | None, *, name: str) -> list[str] | None:
        if values is None:
            return None
        tokens: list[str] = []
        raw_items = [values] if isinstance(values, str) else list(values)
        for raw in raw_items:
            for part in str(raw).split(","):
                tok = part.strip()
                if not tok:
                    continue
                lowered = tok.lower()
                if lowered in valid_keys:
                    tokens.append(lowered)
                elif tok in label_to_key:
                    tokens.append(label_to_key[tok])
                else:
                    raise ValueError(
                        f"Unknown market regime {tok!r} in {name}; valid stages: {', '.join(REGIME_STAGE_ORDER)}"
                    )
        if not tokens:
            raise ValueError(f"{name} cannot be empty when specified")
        ordered = [s for s in REGIME_STAGE_ORDER if s in set(tokens)]
        return ordered

    allowed_list = _parse(allowed_regimes, name="allowed_regimes")
    excluded_list = _parse(excluded_regimes, name="excluded_regimes")

    if allowed_list is None and excluded_list is None:
        return None, {
            "active": False,
            "allowed_regimes": None,
            "excluded_regimes": None,
            "effective_regimes": list(REGIME_STAGE_ORDER),
        }

    base_set = set(allowed_list) if allowed_list is not None else set(REGIME_STAGE_ORDER)
    if excluded_list is not None:
        base_set -= set(excluded_list)
    if not base_set:
        raise ValueError("Regime filter leaves no permitted market regimes")

    effective = [s for s in REGIME_STAGE_ORDER if s in base_set]
    return base_set, {
        "active": True,
        "allowed_regimes": allowed_list,
        "excluded_regimes": excluded_list,
        "effective_regimes": effective,
    }


def _summarize_walk_forward_regime_audit(
    obs_list: list[dict[str, Any]],
    *,
    mid_date: str,
    horizon: int = 5,
    date_to_idx: dict[str, int] | None = None,
    min_regime_days_h1: int = 3,
    adverse_threshold_pct: float = -0.5,
    max_overhead_pct: float = WALK_FORWARD_LOW_OVERHEAD_PCT,
) -> dict[str, Any]:
    """Zero-snooping walk-forward audit: select favorable/non-adverse regimes on H1 only, evaluate strictly OOS on H2."""
    h_key = f"t{horizon}"
    nw_lag = max(NEWEY_WEST_MIN_LAG, int(horizon) - 1)
    raw_ov = finite_float(max_overhead_pct)
    ov_cap = raw_ov if raw_ov is not None else WALK_FORWARD_LOW_OVERHEAD_PCT
    eff_min_days = max(1, safe_int(min_regime_days_h1, default=3))
    raw_adv = finite_float(adverse_threshold_pct)
    eff_adverse = raw_adv if raw_adv is not None else -0.5

    h1_by_stage_date: dict[str, dict[str, list[float]]] = {
        stage: defaultdict(list) for stage in REGIME_STAGE_ORDER
    }
    h1_ew_by_stage_date: dict[str, dict[str, list[float]]] = {
        stage: defaultdict(list) for stage in REGIME_STAGE_ORDER
    }
    h2_records: list[tuple[str, str, float, float | None, float | None]] = []
    h1_purged_signals = 0
    h1_purged_days_set: set[str] = set()

    for item in obs_list:
        res = (item.get("horizons") or {}).get(h_key)
        if not isinstance(res, dict) or res.get("status") != "ok":
            continue
        ex = res.get("net_excess_return_pct")
        if ex is None:
            ex = res.get("excess_return_pct")
        ex_val = finite_float(ex)
        if ex_val is None:
            continue
        day = str(item["date"])
        stage = str(item.get("stage") or item.get("regime_stage") or "neutral")
        if stage not in h1_by_stage_date:
            stage = "neutral"
        ew_val = finite_float(res.get("net_over_ew_pct"))

        split = _classify_split_half(day, res.get("exit_date"), mid_date)
        if split == "h1":
            h1_by_stage_date[stage][day].append(ex_val)
            if ew_val is not None:
                h1_ew_by_stage_date[stage][day].append(ew_val)
        elif split == "purged":
            h1_purged_signals += 1
            h1_purged_days_set.add(day)
        else:
            ov_val = finite_float(item.get("overhead"))
            h2_records.append((day, stage, ex_val, ew_val, ov_val))

    def _cluster_metrics(records: list[tuple[str, float, float | None]]) -> dict[str, Any]:
        if not records:
            return {
                "days": 0,
                "signals": 0,
                "daily_mean_pct": None,
                "ew_daily_mean_pct": None,
                "t_stat": None,
            }
        by_day: dict[str, list[float]] = defaultdict(list)
        ew_by_day: dict[str, list[float]] = defaultdict(list)
        for day, ex_val, ew_val in records:
            by_day[day].append(ex_val)
            if ew_val is not None:
                ew_by_day[day].append(ew_val)
        sorted_days = sorted(by_day)
        daily_series = [float(np.mean(by_day[d])) for d in sorted_days]
        ew_days = sorted(ew_by_day)
        ew_series = [float(np.mean(ew_by_day[d])) for d in ew_days]
        cal_indices = (
            [date_to_idx[d] for d in sorted_days]
            if date_to_idx is not None and all(d in date_to_idx for d in sorted_days)
            else None
        )
        return {
            "days": len(sorted_days),
            "signals": len(records),
            "daily_mean_pct": _mean_or_none(daily_series),
            "ew_daily_mean_pct": _mean_or_none(ew_series),
            "t_stat": _newey_west_t_stat(daily_series, cal_indices, max_lag=nw_lag),
        }

    h1_positive_regimes: list[str] = []
    h1_adverse_regimes: list[str] = []
    h1_non_adverse_regimes: list[str] = []
    per_regime_oos: dict[str, dict[str, Any]] = {}

    for stage in REGIME_STAGE_ORDER:
        h1_days_map = h1_by_stage_date[stage]
        h1_daily = [float(np.mean(h1_days_map[d])) for d in sorted(h1_days_map)]
        h1_mean = _mean_or_none(h1_daily)
        h1_days = len(h1_daily)
        h1_signals = sum(len(v) for v in h1_days_map.values())

        stage_h2 = [(d, ex, ew) for (d, st, ex, ew, _ov) in h2_records if st == stage]
        stage_h2_stats = _cluster_metrics(stage_h2)

        per_regime_oos[stage] = {
            "label": REGIME_STAGE_LABELS.get(stage, stage),
            "h1_days": h1_days,
            "h1_signals": h1_signals,
            "h1_daily_mean_pct": h1_mean,
            "h2_days": stage_h2_stats["days"],
            "h2_signals": stage_h2_stats["signals"],
            "h2_daily_mean_pct": stage_h2_stats["daily_mean_pct"],
            "h2_ew_daily_mean_pct": stage_h2_stats["ew_daily_mean_pct"],
        }

        if h1_days >= eff_min_days and h1_mean is not None:
            if h1_mean > 0:
                h1_positive_regimes.append(stage)
            if h1_mean <= eff_adverse:
                h1_adverse_regimes.append(stage)
            else:
                h1_non_adverse_regimes.append(stage)
        else:
            # Insufficient H1 observations in this stage: keep in non-adverse baseline rather than overfitting-dropping.
            h1_non_adverse_regimes.append(stage)

    pos_set = set(h1_positive_regimes)
    non_adv_set = set(h1_non_adverse_regimes)

    h2_baseline = _cluster_metrics([(d, ex, ew) for (d, _st, ex, ew, _ov) in h2_records])
    h2_positive = _cluster_metrics([(d, ex, ew) for (d, st, ex, ew, _ov) in h2_records if st in pos_set])
    h2_non_adverse = _cluster_metrics(
        [(d, ex, ew) for (d, st, ex, ew, _ov) in h2_records if st in non_adv_set]
    )
    h2_low_overhead = _cluster_metrics(
        [(d, ex, ew) for (d, _st, ex, ew, ov) in h2_records if ov is not None and ov < ov_cap]
    )
    h2_non_adverse_low_overhead = _cluster_metrics(
        [
            (d, ex, ew)
            for (d, st, ex, ew, ov) in h2_records
            if st in non_adv_set and ov is not None and ov < ov_cap
        ]
    )

    def _diff(lhs: float | None, rhs: float | None) -> float | None:
        if lhs is None or rhs is None:
            return None
        return round(float(lhs - rhs), 3)

    base_daily = h2_baseline["daily_mean_pct"]
    base_ew = h2_baseline["ew_daily_mean_pct"]
    has_data = h2_baseline["days"] > 0 and (h2_positive["days"] > 0 or h2_non_adverse["days"] > 0)

    return {
        "horizon": h_key,
        "status": "ok" if has_data else "insufficient_data",
        "boundary_policy": WALK_FORWARD_BOUNDARY_POLICY,
        "eval_mid_date": mid_date,
        "h1_purged_signals": h1_purged_signals,
        "h1_purged_days": len(h1_purged_days_set),
        "min_regime_days_h1": eff_min_days,
        "adverse_threshold_pct": eff_adverse,
        "low_overhead_threshold_pct": ov_cap,
        "h1_positive_regimes": h1_positive_regimes,
        "h1_adverse_regimes": h1_adverse_regimes,
        "h1_non_adverse_regimes": h1_non_adverse_regimes,
        "h2_baseline": h2_baseline,
        "h2_positive_only": h2_positive,
        "h2_non_adverse": h2_non_adverse,
        "h2_low_overhead": h2_low_overhead,
        "h2_non_adverse_low_overhead": h2_non_adverse_low_overhead,
        "delta_positive_vs_h2_baseline_pct": _diff(h2_positive["daily_mean_pct"], base_daily),
        "delta_non_adverse_vs_h2_baseline_pct": _diff(h2_non_adverse["daily_mean_pct"], base_daily),
        "delta_low_overhead_vs_h2_baseline_pct": _diff(h2_low_overhead["daily_mean_pct"], base_daily),
        "delta_non_adverse_low_overhead_vs_h2_baseline_pct": _diff(
            h2_non_adverse_low_overhead["daily_mean_pct"], base_daily
        ),
        "ew_delta_positive_vs_h2_baseline_pct": _diff(h2_positive["ew_daily_mean_pct"], base_ew),
        "ew_delta_non_adverse_vs_h2_baseline_pct": _diff(h2_non_adverse["ew_daily_mean_pct"], base_ew),
        "ew_delta_low_overhead_vs_h2_baseline_pct": _diff(h2_low_overhead["ew_daily_mean_pct"], base_ew),
        "ew_delta_non_adverse_low_overhead_vs_h2_baseline_pct": _diff(
            h2_non_adverse_low_overhead["ew_daily_mean_pct"], base_ew
        ),
        "per_regime_oos": per_regime_oos,
    }


def _summarize_stability(
    obs_list: list[dict[str, Any]],
    *,
    mid_date: str,
    horizon: int = 5,
    date_to_idx: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Date-clustered split-half sign consistency (H1 vs H2) and Newey-West HAC t-stat."""
    h_key = f"t{horizon}"
    all_vals: list[float] = []
    h1_vals: list[float] = []
    h2_vals: list[float] = []
    by_date: dict[str, list[float]] = defaultdict(list)
    h1_by_date: dict[str, list[float]] = defaultdict(list)
    h2_by_date: dict[str, list[float]] = defaultdict(list)

    ew_by_date: dict[str, list[float]] = defaultdict(list)
    ew_h1_by_date: dict[str, list[float]] = defaultdict(list)
    ew_h2_by_date: dict[str, list[float]] = defaultdict(list)
    ew_all_vals: list[float] = []
    ew_h1_count = 0
    ew_h2_count = 0
    matched_ew_by_date: dict[str, float] = {}
    h1_purged_signals = 0
    h1_purged_days_set: set[str] = set()

    for item in obs_list:
        res = item["horizons"].get(h_key)
        if not isinstance(res, dict) or res.get("status") != "ok":
            continue
        day = str(item["date"])
        split = _classify_split_half(day, res.get("exit_date"), mid_date)
        ex = res.get("net_excess_return_pct")
        if ex is None:
            ex = res.get("excess_return_pct")
        val = finite_float(ex)
        has_valid_ex = val is not None
        if val is not None:
            all_vals.append(val)
            by_date[day].append(val)
            if split == "h1":
                h1_vals.append(val)
                h1_by_date[day].append(val)
            elif split == "h2":
                h2_vals.append(val)
                h2_by_date[day].append(val)
            else:
                h1_purged_signals += 1
                h1_purged_days_set.add(day)

        ew_val = finite_float(res.get("net_over_ew_pct"))
        if ew_val is not None:
            ew_all_vals.append(ew_val)
            ew_by_date[day].append(ew_val)
            if split == "h1":
                ew_h1_count += 1
                ew_h1_by_date[day].append(ew_val)
            elif split == "h2":
                ew_h2_count += 1
                ew_h2_by_date[day].append(ew_val)
            elif not has_valid_ex:
                h1_purged_signals += 1
                h1_purged_days_set.add(day)

        same_ew_val = finite_float(res.get("same_day_ew_gross_excess_pct"))
        if same_ew_val is not None and day not in matched_ew_by_date:
            matched_ew_by_date[day] = same_ew_val

    n = len(all_vals)
    h1_n = len(h1_vals)
    h2_n = len(h2_vals)
    mean_pct = _mean_or_none(all_vals)
    h1_mean = _mean_or_none(h1_vals)
    h2_mean = _mean_or_none(h2_vals)

    pooled_t_stat: float | None = None
    if n >= 2:
        std = float(np.std(all_vals, ddof=1))
        if std > 1e-12:
            pooled_t_stat = round(float(np.mean(all_vals) / (std / np.sqrt(n))), 2)

    nw_lag = max(NEWEY_WEST_MIN_LAG, int(horizon) - 1)
    sorted_days = sorted(by_date)
    daily_all = [float(np.mean(by_date[d])) for d in sorted_days]
    h1_daily = [float(np.mean(h1_by_date[d])) for d in sorted(h1_by_date)]
    h2_daily = [float(np.mean(h2_by_date[d])) for d in sorted(h2_by_date)]

    signal_days = len(daily_all)
    h1_days = len(h1_daily)
    h2_days = len(h2_daily)
    daily_mean_pct = _mean_or_none(daily_all)
    h1_daily_mean = _mean_or_none(h1_daily)
    h2_daily_mean = _mean_or_none(h2_daily)

    cal_indices = (
        [date_to_idx[d] for d in sorted_days]
        if date_to_idx is not None and all(d in date_to_idx for d in sorted_days)
        else None
    )
    daily_t_stat = _newey_west_t_stat(daily_all, cal_indices, max_lag=nw_lag)
    naive_daily_t_stat = _naive_daily_t_stat(daily_all)

    sign_consistent = bool(
        h1_days >= STABILITY_MIN_HALF_DAYS
        and h2_days >= STABILITY_MIN_HALF_DAYS
        and h1_n >= STABILITY_MIN_HALF_SAMPLES
        and h2_n >= STABILITY_MIN_HALF_SAMPLES
        and h1_daily_mean is not None
        and h2_daily_mean is not None
        and (h1_daily_mean * h2_daily_mean > 0)
    )
    if sign_consistent and h1_daily_mean is not None and h1_daily_mean > 0:
        direction = "positive"
    elif sign_consistent and h1_daily_mean is not None and h1_daily_mean < 0:
        direction = "negative"
    else:
        direction = "mixed_or_insufficient"

    stability_ready = bool(
        n >= REGIME_SLICE_WEIGHT_READY_SAMPLES
        and h1_n >= STABILITY_MIN_HALF_SAMPLES
        and h2_n >= STABILITY_MIN_HALF_SAMPLES
        and h1_days >= STABILITY_MIN_HALF_DAYS
        and h2_days >= STABILITY_MIN_HALF_DAYS
        and sign_consistent
        and daily_t_stat is not None
        and abs(daily_t_stat) >= STABILITY_T_STAT_THRESHOLD
    )

    ew_sorted_days = sorted(ew_by_date)
    ew_daily_all = [float(np.mean(ew_by_date[d])) for d in ew_sorted_days]
    ew_h1_daily = [float(np.mean(ew_h1_by_date[d])) for d in sorted(ew_h1_by_date)]
    ew_h2_daily = [float(np.mean(ew_h2_by_date[d])) for d in sorted(ew_h2_by_date)]
    ew_signal_days = len(ew_daily_all)
    ew_h1_days = len(ew_h1_daily)
    ew_h2_days = len(ew_h2_daily)
    ew_daily_mean = _mean_or_none(ew_daily_all)
    ew_h1_daily_mean = _mean_or_none(ew_h1_daily)
    ew_h2_daily_mean = _mean_or_none(ew_h2_daily)
    ew_cal_indices = (
        [date_to_idx[d] for d in ew_sorted_days]
        if date_to_idx is not None and all(d in date_to_idx for d in ew_sorted_days)
        else None
    )
    ew_t_stat = _newey_west_t_stat(ew_daily_all, ew_cal_indices, max_lag=nw_lag)
    ew_naive_daily_t_stat = _naive_daily_t_stat(ew_daily_all)
    ew_sign_consistent = bool(
        ew_h1_days >= STABILITY_MIN_HALF_DAYS
        and ew_h2_days >= STABILITY_MIN_HALF_DAYS
        and ew_h1_count >= STABILITY_MIN_HALF_SAMPLES
        and ew_h2_count >= STABILITY_MIN_HALF_SAMPLES
        and ew_h1_daily_mean is not None
        and ew_h2_daily_mean is not None
        and (ew_h1_daily_mean * ew_h2_daily_mean > 0)
    )
    if ew_sign_consistent and ew_h1_daily_mean is not None and ew_h1_daily_mean > 0:
        ew_direction = "positive"
    elif ew_sign_consistent and ew_h1_daily_mean is not None and ew_h1_daily_mean < 0:
        ew_direction = "negative"
    else:
        ew_direction = "mixed_or_insufficient"
    matched_ew_excess_mean_pct = _mean_or_none([matched_ew_by_date[d] for d in sorted(matched_ew_by_date)])

    return {
        "boundary_policy": WALK_FORWARD_BOUNDARY_POLICY,
        "h1_purged_signals": h1_purged_signals,
        "h1_purged_days": len(h1_purged_days_set),
        "n": n,
        "mean_pct": mean_pct,
        "signal_days": signal_days,
        "daily_mean_pct": daily_mean_pct,
        "t_stat": daily_t_stat,
        "naive_daily_t_stat": naive_daily_t_stat,
        "nw_lag": nw_lag,
        "pooled_t_stat": pooled_t_stat,
        "h1_n": h1_n,
        "h1_days": h1_days,
        "h1_excess_mean_pct": h1_mean,
        "h1_daily_excess_mean_pct": h1_daily_mean,
        "h2_n": h2_n,
        "h2_days": h2_days,
        "h2_excess_mean_pct": h2_mean,
        "h2_daily_excess_mean_pct": h2_daily_mean,
        "sign_consistent": sign_consistent,
        "stable_direction": direction,
        "stability_ready": stability_ready,
        "ew_n": len(ew_all_vals),
        "ew_signal_days": ew_signal_days,
        "ew_daily_mean_pct": ew_daily_mean,
        "ew_t_stat": ew_t_stat,
        "ew_naive_daily_t_stat": ew_naive_daily_t_stat,
        "ew_h1_n": ew_h1_count,
        "ew_h1_days": ew_h1_days,
        "ew_h1_daily_mean_pct": ew_h1_daily_mean,
        "ew_h2_n": ew_h2_count,
        "ew_h2_days": ew_h2_days,
        "ew_h2_daily_mean_pct": ew_h2_daily_mean,
        "ew_sign_consistent": ew_sign_consistent,
        "ew_stable_direction": ew_direction,
        "matched_ew_excess_mean_pct": matched_ew_excess_mean_pct,
    }


def _summarize_horizon_obs(
    obs_list: list[dict[str, Any]],
    horizon: int,
    *,
    net_cost_bps: float = GRADUATION_COST_BPS,
    applied_cost_bps: float = 0.0,
) -> dict[str, Any]:
    raws: list[float] = []
    excesses: list[float] = []
    gross_excesses: list[float] = []
    pending = 0
    delayed = 0
    h_key = f"t{horizon}"
    for item in obs_list:
        res = item["horizons"].get(h_key)
        if res is None:
            continue
        status = res["status"]
        if status == "ok":
            raw_val = finite_float(res.get("raw_return_pct"))
            if raw_val is None:
                continue
            raws.append(raw_val)
            ex_val = finite_float(res.get("excess_return_pct"))
            g_ex_val = finite_float(res.get("gross_excess_return_pct", ex_val))
            if ex_val is not None:
                excesses.append(ex_val)
            if g_ex_val is not None:
                gross_excesses.append(g_ex_val)
            if res.get("exit_delayed"):
                delayed += 1
        elif status == "pending":
            pending += 1

    eff_net_cost_bps = finite_float(net_cost_bps)
    if eff_net_cost_bps is None:
        eff_net_cost_bps = GRADUATION_COST_BPS
    eff_applied_cost_bps = finite_float(applied_cost_bps)
    if eff_applied_cost_bps is None:
        eff_applied_cost_bps = 0.0

    scored = len(raws)
    excess_scored = len(excesses)
    excess_mean = _mean_or_none(excesses)
    gross_excess_mean = _mean_or_none(gross_excesses)
    if eff_applied_cost_bps > 0.0:
        net_excess_mean = excess_mean
    elif gross_excess_mean is not None:
        net_excess_mean = round(float(gross_excess_mean) - eff_net_cost_bps / 100.0, 3)
    else:
        net_excess_mean = None
    return {
        "horizon_days": horizon,
        "scored": scored,
        "excess_scored": excess_scored,
        "unmatched_benchmark": max(0, scored - excess_scored),
        "pending": pending,
        "exit_delayed_count": delayed,
        "raw_mean_pct": _mean_or_none(raws),
        "raw_median_pct": _median_or_none(raws),
        "win_rate_pct": _win_rate_or_none(raws),
        "excess_mean_pct": excess_mean,
        "gross_excess_mean_pct": gross_excess_mean,
        "net_excess_mean_pct": net_excess_mean,
        "excess_median_pct": _median_or_none(excesses),
        "excess_win_rate_pct": _win_rate_or_none(excesses),
    }


def _evaluate_graduation(
    spec: PatternSpec,
    t5_summary: dict[str, Any],
    *,
    stability: dict[str, Any] | None = None,
    universe_baseline_t5: dict[str, Any] | None = None,
    net_cost_bps: float = GRADUATION_COST_BPS,
    multiple_testing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw_scored = int(t5_summary.get("scored", 0))
    matched_scored = int(t5_summary.get("excess_scored", 0))
    gross_excess = t5_summary.get("gross_excess_mean_pct", t5_summary.get("excess_mean_pct"))
    effective_net = t5_summary.get("net_excess_mean_pct")
    if effective_net is None:
        effective_net = t5_summary.get("excess_mean_pct")

    samples_ok = matched_scored >= GRADUATION_MIN_SAMPLES
    net_excess_ok = effective_net is not None and float(effective_net) > 0.0

    # 1) Fail-closed stability & split-half / Newey-West HAC check
    stability_missing = stability is None
    if stability is None:
        stability_ok = False
    else:
        t_val = stability.get("t_stat")
        half_days_ok = True
        if stability.get("h1_days") is not None and stability.get("h2_days") is not None:
            half_days_ok = (
                int(stability["h1_days"]) >= STABILITY_MIN_HALF_DAYS
                and int(stability["h2_days"]) >= STABILITY_MIN_HALF_DAYS
            )
        half_n_ok = True
        if stability.get("h1_n") is not None and stability.get("h2_n") is not None:
            half_n_ok = (
                int(stability["h1_n"]) >= STABILITY_MIN_HALF_SAMPLES
                and int(stability["h2_n"]) >= STABILITY_MIN_HALF_SAMPLES
            )
        daily_pos_ok = True
        if stability.get("daily_mean_pct") is not None:
            daily_pos_ok = float(stability["daily_mean_pct"]) > 0.0
        stability_ok = bool(
            stability.get("sign_consistent")
            and stability.get("stable_direction") == "positive"
            and t_val is not None
            and float(t_val) >= STABILITY_T_STAT_THRESHOLD
            and half_days_ok
            and half_n_ok
            and daily_pos_ok
        )

    # 2) Same-day matched All-A equal-weight alpha check (fallback to aggregate baseline in unit tests; fail-closed if absent)
    ew_bench = (universe_baseline_t5 or {}).get("equal_weight_excess_mean_pct")
    matched_ew_mean = stability.get("ew_daily_mean_pct") if stability is not None else None
    matched_ew_used = matched_ew_mean is not None
    ew_missing = False
    if matched_ew_used and stability is not None:
        ew_t_val = stability.get("ew_t_stat")
        beats_universe_ok = bool(
            float(matched_ew_mean) > 0.0
            and stability.get("ew_sign_consistent")
            and stability.get("ew_stable_direction") == "positive"
            and ew_t_val is not None
            and float(ew_t_val) >= STABILITY_T_STAT_THRESHOLD
        )
    elif ew_bench is not None:
        beats_universe_ok = effective_net is not None and float(effective_net) > float(ew_bench)
    else:
        beats_universe_ok = False
        ew_missing = True

    # 3) Multiple-testing BH-FDR check (applied in full replay across tested patterns)
    bh_fdr_ok = True if multiple_testing is None else bool(multiple_testing.get("bh_fdr_pass"))

    passed = bool(samples_ok and net_excess_ok and beats_universe_ok and stability_ok and bh_fdr_ok)
    reasons: list[str] = []
    if not samples_ok:
        reasons.append(f"样本 {matched_scored}（总完成 {raw_scored}）< {GRADUATION_MIN_SAMPLES}")
    if effective_net is None:
        reasons.append("缺少基准超额收益数据")
    elif not net_excess_ok:
        reasons.append(f"扣 {float(net_cost_bps):.0f}bp 净超额 {float(effective_net):+.3f}% <= 0%")
    if not beats_universe_ok:
        if ew_missing:
            reasons.append("缺少全A等权基线数据")
        elif matched_ew_used and stability is not None:
            ew_t_txt = "-" if stability.get("ew_t_stat") is None else f"{float(stability['ew_t_stat']):+.2f}"
            reasons.append(
                f"同信号日扣 {float(net_cost_bps):.0f}bp 跑赢全A等权未达标"
                f"（日均 {float(matched_ew_mean):+.3f}%，NW t={ew_t_txt}）"
            )
        elif ew_bench is not None:
            eff_str = "-" if effective_net is None else f"{float(effective_net):+.3f}%"
            reasons.append(f"净超额 {eff_str} 未跑赢全A等权基线 {float(ew_bench):+.3f}%")
    if not stability_ok:
        if stability_missing:
            reasons.append("缺少分半期稳定性与 Newey-West 聚日检验数据")
        else:
            t_txt = "-" if stability is None or stability.get("t_stat") is None else f"{float(stability['t_stat']):+.2f}"
            reasons.append(
                f"H1/H2（各>={STABILITY_MIN_HALF_DAYS}d且>={STABILITY_MIN_HALF_SAMPLES}样本）未同号正超额"
                f"或 NW t={t_txt} < {STABILITY_T_STAT_THRESHOLD}"
            )
    if not bh_fdr_ok and multiple_testing is not None:
        q_csi = multiple_testing.get("bh_q_value_csi300")
        q_ew = multiple_testing.get("bh_q_value_ew")
        reasons.append(f"多重检验 BH-FDR 未通过（q_csi300={q_csi}, q_ew={q_ew} > {GRADUATION_BH_FDR_ALPHA}）")

    if passed:
        ew_part = (
            f"同日跑赢全A等权 {float(matched_ew_mean):+.3f}%（t={float(stability['ew_t_stat']):+.2f}）"
            if matched_ew_used and stability is not None and stability.get("ew_t_stat") is not None
            else "跑赢全A等权基线"
        )
        reason = (
            f"达标：样本 {matched_scored} >= {GRADUATION_MIN_SAMPLES}，扣 {float(net_cost_bps):.0f}bp "
            f"净超额 {float(effective_net):+.3f}% > 0 且{ew_part}，"
            f"H1/H2 同号正超额且 NW t={float(stability['t_stat']):+.2f}"
        )
    else:
        reason = "未达标：" + "；".join(reasons)

    return {
        "passed": passed,
        "current_yaml_status": spec.status,
        "recommended_status": "active" if passed else "experimental",
        "min_samples": GRADUATION_MIN_SAMPLES,
        "t5_scored": raw_scored,
        "t5_excess_scored": matched_scored,
        "t5_unmatched_benchmark": int(t5_summary.get("unmatched_benchmark", max(0, raw_scored - matched_scored))),
        "t5_excess_mean_pct": t5_summary.get("excess_mean_pct"),
        "t5_gross_excess_mean_pct": gross_excess,
        "t5_net_excess_mean_pct": effective_net,
        "checks": {
            "samples_ok": samples_ok,
            "net_excess_ok": net_excess_ok,
            "beats_universe_ok": beats_universe_ok,
            "stability_ok": stability_ok,
            "bh_fdr_ok": bh_fdr_ok,
            "net_cost_bps": float(net_cost_bps),
            "matched_date_ew_used": matched_ew_used,
        },
        "reason": reason,
    }


def _overhead_bucket(val: float | None) -> str | None:
    if val is None or not np.isfinite(val):
        return None
    if val < 15.0:
        return "low_lt15"
    if val < 35.0:
        return "mid_15_35"
    return "high_ge35"


def _compute_universe_baseline_with_daily(
    *,
    adj_open: np.ndarray,
    adj_close: np.ndarray,
    raw_close: np.ndarray,
    raw_volume: np.ndarray,
    active: np.ndarray,
    one_lu: np.ndarray,
    one_ld: np.ndarray,
    dates: list[str],
    bench_open: dict[str, float],
    bench_close: dict[str, float],
    warmup_days: int,
    end_t: int,
    horizons: tuple[int, ...],
    cost_bps: float,
    liquid_proxy_amount_min: float = 80_000_000.0,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, dict[str, float]]]]:
    """Equal-weight and liquid-universe ``next_open`` baseline plus per-day EW maps."""
    proxy_amt = np.asarray(raw_close, dtype=np.float64) * np.asarray(raw_volume, dtype=np.float64)
    cost_pct = float(cost_bps) / 100.0
    baseline: dict[str, dict[str, Any]] = {}
    daily_ew_by_horizon: dict[str, dict[str, dict[str, float]]] = {}
    t_len = len(dates)

    for h in horizons:
        ew_raw: list[float] = []
        ew_ex: list[float] = []
        ew_gross_ex: list[float] = []
        liq_raw: list[float] = []
        liq_ex: list[float] = []
        bench_rets: list[float] = []
        daily_ew_map: dict[str, dict[str, float]] = {}

        for t in range(warmup_days, end_t):
            t_in = t + 1
            t_out = t + h
            if t_in >= t_len or t_out >= t_len:
                continue
            bo = bench_open.get(dates[t_in])
            bc = bench_close.get(dates[t_out])
            bench_ret = _benchmark_return_pct(bo, bc)
            if bench_ret is None:
                continue

            tradable = (
                active[t]
                & active[t_in]
                & active[t_out]
                & ~one_lu[t_in]
                & ~one_ld[t_out]
                & np.isfinite(adj_open[t_in])
                & (adj_open[t_in] > 0)
                & np.isfinite(adj_close[t_out])
                & (adj_close[t_out] > 0)
            )
            if not np.any(tradable):
                continue

            gross_rets = (adj_close[t_out, tradable] / adj_open[t_in, tradable] - 1.0) * 100.0
            mean_ew_gross = float(np.mean(gross_rets))
            mean_ew_net = mean_ew_gross - cost_pct
            ew_raw.append(mean_ew_net)
            bench_rets.append(float(bench_ret))
            ew_ex.append(mean_ew_net - float(bench_ret))
            ew_gross_ex.append(mean_ew_gross - float(bench_ret))
            daily_ew_map[dates[t]] = {
                "gross_raw_pct": mean_ew_gross,
                "gross_excess_pct": mean_ew_gross - float(bench_ret),
                "net_raw_pct": mean_ew_net,
                "net_excess_pct": mean_ew_net - float(bench_ret),
            }

            liq_mask = tradable & np.isfinite(proxy_amt[t]) & (proxy_amt[t] >= liquid_proxy_amount_min)
            if np.any(liq_mask):
                rets_l = (adj_close[t_out, liq_mask] / adj_open[t_in, liq_mask] - 1.0) * 100.0 - cost_pct
                mean_liq = float(np.mean(rets_l))
                liq_raw.append(mean_liq)
                liq_ex.append(mean_liq - float(bench_ret))

        daily_ew_by_horizon[f"t{h}"] = daily_ew_map
        baseline[f"t{h}"] = {
            "horizon_days": h,
            "sessions": len(ew_raw),
            "benchmark_mean_pct": _mean_or_none(bench_rets),
            "equal_weight_raw_mean_pct": _mean_or_none(ew_raw),
            "equal_weight_excess_mean_pct": _mean_or_none(ew_ex),
            "equal_weight_gross_excess_mean_pct": _mean_or_none(ew_gross_ex),
            "liquid_raw_mean_pct": _mean_or_none(liq_raw),
            "liquid_excess_mean_pct": _mean_or_none(liq_ex),
            "liquid_proxy_amount_min": liquid_proxy_amount_min,
        }
    return baseline, daily_ew_by_horizon


def _compute_universe_baseline(
    *,
    adj_open: np.ndarray,
    adj_close: np.ndarray,
    raw_close: np.ndarray,
    raw_volume: np.ndarray,
    active: np.ndarray,
    one_lu: np.ndarray,
    one_ld: np.ndarray,
    dates: list[str],
    bench_open: dict[str, float],
    bench_close: dict[str, float],
    warmup_days: int,
    end_t: int,
    horizons: tuple[int, ...],
    cost_bps: float,
    liquid_proxy_amount_min: float = 80_000_000.0,
) -> dict[str, dict[str, Any]]:
    """Equal-weight and liquid-universe ``next_open`` baseline over ``[warmup_days, end_t)``."""
    baseline, _ = _compute_universe_baseline_with_daily(
        adj_open=adj_open,
        adj_close=adj_close,
        raw_close=raw_close,
        raw_volume=raw_volume,
        active=active,
        one_lu=one_lu,
        one_ld=one_ld,
        dates=dates,
        bench_open=bench_open,
        bench_close=bench_close,
        warmup_days=warmup_days,
        end_t=end_t,
        horizons=horizons,
        cost_bps=cost_bps,
        liquid_proxy_amount_min=liquid_proxy_amount_min,
    )
    return baseline


def replay_patterns(
    daily_pack: DailyPack,
    *,
    patterns: Sequence[str] | None = None,
    benchmark_df: pd.DataFrame | None = None,
    horizons: tuple[int, ...] = (5, 10),
    warmup_days: int = 60,
    cost_bps: float = 0.0,
    patterns_dir: Path | None = None,
    allowed_regimes: Sequence[str] | None = None,
    excluded_regimes: Sequence[str] | None = None,
    max_overhead_pct: float | None = None,
) -> dict[str, Any]:
    """Replay CN patterns point-in-time on ``daily_pack`` using ``next_open`` + tradability rules."""
    sorted_horizons = tuple(
        sorted({int(h) for h in horizons if not isinstance(h, bool) and (finite_float(h) or 0) > 0})
    )
    if not sorted_horizons:
        raise ValueError("horizons must include at least one positive integer")
    max_h = max(sorted_horizons)

    eff_cost_bps = finite_float(cost_bps)
    if eff_cost_bps is None or eff_cost_bps < 0.0:
        raise ValueError(f"cost_bps must be a finite non-negative number, got {cost_bps!r}")

    if isinstance(warmup_days, bool) or finite_float(warmup_days) is None or int(warmup_days) < 0:
        raise ValueError(f"warmup_days must be a non-negative integer, got {warmup_days!r}")
    warmup_days = int(warmup_days)

    if patterns:
        specs = [load_pattern(name, patterns_dir=patterns_dir) for name in patterns]
    else:
        specs = list_patterns(include_experimental=True, patterns_dir=patterns_dir)

    if benchmark_df is None:
        benchmark_df = load_cn_benchmark(lookback_days=max(len(daily_pack.dates) + 40, 320))

    bench_open, bench_close = _extract_benchmark_maps(benchmark_df)

    limit_masks = compute_limit_masks(daily_pack)
    regime_series = compute_market_regime_series(daily_pack, masks=limit_masks)
    ctx = build_pattern_context(daily_pack)
    adj = forward_adjust(daily_pack)

    dates = [str(d) for d in daily_pack.dates]
    t_len = len(dates)
    end_t = t_len - max_h
    if end_t <= warmup_days:
        raise ValueError(
            f"Not enough sessions ({t_len}) for warmup_days={warmup_days} and max horizon={max_h}"
        )

    active = limit_masks["active"]
    one_lu = limit_masks["is_one_price_limit_up"]
    one_ld = limit_masks["is_one_price_limit_down"]
    adj_open = np.asarray(adj["open"], dtype=np.float64)
    adj_close = np.asarray(adj["close"], dtype=np.float64)

    eval_regimes = regime_series[warmup_days:end_t]
    regime_distribution = summarize_regime_distribution(eval_regimes)
    mid_date = dates[warmup_days + (end_t - warmup_days) // 2]
    gate_cost_bps = eff_cost_bps if eff_cost_bps > 0.0 else GRADUATION_COST_BPS
    date_to_idx = {d: i for i, d in enumerate(dates)}
    universe_baseline, daily_ew_by_horizon = _compute_universe_baseline_with_daily(
        adj_open=adj_open,
        adj_close=adj_close,
        raw_close=daily_pack.matrices["close"],
        raw_volume=daily_pack.matrices["volume"],
        active=active,
        one_lu=one_lu,
        one_ld=one_ld,
        dates=dates,
        bench_open=bench_open,
        bench_close=bench_close,
        warmup_days=warmup_days,
        end_t=end_t,
        horizons=sorted_horizons,
        cost_bps=eff_cost_bps,
    )

    ov_ceiling: float | None = None
    if max_overhead_pct is not None:
        if isinstance(max_overhead_pct, bool):
            raise ValueError("max_overhead_pct must be a number in (0, 100]")
        try:
            ov_arg = float(max_overhead_pct)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid max_overhead_pct: {max_overhead_pct!r}") from exc
        if not math.isfinite(ov_arg) or ov_arg <= 0.0 or ov_arg > 100.0:
            raise ValueError(f"max_overhead_pct must be in (0, 100], got {max_overhead_pct!r}")
        ov_ceiling = ov_arg

    allowed_stage_set, regime_filter_meta = _normalize_regime_filter(
        allowed_regimes,
        excluded_regimes,
    )

    preliminary_reports: list[dict[str, Any]] = []
    for spec in specs:
        sig_mask, _ = evaluate_pattern_matrix(ctx, spec)
        total_signals = 0
        untradable_count = 0
        observations: list[dict[str, Any]] = []
        regime_signal_counts: dict[str, int] = {stage: 0 for stage in REGIME_STAGE_ORDER}
        regime_untradable_counts: dict[str, int] = {stage: 0 for stage in REGIME_STAGE_ORDER}

        for t in range(warmup_days, end_t):
            stage = regime_series[t].regime_stage
            if allowed_stage_set is not None and stage not in allowed_stage_set:
                continue
            cols = np.flatnonzero(sig_mask[t])
            if cols.size == 0:
                continue
            overhead_vals = compute_overhead_supply_10pct_row(ctx, t, cols)
            day_str = dates[t]

            for pos, j in enumerate(cols.tolist()):
                ov_val = float(overhead_vals[pos]) if np.isfinite(overhead_vals[pos]) else None
                if ov_ceiling is not None and (ov_val is None or ov_val >= ov_ceiling):
                    continue
                total_signals += 1
                regime_signal_counts[stage] = regime_signal_counts.get(stage, 0) + 1

                future_active = np.flatnonzero(active[t + 1 :, j]) + (t + 1)
                if future_active.size == 0:
                    observations.append({
                        "date": day_str,
                        "code": str(ctx.codes[j]),
                        "stage": stage,
                        "overhead": ov_val,
                        "untradable": False,
                        "horizons": {f"t{h}": {"status": "pending"} for h in sorted_horizons},
                    })
                    continue

                t_entry = int(future_active[0])
                entry_open_px = float(adj_open[t_entry, j])
                if one_lu[t_entry, j] or not np.isfinite(entry_open_px) or entry_open_px <= 0:
                    untradable_count += 1
                    regime_untradable_counts[stage] = regime_untradable_counts.get(stage, 0) + 1
                    observations.append({
                        "date": day_str,
                        "code": str(ctx.codes[j]),
                        "stage": stage,
                        "overhead": ov_val,
                        "untradable": True,
                        "horizons": {},
                    })
                    continue

                entry_date = dates[t_entry]
                b_open = bench_open.get(entry_date)
                h_map: dict[str, dict[str, Any]] = {}
                for h in sorted_horizons:
                    k = h - 1
                    while k < future_active.size and one_ld[int(future_active[k]), j]:
                        k += 1
                    if k >= future_active.size:
                        h_map[f"t{h}"] = {"status": "pending"}
                        continue
                    t_exit = int(future_active[k])
                    exit_close_px = float(adj_close[t_exit, j])
                    if not np.isfinite(exit_close_px) or exit_close_px <= 0:
                        h_map[f"t{h}"] = {"status": "pending"}
                        continue
                    gross_raw_ret = (exit_close_px / entry_open_px - 1.0) * 100.0
                    raw_ret = gross_raw_ret - eff_cost_bps / 100.0
                    exit_date = dates[t_exit]
                    b_close = bench_close.get(exit_date)
                    gross_excess_ret = None
                    excess_ret = None
                    net_excess_ret = None
                    bench_ret = _benchmark_return_pct(b_open, b_close)
                    if bench_ret is not None:
                        gross_excess_ret = gross_raw_ret - bench_ret
                        excess_ret = raw_ret - bench_ret
                        net_excess_ret = gross_excess_ret - gate_cost_bps / 100.0
                    ew_day = (daily_ew_by_horizon.get(f"t{h}") or {}).get(day_str)
                    same_day_ew_gross_excess_pct = (
                        float(ew_day["gross_excess_pct"]) if ew_day is not None else None
                    )
                    net_over_ew_pct = (
                        (gross_raw_ret - gate_cost_bps / 100.0) - float(ew_day["gross_raw_pct"])
                        if ew_day is not None
                        else None
                    )
                    h_map[f"t{h}"] = {
                        "status": "ok",
                        "entry_date": entry_date,
                        "exit_date": exit_date,
                        "raw_return_pct": raw_ret,
                        "gross_raw_return_pct": gross_raw_ret,
                        "excess_return_pct": excess_ret,
                        "gross_excess_return_pct": gross_excess_ret,
                        "net_excess_return_pct": net_excess_ret,
                        "same_day_ew_gross_excess_pct": same_day_ew_gross_excess_pct,
                        "net_over_ew_pct": net_over_ew_pct,
                        "exit_delayed": bool(k > h - 1),
                    }

                observations.append({
                    "date": day_str,
                    "code": str(ctx.codes[j]),
                    "stage": stage,
                    "overhead": ov_val,
                    "untradable": False,
                    "horizons": h_map,
                })

        untradable_share = round((untradable_count / total_signals) * 100.0, 2) if total_signals > 0 else 0.0
        horizons_summary = {
            f"t{h}": _summarize_horizon_obs(
                observations, h, net_cost_bps=gate_cost_bps, applied_cost_bps=eff_cost_bps
            )
            for h in sorted_horizons
        }
        primary_t5 = horizons_summary.get("t5") or horizons_summary[f"t{sorted_horizons[0]}"]
        primary_h = int(sorted_horizons[0]) if 5 not in sorted_horizons else 5
        stability = _summarize_stability(
            observations,
            mid_date=mid_date,
            horizon=primary_h,
            date_to_idx=date_to_idx,
        )
        walk_forward_regime_audit = _summarize_walk_forward_regime_audit(
            observations,
            mid_date=mid_date,
            horizon=primary_h,
            date_to_idx=date_to_idx,
        )

        by_regime: dict[str, Any] = {}
        for stage in REGIME_STAGE_ORDER:
            stage_obs = [o for o in observations if o["stage"] == stage]
            sig_n = regime_signal_counts.get(stage, 0)
            unt_n = regime_untradable_counts.get(stage, 0)
            s_t5 = _summarize_horizon_obs(stage_obs, 5, net_cost_bps=gate_cost_bps, applied_cost_bps=float(cost_bps)) if 5 in sorted_horizons else None
            s_t10 = _summarize_horizon_obs(stage_obs, 10, net_cost_bps=gate_cost_bps, applied_cost_bps=float(cost_bps)) if 10 in sorted_horizons else None
            stage_stab = _summarize_stability(
                stage_obs,
                mid_date=mid_date,
                horizon=primary_h,
                date_to_idx=date_to_idx,
            )
            t5_scored = int(s_t5["scored"]) if s_t5 else 0
            t5_excess_scored = int(s_t5["excess_scored"]) if s_t5 else 0
            by_regime[stage] = {
                "label": REGIME_STAGE_LABELS[stage],
                "signals": sig_n,
                "untradable_count": unt_n,
                "untradable_share_pct": round((unt_n / sig_n) * 100.0, 2) if sig_n > 0 else 0.0,
                "t5_scored": t5_scored,
                "t5_excess_scored": t5_excess_scored,
                "t5_raw_mean_pct": s_t5["raw_mean_pct"] if s_t5 else None,
                "t5_excess_mean_pct": s_t5["excess_mean_pct"] if s_t5 else None,
                "t5_win_rate_pct": s_t5["win_rate_pct"] if s_t5 else None,
                "t10_scored": int(s_t10["scored"]) if s_t10 else 0,
                "t10_excess_mean_pct": s_t10["excess_mean_pct"] if s_t10 else None,
                "weight_eval_ready": t5_excess_scored >= REGIME_SLICE_WEIGHT_READY_SAMPLES,
                "stability": stage_stab,
                "stability_ready": stage_stab["stability_ready"],
            }

        by_overhead: dict[str, Any] = {}
        for bucket in ("low_lt15", "mid_15_35", "high_ge35"):
            b_obs = [o for o in observations if _overhead_bucket(o["overhead"]) == bucket]
            s_t5 = _summarize_horizon_obs(b_obs, 5, net_cost_bps=gate_cost_bps, applied_cost_bps=float(cost_bps)) if 5 in sorted_horizons else None
            s_t10 = _summarize_horizon_obs(b_obs, 10, net_cost_bps=gate_cost_bps, applied_cost_bps=float(cost_bps)) if 10 in sorted_horizons else None
            b_stab = _summarize_stability(
                b_obs,
                mid_date=mid_date,
                horizon=primary_h,
                date_to_idx=date_to_idx,
            )
            by_overhead[bucket] = {
                "signals": len(b_obs),
                "t5_scored": int(s_t5["scored"]) if s_t5 else 0,
                "t5_excess_scored": int(s_t5["excess_scored"]) if s_t5 else 0,
                "t5_excess_mean_pct": s_t5["excess_mean_pct"] if s_t5 else None,
                "t5_win_rate_pct": s_t5["win_rate_pct"] if s_t5 else None,
                "t10_scored": int(s_t10["scored"]) if s_t10 else 0,
                "t10_excess_mean_pct": s_t10["excess_mean_pct"] if s_t10 else None,
                "stability": b_stab,
            }

        monthly_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for o in observations:
            monthly_groups[o["date"][:7]].append(o)
        by_month: dict[str, Any] = {}
        for ym in sorted(monthly_groups):
            m_obs = monthly_groups[ym]
            s_t5 = _summarize_horizon_obs(m_obs, 5, net_cost_bps=gate_cost_bps, applied_cost_bps=float(cost_bps)) if 5 in sorted_horizons else None
            s_t10 = _summarize_horizon_obs(m_obs, 10, net_cost_bps=gate_cost_bps, applied_cost_bps=float(cost_bps)) if 10 in sorted_horizons else None
            by_month[ym] = {
                "signals": len(m_obs),
                "t5_scored": int(s_t5["scored"]) if s_t5 else 0,
                "t5_excess_mean_pct": s_t5["excess_mean_pct"] if s_t5 else None,
                "t10_excess_mean_pct": s_t10["excess_mean_pct"] if s_t10 else None,
            }

        preliminary_reports.append({
            "spec": spec,
            "primary_t5": primary_t5,
            "primary_h": primary_h,
            "total_signals": total_signals,
            "untradable_count": untradable_count,
            "untradable_share_pct": untradable_share,
            "horizons": horizons_summary,
            "stability": stability,
            "by_regime": by_regime,
            "by_overhead_supply": by_overhead,
            "by_month": by_month,
            "walk_forward_regime_audit": walk_forward_regime_audit,
        })

    n_tested = len(preliminary_reports)
    p_csi = [_positive_gate_p_value(item["stability"].get("t_stat")) for item in preliminary_reports]
    p_ew = [_positive_gate_p_value(item["stability"].get("ew_t_stat")) for item in preliminary_reports]
    q_csi = _benjamini_hochberg_q_values(p_csi)
    q_ew = _benjamini_hochberg_q_values(p_ew)

    pattern_reports: list[dict[str, Any]] = []
    for idx, item in enumerate(preliminary_reports):
        spec = item["spec"]
        primary_t5 = item["primary_t5"]
        primary_h = item["primary_h"]
        stability = item["stability"]
        qc = q_csi[idx]
        qe = q_ew[idx]
        mt = {
            "n_patterns_tested": n_tested,
            "fdr_alpha": GRADUATION_BH_FDR_ALPHA,
            "p_value_csi300": round(p_csi[idx], 6),
            "bh_q_value_csi300": qc,
            "p_value_ew": round(p_ew[idx], 6),
            "bh_q_value_ew": qe,
            "bh_fdr_pass": bool(
                n_tested >= 1
                and qc is not None
                and qc <= GRADUATION_BH_FDR_ALPHA
                and qe is not None
                and qe <= GRADUATION_BH_FDR_ALPHA
            ),
        }
        graduation = _evaluate_graduation(
            spec,
            primary_t5,
            stability=stability,
            universe_baseline_t5=universe_baseline.get(f"t{primary_h}"),
            net_cost_bps=gate_cost_bps,
            multiple_testing=mt,
        )
        pattern_reports.append({
            "pattern": spec.name,
            "display_name": spec.display_name,
            "family": spec.family,
            "mode": spec.mode,
            "aligned_strategy": spec.aligned_strategy,
            "total_signals": item["total_signals"],
            "untradable_count": item["untradable_count"],
            "untradable_share_pct": item["untradable_share_pct"],
            "horizons": item["horizons"],
            "graduation": graduation,
            "stability": stability,
            "multiple_testing": mt,
            "by_regime": item["by_regime"],
            "by_overhead_supply": item["by_overhead_supply"],
            "by_month": item["by_month"],
            "walk_forward_regime_audit": item["walk_forward_regime_audit"],
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entry_mode": "next_open",
        "benchmark": "sh000300",
        "cost_bps": float(cost_bps),
        "regime_filter": regime_filter_meta,
        "overhead_filter": {"active": ov_ceiling is not None, "max_overhead_pct": ov_ceiling},
        "graduation_rule": {
            "min_samples": GRADUATION_MIN_SAMPLES,
            "net_cost_bps": gate_cost_bps,
            "t5_net_excess_mean_pct_gt": 0.0,
            "beats_same_day_universe_equal_weight": True,
            "split_half_positive_consistent": True,
            "min_half_days": STABILITY_MIN_HALF_DAYS,
            "min_half_samples": STABILITY_MIN_HALF_SAMPLES,
            "min_clustered_t_stat": STABILITY_T_STAT_THRESHOLD,
            "newey_west_min_lag": NEWEY_WEST_MIN_LAG,
            "bh_fdr_alpha": GRADUATION_BH_FDR_ALPHA,
        },
        "regime_weight_policy": "reporting_and_slice_only",
        "pack_summary": {
            "dates_total": t_len,
            "codes_total": int(len(daily_pack.codes)),
            "eval_sessions": int(end_t - warmup_days),
            "eval_start_date": dates[warmup_days],
            "eval_mid_date": mid_date,
            "eval_end_date": dates[end_t - 1],
            "pack_end_date": dates[-1],
        },
        "regime_distribution": regime_distribution,
        "universe_baseline": universe_baseline,
        "patterns": pattern_reports,
    }


def _fmt_pct(val: float | None) -> str:
    return "-" if val is None else f"{val:+.2f}%"


def _fmt_rate(val: float | None) -> str:
    return "-" if val is None else f"{val:.1f}%"


def render_replay_markdown(report: dict[str, Any]) -> str:
    """Render concise Markdown report for pattern replay, regime slices, and gating."""
    ps = report["pack_summary"]
    ub = (report.get("universe_baseline") or {}).get("t5") or {}
    baseline_line: list[str] = []
    if ub.get("sessions"):
        baseline_line = [
            f"- 同期样本基线 (T+5, {ub['sessions']} 日): 基准均值 {_fmt_pct(ub.get('benchmark_mean_pct'))} | "
            f"全A等权超额 {_fmt_pct(ub.get('equal_weight_excess_mean_pct'))} | "
            f"流动性>=8000万超额 {_fmt_pct(ub.get('liquid_excess_mean_pct'))}"
        ]
    gate_bps = float((report.get("graduation_rule") or {}).get("net_cost_bps", GRADUATION_COST_BPS))
    regime_filter = report.get("regime_filter") or {}
    filter_line: list[str] = []
    if regime_filter.get("active"):
        eff = regime_filter.get("effective_regimes") or []
        eff_labels = "、".join(f"{REGIME_STAGE_LABELS.get(s, s)}(`{s}`)" for s in eff)
        filter_line = [f"- 情绪过滤: 仅评估阶段 {eff_labels}"]
    overhead_filter = report.get("overhead_filter") or {}
    if overhead_filter.get("active") and overhead_filter.get("max_overhead_pct") is not None:
        filter_line.append(
            f"- 套牢盘过滤: 仅保留上方 10% 筹码占比 < {float(overhead_filter['max_overhead_pct']):.1f}% 的信号"
        )
    lines = [
        "# A 股形态 250 日 next_open 回放报告",
        "",
        f"- 评估区间: `{ps['eval_start_date']}` .. `{ps['eval_end_date']}` ({ps['eval_sessions']} 交易日, 股票池 {ps['codes_total']} 只, 包截止 `{ps['pack_end_date']}`)",
        f"- 口径: `{report['entry_mode']}` 入场（一字涨停不可成交剔除，退出一字跌停顺延），基准 `{report['benchmark']}` 同期开盘→收盘，回放已计入 `{float(report.get('cost_bps', 0.0)):.0f}bp` 成本",
        *baseline_line,
        *filter_line,
        f"- 毕业门槛: `T+5 基准匹配样本 >= {GRADUATION_MIN_SAMPLES}` 且扣 `{gate_bps:.0f}bp` 成本 `净超额 > 0%`、同信号日跑赢全A等权基线、H1/H2（各 `>= {STABILITY_MIN_HALF_DAYS}d` 且 `>= {STABILITY_MIN_HALF_SAMPLES}`）同号正超额、Newey-West HAC 聚日 `t >= {STABILITY_T_STAT_THRESHOLD}`（`lag >= {NEWEY_WEST_MIN_LAG}`）且多重检验 BH-FDR `q <= {GRADUATION_BH_FDR_ALPHA}`（否则标 `experimental`）",
        "",
        "## 形态总览与毕业判定",
        "",
        f"| 形态 | 谱系 | 模式 | 信号数 | 不可成交 | T+5 匹配样本 | T+5 原始 | T+5 毛超额 | T+5 净超额 (-{gate_bps:.0f}bp) | T+5 胜率 | T+10 超额 | 判定 |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in report["patterns"]:
        h5 = item["horizons"].get("t5") or {}
        h10 = item["horizons"].get("t10") or {}
        grad = item["graduation"]
        matched_n = h5.get("excess_scored", h5.get("scored", 0))
        gross_ex = h5.get("gross_excess_mean_pct", h5.get("excess_mean_pct"))
        net_ex = grad.get("t5_net_excess_mean_pct", h5.get("net_excess_mean_pct"))
        lines.append(
            f"| {item['display_name']} (`{item['pattern']}`) | {item['family']} | {item['mode']} | "
            f"{item['total_signals']} | {item['untradable_share_pct']:.1f}% | "
            f"{matched_n} | {_fmt_pct(h5.get('raw_mean_pct'))} | "
            f"{_fmt_pct(gross_ex)} | {_fmt_pct(net_ex)} | {_fmt_rate(h5.get('win_rate_pct'))} | "
            f"{_fmt_pct(h10.get('excess_mean_pct'))} | **{grad['recommended_status']}** |"
        )

    lines.extend([
        "",
        "## 市场阶段分布（切片元数据）",
        "",
        "| 阶段 | 天数 | 占比 |",
        "|---|---:|---:|",
    ])
    for stage in REGIME_STAGE_ORDER:
        info = report["regime_distribution"][stage]
        lines.append(f"| {info['label']} (`{stage}`) | {info['days']} | {info['share_pct']:.1f}% |")

    lines.extend([
        "",
        "## 形态 × 市场阶段切片（T+5 样本 / 平均超额）",
        "",
        "| 形态 | " + " | ".join(f"{REGIME_STAGE_LABELS[s]}" for s in REGIME_STAGE_ORDER) + " |",
        "|---|" + "|".join("---:" for _ in REGIME_STAGE_ORDER) + "|",
    ])
    for item in report["patterns"]:
        cells = []
        for s in REGIME_STAGE_ORDER:
            sl = item["by_regime"][s]
            mark = "" if sl["weight_eval_ready"] else "*"
            cells.append(f"{sl['t5_scored']}{mark} / {_fmt_pct(sl['t5_excess_mean_pct'])}")
        lines.append(f"| {item['display_name']} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("_注：带 `*` 表示该格 T+5 样本 < 100，仅作观察，暂不满足调权样本要求。_")

    lines.extend([
        "",
        "## 上方 10% 筹码占比切片（仅特征观察，非一票否决）",
        "",
        "| 形态 | <15% (样本/T+5超额) | 15%-35% (样本/T+5超额) | >=35% (样本/T+5超额) |",
        "|---|---:|---:|---:|",
    ])
    for item in report["patterns"]:
        ov = item["by_overhead_supply"]
        c1 = f"{ov['low_lt15']['t5_scored']} / {_fmt_pct(ov['low_lt15']['t5_excess_mean_pct'])}"
        c2 = f"{ov['mid_15_35']['t5_scored']} / {_fmt_pct(ov['mid_15_35']['t5_excess_mean_pct'])}"
        c3 = f"{ov['high_ge35']['t5_scored']} / {_fmt_pct(ov['high_ge35']['t5_excess_mean_pct'])}"
        lines.append(f"| {item['display_name']} | {c1} | {c2} | {c3} |")

    lines.extend([
        "",
        f"## 时间前后半段稳定性检验（按实际退出日切断 H1 < 切分日 `{ps.get('eval_mid_date', '-')}`，剔除跨界样本）",
        "",
        "| 形态 | H1 日数/日均超额 | H2 日数/日均超额 | NW t-stat (naive / EW / q) | 前后半段方向 | 达标稳定切片 |",
        "|---|---:|---:|---:|---|---|",
    ])
    stable_slices: list[str] = []
    for item in report["patterns"]:
        st = item.get("stability") or {}
        mt = item.get("multiple_testing") or {}
        t_str = "-" if st.get("t_stat") is None else f"{st['t_stat']:+.2f}"
        parts: list[str] = []
        if st.get("naive_daily_t_stat") is not None:
            parts.append(f"naive={st['naive_daily_t_stat']:+.2f}")
        elif st.get("pooled_t_stat") is not None:
            parts.append(f"pooled={st['pooled_t_stat']:+.2f}")
        if st.get("ew_t_stat") is not None:
            parts.append(f"EW={st['ew_t_stat']:+.2f}")
        if mt.get("bh_q_value_csi300") is not None:
            parts.append(f"q={mt['bh_q_value_csi300']:.3f}")
        if parts:
            t_str = f"{t_str} ({', '.join(parts)})"
        h1_pct = st.get("h1_daily_excess_mean_pct", st.get("h1_excess_mean_pct"))
        h2_pct = st.get("h2_daily_excess_mean_pct", st.get("h2_excess_mean_pct"))
        pos_cells = [
            f"{item['display_name']}×{REGIME_STAGE_LABELS[s]}({sl['t5_excess_mean_pct']:+.2f}%)"
            for s, sl in (item.get("by_regime") or {}).items()
            if sl.get("stability_ready") and (sl.get("t5_excess_mean_pct") or 0) > 0
        ]
        stable_slices.extend(pos_cells)
        cell_txt = "、".join(pos_cells) if pos_cells else "无"
        lines.append(
            f"| {item['display_name']} | {st.get('h1_days', 0)}d({st.get('h1_n', 0)}) / {_fmt_pct(h1_pct)} | "
            f"{st.get('h2_days', 0)}d({st.get('h2_n', 0)}) / {_fmt_pct(h2_pct)} | {t_str} | "
            f"{st.get('stable_direction', '-')} | {cell_txt} |"
        )
    if not stable_slices:
        lines.append("")
        lines.append("_注：当前暂无同时满足基准匹配样本 >= 100、前后半段各 >= 15 交易日且 >= 30 样本同号，并满足 Newey-West HAC |t| >= 1.96 的稳定正超额切片，保持情绪阶段不调权重。_")

    lines.extend([
        "",
        "## Walk-Forward 情绪门控样本外检验（H1 严格按退出日 < 切分日选阶段，剔除跨界样本 → H2 样本外对比）",
        "",
        "| 形态 | H1 正超额阶段 | H1 剔除逆风阶段 | H2 基线日均 (日数) | H2 仅正阶段 (OOS) | Δ 正阶段 vs 基线 | H2 剔除逆风 (OOS) | Δ 剔逆风 vs 基线 | H2 非逆风×低套牢<15% (OOS) | Δ 联合 vs 基线 |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for item in report["patterns"]:
        wf = item.get("walk_forward_regime_audit") or {}
        pos_stages = [REGIME_STAGE_LABELS.get(s, s) for s in (wf.get("h1_positive_regimes") or [])]
        adv_stages = [REGIME_STAGE_LABELS.get(s, s) for s in (wf.get("h1_adverse_regimes") or [])]
        h2_base = wf.get("h2_baseline") or {}
        h2_pos = wf.get("h2_positive_only") or {}
        h2_non_adv = wf.get("h2_non_adverse") or {}
        h2_joint = wf.get("h2_non_adverse_low_overhead") or {}
        base_str = f"{_fmt_pct(h2_base.get('daily_mean_pct'))} ({h2_base.get('days', 0)}d)"
        pos_str = f"{_fmt_pct(h2_pos.get('daily_mean_pct'))} ({h2_pos.get('days', 0)}d)"
        non_adv_str = f"{_fmt_pct(h2_non_adv.get('daily_mean_pct'))} ({h2_non_adv.get('days', 0)}d)"
        joint_str = f"{_fmt_pct(h2_joint.get('daily_mean_pct'))} ({h2_joint.get('days', 0)}d)"
        lines.append(
            f"| {item['display_name']} | "
            f"{'、'.join(pos_stages) if pos_stages else '无'} | "
            f"{'、'.join(adv_stages) if adv_stages else '无'} | "
            f"{base_str} | {pos_str} | {_fmt_pct(wf.get('delta_positive_vs_h2_baseline_pct'))} | "
            f"{non_adv_str} | {_fmt_pct(wf.get('delta_non_adverse_vs_h2_baseline_pct'))} | "
            f"{joint_str} | {_fmt_pct(wf.get('delta_non_adverse_low_overhead_vs_h2_baseline_pct'))} |"
        )

    return "\n".join(lines) + "\n"
