from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from alphasift import pack
from alphasift.config import Config
from alphasift.daily import _DAILY_FEATURE_DEFAULTS, compute_daily_features
from alphasift.markets import get_market
from alphasift.pack_features import compute_matrix_daily_features, compute_pack_daily_features
from alphasift.pipeline import screen


def _dates(n: int, start: str = "2025-01-02") -> np.ndarray:
    return np.array(pd.bdate_range(start, periods=n).strftime("%Y-%m-%d").tolist(), dtype="U10")


def _assert_parity(pack_obj: pack.DailyPack, code: str, got_row: pd.Series) -> None:
    adj = pack.forward_adjust(pack_obj)
    idx = int(pack_obj.codes.searchsorted(code))
    hist = pd.DataFrame({
        "date": pack_obj.dates,
        **{k: adj[k][:, idx] for k in ("open", "high", "low", "close", "volume")},
    }).dropna(subset=["close"]).reset_index(drop=True)
    ref = compute_daily_features(hist)
    for col in _DAILY_FEATURE_DEFAULTS:
        if col == "daily_source":
            assert got_row[col] == "pack"
            continue
        rv = ref.get(col)
        gv = got_row.get(col)
        if gv is pd.NA or (isinstance(gv, float) and np.isnan(gv)):
            gv = None
        if rv is None and gv is None:
            continue
        if isinstance(rv, bool) or isinstance(gv, bool):
            assert bool(rv) == bool(gv), f"{code}.{col}: {rv} != {gv}"
        elif isinstance(rv, str) or isinstance(gv, str):
            assert str(rv) == str(gv), f"{code}.{col}: {rv!r} != {gv!r}"
        else:
            assert gv is not None and rv is not None, f"{code}.{col}: {rv} != {gv}"
            assert float(gv) == pytest.approx(float(rv), abs=2e-4), f"{code}.{col}: {rv} != {gv}"


def test_pack_features_exact_parity_across_lengths_gaps_and_splits():
    n_dates = 120
    dates = _dates(n_dates)
    lengths = [1, 2, 10, 15, 20, 34, 35, 59, 60, 120, 120, 120, 120]
    codes = np.array([f"000{i + 1:03d}" for i in range(len(lengths))], dtype="U6")
    mats = {k: np.full((n_dates, len(codes)), np.nan, dtype=np.float32) for k in pack.FIELDS}

    rng = np.random.default_rng(123)
    for j, length in enumerate(lengths):
        start = n_dates - length
        if j == 10:
            # Flat price -> zero-loss RSI -> None
            close = np.full(length, 10.0, dtype=np.float32)
        elif j == 11:
            # Ex-rights split (halving on day 60)
            close = 20.0 + np.linspace(0, 4.0, length, dtype=np.float32)
            close[60:] *= 0.5
        else:
            close = 12.0 * np.cumprod(1.0 + rng.normal(0.001, 0.02, size=length)).astype(np.float32)
        mats["close"][start:, j] = close
        mats["open"][start:, j] = close * np.float32(0.995)
        mats["high"][start:, j] = close * np.float32(1.015)
        mats["low"][start:, j] = close * np.float32(0.985)
        mats["pre_close"][start:, j] = close
        if length > 1:
            mats["pre_close"][start + 1 :, j] = close[:-1]
        if j == 11:
            mats["pre_close"][start + 60, j] = np.float32(close[59] * 0.5)
        mats["volume"][start:, j] = np.linspace(1000, 2000, length, dtype=np.float32)
        mats["amount"][start:, j] = mats["volume"][start:, j] * close

    # Inject internal suspension NaN gaps into column 9 (length=120)
    for gap_row in (10, 45, 46, 95):
        for k in pack.FIELDS:
            mats[k][gap_row, 9] = np.nan

    # Inject invalid OHLC and negative volume into column 12
    mats["high"][-1, 12] = mats["low"][-1, 12] - np.float32(0.5)
    mats["volume"][-5, 12] = np.float32(-10.0)

    daily_pack = pack.DailyPack(
        dates=dates,
        codes=codes,
        matrices=mats,
        meta=pd.DataFrame({"code": codes, "name": ["样本"] * len(codes)}),
        sources=("synthetic",),
    )
    features = compute_pack_daily_features(daily_pack).set_index("code")
    for code in codes:
        _assert_parity(daily_pack, str(code), features.loc[str(code)])

    assert pd.isna(features.loc["000011", "rsi14"])
    assert features.loc["000011", "rsi_status"] == "neutral"
    assert "invalid_ohlc" in features.loc["000013", "daily_quality_flags"]
    assert "negative_volume" in features.loc["000013", "daily_quality_flags"]


