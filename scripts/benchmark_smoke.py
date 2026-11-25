#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic offline performance & cache benchmark for Issue #34 P7."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import time

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from alphasift import daily as daily_mod  # noqa: E402
from alphasift.config import Config  # noqa: E402
from alphasift.doctor import doctor_data_sources  # noqa: E402
from alphasift.filter import apply_hard_filters, hard_filter_waterfall  # noqa: E402
from alphasift.jsonutil import dumps_strict_json  # noqa: E402
from alphasift.models import HardFilterConfig, Pick, ScreeningConfig  # noqa: E402
from alphasift.risk import summarize_portfolio_exposure  # noqa: E402
from alphasift.scorer import compute_screen_scores  # noqa: E402


def _synthetic_snapshot(rows: int) -> pd.DataFrame:
    rng = np.random.default_rng(20261122)
    industries = ["医药", "银行", "半导体", "化工", "电气设备", "食品饮料"]
    return pd.DataFrame({
        "code": [f"{i:06d}" for i in range(1, rows + 1)],
        "name": [f"样本{i:04d}" for i in range(1, rows + 1)],
        "price": np.round(rng.uniform(4.0, 120.0, rows), 2),
        "change_pct": np.round(rng.uniform(-6.0, 9.5, rows), 2),
        "amount": np.round(rng.uniform(3e7, 2e9, rows), 0),
        "total_mv": np.round(rng.uniform(3e9, 4e11, rows), 0),
        "turnover_rate": np.round(rng.uniform(0.3, 12.0, rows), 2),
        "volume_ratio": np.round(rng.uniform(0.5, 4.0, rows), 2),
        "pe_ratio": np.round(rng.uniform(6.0, 90.0, rows), 2),
        "pb_ratio": np.round(rng.uniform(0.6, 8.0, rows), 2),
        "industry": [industries[i % len(industries)] for i in range(rows)],
        "concepts": [f"概念{i % 15}" for i in range(rows)],
        "change_60d": np.round(rng.uniform(-25.0, 60.0, rows), 2),
        "breakout_20d_pct": np.round(rng.uniform(-8.0, 12.0, rows), 2),
        "volatility_20d_pct": np.round(rng.uniform(1.0, 6.0, rows), 2),
        "atr_20_pct": np.round(rng.uniform(1.2, 6.5, rows), 2),
        "pullback_to_ma20_pct": np.round(rng.uniform(-10.0, 10.0, rows), 2),
        "range_20d_pct": np.round(rng.uniform(3.0, 28.0, rows), 2),
        "volume_ratio_20d": np.round(rng.uniform(0.5, 3.0, rows), 2),
        "body_pct": np.round(rng.uniform(-3.0, 5.0, rows), 2),
    })


def _sample_daily_df() -> pd.DataFrame:
    dates = pd.bdate_range("2026-06-01", periods=35).strftime("%Y-%m-%d")
    base = np.linspace(10.0, 13.4, len(dates))
    return pd.DataFrame({
        "date": dates,
        "open": base,
        "high": base + 0.2,
        "low": base - 0.2,
        "close": base + 0.05,
        "volume": np.full(len(dates), 1_000_000.0),
    })


