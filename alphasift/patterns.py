# -*- coding: utf-8 -*-
"""Stateless CN daily-matrix pattern engine with strict schema validation.

All patterns operate on CN A-share DailyPack matrices via atomic vectorized
operators and stateless observe/confirm lookback (no persistent state machine).
``overhead_supply_10pct`` is attached as an observation feature only and never
acts as a hard veto.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from alphasift.market_regime import (
    MarketRegimeSnapshot,
    compute_limit_masks,
    compute_market_regime,
)
from alphasift.normalize import normalize_code
from alphasift.pack import DailyPack, forward_adjust

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BUNDLED_PATTERNS_DIR = Path(__file__).resolve().parent / "patterns"

VALID_FAMILIES = frozenset({"bottom_reversal", "trend_continuation", "breakout"})
VALID_STATUSES = frozenset({"active", "experimental"})
VALID_MODES = frozenset({"direct", "observe_confirm"})

_TOP_LEVEL_KEYS = {
    "name",
    "display_name",
    "family",
    "status",
    "version",
    "description",
    "aligned_strategy",
    "tags",
    "market_scope",
    "min_history_days",
    "cooldown_days",
    "universe",
    "mode",
    "conditions",
    "observe",
    "confirm",
    "lookback_days",
    "min_wait_days",
    "invalidation",
}
_UNIVERSE_KEYS = {
    "exclude_st",
    "exclude_one_price_limit_up",
    "proxy_amount_min",
    "close_min",
}
_CONDITION_KEYS = {"feature", "min", "max", "equals", "lag", "params"}
_INVALIDATION_KEYS = {"rule", "tolerance_atr"}
_INVALIDATION_RULES = {
    "none",
    "close_below_observe_low",
    "low_below_observe_low",
    "close_below_observe_open",
    "close_below_observe_mid",
}

_STATIC_FEATURES = {
    "valid_bars",
    "valid_streak",
    "bull_streak",
    "close_higher_streak",
    "open_in_prev_body",
    "body_ratio_vs_prev",
    "is_bull_bar",
    "is_bear_bar",
    "is_limit_up",
    "not_one_price_limit_up",
    "ma_bullish",
    "ma20_above_ma60",
    "price_above_ma20",
    "price_above_ma60",
    "prev_close_above_ma20",
    "ma20_slope_5d_pct",
    "pos_in_60d",
    "drawdown_from_60d_high_pct",
    "prior_60d_decline_pct",
    "change_pct",
    "ret_limit_ratio",
    "ret_3d_limit_ratio",
    "body_pct",
    "body_atr",
    "body_limit_ratio",
    "bar_range_atr",
    "upper_shadow_atr",
    "lower_shadow_atr",
    "upper_shadow_to_range",
    "close_pos_in_bar",
    "atr20_pct",
    "vol_ratio_1d",
    "vol_ratio_5d",
    "vol_ratio_20d",
    "prev_range_20d_pct",
    "prev_range_20d_atr",
    "breakout_20d_pct",
    "breakout_20d_atr",
    "prev_below_prev_high_20d",
    "pullback_to_ma20_pct",
    "pullback_to_ma20_atr",
    "low_to_ma20_atr",
    "double_bottom_neckline_breakout",
}
_OBSERVE_RELATIVE_FEATURES = {
    "close_above_observe_high",
    "close_above_observe_close",
    "close_above_observe_mid",
    "hold_above_observe_low",
    "volume_below_observe_ratio",
    "range_ratio_vs_observe",
}
_ALL_FEATURES = _STATIC_FEATURES | _OBSERVE_RELATIVE_FEATURES


@dataclass
class PatternSpec:
    """Validated pattern definition loaded from YAML."""

    name: str
    display_name: str
    family: str
    status: str
    version: str
    description: str
    mode: str
    market_scope: tuple[str, ...] = ("cn",)
    aligned_strategy: str | None = None
    tags: tuple[str, ...] = ()
    min_history_days: int = 60
    universe: dict[str, Any] = field(default_factory=dict)
    conditions: list[dict[str, Any]] = field(default_factory=list)
    observe: list[dict[str, Any]] = field(default_factory=list)
    confirm: list[dict[str, Any]] = field(default_factory=list)
    lookback_days: int = 5
    min_wait_days: int = 1
    invalidation: dict[str, Any] = field(default_factory=lambda: {"rule": "none", "tolerance_atr": 0.0})
    cooldown_days: int = 0


@dataclass
class PatternSignal:
    """Single point-in-time CN pattern match."""

    pattern: str
    display_name: str
    family: str
    status: str
    code: str
    name: str
    industry: str
    trade_date: str
    close: float
    change_pct: float
    proxy_amount: float | None
    atr20_pct: float | None
    vol_ratio_20d: float | None
    overhead_supply_10pct: float | None
    observe_date: str | None = None
    observe_lag_days: int | None = None
    aligned_strategy: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PatternScanResult:
    """Scan output across one or more patterns for a single CN session."""

    trade_date: str
    pack_trade_date: str
    universe_count: int
    patterns_evaluated: list[str]
    market_regime: MarketRegimeSnapshot
    signals_by_pattern: dict[str, list[PatternSignal]]
    counts_by_pattern: dict[str, int]
    usage_policy: str = "cn_only_regime_slice_only"

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "pack_trade_date": self.pack_trade_date,
            "universe_count": self.universe_count,
            "patterns_evaluated": list(self.patterns_evaluated),
            "market_regime": self.market_regime.to_dict(),
            "counts_by_pattern": dict(self.counts_by_pattern),
            "signals_by_pattern": {
                name: [sig.to_dict() for sig in items]
                for name, items in self.signals_by_pattern.items()
            },
            "usage_policy": self.usage_policy,
        }


@dataclass
class PatternMatrixContext:
    """Precomputed vectorized (T, N) feature matrices for CN pattern matching."""

    dates: np.ndarray
    codes: np.ndarray
    names: np.ndarray
    industries: np.ndarray
    valid: np.ndarray
    valid_count: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    raw_close: np.ndarray
    volume: np.ndarray
    proxy_amount: np.ndarray
    is_st: np.ndarray
    is_one_price_limit_up: np.ndarray
    limit_pct: np.ndarray
    features: dict[str, np.ndarray]
    double_bottom_cache: dict[tuple[tuple[str, Any], ...], np.ndarray] = field(default_factory=dict)


def _validate_pattern_dir_sync(patterns_dir: Path) -> None:
    resolved = patterns_dir.resolve()
    repo_dir = (_PROJECT_ROOT / "patterns").resolve()
    bundled_dir = _BUNDLED_PATTERNS_DIR.resolve()
    if resolved != repo_dir or not bundled_dir.is_dir():
        return
    repo_files = {f.name: f for f in repo_dir.glob("*.yaml")}
    bundled_files = {f.name: f for f in bundled_dir.glob("*.yaml")}
    missing_from_repo = bundled_files.keys() - repo_files.keys()
    if missing_from_repo:
        raise RuntimeError(
            "Pattern directories are out of sync: bundled patterns are missing from "
            f"patterns/: {', '.join(sorted(missing_from_repo))}."
        )
    for name, bundled_file in bundled_files.items():
        if repo_files[name].read_bytes() != bundled_file.read_bytes():
            raise RuntimeError(
                f"Pattern directories are out of sync: patterns/{name} does not match alphasift/patterns/{name}."
            )


def _resolve_patterns_dir(patterns_dir: Path | None) -> Path:
    if patterns_dir is not None:
        resolved = Path(patterns_dir)
        _validate_pattern_dir_sync(resolved)
        return resolved
    repo_dir = _PROJECT_ROOT / "patterns"
    if repo_dir.is_dir():
        _validate_pattern_dir_sync(repo_dir)
        return repo_dir
    if _BUNDLED_PATTERNS_DIR.is_dir():
        return _BUNDLED_PATTERNS_DIR
    raise FileNotFoundError("Pattern directory not found")


def _validate_condition_list(
    items: Any,
    *,
    section: str,
    filepath: Path,
    allow_observe_relative: bool,
) -> list[dict[str, Any]]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise ValueError(f"Expected list for {section} in {filepath.name}")
    allowed_feats = _ALL_FEATURES if allow_observe_relative else _STATIC_FEATURES
    validated: list[dict[str, Any]] = []
    for idx, entry in enumerate(items):
        if not isinstance(entry, dict):
            raise ValueError(f"Condition #{idx} in {section} of {filepath.name} must be a mapping")
        unknown = sorted(set(entry.keys()) - _CONDITION_KEYS)
        if unknown:
            raise ValueError(f"Unknown keys in {section}[{idx}] of {filepath.name}: {', '.join(unknown)}")
        feat = entry.get("feature")
        if not isinstance(feat, str) or feat not in allowed_feats:
            raise ValueError(f"Invalid or disallowed feature {feat!r} in {section}[{idx}] of {filepath.name}")
        has_bound = any(k in entry for k in ("min", "max", "equals"))
        if not has_bound:
            raise ValueError(f"Condition {feat!r} in {section}[{idx}] of {filepath.name} needs min/max/equals")
        lag = entry.get("lag")
        if lag is not None and (not isinstance(lag, int) or isinstance(lag, bool) or lag < 0 or lag > 10):
            raise ValueError(f"lag in {section}[{idx}] of {filepath.name} must be an int in 0..10")
        params = entry.get("params")
        if params is not None and not isinstance(params, dict):
            raise ValueError(f"params in {section}[{idx}] of {filepath.name} must be a mapping")
        validated.append(dict(entry))
    return validated


def load_pattern(name_or_path: str | Path, *, patterns_dir: Path | None = None) -> PatternSpec:
    """Load and strictly validate a pattern YAML file."""
    candidate = Path(name_or_path)
    if candidate.is_file():
        filepath = candidate
    else:
        directory = _resolve_patterns_dir(patterns_dir)
        stem = str(name_or_path).removesuffix(".yaml")
        filepath = directory / f"{stem}.yaml"
    if not filepath.is_file():
        raise FileNotFoundError(f"Pattern YAML not found: {filepath}")

    data = yaml.safe_load(filepath.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Pattern YAML {filepath.name} must be a mapping")

    unknown = sorted(set(data.keys()) - _TOP_LEVEL_KEYS)
    if unknown:
        raise ValueError(f"Unknown top-level keys in {filepath.name}: {', '.join(unknown)}")

    name = str(data.get("name") or filepath.stem).strip()
    display_name = str(data.get("display_name") or name).strip()
    family = str(data.get("family") or "").strip()
    if family not in VALID_FAMILIES:
        raise ValueError(
            f"Invalid family {family!r} in {filepath.name}; expected one of {sorted(VALID_FAMILIES)}"
        )
    status = str(data.get("status") or "experimental").strip()
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status {status!r} in {filepath.name}; expected one of {sorted(VALID_STATUSES)}"
        )
    mode = str(data.get("mode") or "direct").strip()
    if mode not in VALID_MODES:
        raise ValueError(
            f"Invalid mode {mode!r} in {filepath.name}; expected one of {sorted(VALID_MODES)}"
        )

    scope_raw = data.get("market_scope", ["cn"])
    if not isinstance(scope_raw, list) or [str(x).lower() for x in scope_raw] != ["cn"]:
        raise ValueError(f"Pattern {filepath.name} market_scope must be ['cn']")

    min_hist = int(data.get("min_history_days", 60))
    if min_hist < 2:
        raise ValueError(f"min_history_days must be >= 2 in {filepath.name}")
    cooldown_days = int(data.get("cooldown_days", 0))
    if cooldown_days < 0 or cooldown_days > 20:
        raise ValueError(f"cooldown_days must be in 0..20 in {filepath.name}")

    universe = data.get("universe") or {}
    if not isinstance(universe, dict):
        raise ValueError(f"universe must be a mapping in {filepath.name}")
    unknown_uni = sorted(set(universe.keys()) - _UNIVERSE_KEYS)
    if unknown_uni:
        raise ValueError(f"Unknown universe keys in {filepath.name}: {', '.join(unknown_uni)}")

    inv = data.get("invalidation") or {"rule": "none", "tolerance_atr": 0.0}
    if not isinstance(inv, dict):
        raise ValueError(f"invalidation must be a mapping in {filepath.name}")
    unknown_inv = sorted(set(inv.keys()) - _INVALIDATION_KEYS)
    if unknown_inv:
        raise ValueError(f"Unknown invalidation keys in {filepath.name}: {', '.join(unknown_inv)}")
    inv_rule = str(inv.get("rule", "none"))
    if inv_rule not in _INVALIDATION_RULES:
        raise ValueError(f"Invalid invalidation rule {inv_rule!r} in {filepath.name}")

    conditions = _validate_condition_list(
        data.get("conditions"), section="conditions", filepath=filepath, allow_observe_relative=False
    )
    observe = _validate_condition_list(
        data.get("observe"), section="observe", filepath=filepath, allow_observe_relative=False
    )
    confirm = _validate_condition_list(
        data.get("confirm"), section="confirm", filepath=filepath, allow_observe_relative=True
    )

    lookback_days = int(data.get("lookback_days", 5))
    min_wait_days = int(data.get("min_wait_days", 1))
    if mode == "direct":
        if not conditions:
            raise ValueError(f"Direct pattern {filepath.name} must define conditions")
        if observe or confirm:
            raise ValueError(f"Direct pattern {filepath.name} must not define observe/confirm")
    else:
        if not observe or not confirm:
            raise ValueError(f"observe_confirm pattern {filepath.name} must define both observe and confirm")
        if conditions:
            raise ValueError(f"observe_confirm pattern {filepath.name} must not define top-level conditions")
        if min_wait_days < 1 or lookback_days < min_wait_days or lookback_days > 20:
            raise ValueError(
                f"Invalid wait window ({min_wait_days}..{lookback_days}) in {filepath.name}"
            )

    aligned = data.get("aligned_strategy")
    return PatternSpec(
        name=name,
        display_name=display_name,
        family=family,
        status=status,
        version=str(data.get("version", "1.0")),
        description=str(data.get("description", "")).strip(),
        mode=mode,
        market_scope=("cn",),
        aligned_strategy=str(aligned).strip() if aligned else None,
        tags=tuple(str(t).strip() for t in (data.get("tags") or [])),
        min_history_days=min_hist,
        universe=dict(universe),
        conditions=conditions,
        observe=observe,
        confirm=confirm,
        lookback_days=lookback_days,
        min_wait_days=min_wait_days,
        invalidation={"rule": inv_rule, "tolerance_atr": float(inv.get("tolerance_atr", 0.0))},
        cooldown_days=cooldown_days,
    )


def list_patterns(
    *,
    include_experimental: bool = True,
    patterns_dir: Path | None = None,
) -> list[PatternSpec]:
    """List validated CN pattern specs sorted by family and name."""
    directory = _resolve_patterns_dir(patterns_dir)
    specs = [load_pattern(path, patterns_dir=directory) for path in sorted(directory.glob("*.yaml"))]
    if not include_experimental:
        specs = [spec for spec in specs if spec.status == "active"]
    return specs


def _rolling_mean_valid(
    arr: np.ndarray,
    valid: np.ndarray,
    window: int,
    *,
    min_valid: int | None = None,
) -> np.ndarray:
    t_len, n_codes = arr.shape
    req = min_valid if min_valid is not None else max(1, int(np.ceil(window * 0.8)))
    clean_val = np.where(valid, arr, 0.0)
    clean_cnt = valid.astype(np.int64)

    cs_val = np.zeros((t_len + 1, n_codes), dtype=np.float64)
    cs_cnt = np.zeros((t_len + 1, n_codes), dtype=np.int64)
    cs_val[1:] = np.cumsum(clean_val, axis=0)
    cs_cnt[1:] = np.cumsum(clean_cnt, axis=0)

    idx = np.arange(1, t_len + 1, dtype=np.intp)
    lo = np.maximum(0, idx - window)
    win_sum = cs_val[idx] - cs_val[lo]
    win_cnt = cs_cnt[idx] - cs_cnt[lo]

    out = np.full((t_len, n_codes), np.nan, dtype=np.float64)
    ok = win_cnt >= req
    out[ok] = win_sum[ok] / win_cnt[ok]
    return out


def _shift_rows(arr: np.ndarray, lag: int = 1, fill: float = np.nan) -> np.ndarray:
    out = np.full_like(arr, fill)
    if lag < arr.shape[0]:
        out[lag:] = arr[:-lag]
    return out


def _rolling_extrema(
    high: np.ndarray,
    low: np.ndarray,
    valid: np.ndarray,
    window: int,
    *,
    strict_prior: bool = False,
    min_valid: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    t_len, n_codes = high.shape
    req = min_valid if min_valid is not None else max(2, int(np.ceil(window * 0.75)))
    hi_out = np.full((t_len, n_codes), np.nan, dtype=np.float64)
    lo_out = np.full((t_len, n_codes), np.nan, dtype=np.float64)

    h_pos = np.where(valid, high, -np.inf)
    l_pos = np.where(valid, low, np.inf)
    cs_cnt = np.zeros((t_len + 1, n_codes), dtype=np.int64)
    cs_cnt[1:] = np.cumsum(valid, axis=0)

    for t in range(t_len):
        end = t if strict_prior else t + 1
        start = max(0, end - window)
        if end <= start:
            continue
        cnt = cs_cnt[end] - cs_cnt[start]
        ok = cnt >= req
        if not ok.any():
            continue
        hi_out[t, ok] = h_pos[start:end, ok].max(axis=0)
        lo_out[t, ok] = l_pos[start:end, ok].min(axis=0)
    return hi_out, lo_out


def build_pattern_context(
    daily_pack: DailyPack,
    *,
    end_index: int | None = None,
) -> PatternMatrixContext:
    """Build point-in-time vectorized feature matrices from ``daily_pack``."""
    total_dates = len(daily_pack.dates)
    if end_index is not None:
        end_idx = end_index + 1 if end_index >= 0 else total_dates + end_index + 1
        if end_idx <= 0 or end_idx > total_dates:
            raise IndexError(f"end_index {end_index} out of range for {total_dates} sessions")
        # Slice strictly before forward_adjust so future splits never rescale past queries.
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

    limit_masks = compute_limit_masks(work_pack)
    adj = forward_adjust(work_pack)

    dates = np.asarray(work_pack.dates, dtype=str)
    codes = np.asarray(work_pack.codes, dtype=str)
    t_len, n_codes = len(dates), len(codes)

    name_map: dict[str, str] = {}
    ind_map: dict[str, str] = {}
    if work_pack.meta is not None and not work_pack.meta.empty and "code" in work_pack.meta.columns:
        for row in work_pack.meta.itertuples(index=False):
            c = normalize_code(getattr(row, "code", ""), allow_ticker=False)
            if not c:
                continue
            nm = getattr(row, "name", "")
            ind = getattr(row, "industry", "")
            name_map[c] = "" if nm is None or pd.isna(nm) else str(nm)
            ind_map[c] = "" if ind is None or pd.isna(ind) else str(ind)
    names = np.asarray([name_map.get(normalize_code(c, allow_ticker=False) or c, "") for c in codes], dtype=object)
    industries = np.asarray([ind_map.get(normalize_code(c, allow_ticker=False) or c, "") for c in codes], dtype=object)

    open_ = np.asarray(adj["open"], dtype=np.float64)
    high = np.asarray(adj["high"], dtype=np.float64)
    low = np.asarray(adj["low"], dtype=np.float64)
    close = np.asarray(adj["close"], dtype=np.float64)
    raw_close = np.asarray(work_pack.matrices["close"], dtype=np.float64)
    vol = np.asarray(work_pack.matrices["volume"], dtype=np.float64)

    valid = (
        np.isfinite(close) & (close > 0)
        & np.isfinite(open_) & (open_ > 0)
        & np.isfinite(high) & (high > 0)
        & np.isfinite(low) & (low > 0)
        & (~np.isfinite(vol) | (vol > 0))
    )
    valid_count = np.cumsum(valid, axis=0)

    # Carry forward last valid close and volume (per stock, strictly backward-looking).
    prev_valid_close = np.full((t_len, n_codes), np.nan, dtype=np.float64)
    prev_valid_volume = np.full((t_len, n_codes), np.nan, dtype=np.float64)
    last_c = np.full(n_codes, np.nan, dtype=np.float64)
    last_v = np.full(n_codes, np.nan, dtype=np.float64)
    vol_valid = valid & np.isfinite(vol) & (vol > 0)
    for t in range(t_len):
        prev_valid_close[t] = last_c
        prev_valid_volume[t] = last_v
        v_t = valid[t]
        if v_t.any():
            last_c = np.where(v_t, close[t], last_c)
        vv_t = vol_valid[t]
        if vv_t.any():
            last_v = np.where(vv_t, vol[t], last_v)

    ma5 = _rolling_mean_valid(close, valid, 5, min_valid=4)
    ma10 = _rolling_mean_valid(close, valid, 10, min_valid=8)
    ma20 = _rolling_mean_valid(close, valid, 20, min_valid=16)
    ma60 = _rolling_mean_valid(close, valid, 60, min_valid=48)
    ma20_lag1 = _shift_rows(ma20, 1)
    ma20_lag5 = _shift_rows(ma20, 5)

    vol_shift = _shift_rows(vol, 1)
    vol_valid_shift = _shift_rows(vol_valid.astype(np.float64), 1, fill=0.0) > 0.5
    vol_ma5_prev = _rolling_mean_valid(vol_shift, vol_valid_shift, 5, min_valid=3)
    vol_ma20_prev = _rolling_mean_valid(vol_shift, vol_valid_shift, 20, min_valid=12)

    tr = np.where(
        valid,
        np.fmax(
            high - low,
            np.fmax(np.abs(high - prev_valid_close), np.abs(low - prev_valid_close)),
        ),
        np.nan,
    )
    atr20 = _rolling_mean_valid(tr, valid & np.isfinite(tr), 20, min_valid=14)
    atr_pos = np.where(np.isfinite(atr20) & (atr20 > 0), atr20, np.nan)

    limit_pct = limit_masks["limit_pct"]
    change_pct = (close / prev_valid_close - 1.0) * 100.0
    ret_limit_ratio = (close / prev_valid_close - 1.0) / limit_pct[None, :]
    body_pct = (close / open_ - 1.0) * 100.0
    body_atr = (close - open_) / atr_pos
    body_limit_ratio = (close / open_ - 1.0) / limit_pct[None, :]

    bar_range = np.maximum(high - low, 0.0)
    upper_shadow = np.maximum(high - np.maximum(open_, close), 0.0)
    lower_shadow = np.maximum(np.minimum(open_, close) - low, 0.0)
    bar_range_atr = bar_range / atr_pos
    upper_shadow_atr = upper_shadow / atr_pos
    lower_shadow_atr = lower_shadow / atr_pos
    range_pos = valid & (bar_range > 0)
    upper_shadow_to_range = np.divide(
        upper_shadow, bar_range, out=np.zeros_like(bar_range), where=range_pos
    )
    close_pos_in_bar = np.divide(
        close - low, bar_range, out=np.full_like(bar_range, 0.5), where=range_pos
    )
    atr20_pct = (atr_pos / close) * 100.0

    vol_ratio_1d = np.divide(
        vol, prev_valid_volume, out=np.full_like(vol, np.nan), where=vol_valid & (prev_valid_volume > 0)
    )
    vol_ratio_5d = np.divide(
        vol, vol_ma5_prev, out=np.full_like(vol, np.nan), where=vol_valid & (vol_ma5_prev > 0)
    )
    vol_ratio_20d = np.divide(
        vol, vol_ma20_prev, out=np.full_like(vol, np.nan), where=vol_valid & (vol_ma20_prev > 0)
    )

    high_60d, low_60d = _rolling_extrema(high, low, valid, 60, strict_prior=False, min_valid=45)
    span_60d = high_60d - low_60d
    pos_in_60d = np.divide(
        close - low_60d, span_60d, out=np.full_like(close, np.nan), where=span_60d > 0
    )
    drawdown_from_60d_high_pct = (
        np.divide(close, high_60d, out=np.full_like(close, np.nan), where=high_60d > 0) - 1.0
    ) * 100.0

    prev_high_20d, prev_low_20d = _rolling_extrema(high, low, valid, 20, strict_prior=True, min_valid=15)
    prev_range_20d_pct = (
        np.divide(prev_high_20d, prev_low_20d, out=np.full_like(prev_high_20d, np.nan), where=prev_low_20d > 0)
        - 1.0
    ) * 100.0
    prev_range_20d_atr = (prev_high_20d - prev_low_20d) / atr_pos
    breakout_20d_pct = (
        np.divide(close, prev_high_20d, out=np.full_like(close, np.nan), where=prev_high_20d > 0) - 1.0
    ) * 100.0
    breakout_20d_atr = (close - prev_high_20d) / atr_pos
    prev_below_prev_high_20d = (
        np.isfinite(prev_valid_close) & np.isfinite(prev_high_20d) & (prev_valid_close <= prev_high_20d)
    ).astype(np.float64)

    # Prior 60d decline into recent 10d low
    _, recent_low_10d = _rolling_extrema(high, low, valid, 10, strict_prior=False, min_valid=6)
    prior_high_60d, _ = _rolling_extrema(high, low, valid, 60, strict_prior=True, min_valid=40)
    prior_60d_decline_pct = (
        np.divide(prior_high_60d, recent_low_10d, out=np.full_like(close, np.nan), where=recent_low_10d > 0) - 1.0
    ) * 100.0

    pullback_to_ma20_pct = (
        np.divide(close, ma20, out=np.full_like(close, np.nan), where=ma20 > 0) - 1.0
    ) * 100.0
    pullback_to_ma20_atr = (close - ma20) / atr_pos
    low_to_ma20_atr = (low - ma20) / atr_pos
    ma20_slope_5d_pct = (
        np.divide(ma20, ma20_lag5, out=np.full_like(ma20, np.nan), where=ma20_lag5 > 0) - 1.0
    ) * 100.0

    ma_bullish = (np.isfinite(ma5) & np.isfinite(ma20) & np.isfinite(ma60) & (ma5 >= ma20) & (ma20 >= ma60)).astype(np.float64)
    ma20_above_ma60 = (np.isfinite(ma20) & np.isfinite(ma60) & (ma20 >= ma60)).astype(np.float64)
    price_above_ma20 = (np.isfinite(ma20) & (close >= ma20)).astype(np.float64)
    price_above_ma60 = (np.isfinite(ma60) & (close >= ma60)).astype(np.float64)
    prev_close_above_ma20 = (
        np.isfinite(prev_valid_close) & np.isfinite(ma20_lag1) & (prev_valid_close >= ma20_lag1)
    ).astype(np.float64)

    valid_lag1 = _shift_rows(valid.astype(np.float64), 1, fill=0.0) > 0.5
    open_lag1 = _shift_rows(open_, 1)
    close_lag1 = _shift_rows(close, 1)
    valid_lag3 = _shift_rows(valid.astype(np.float64), 3, fill=0.0) > 0.5
    close_lag3 = _shift_rows(close, 3)

    valid_streak = np.zeros((t_len, n_codes), dtype=np.float64)
    bull_streak = np.zeros((t_len, n_codes), dtype=np.float64)
    close_higher_streak = np.zeros((t_len, n_codes), dtype=np.float64)
    bull_bar = valid & (close > open_)
    higher_bar = valid & valid_lag1 & (close > close_lag1)
    for t in range(t_len):
        if t == 0:
            valid_streak[t] = np.where(valid[t], 1.0, 0.0)
            bull_streak[t] = np.where(bull_bar[t], 1.0, 0.0)
            close_higher_streak[t] = 0.0
        else:
            valid_streak[t] = np.where(valid[t], valid_streak[t - 1] + 1.0, 0.0)
            bull_streak[t] = np.where(bull_bar[t], bull_streak[t - 1] + 1.0, 0.0)
            close_higher_streak[t] = np.where(higher_bar[t], close_higher_streak[t - 1] + 1.0, 0.0)

    body_lo_prev = np.minimum(open_lag1, close_lag1) - 0.10 * atr_pos
    body_hi_prev = np.maximum(open_lag1, close_lag1) + 0.10 * atr_pos
    open_in_prev_body = np.where(
        valid & valid_lag1 & np.isfinite(atr_pos),
        ((open_ >= body_lo_prev) & (open_ <= body_hi_prev)).astype(np.float64),
        np.nan,
    )
    body_cur = close - open_
    body_prev = close_lag1 - open_lag1
    body_ratio_vs_prev = np.divide(
        body_cur,
        body_prev,
        out=np.full_like(close, np.nan),
        where=valid & valid_lag1 & (body_cur > 0) & (body_prev > 0),
    )
    is_limit_up_feat = np.where(valid, limit_masks["is_limit_up"].astype(np.float64), np.nan)
    ret_3d_limit_ratio = np.where(
        (valid_streak >= 3.0) & valid_lag3 & (close_lag3 > 0),
        (close / close_lag3 - 1.0) / limit_pct[None, :],
        np.nan,
    )

    features: dict[str, np.ndarray] = {
        "valid_bars": valid_count.astype(np.float64),
        "valid_streak": valid_streak,
        "bull_streak": bull_streak,
        "close_higher_streak": close_higher_streak,
        "open_in_prev_body": open_in_prev_body,
        "body_ratio_vs_prev": body_ratio_vs_prev,
        "is_bull_bar": (valid & (close > open_)).astype(np.float64),
        "is_bear_bar": (valid & (close < open_)).astype(np.float64),
        "is_limit_up": is_limit_up_feat,
        "not_one_price_limit_up": (~limit_masks["is_one_price_limit_up"]).astype(np.float64),
        "ma_bullish": ma_bullish,
        "ma20_above_ma60": ma20_above_ma60,
        "price_above_ma20": price_above_ma20,
        "price_above_ma60": price_above_ma60,
        "prev_close_above_ma20": prev_close_above_ma20,
        "ma20_slope_5d_pct": ma20_slope_5d_pct,
        "pos_in_60d": pos_in_60d,
        "drawdown_from_60d_high_pct": drawdown_from_60d_high_pct,
        "prior_60d_decline_pct": prior_60d_decline_pct,
        "change_pct": change_pct,
        "ret_limit_ratio": ret_limit_ratio,
        "ret_3d_limit_ratio": ret_3d_limit_ratio,
        "body_pct": body_pct,
        "body_atr": body_atr,
        "body_limit_ratio": body_limit_ratio,
        "bar_range_atr": bar_range_atr,
        "upper_shadow_atr": upper_shadow_atr,
        "lower_shadow_atr": lower_shadow_atr,
        "upper_shadow_to_range": upper_shadow_to_range,
        "close_pos_in_bar": close_pos_in_bar,
        "atr20_pct": atr20_pct,
        "vol_ratio_1d": vol_ratio_1d,
        "vol_ratio_5d": vol_ratio_5d,
        "vol_ratio_20d": vol_ratio_20d,
        "prev_range_20d_pct": prev_range_20d_pct,
        "prev_range_20d_atr": prev_range_20d_atr,
        "breakout_20d_pct": breakout_20d_pct,
        "breakout_20d_atr": breakout_20d_atr,
        "prev_below_prev_high_20d": prev_below_prev_high_20d,
        "pullback_to_ma20_pct": pullback_to_ma20_pct,
        "pullback_to_ma20_atr": pullback_to_ma20_atr,
        "low_to_ma20_atr": low_to_ma20_atr,
    }
    _ = ma10  # Reserved for future trend templates.

    return PatternMatrixContext(
        dates=dates,
        codes=codes,
        names=names,
        industries=industries,
        valid=valid,
        valid_count=valid_count,
        open=open_,
        high=high,
        low=low,
        close=close,
        raw_close=raw_close,
        volume=vol,
        proxy_amount=limit_masks["proxy_amount"],
        is_st=limit_masks["is_st"],
        is_one_price_limit_up=limit_masks["is_one_price_limit_up"],
        limit_pct=limit_pct,
        features=features,
    )


def _compute_double_bottom_neckline_breakout(
    ctx: PatternMatrixContext,
    params: dict[str, Any] | None = None,
) -> np.ndarray:
    cfg = dict(params or {})
    key = tuple(sorted(cfg.items()))
    if key in ctx.double_bottom_cache:
        return ctx.double_bottom_cache[key]

    prior_decline_min_pct = float(cfg.get("prior_decline_min_pct", 12.0))
    trough_diff_max_atr = float(cfg.get("trough_diff_max_atr", 1.2))
    min_trough_gap = int(cfg.get("min_trough_gap", 7))
    neckline_min_atr = float(cfg.get("neckline_min_atr", 1.5))
    neckline_min_pct = float(cfg.get("neckline_min_pct", 5.0))
    overshoot_max_atr = float(cfg.get("breakout_max_overshoot_atr", 2.2))

    t_len, n_codes = ctx.close.shape
    out = np.zeros((t_len, n_codes), dtype=bool)
    if t_len < 56:
        ctx.double_bottom_cache[key] = out
        return out

    atr = ctx.features["atr20_pct"] / 100.0 * ctx.close
    prev_c = _shift_rows(ctx.close, 1)
    offsets = np.arange(55, dtype=np.int64)[:, None]

    for t in range(55, t_len):
        eligible = ctx.valid[t] & (ctx.valid_count[t] >= 55) & np.isfinite(atr[t]) & (atr[t] > 0)
        cols = np.flatnonzero(eligible)
        if cols.size == 0:
            continue

        s0 = t - 55
        win_v = ctx.valid[s0:t, cols]
        win_l = np.where(win_v, ctx.low[s0:t, cols], np.inf)
        win_h = np.where(win_v, ctx.high[s0:t, cols], -np.inf)

        # Left trough in [t-55 .. t-21] (offsets 0..34), right trough in [t-18 .. t-2] (37..53).
        left_slice = win_l[:35]
        right_slice = win_l[37:54]
        i1 = np.argmin(left_slice, axis=0)
        i2 = 37 + np.argmin(right_slice, axis=0)
        l1 = left_slice[i1, np.arange(cols.size)]
        l2 = right_slice[i2 - 37, np.arange(cols.size)]

        mid_mask = (offsets > i1[None, :]) & (offsets < i2[None, :]) & win_v
        n_peak = np.where(mid_mask, win_h, -np.inf).max(axis=0)

        p_start = max(0, t - 70)
        prior_hi = np.where(
            ctx.valid[p_start : t - 15, cols],
            ctx.high[p_start : t - 15, cols],
            -np.inf,
        ).max(axis=0)

        atr_t = atr[t, cols]
        close_t = ctx.close[t, cols]
        prev_t = prev_c[t, cols]
        max_trough = np.maximum(l1, l2)
        min_trough = np.minimum(l1, l2)

        ok = (
            np.isfinite(l1)
            & np.isfinite(l2)
            & np.isfinite(n_peak)
            & np.isfinite(prior_hi)
            & (min_trough > 0)
            & ((i2 - i1) >= min_trough_gap)
            & ((prior_hi / min_trough - 1.0) * 100.0 >= prior_decline_min_pct)
            & (np.abs(l2 - l1) <= trough_diff_max_atr * atr_t)
            & (l2 >= l1 - 0.8 * atr_t)
            & ((n_peak - max_trough) >= neckline_min_atr * atr_t)
            & ((n_peak / max_trough - 1.0) * 100.0 >= neckline_min_pct)
            & (close_t > n_peak)
            & (~np.isfinite(prev_t) | (prev_t <= n_peak * 1.01))
            & ((close_t - n_peak) <= overshoot_max_atr * atr_t)
        )
        if ok.any():
            out[t, cols[ok]] = True

    ctx.double_bottom_cache[key] = out
    return out


def _eval_static_condition(ctx: PatternMatrixContext, cond: dict[str, Any]) -> np.ndarray:
    feat = cond["feature"]
    if feat == "double_bottom_neckline_breakout":
        arr = _compute_double_bottom_neckline_breakout(ctx, cond.get("params")).astype(np.float64)
    else:
        arr = ctx.features[feat]

    lag = int(cond.get("lag") or 0)
    if lag > 0:
        arr = _shift_rows(arr, lag)

    mask = np.isfinite(arr)
    if "equals" in cond:
        eq = cond["equals"]
        target = 1.0 if eq is True else (0.0 if eq is False else float(eq))
        mask &= arr == target
    if "min" in cond and cond["min"] is not None:
        mask &= arr >= float(cond["min"])
    if "max" in cond and cond["max"] is not None:
        mask &= arr <= float(cond["max"])
    return mask


def _universe_mask(ctx: PatternMatrixContext, spec: PatternSpec) -> np.ndarray:
    mask = ctx.valid & (ctx.valid_count >= spec.min_history_days)
    uni = spec.universe
    if uni.get("exclude_st", True):
        mask &= (~ctx.is_st)[None, :]
    if uni.get("exclude_one_price_limit_up", False):
        mask &= ~ctx.is_one_price_limit_up
    amt_min = uni.get("proxy_amount_min")
    if amt_min is not None:
        mask &= np.isfinite(ctx.proxy_amount) & (ctx.proxy_amount >= float(amt_min))
    close_min = uni.get("close_min")
    if close_min is not None:
        mask &= ctx.close >= float(close_min)
    return mask


def _eval_observe_relative(
    ctx: PatternMatrixContext,
    cond: dict[str, Any],
    obs_slice: slice,
    cur_slice: slice,
) -> np.ndarray:
    feat = cond["feature"]
    if feat == "close_above_observe_high":
        arr = (ctx.close[cur_slice] > ctx.high[obs_slice]).astype(np.float64)
    elif feat == "close_above_observe_close":
        arr = (ctx.close[cur_slice] > ctx.close[obs_slice]).astype(np.float64)
    elif feat == "close_above_observe_mid":
        mid = 0.5 * (ctx.open[obs_slice] + ctx.close[obs_slice])
        arr = (ctx.close[cur_slice] >= mid).astype(np.float64)
    elif feat == "hold_above_observe_low":
        arr = (ctx.close[cur_slice] >= ctx.low[obs_slice]).astype(np.float64)
    elif feat == "volume_below_observe_ratio":
        obs_v = ctx.volume[obs_slice]
        arr = np.where(obs_v > 0, ctx.volume[cur_slice] / obs_v, np.nan)
    elif feat == "range_ratio_vs_observe":
        obs_r = np.maximum(ctx.high[obs_slice] - ctx.low[obs_slice], 0.0)
        cur_r = np.maximum(ctx.high[cur_slice] - ctx.low[cur_slice], 0.0)
        arr = np.where(obs_r > 0, cur_r / obs_r, np.nan)
    else:
        raise ValueError(f"Unsupported observe-relative feature {feat!r}")

    mask = np.isfinite(arr)
    if "equals" in cond:
        eq = cond["equals"]
        target = 1.0 if eq is True else (0.0 if eq is False else float(eq))
        mask &= arr == target
    if "min" in cond and cond["min"] is not None:
        mask &= arr >= float(cond["min"])
    if "max" in cond and cond["max"] is not None:
        mask &= arr <= float(cond["max"])
    return mask


def _apply_cooldown(
    signal_mask: np.ndarray,
    observe_idx: np.ndarray,
    cooldown_days: int,
) -> tuple[np.ndarray, np.ndarray]:
    if cooldown_days <= 0:
        return signal_mask, observe_idx
    t_len, n_codes = signal_mask.shape
    out_mask = signal_mask.copy()
    out_obs = observe_idx.copy()
    last_fire = np.full(n_codes, -(cooldown_days + 1), dtype=np.int64)
    for t in range(t_len):
        keep = out_mask[t] & ((t - last_fire) > cooldown_days)
        out_mask[t] = keep
        out_obs[t] = np.where(keep, out_obs[t], -1)
        if keep.any():
            last_fire = np.where(keep, t, last_fire)
    return out_mask, out_obs


def evaluate_pattern_matrix(
    ctx: PatternMatrixContext,
    spec: PatternSpec,
) -> tuple[np.ndarray, np.ndarray]:
    """Evaluate a single ``PatternSpec`` over ``ctx``, returning (signal_mask, observe_index)."""
    t_len, n_codes = ctx.close.shape
    uni_mask = _universe_mask(ctx, spec)
    observe_idx = np.full((t_len, n_codes), -1, dtype=np.int32)

    if spec.mode == "direct":
        sig = uni_mask.copy()
        for cond in spec.conditions:
            sig &= _eval_static_condition(ctx, cond)
        return _apply_cooldown(sig, observe_idx, spec.cooldown_days)

    # Stateless observe/confirm lookback
    obs_mask = ctx.valid & (ctx.valid_count >= spec.min_history_days)
    if spec.universe.get("exclude_st", True):
        obs_mask &= (~ctx.is_st)[None, :]
    for cond in spec.observe:
        obs_mask &= _eval_static_condition(ctx, cond)

    static_confirm: list[dict[str, Any]] = []
    rel_confirm: list[dict[str, Any]] = []
    for cond in spec.confirm:
        if cond["feature"] in _OBSERVE_RELATIVE_FEATURES:
            rel_confirm.append(cond)
        else:
            static_confirm.append(cond)

    confirm_base = uni_mask.copy()
    for cond in static_confirm:
        confirm_base &= _eval_static_condition(ctx, cond)

    inv_rule = spec.invalidation["rule"]
    tol_atr = float(spec.invalidation.get("tolerance_atr", 0.0))
    atr = np.where(np.isfinite(ctx.features["atr20_pct"]), ctx.features["atr20_pct"] / 100.0 * ctx.close, 0.0)

    if inv_rule == "low_below_observe_low":
        inv_floor = ctx.low - tol_atr * atr
        check_series = ctx.low
    elif inv_rule == "close_below_observe_low":
        inv_floor = ctx.low - tol_atr * atr
        check_series = ctx.close
    elif inv_rule == "close_below_observe_open":
        inv_floor = ctx.open - tol_atr * atr
        check_series = ctx.close
    elif inv_rule == "close_below_observe_mid":
        inv_floor = 0.5 * (ctx.open + ctx.close) - tol_atr * atr
        check_series = ctx.close
    else:
        inv_floor = np.full((t_len, n_codes), -np.inf, dtype=np.float64)
        check_series = ctx.close

    signal_mask = np.zeros((t_len, n_codes), dtype=bool)
    for lag in range(spec.min_wait_days, min(spec.lookback_days, t_len - 1) + 1):
        obs_slice = slice(0, t_len - lag)
        cur_slice = slice(lag, t_len)
        pair_ok = obs_mask[obs_slice] & confirm_base[cur_slice]
        if not pair_ok.any():
            continue

        if inv_rule != "none":
            floor = inv_floor[obs_slice]
            for step in range(1, lag + 1):
                mid_slice = slice(step, t_len - lag + step)
                breached = ctx.valid[mid_slice] & (check_series[mid_slice] < floor)
                pair_ok &= ~breached
                if not pair_ok.any():
                    break
        if not pair_ok.any():
            continue

        for rel_cond in rel_confirm:
            pair_ok &= _eval_observe_relative(ctx, rel_cond, obs_slice, cur_slice)
            if not pair_ok.any():
                break
        if not pair_ok.any():
            continue

        new_hits = pair_ok & ~signal_mask[cur_slice]
        if new_hits.any():
            signal_mask[cur_slice] |= new_hits
            obs_rows = np.arange(t_len - lag, dtype=np.int32)[:, None]
            observe_idx[cur_slice] = np.where(new_hits, obs_rows, observe_idx[cur_slice])

    return _apply_cooldown(signal_mask, observe_idx, spec.cooldown_days)


def compute_overhead_supply_10pct_row(
    ctx: PatternMatrixContext,
    row_idx: int,
    col_indices: np.ndarray,
    *,
    window: int = 60,
) -> np.ndarray:
    """Volume share in [close, close * 1.10] over the prior ``window`` valid sessions."""
    out = np.full(len(col_indices), np.nan, dtype=np.float64)
    if row_idx <= 0 or len(col_indices) == 0:
        return out
    start = max(0, row_idx - window)
    v_win = ctx.valid[start:row_idx, col_indices] & np.isfinite(ctx.volume[start:row_idx, col_indices]) & (ctx.volume[start:row_idx, col_indices] > 0)
    vol_win = np.where(v_win, ctx.volume[start:row_idx, col_indices], 0.0)
    total_vol = vol_win.sum(axis=0)
    tp = (
        ctx.high[start:row_idx, col_indices]
        + ctx.low[start:row_idx, col_indices]
        + ctx.close[start:row_idx, col_indices]
    ) / 3.0
    c_now = ctx.close[row_idx, col_indices][None, :]
    in_band = v_win & (tp > c_now) & (tp <= c_now * 1.10)
    band_vol = np.where(in_band, vol_win, 0.0).sum(axis=0)
    ok = total_vol > 0
    out[ok] = (band_vol[ok] / total_vol[ok]) * 100.0
    return out


def scan_patterns(
    daily_pack: DailyPack,
    *,
    patterns: Sequence[str] | None = None,
    as_of_index: int = -1,
    trade_date: str | None = None,
    include_experimental: bool = False,
    patterns_dir: Path | None = None,
) -> PatternScanResult:
    """Scan CN ``daily_pack`` at ``as_of_index`` or ``trade_date`` without persisted state."""
    dates = [str(d) for d in daily_pack.dates]
    if not dates:
        raise ValueError("DailyPack contains no sessions")
    if trade_date is not None:
        if trade_date not in dates:
            raise ValueError(f"trade_date {trade_date!r} not found in DailyPack ({dates[0]}..{dates[-1]})")
        idx = dates.index(trade_date)
    else:
        idx = as_of_index if as_of_index >= 0 else len(dates) + as_of_index
        if idx < 0 or idx >= len(dates):
            raise IndexError(f"as_of_index {as_of_index} out of range for {len(dates)} sessions")

    if patterns:
        specs = [load_pattern(name, patterns_dir=patterns_dir) for name in patterns]
    else:
        specs = list_patterns(include_experimental=include_experimental, patterns_dir=patterns_dir)

    ctx = build_pattern_context(daily_pack, end_index=idx)
    regime = compute_market_regime(daily_pack, as_of_index=idx)
    last_row = len(ctx.dates) - 1
    universe_count = int(ctx.valid[last_row].sum())

    signals_by_pattern: dict[str, list[PatternSignal]] = {}
    counts_by_pattern: dict[str, int] = {}

    for spec in specs:
        sig_mask, obs_idx = evaluate_pattern_matrix(ctx, spec)
        cols = np.flatnonzero(sig_mask[last_row])
        overhead = compute_overhead_supply_10pct_row(ctx, last_row, cols)
        items: list[PatternSignal] = []
        for pos, j in enumerate(cols.tolist()):
            obs_row = int(obs_idx[last_row, j])
            chg = ctx.features["change_pct"][last_row, j]
            amt = ctx.proxy_amount[last_row, j]
            atr_pct = ctx.features["atr20_pct"][last_row, j]
            vr20 = ctx.features["vol_ratio_20d"][last_row, j]
            ov = overhead[pos]
            items.append(
                PatternSignal(
                    pattern=spec.name,
                    display_name=spec.display_name,
                    family=spec.family,
                    status=spec.status,
                    code=str(ctx.codes[j]),
                    name=str(ctx.names[j]),
                    industry=str(ctx.industries[j]),
                    trade_date=str(ctx.dates[last_row]),
                    close=round(float(ctx.raw_close[last_row, j]), 4),
                    change_pct=round(float(chg), 2) if np.isfinite(chg) else 0.0,
                    proxy_amount=round(float(amt), 2) if np.isfinite(amt) else None,
                    atr20_pct=round(float(atr_pct), 2) if np.isfinite(atr_pct) else None,
                    vol_ratio_20d=round(float(vr20), 2) if np.isfinite(vr20) else None,
                    overhead_supply_10pct=round(float(ov), 2) if np.isfinite(ov) else None,
                    observe_date=str(ctx.dates[obs_row]) if obs_row >= 0 else None,
                    observe_lag_days=(last_row - obs_row) if obs_row >= 0 else None,
                    aligned_strategy=spec.aligned_strategy,
                )
            )
        items.sort(key=lambda s: (-(s.proxy_amount or 0.0), s.code))
        signals_by_pattern[spec.name] = items
        counts_by_pattern[spec.name] = len(items)

    return PatternScanResult(
        trade_date=str(ctx.dates[last_row]),
        pack_trade_date=str(daily_pack.dates[-1]),
        universe_count=universe_count,
        patterns_evaluated=[spec.name for spec in specs],
        market_regime=regime,
        signals_by_pattern=signals_by_pattern,
        counts_by_pattern=counts_by_pattern,
    )


def extract_mini_kline_bars(
    daily_pack: DailyPack,
    codes: Sequence[str],
    *,
    as_of_index: int = -1,
    trade_date: str | None = None,
    bars: int = 20,
) -> dict[str, list[list[float]]]:
    """Extract up to ``bars`` forward-adjusted [o, h, l, c] bars per code without look-ahead."""
    dates = [str(d) for d in daily_pack.dates]
    if not dates or len(daily_pack.codes) == 0 or int(bars) <= 0:
        return {}
    if trade_date is not None:
        if trade_date not in dates:
            raise ValueError(f"trade_date {trade_date!r} not found in DailyPack")
        idx = dates.index(trade_date)
    else:
        idx = as_of_index if as_of_index >= 0 else len(dates) + as_of_index
        if idx < 0 or idx >= len(dates):
            raise IndexError(f"as_of_index {as_of_index} out of range for {len(dates)} sessions")

    sub_pack = DailyPack(
        dates=daily_pack.dates[: idx + 1],
        codes=daily_pack.codes,
        matrices={k: v[: idx + 1] for k, v in daily_pack.matrices.items()},
        meta=daily_pack.meta,
        sources=daily_pack.sources,
        manifest=daily_pack.manifest,
    )
    adj = forward_adjust(sub_pack)
    pack_codes = np.asarray(sub_pack.codes, dtype=str)
    o_mat = np.asarray(adj["open"], dtype=np.float64)
    h_mat = np.asarray(adj["high"], dtype=np.float64)
    lo_mat = np.asarray(adj["low"], dtype=np.float64)
    c_mat = np.asarray(adj["close"], dtype=np.float64)
    v_mat = np.asarray(sub_pack.matrices["volume"], dtype=np.float64)

    out: dict[str, list[list[float]]] = {}
    n_bars = int(bars)
    for raw_code in codes:
        code = normalize_code(raw_code, allow_ticker=False) or str(raw_code).strip()
        if not code or code in out:
            continue
        pos = int(np.searchsorted(pack_codes, code))
        if pos >= len(pack_codes) or pack_codes[pos] != code:
            continue
        valid_col = (
            np.isfinite(o_mat[:, pos]) & (o_mat[:, pos] > 0)
            & np.isfinite(h_mat[:, pos]) & (h_mat[:, pos] > 0)
            & np.isfinite(lo_mat[:, pos]) & (lo_mat[:, pos] > 0)
            & np.isfinite(c_mat[:, pos]) & (c_mat[:, pos] > 0)
            & (~np.isfinite(v_mat[:, pos]) | (v_mat[:, pos] > 0))
        )
        rows = np.flatnonzero(valid_col)[-n_bars:]
        out[code] = [
            [
                round(float(o_mat[r, pos]), 2),
                round(float(h_mat[r, pos]), 2),
                round(float(lo_mat[r, pos]), 2),
                round(float(c_mat[r, pos]), 2),
            ]
            for r in rows
        ]
    return out