def test_pack_features_as_of_index_has_no_lookahead():
    codes = np.array(["000001", "600000"], dtype="U6")
    mats = {k: np.full((90, 2), np.nan, dtype=np.float32) for k in pack.FIELDS}
    base = np.linspace(10.0, 15.0, 90, dtype=np.float32)
    for j in range(2):
        mats["close"][:, j] = base
        mats["open"][:, j] = base * np.float32(0.99)
        mats["high"][:, j] = base * np.float32(1.01)
        mats["low"][:, j] = base * np.float32(0.98)
        mats["pre_close"][:, j] = np.r_[base[0], base[:-1]]
        mats["volume"][:, j] = 1000.0
        mats["amount"][:, j] = 10000.0

    f_before = compute_matrix_daily_features(codes, mats, as_of_index=74).set_index("code")
    # Mutate future bars (75..89) drastically
    mats["close"][75:, :] *= 3.0
    mats["high"][75:, :] *= 3.0
    mats["low"][75:, :] *= 3.0
    mats["open"][75:, :] *= 3.0
    mats["volume"][75:, :] *= 10.0
    f_after = compute_matrix_daily_features(codes, mats, as_of_index=74).set_index("code")
    pd.testing.assert_frame_equal(f_before, f_after)


def _build_screening_fixture(
    n_codes: int = 160,
    trade_date: str = "2026-11-20",
    *,
    strategy_mode: str = "volume_breakout",
) -> tuple[pack.DailyPack, pd.DataFrame, str]:
    n_dates = 90
    dates = np.array(
        pd.bdate_range(end=trade_date, periods=n_dates).strftime("%Y-%m-%d").tolist(),
        dtype="U10",
    )
    codes = np.array([f"00{i + 1:04d}" for i in range(n_codes)], dtype="U6")
    mats = {k: np.full((n_dates, n_codes), np.nan, dtype=np.float32) for k in pack.FIELDS}
    target_idx = min(149, n_codes - 1)  # rank past Top-100 when n_codes >= 150
    target_code = str(codes[target_idx])

    for j in range(n_codes):
        if j == target_idx:
            if strategy_mode == "volume_breakout":
                # Tight 15d consolidation then clear breakout above 20d high with 2x volume
                close = np.full(n_dates, 10.0, dtype=np.float32)
                close[:65] = np.linspace(9.2, 10.0, 65, dtype=np.float32)
                close[65:-1] = np.float32(10.0)
                close[-1] = np.float32(10.45)
                open_ = close.copy()
                open_[-1] = np.float32(10.05)
                high = close * np.float32(1.01)
                low = close * np.float32(0.99)
                vol = np.full(n_dates, 1000.0, dtype=np.float32)
                vol[-1] = np.float32(2500.0)
            else:
                # shrink_pullback: steady bullish trend + mild low-volume pullback right above ma20
                close = np.linspace(10.0, 13.0, n_dates, dtype=np.float32)
                close[-4:] = np.array([12.95, 12.88, 12.84, 12.82], dtype=np.float32)
                open_ = close * np.float32(0.998)
                high = close * np.float32(1.008)
                low = close * np.float32(0.992)
                vol = np.full(n_dates, 1500.0, dtype=np.float32)
                vol[-1] = np.float32(900.0)
        else:
            # Fails daily hard filters (below MA20 downtrend) even though high snapshot score
            close = np.linspace(20.0, 10.0, n_dates, dtype=np.float32)
            open_ = close * np.float32(1.002)
            high = close * np.float32(1.01)
            low = close * np.float32(0.99)
            vol = np.full(n_dates, 1000.0, dtype=np.float32)

        mats["close"][:, j] = close
        mats["open"][:, j] = open_
        mats["high"][:, j] = high
        mats["low"][:, j] = low
        mats["pre_close"][:, j] = np.r_[close[0], close[:-1]]
        mats["volume"][:, j] = vol
        mats["amount"][:, j] = vol * close

    snap_rows = []
    for j, code in enumerate(codes):
        is_target = j == target_idx
        snap_rows.append({
            "code": str(code),
            "name": f"样本{j}",
            "industry": f"行业{j % 10}",
            "price": float(mats["close"][-1, j]),
            "change_pct": 4.5 if is_target else 5.0,
            "amount": 200_000_000.0 if is_target else (500_000_000.0 + (n_codes - j) * 1_000_000.0),
            "turnover_rate": 3.5 if (is_target and strategy_mode == "volume_breakout") else (2.0 if is_target else 6.0),
            "volume_ratio": 2.5 if (is_target and strategy_mode == "volume_breakout") else (1.0 if is_target else 3.0),
            "pe_ratio": 20.0 if is_target else 8.0,
            "pb_ratio": 2.0 if is_target else 0.8,
            "total_mv": 10_000_000_000.0,
        })
    snap = pd.DataFrame(snap_rows)
    snap.attrs["snapshot_source"] = "test"
    snap.attrs["quote_date"] = trade_date
    daily_pack = pack.DailyPack(
        dates=dates,
        codes=codes,
        matrices=mats,
        meta=pd.DataFrame({"code": codes, "name": [f"样本{j}" for j in range(n_codes)]}),
        sources=("synthetic",),
    )
    return daily_pack, snap, target_code