def run_benchmark(*, rows: int = 5000) -> dict[str, object]:
    """Run deterministic offline timings for CLI doctor, waterfall, scoring, exposure, and daily cache."""
    cfg = Config()
    df = _synthetic_snapshot(max(50, int(rows)))
    filters = HardFilterConfig(
        pe_ttm_max=60.0,
        pb_max=6.0,
        market_cap_min=3_000_000_000.0,
        amount_min=50_000_000.0,
    )
    screening = ScreeningConfig(
        enabled=True,
        hard_filters=filters,
        factor_weights={"value": 0.4, "momentum": 0.3, "liquidity": 0.3},
    )

    t0 = time.perf_counter()
    doc = doctor_data_sources(cfg, market="cn", run_live=False)
    doctor_ms = (time.perf_counter() - t0) * 1000.0

    t1 = time.perf_counter()
    filtered = apply_hard_filters(df, filters)
    apply_filters_ms = (time.perf_counter() - t1) * 1000.0

    t1b = time.perf_counter()
    steps = hard_filter_waterfall(df, filters, include_quantiles=True)
    waterfall_ms = (time.perf_counter() - t1b) * 1000.0

    t2 = time.perf_counter()
    scored = compute_screen_scores(filtered, screening)
    scoring_ms = (time.perf_counter() - t2) * 1000.0

    selected = [
        Pick(
            rank=idx + 1,
            code=str(row["code"]),
            name=str(row["name"]),
            final_score=float(row["screen_score"]),
            screen_score=float(row["screen_score"]),
            industry=str(row["industry"]),
        )
        for idx, (_, row) in enumerate(scored.head(10).iterrows())
    ]
    pool = [
        Pick(
            rank=idx + 11,
            code=str(row["code"]),
            name=str(row["name"]),
            final_score=float(row["screen_score"]),
            screen_score=float(row["screen_score"]),
            industry=str(row["industry"]),
        )
        for idx, (_, row) in enumerate(scored.iloc[10:30].iterrows())
    ]
    t3 = time.perf_counter()
    exposure, _, replacements = summarize_portfolio_exposure(selected, candidate_pool=pool, max_same_bucket=2)
    exposure_ms = (time.perf_counter() - t3) * 1000.0

    sample = _sample_daily_df()
    orig_fetch = daily_mod._fetch_daily_tencent
    orig_disabled = daily_mod._source_disabled_reason
    orig_record_success = daily_mod._record_source_success
    orig_record_failure = daily_mod._record_source_failure

    def _stub_fetch(_code: str, *, lookback_days: int) -> pd.DataFrame:
        return sample.tail(lookback_days).copy()

    def _failing_fetch(_code: str, *, lookback_days: int) -> pd.DataFrame:
        raise RuntimeError("offline simulated outage")

    with tempfile.TemporaryDirectory() as tmp:
        cache_dir = Path(tmp)
        try:
            daily_mod._source_disabled_reason = lambda _src: None
            daily_mod._record_source_success = lambda *_a, **_kw: None
            daily_mod._record_source_failure = lambda *_a, **_kw: None

            daily_mod._fetch_daily_tencent = _stub_fetch
            t4 = time.perf_counter()
            miss_df = daily_mod.fetch_daily_history(
                "600519",
                source="tencent",
                lookback_days=35,
                retries=0,
                cache_dir=cache_dir,
                cache_ttl_seconds=3600.0,
                cache_write=True,
            )
            cache_miss_ms = (time.perf_counter() - t4) * 1000.0

            daily_mod._fetch_daily_tencent = _failing_fetch
            t5 = time.perf_counter()
            hit_df = daily_mod.fetch_daily_history(
                "600519",
                source="tencent",
                lookback_days=35,
                retries=0,
                cache_dir=cache_dir,
                cache_ttl_seconds=3600.0,
                cache_write=True,
            )
            cache_hit_ms = (time.perf_counter() - t5) * 1000.0

            stale_df = daily_mod.fetch_daily_history(
                "600519",
                source="tencent",
                lookback_days=35,
                retries=0,
                cache_dir=cache_dir,
                cache_ttl_seconds=0.0,
                cache_write=False,
            )
        finally:
            daily_mod._fetch_daily_tencent = orig_fetch
            daily_mod._source_disabled_reason = orig_disabled
            daily_mod._record_source_success = orig_record_success
            daily_mod._record_source_failure = orig_record_failure

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": len(df),
        "filtered_rows": len(filtered),
        "waterfall_steps": len(steps),
        "doctor_status": doc.status,
        "exposure_buckets": len(exposure),
        "replacement_candidates": len(replacements),
        "timings_ms": {
            "doctor_no_live_ms": round(doctor_ms, 2),
            "apply_hard_filters_ms": round(apply_filters_ms, 2),
            "hard_filter_waterfall_ms": round(waterfall_ms, 2),
            "compute_screen_scores_ms": round(scoring_ms, 2),
            "summarize_portfolio_exposure_ms": round(exposure_ms, 2),
            "daily_cache_miss_ms": round(cache_miss_ms, 2),
            "daily_cache_hit_ms": round(cache_hit_ms, 2),
        },
        "cache_checks": {
            "miss_rows": len(miss_df),
            "hit_source": hit_df.attrs.get("daily_source"),
            "hit_stale": bool(hit_df.attrs.get("daily_stale")),
            "stale_cache_flagged": bool(stale_df.attrs.get("daily_stale")),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic AlphaSift offline benchmark smoke.")
    parser.add_argument("--rows", type=int, default=5000, help="Synthetic snapshot row count (default: 5000)")
    parser.add_argument("--json", action="store_true", help="Output JSON payload")
    args = parser.parse_args(argv)
    payload = run_benchmark(rows=args.rows)
    if args.json:
        print(dumps_strict_json(payload, indent=2))
    else:
        t = payload["timings_ms"]
        print(
            f"AlphaSift benchmark ({payload['rows']} rows -> {payload['filtered_rows']} filtered, "
            f"{payload['waterfall_steps']} steps): "
            f"doctor={t['doctor_no_live_ms']}ms "
            f"waterfall={t['hard_filter_waterfall_ms']}ms "
            f"scoring={t['compute_screen_scores_ms']}ms "
            f"exposure={t['summarize_portfolio_exposure_ms']}ms "
            f"cache_miss={t['daily_cache_miss_ms']}ms "
            f"cache_hit={t['daily_cache_hit_ms']}ms "
            f"stale_ok={payload['cache_checks']['stale_cache_flagged']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