@pytest.mark.parametrize("strategy_name", ["volume_breakout", "shrink_pullback"])
def test_pipeline_pack_discovers_candidate_past_top_100(monkeypatch, strategy_name):
    daily_pack, snap, target_code = _build_screening_fixture(strategy_mode=strategy_name)
    monkeypatch.setattr("alphasift.pipeline.fetch_snapshot_with_fallback", lambda sources, **kwargs: snap)
    seen_without_pack: list[str] = []

    def fake_enrich_top100(df, **kwargs):
        seen_without_pack.extend(df["code"].tolist())
        return df.assign(
            ma_bullish=False,
            price_above_ma20=False,
            signal_score=40.0,
            macd_status="bearish",
            rsi_status="neutral",
            breakout_20d_pct=-10.0,
            range_20d_pct=40.0,
            volume_ratio_20d=0.5,
            body_pct=-1.0,
            pullback_to_ma20_pct=-10.0,
            consolidation_days_20d=0,
            volatility_20d_pct=60.0,
            max_drawdown_20d_pct=-20.0,
            atr_20_pct=9.0,
            daily_quality_score=100.0,
            daily_quality_flags="",
            daily_source="mock",
        )

    monkeypatch.setattr("alphasift.pipeline.enrich_daily_features", fake_enrich_top100)
    cfg = Config(
        llm_api_key="",
        snapshot_source_priority=["test"],
        strategies_dir=Path("strategies"),
        daily_enrich_max_candidates=100,
        risk_enabled=False,
    )

    # Without pack: target #150 is truncated out of Top-100
    cfg_no_pack = Config(
        llm_api_key="",
        snapshot_source_priority=["test"],
        strategies_dir=Path("strategies"),
        daily_enrich_max_candidates=100,
        daily_pack_enabled=False,
        risk_enabled=False,
    )
    without_pack = screen(strategy_name, use_llm=False, post_analyzers=[], config=cfg_no_pack)
    assert without_pack.picks == []
    assert len(seen_without_pack) == 100
    assert target_code not in seen_without_pack

    # With pack: target #150 is discovered across full market
    with_pack = screen(
        strategy_name,
        use_llm=False,
        post_analyzers=[],
        config=cfg,
        daily_pack=daily_pack,
        explain_filters=True,
    )
    assert with_pack.daily_enriched is True
    assert with_pack.daily_enrich_count == 160
    assert [p.code for p in with_pack.picks] == [target_code]
    assert with_pack.picks[0].daily_source == "pack"
    assert any("Daily K-line enrichment via CN pack" in item for item in with_pack.degradation)


def test_pipeline_pack_fallback_on_corrupt_or_stale_and_stitch_on_ohlc(tmp_path, monkeypatch):
    daily_pack, snap, target_code = _build_screening_fixture(n_codes=10, trade_date="2026-11-20")
    pack_dir_path = tmp_path / "pack"
    pack.save_pack(pack_dir_path, daily_pack)
    monkeypatch.setattr("alphasift.pipeline.fetch_snapshot_with_fallback", lambda sources, **kwargs: snap)

    fallback_calls = []

    def fake_enrich(df, **kwargs):
        fallback_calls.append(len(df))
        out = df.copy()
        for col, default in _DAILY_FEATURE_DEFAULTS.items():
            out[col] = default
        out["daily_source"] = "fallback"
        return out

    monkeypatch.setattr("alphasift.pipeline.enrich_daily_features", fake_enrich)
    cfg = Config(
        llm_api_key="",
        snapshot_source_priority=["test"],
        strategies_dir=Path("strategies"),
        daily_pack_dir=pack_dir_path,
        risk_enabled=False,
    )

    # 1. Corrupt manifest -> degrades cleanly to enrich_daily_features
    (pack_dir_path / "manifest.json").write_text("{bad json", encoding="utf-8")
    res_corrupt = screen("volume_breakout", use_llm=False, post_analyzers=[], config=cfg)
    assert len(fallback_calls) == 1
    assert any("CN daily pack fallback:" in item for item in res_corrupt.degradation)

    # 2. Stale pack + snapshot without OHLC -> degrades cleanly
    stale_dates = daily_pack.dates[:-1]
    stale_mats = {k: v[:-1] for k, v in daily_pack.matrices.items()}
    stale_pack = pack.DailyPack(
        dates=stale_dates,
        codes=daily_pack.codes,
        matrices=stale_mats,
        meta=daily_pack.meta,
        sources=("synthetic",),
    )
    pack.save_pack(pack_dir_path, stale_pack)
    res_stale = screen("volume_breakout", use_llm=False, post_analyzers=[], config=cfg)
    assert len(fallback_calls) == 2
    assert any("CN daily pack stale" in item for item in res_stale.degradation)

    # 3. Stale-by-1-day pack + snapshot WITH Sina-mapped OHLC -> stitches in memory & succeeds via pack
    snap_ohlc = snap.copy()
    snap_ohlc.attrs["snapshot_source"] = "sina"
    snap_ohlc.attrs["quote_date"] = "2026-11-20"
    code_to_col = {str(c): idx for idx, c in enumerate(daily_pack.codes)}
    snap_ohlc["open"] = [float(daily_pack.matrices["open"][-1, code_to_col[c]]) for c in snap_ohlc["code"]]
    snap_ohlc["high"] = [float(daily_pack.matrices["high"][-1, code_to_col[c]]) for c in snap_ohlc["code"]]
    snap_ohlc["low"] = [float(daily_pack.matrices["low"][-1, code_to_col[c]]) for c in snap_ohlc["code"]]
    snap_ohlc["settlement"] = [float(daily_pack.matrices["pre_close"][-1, code_to_col[c]]) for c in snap_ohlc["code"]]
    snap_ohlc["volume"] = [float(daily_pack.matrices["volume"][-1, code_to_col[c]]) for c in snap_ohlc["code"]]
    monkeypatch.setattr("alphasift.pipeline.fetch_snapshot_with_fallback", lambda sources, **kwargs: snap_ohlc)

    res_stitched = screen("volume_breakout", use_llm=False, post_analyzers=[], config=cfg)
    assert len(fallback_calls) == 2  # did NOT fall back
    assert [p.code for p in res_stitched.picks] == [target_code]
    assert res_stitched.picks[0].daily_source == "pack"


def test_non_cn_market_ignores_daily_pack(tmp_path, monkeypatch):
    assert get_market("cn").supports_daily_pack is True
    assert get_market("us").supports_daily_pack is False

    daily_pack, _, _ = _build_screening_fixture(n_codes=5, trade_date="2026-11-20")
    pack_dir_path = tmp_path / "pack"
    pack.save_pack(pack_dir_path, daily_pack)
    (pack_dir_path / "manifest.json").write_text(json.dumps({"broken": True}), encoding="utf-8")

    us_snap = pd.DataFrame([
        {
            "code": "AAPL",
            "name": "Apple Inc.",
            "price": 220.0,
            "change_pct": 1.2,
            "amount": 5_000_000_000.0,
            "avg_amount_usd": 5_000_000_000.0,
            "total_mv": 3_000_000_000_000.0,
            "pe_ratio": 10.0,
            "pb_ratio": 1.5,
            "industry": "Technology",
        }
    ])
    us_snap.attrs["snapshot_source"] = "yahoo_screener"
    monkeypatch.setattr("alphasift.pipeline.fetch_snapshot_with_fallback", lambda sources, **kwargs: us_snap)

    seen_sources = []

    def fake_enrich(df, **kwargs):
        seen_sources.append(kwargs.get("source"))
        return df.assign(daily_source="yfinance")

    monkeypatch.setattr("alphasift.pipeline.enrich_daily_features", fake_enrich)
    res = screen(
        "global_value",
        market="us",
        daily_enrich=True,
        use_llm=False,
        post_analyzers=[],
        config=Config(
            llm_api_key="",
            snapshot_source_priority=["yahoo_screener"],
            strategies_dir=Path("strategies"),
            daily_pack_dir=pack_dir_path,
            risk_enabled=False,
        ),
    )
    assert seen_sources == ["yfinance"]
    assert not any("CN daily pack" in item for item in res.degradation)


def test_pack_features_performance_250_by_5400():
    n_dates, n_codes = 250, 5400
    dates = _dates(n_dates)
    codes = np.array([f"{i + 1:06d}" for i in range(n_codes)], dtype="U6")
    base = np.linspace(10.0, 12.0, n_dates, dtype=np.float32)[:, None]
    close = np.broadcast_to(base, (n_dates, n_codes)).copy()
    mats = {
        "open": close * np.float32(0.995),
        "high": close * np.float32(1.01),
        "low": close * np.float32(0.99),
        "close": close,
        "pre_close": close,
        "volume": np.full((n_dates, n_codes), 10000.0, dtype=np.float32),
        "amount": np.full((n_dates, n_codes), 100000.0, dtype=np.float32),
    }
    daily_pack = pack.DailyPack(
        dates=dates,
        codes=codes,
        matrices=mats,
        meta=pd.DataFrame({"code": codes}),
        sources=("synthetic",),
    )
    t0 = time.perf_counter()
    features = compute_pack_daily_features(daily_pack)
    elapsed = time.perf_counter() - t0
    assert len(features) == n_codes
    assert elapsed < 3.0
