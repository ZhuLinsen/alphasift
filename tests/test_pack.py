from __future__ import annotations

import hashlib
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import baostock as bs
import numpy as np
import pandas as pd
import pytest

from alphasift import cli, pack
from scripts import build_pack

DATES = ("2025-01-06", "2025-01-07", "2025-01-08")
CODES = ("000001", "000002", "600000")


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(pack, "_baostock_reachable", lambda: True)
    monkeypatch.delenv("TICKPLUS_API_KEY", raising=False)


def _pack(dates=DATES, codes=CODES):
    close = np.arange(len(dates) * len(codes), dtype=np.float32).reshape(len(dates), len(codes)) + 10
    matrices = {key: close.copy() for key in pack.FIELDS}
    meta = pd.DataFrame({"code": codes, "name": ["样本"] * len(codes)})
    return pack.DailyPack(np.array(dates), np.array(codes), matrices, meta, ("synthetic",))


def _daily(codes=CODES, price=12.0):
    return pd.DataFrame({"code": list(codes), **dict.fromkeys(pack.FIELDS, price)})


def test_pack_round_trip_and_history(tmp_path):
    raw = _pack()
    for values in raw.matrices.values():
        values[0, 0] = np.nan
    manifest = pack.save_pack(tmp_path, raw)
    loaded = pack.load_pack(tmp_path)
    assert manifest == loaded.manifest
    assert {
        key: manifest[key] for key in ("schema_version", "market", "n_dates", "n_codes", "first_date", "trade_date", "sources")
    } == {
        "schema_version": 1, "market": "cn", "n_dates": 3, "n_codes": 3,
        "first_date": DATES[0], "trade_date": DATES[-1], "sources": ["synthetic"],
    }
    assert datetime.fromisoformat(manifest["built_at"]).utcoffset().total_seconds() == 0
    assert pack.is_fresh(loaded, DATES[-1])
    assert not pack.is_fresh(loaded, "2025-01-09")
    np.testing.assert_array_equal(loaded.dates, raw.dates)
    np.testing.assert_array_equal(loaded.codes, raw.codes)
    for field in pack.FIELDS:
        np.testing.assert_array_equal(loaded.matrices[field], raw.matrices[field])
        assert loaded.matrices[field].dtype == np.float32
    pd.testing.assert_frame_equal(loaded.meta, raw.meta)
    assert loaded.history("sz.000001")["date"].tolist() == list(DATES[1:])
    assert np.isnan(loaded.history("000001", include_missing=True).loc[0, "close"])
    with pytest.raises(KeyError):
        loaded.history("000003")


@pytest.mark.parametrize("name", ["daily.npz", "meta.csv.gz"])
def test_load_rejects_sha256_mismatch(tmp_path, name):
    pack.save_pack(tmp_path, _pack())
    path = tmp_path / name
    contents = path.read_bytes()
    path.write_bytes(bytes([contents[0] ^ 1]) + contents[1:])
    with pytest.raises(pack.PackError, match=f"SHA-256 mismatch for {name}"):
        pack.load_pack(tmp_path)


def test_load_disallows_pickle(tmp_path):
    raw = _pack()
    manifest = pack.save_pack(tmp_path, raw)
    path = tmp_path / "daily.npz"
    np.savez_compressed(path, dates=raw.dates.astype(object), codes=raw.codes, **raw.matrices)
    manifest["files"][path.name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="allow_pickle=False"):
        pack.load_pack(tmp_path)


def test_failed_publication_restores_previous_assets(tmp_path, monkeypatch):
    before = pack.save_pack(tmp_path, _pack())
    replace = Path.replace

    def fail_manifest(self, target):
        if self.name == "manifest.json":
            raise OSError("simulated rename failure")
        return replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_manifest)
    with pytest.raises(OSError, match="simulated rename failure"):
        pack.save_pack(tmp_path, _pack((*DATES, "2025-01-09")))
    assert pack.load_pack(tmp_path).manifest == before


@pytest.mark.parametrize(
    "close,reference,scales",
    [
        ([100, 104, 52, 53], [99, 100, 52, 52], [0.5, 0.5, 1, 1]),
        ([100, 50, 60, 42], [99, 50, 50, 30], [0.25, 0.5, 0.5, 1]),
        ([100, np.nan, 51, np.nan], [99, np.nan, 50, np.nan], [0.5, 0.5, 1, 1]),
        ([np.nan, 100, 97, 99], [np.nan, 0, 100.0001, 97], [1, 1, 1, 1]),
    ],
)
def test_forward_adjust_by_later_factors(close, reference, scales):
    raw = _pack((*DATES, "2025-01-09"), ("000001", "600000"))
    raw.matrices["close"][:, 0] = close
    raw.matrices["pre_close"][:, 0] = reference
    for key, multiplier in (("open", 0.98), ("high", 1.03), ("low", 0.95)):
        raw.matrices[key][:, 0] = np.array(close) * multiplier
    for key in ("volume", "amount"):
        raw.matrices[key][np.isnan(close), 0] = np.nan
    raw.matrices["pre_close"][1:, 1] = raw.matrices["close"][:-1, 1]
    adjusted = pack.forward_adjust(raw)
    for key in pack.PRICE_FIELDS:
        np.testing.assert_allclose(adjusted[key][:, 0], raw.matrices[key][:, 0] * scales, rtol=1e-6)
        np.testing.assert_array_equal(adjusted[key][:, 1], raw.matrices[key][:, 1])
    for key in ("volume", "amount"):
        np.testing.assert_array_equal(adjusted[key], raw.matrices[key])
    np.testing.assert_array_equal(raw.matrices["close"][:, 0], close)


@pytest.mark.parametrize("dates", [(DATES[0], DATES[0]), (DATES[1], DATES[0])])
def test_save_rejects_duplicate_or_unsorted_dates(tmp_path, dates):
    with pytest.raises(pack.PackError, match="strictly increasing"):
        pack.save_pack(tmp_path, _pack(dates))
    assert not (tmp_path / "manifest.json").exists()


def test_stitch_requires_snapshot_ohlc_and_keeps_missing_codes():
    original = _pack(codes=("000001", "000002", "000003", "000004", "600000"))
    snapshot = _daily(("000002", "000003", "000004", "600000", "600001")).rename(columns={"close": "price"})
    snapshot["name"] = ["新名", "样本", "*ST样本", "样本", "新股"]
    snapshot.attrs.update(quote_date="2025-01-09", snapshot_source="fixture")
    stitched = pack.stitch_snapshot(original, snapshot, "2025-01-09")
    assert stitched.dates.tolist() == [*DATES, "2025-01-09"]
    assert stitched.codes.tolist() == ["000001", "000002", "000003", "000004", "600000", "600001"]
    assert "snapshot:fixture" in stitched.sources
    assert stitched.meta.set_index("code").loc["000004", "is_st"]
    assert stitched.history("600001")["date"].tolist() == ["2025-01-09"]
    assert np.isnan(stitched.history("000001", include_missing=True)["close"].iloc[-1])
    assert original.trade_date == DATES[-1]
    assert pack.stitch_snapshot(stitched, snapshot, "2025-01-09") is stitched

    with pytest.raises(pack.SnapshotStitchError, match=r"Snapshot stitch skipped:.*high, low, open, pre_close"):
        pack.stitch_snapshot(original, snapshot.drop(columns=["high", "low", "open", "pre_close"]), "2025-01-09")
    with pytest.raises(pack.SnapshotStitchError, match="quote date"):
        pack.stitch_snapshot(original, snapshot, "2025-01-10")


def _source_snapshot(source):
    names = dict(zip(("open", "high", "low", "pre_close", "volume"), pack._SNAPSHOT_QUOTES[source][:5]))
    extra = ["600001", "600002", "600003"]
    frame = pd.DataFrame({
        "code": ["000001", "000002", "600000", *extra], "name": ["样本"] * 6, "price": [11.0, 20.0, 5.0, 5.0, 5.0, 5.0],
        names["open"]: [10.5, 0.0, 5.0, 5.0, 5.0, 5.0], names["high"]: [11.2, 0.0, 5.1, 5.1, 5.1, 5.1],
        names["low"]: [10.4, 0.0, 4.9, 4.9, 4.9, 4.9], names["pre_close"]: [10.0, 20.0, 5.0, 5.0, 5.0, 5.0],
        names["volume"]: [300, 0, 50, 50, 50, 50], "amount": [3300.0, 0.0, 250.0, 250.0, 250.0, 250.0],
    })
    frame.attrs["snapshot_source"] = source
    return frame


@pytest.mark.parametrize(
    ("source", "shares"),
    [("sina", 300), ("efinance", 30000), ("akshare_em", 30000), ("em_datacenter", 30000)],
)
def test_stitch_maps_existing_snapshot_sources_and_drops_untraded_rows(source, shares):
    codes = ("000001", "000002", "600000", "600001", "600002", "600003")
    stitched = pack.stitch_snapshot(_pack(codes=codes), _source_snapshot(source), "2025-01-09")
    row = stitched.history("000001").iloc[-1]
    assert (row["open"], row["high"], row["low"], row["close"], row["pre_close"]) == (10.5, 11.2, 10.4, 11.0, 10.0)
    assert row["volume"] == shares
    # 000002 did not trade: no bar, rather than a zero-price one.
    assert np.isnan(stitched.history("000002", include_missing=True)["close"].iloc[-1])


def test_snapshot_provider_uses_first_source_with_quotes(monkeypatch):
    monkeypatch.setattr(pack, "expected_trade_date", lambda: "2025-01-09")
    calls = []

    def fetch(source):
        calls.append(source)
        if source == "sina":
            raise RuntimeError("sina down")
        return _source_snapshot(source)

    monkeypatch.setattr(pack, "fetch_cn_snapshot", fetch)
    config = SimpleNamespace(snapshot_source_priority=["tushare", "sina", "efinance", "akshare_em"])
    provider = pack.SnapshotProvider(config)
    bars = provider.fetch_day("2025-01-09")
    assert calls == ["sina", "efinance"]  # tushare has no open/high/low/previous close
    assert provider.name == "snapshot:efinance"
    assert bars["code"].tolist() == ["000001", "600000", "600001", "600002", "600003"]
    with pytest.raises(pack.PackError, match="latest settled session"):
        provider.fetch_day("2025-01-08")


def test_snapshot_provider_uses_em_datacenter_and_drops_suspended(monkeypatch):
    monkeypatch.setattr(pack, "expected_trade_date", lambda: "2026-11-20")
    snap = pd.DataFrame([
        {
            "code": "000001", "name": "平安", "price": 11.2, "amount": 5.6e8,
            "OPEN_PRICE": 11.0, "HIGH_PRICE": 11.3, "LOW_PRICE": 10.9,
            "PRE_CLOSE_PRICE": 11.05, "VOLUME": 500000,
        },
        {
            "code": "920000", "name": "凤凰", "price": 22.5, "amount": 2.7e7,
            "OPEN_PRICE": 22.0, "HIGH_PRICE": 22.9, "LOW_PRICE": 21.8,
            "PRE_CLOSE_PRICE": 21.9, "VOLUME": 12000,
        },
        {
            "code": "000635", "name": "停牌股", "price": 10.0, "amount": 0.0,
            "OPEN_PRICE": "-", "HIGH_PRICE": "-", "LOW_PRICE": "-",
            "PRE_CLOSE_PRICE": 10.0, "VOLUME": "-",
        },
    ])
    snap.attrs.update(snapshot_source="em_datacenter", quote_date="2026-11-20")
    monkeypatch.setattr(pack, "fetch_cn_snapshot", lambda source: snap)

    config = SimpleNamespace(snapshot_source_priority=["em_datacenter", "sina"])
    provider = pack.SnapshotProvider(config)
    bars = provider.fetch_day("2026-11-20")

    assert provider.name == "snapshot:em_datacenter"
    assert bars["code"].tolist() == ["000001", "920000"]
    assert bars.loc[bars["code"] == "920000", "volume"].iloc[0] == pytest.approx(1_200_000.0)


def test_pack_price_paths_qfq_raw_limit_and_next_open_eval(tmp_path):
    from alphasift.evaluate import evaluate_saved_run
    from alphasift.models import Pick, ScreenResult
    from alphasift.store import save_screen_result

    dates = tuple(d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-04-01", periods=10))
    codes = ("000001", "000002", "920000")
    mats = {field: np.full((10, 3), np.nan, dtype=np.float32) for field in pack.FIELDS}
    for t in range(10):
        # 000001 normal post-entry 2-for-1 split at t=7
        px = 20.0 if t < 7 else 10.0 * (1.02 ** (t - 7))
        pre = 20.0 if t < 7 else (10.0 if t == 7 else mats["close"][t - 1, 0])
        mats["open"][t, 0] = px
        mats["high"][t, 0] = px * 1.01
        mats["low"][t, 0] = px * 0.99
        mats["close"][t, 0] = px
        mats["pre_close"][t, 0] = pre
        mats["volume"][t, 0] = 1_000_000.0
        mats["amount"][t, 0] = 10_000_000.0

        # 000002: pre_close=10.15 on t=4, t=5 opens at 1-price LU=11.17 (10.15*1.10=11.165 -> 11.17),
        # then undergoes 0.909 ex-dividend at t=6 so forward-adjusted prices alone would distort tick math.
        if t < 5:
            p2 = 10.15
            pc2 = 10.15
            o2 = h2 = lo2 = c2 = p2
        elif t == 5:
            pc2 = 10.15
            o2 = h2 = lo2 = c2 = 11.17
        elif t == 6:
            pc2 = 10.15  # ~1.02 ex-div factor
            o2 = h2 = lo2 = c2 = 10.15
        else:
            pc2 = 10.15
            o2 = h2 = lo2 = c2 = 10.15
        mats["open"][t, 1] = o2
        mats["high"][t, 1] = h2
        mats["low"][t, 1] = lo2
        mats["close"][t, 1] = c2
        mats["pre_close"][t, 1] = pc2
        mats["volume"][t, 1] = 1_000_000.0
        mats["amount"][t, 1] = 10_000_000.0

        if t != 2:
            mats["open"][t, 2] = 8.0
            mats["high"][t, 2] = 8.2
            mats["low"][t, 2] = 7.9
            mats["close"][t, 2] = 8.0
            mats["pre_close"][t, 2] = 8.0
            mats["volume"][t, 2] = 500_000.0
            mats["amount"][t, 2] = 4_000_000.0

    meta = pd.DataFrame({"code": list(codes), "name": ["平安", "一字涨停股", "凤凰"]})
    raw_pack = pack.DailyPack(np.array(dates), np.array(codes), mats, meta, ("test",))

    adj_paths = pack.pack_price_paths(raw_pack, codes=["sz.000001", "000002", "920000", "600999"], adjusted=True)
    raw_paths = pack.pack_price_paths(raw_pack, codes=["000001"], adjusted=False)

    assert sorted(adj_paths) == ["000001", "000002", "920000"]
    assert len(adj_paths["920000"]) == 9  # NaN row excluded
    assert adj_paths["000001"].loc[0, "close"] == pytest.approx(10.0, rel=1e-4)
    assert raw_paths["000001"].loc[0, "close"] == pytest.approx(20.0, rel=1e-4)
    assert adj_paths["000002"].loc[5, "raw_open"] == 11.17
    assert adj_paths["000002"].loc[5, "raw_pre_close"] == 10.15

    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="r_pack_eval",
            created_at=f"{dates[4]}T20:00:00+08:00",
            picks=[
                Pick(rank=1, code="000001", name="平安", final_score=80.0, screen_score=80.0, price=20.0),
                Pick(rank=2, code="000002", name="一字涨停股", final_score=78.0, screen_score=78.0, price=10.15),
            ],
        ),
        data_dir=tmp_path,
    )
    bench = pd.DataFrame({"date": list(dates), "open": [3000.0] * len(dates), "close": [3000.0] * len(dates)})
    res = evaluate_saved_run(
        "r_pack_eval",
        config=SimpleNamespace(
            data_dir=tmp_path,
            evaluation_cost_bps=0.0,
            evaluation_follow_through_pct=3.0,
            evaluation_failed_breakout_pct=-5.0,
            evaluation_price_path_enabled=True,
            evaluation_price_path_lookback_days=20,
            daily_source="auto",
            daily_fetch_retries=0,
            daily_fetch_max_workers=1,
            daily_history_cache_dir=None,
            daily_history_cache_ttl_hours=0,
        ),
        current_snapshot=pd.DataFrame(columns=["code", "price"]),
        price_paths=adj_paths,
        with_price_path=False,
        horizon_days=3,
        entry_mode="next_open",
        benchmark_paths={"cn": bench},
    )
    assert res.picks[0].status == "ok"
    assert res.picks[1].status == "untradable_limit_up"
    assert res.untradable_count == 1
    assert res.untradable_share_pct == 50.0


def _daily_sources(monkeypatch, raw_close, adjusted_close, volume=None):
    days = ["2025-01-03", *DATES]
    calls = []

    def fetch(code, *, lookback_days, source, cache_write):
        assert not cache_write
        calls.append((code, source))
        close = raw_close if source == "sina" else adjusted_close
        frame = pd.DataFrame({"date": days, "open": close, "high": close, "low": close, "close": close})
        frame["volume"] = volume.get(code, 100) if volume else 100
        frame["amount"] = np.nan
        return frame

    monkeypatch.setattr(pack, "fetch_daily_history", fetch)
    return calls


def test_daily_sources_rebuild_previous_close_on_ex_date_only(monkeypatch):
    # 10 -> 10.5, then a 1.00 cash dividend (reference 9.50), then 9.7. The qfq
    # series carries a one-cent rounding wobble on the first day, which is not an event.
    _daily_sources(monkeypatch, [10.0, 10.5, 9.6, 9.7], [9.05, 9.5, 9.6, 9.7])
    bars = pack._daily_source_history("000001", list(DATES))
    assert bars["date"].tolist() == list(DATES)
    np.testing.assert_allclose(bars["pre_close"], [10.0, 9.5, 9.6], rtol=1e-6)
    assert bars["amount"].isna().all()

    built = pack.DailyPack(
        np.array(DATES), np.array(["000001"]),
        {key: bars[key].to_numpy(dtype=np.float32)[:, None] for key in pack.FIELDS},
        pd.DataFrame({"code": ["000001"]}), ("sina+tencent",),
    )
    np.testing.assert_allclose(pack.forward_adjust(built)["close"][:, 0], [9.5, 9.6, 9.7], rtol=1e-6)


def test_backfill_from_daily_sources_skips_suspended_days_and_tolerates_one_bad_code(tmp_path, monkeypatch):
    monkeypatch.setattr(pack, "_baostock_reachable", lambda: False)
    listed = (*CODES, "000003", "000004", "000005", "000006", "200002")
    monkeypatch.setattr(pack, "_latest_snapshot", lambda config: _daily(listed))
    flat = [10.0, 10.0, 10.0, 10.0]
    calls = _daily_sources(monkeypatch, flat, flat, volume={"000001": [100, 100, 0, 100]})
    fetch = pack.fetch_daily_history

    def flaky(code, **kwargs):
        if code == "000003":
            raise RuntimeError("source down")
        return fetch(code, **kwargs)

    monkeypatch.setattr(pack, "fetch_daily_history", flaky)
    manifest = pack.backfill(tmp_path, days=3, trade_date=DATES[-1], source="daily")
    loaded = pack.load_pack(tmp_path)
    assert manifest["sources"][0] == "sina+tencent"
    assert loaded.dates.tolist() == list(DATES)
    assert loaded.history("000001")["date"].tolist() == [DATES[0], DATES[2]]
    assert loaded.history("000003").empty
    assert "200002" not in loaded.codes  # B shares in a snapshot are not part of the pack
    assert ("000001", "sina") in calls and ("000001", "tencent") in calls

    calls.clear()
    pack.backfill(tmp_path, days=3, trade_date=DATES[-1], source="daily")
    assert {code for code, _ in calls if code not in pack._REFERENCE_CODES} == set()


def _yf_multi_frame(ticker_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return pd.concat(ticker_frames, axis=1)


def test_yfinance_bars_unsplits_and_roundtrips_forward_adjust():
    # Simulate 002594-style 3-for-1 split + dividend on 2025-01-08:
    # Raw prices: day1=330 (vol=1000), day2=337 (vol=1200), day3=111.42 (vol=3600), day4=112.00 (vol=3000)
    # Ex-date pre_close on day3 = 111.01 (derived from raw_close * adj_prev / adj_cur)
    idx = pd.to_datetime(["2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09"])
    frame = pd.DataFrame({
        "Open": [328.0 / 3, 330.0 / 3, 335.0 / 3, 112.01, 111.50],
        "High": [332.0 / 3, 333.0 / 3, 338.0 / 3, 112.50, 113.00],
        "Low": [327.0 / 3, 329.0 / 3, 334.0 / 3, 109.77, 110.80],
        "Close": [330.0 / 3, 330.0 / 3, 337.0 / 3, 111.42, 112.00],
        "Adj Close": [108.0, 108.0, 110.2909, 111.0054, 111.5833],
        "Volume": [3000.0, 3000.0, 3600.0, 3600.0, 3000.0],
        "Dividends": [0.0, 0.0, 0.0, 1.32466, 0.0],
        "Stock Splits": [0.0, 0.0, 0.0, 3.0, 0.0],
    }, index=idx)
    bars = pack._yfinance_bars_from_frame(frame, ["2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09"])
    assert bars["date"].tolist() == ["2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09"]
    np.testing.assert_allclose(bars["close"], [330.0, 337.0, 111.42, 112.0], rtol=1e-4)
    np.testing.assert_allclose(bars["volume"], [1000.0, 1200.0, 3600.0, 3000.0], rtol=1e-4)
    assert bars.loc[1, "pre_close"] == pytest.approx(330.0, abs=0.01)
    assert bars.loc[2, "pre_close"] == pytest.approx(110.70, abs=0.02)
    assert bars["amount"].isna().all()

    built = pack.DailyPack(
        np.array(bars["date"].tolist()), np.array(["002594"]),
        {key: bars[key].to_numpy(dtype=np.float32)[:, None] for key in pack.FIELDS},
        pd.DataFrame({"code": ["002594"]}), ("yfinance",),
    )
    adj_close = pack.forward_adjust(built)["close"][:, 0]
    # Adjusted return from day 2 to day 3 matches Adj Close return within rounding
    assert (adj_close[2] / adj_close[1]) == pytest.approx(111.0054 / 110.2909, rel=5e-4)


def test_backfill_auto_uses_yfinance_resumes_and_tolerates_one_bad_code(tmp_path, monkeypatch):
    monkeypatch.setattr(pack, "_baostock_reachable", lambda: False)
    listed = (*CODES, "000003")
    monkeypatch.setattr(pack, "_latest_snapshot", lambda config: _daily(listed))
    idx = pd.to_datetime(["2025-01-03", *DATES])
    downloads = []

    def fake_yf(tickers, *, start, end, actions=True):
        downloads.append(list(tickers) if isinstance(tickers, list) else [tickers])
        frames = {}
        for tk in downloads[-1]:
            if tk == "000003.SZ":
                continue
            # 000001 has a cash dividend on 2025-01-08
            if tk == "000001.SZ":
                frames[tk] = pd.DataFrame({
                    "Open": [10.0, 10.2, 10.5, 9.6],
                    "High": [10.1, 10.6, 10.6, 9.8],
                    "Low": [9.9, 10.1, 10.3, 9.4],
                    "Close": [10.0, 10.5, 10.5, 9.6],
                    "Adj Close": [9.0, 9.45, 9.5, 9.6],
                    "Volume": [1000.0, 1100.0, 1200.0, 1300.0],
                    "Dividends": [0.0, 0.0, 0.0, 1.0],
                    "Stock Splits": [0.0, 0.0, 0.0, 0.0],
                }, index=idx)
            else:
                frames[tk] = pd.DataFrame({
                    "Open": [20.0, 20.0, 20.0, 20.0],
                    "High": [21.0, 21.0, 21.0, 21.0],
                    "Low": [19.0, 19.0, 19.0, 19.0],
                    "Close": [20.0, 20.0, 20.0, 20.0],
                    "Adj Close": [20.0, 20.0, 20.0, 20.0],
                    "Volume": [500.0, 500.0, 500.0, 500.0],
                    "Dividends": [0.0, 0.0, 0.0, 0.0],
                    "Stock Splits": [0.0, 0.0, 0.0, 0.0],
                }, index=idx)
        return _yf_multi_frame(frames)

    monkeypatch.setattr(pack, "_yf_download", fake_yf)
    manifest = pack.backfill(tmp_path, days=3, trade_date=DATES[-1])
    loaded = pack.load_pack(tmp_path)
    assert manifest["sources"][0] == "yfinance"
    assert loaded.dates.tolist() == list(DATES)
    assert loaded.history("000001")["pre_close"].tolist() == pytest.approx([10.0, 10.5, 9.5], abs=0.02)
    assert loaded.history("000003").empty

    downloads.clear()
    pack.backfill(tmp_path, days=3, trade_date=DATES[-1])
    # Calendar call still runs, but all cached codes skip bulk download except missing 000003 retry
    assert len(downloads) == 2
    assert downloads[1] == ["000003.SZ"]


def _qt_line(sym: str, code: str, dt: str, o: float, h: float, low_p: float, c: float, pc: float, vol: float, amt_w: float) -> str:
    fields = [""] * 46
    fields[0] = "51"
    fields[1] = "样本"
    fields[2] = code
    fields[3] = str(c)
    fields[4] = str(pc)
    fields[5] = str(o)
    fields[6] = str(vol)
    fields[30] = dt
    fields[33] = str(h)
    fields[34] = str(low_p)
    fields[37] = str(amt_w)
    return f'v_{sym}="{"~".join(fields)}";'


def test_tencent_quote_provider_units_and_update_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(pack, "expected_trade_date", lambda: "2025-01-09")
    monkeypatch.setattr(pack, "fetch_cn_snapshot", lambda source: (_ for _ in ()).throw(RuntimeError("down")))
    base = _pack(codes=("000001", "000002", "688981", "689009", "920002"))
    pack.save_pack(tmp_path, base)
    monkeypatch.setattr(pack, "_latest_snapshot", lambda config: pd.DataFrame({"code": list(base.codes)}))

    lines = "\n".join([
        _qt_line("sz000001", "000001", "20250109150000", 11.9, 12.2, 11.8, 12.1, 12.0, 1000, 120.0),
        _qt_line("sh688981", "688981", "20250109150000", 90.0, 92.0, 89.0, 91.0, 90.5, 50000, 455.0),
        _qt_line("sh689009", "689009", "20250109150000", 34.0, 34.5, 33.5, 34.2, 34.0, 20000, 68.4),
        _qt_line("bj920002", "920002", "20250109150000", 41.0, 42.0, 40.5, 41.5, 41.0, 300, 124.5),
        _qt_line("sz000002", "000002", "20250109150000", 0.0, 0.0, 0.0, 8.0, 8.0, 0, 0.0),
    ])

    class _FakeResp:
        def raise_for_status(self):
            pass

        @property
        def content(self):
            return lines.encode("gbk")

    monkeypatch.setattr(pack.requests.Session, "get", lambda self, url, **kwargs: _FakeResp())
    bars = pack.TencentQuoteProvider(codes=list(base.codes), batch_size=3, workers=2, batch_delay_sec=0.0).fetch_day("2025-01-09")
    by_code = bars.set_index("code")
    assert list(by_code.index) == ["000001", "688981", "689009", "920002"]  # 000002 suspended dropped
    assert by_code.loc["000001", "volume"] == 100000  # lots * 100
    assert by_code.loc["000001", "amount"] == pytest.approx(1200000.0)
    assert by_code.loc["688981", "volume"] == 50000  # STAR shares * 1
    assert by_code.loc["689009", "volume"] == 20000  # CDR shares * 1
    assert by_code.loc["920002", "volume"] == 30000  # BJ lots * 100

    with pytest.raises(pack.PackError, match="no bars for 2025-01-10"):
        pack.TencentQuoteProvider(codes=["000001"], batch_delay_sec=0.0).fetch_day("2025-01-10")

    manifest = pack.update(tmp_path, trade_date="2025-01-09", config=SimpleNamespace(snapshot_source_priority=["sina"]))
    assert "tencent_quote" in manifest["sources"]
    assert pack.load_pack(tmp_path).trade_date == "2025-01-09"


def test_update_prefers_tickplus_only_when_key_is_set(tmp_path, monkeypatch):
    pack.save_pack(tmp_path, _pack())
    monkeypatch.setattr(pack, "_latest_snapshot", lambda config: _daily())
    used = []
    for cls, price in ((pack.TickPlusProvider, 30), (pack.SnapshotProvider, 20)):
        monkeypatch.setattr(cls, "fetch_day", lambda self, day, price=price: used.append(type(self).__name__) or _daily(price=price))
    pack.update(tmp_path, trade_date="2025-01-09")
    assert used == ["SnapshotProvider"]

    monkeypatch.setenv("TICKPLUS_API_KEY", "fixture-key")
    pack.update(tmp_path, trade_date="2025-01-10")
    assert used == ["SnapshotProvider", "TickPlusProvider"]
    assert pack.load_pack(tmp_path).matrices["close"][-1, 0] == 30


class _DayProvider:
    name = "test-provider"

    def __init__(self, bars):
        self.bars = bars
        self.calls = []

    def fetch_day(self, day):
        self.calls.append(day)
        if isinstance(self.bars, Exception):
            raise self.bars
        return self.bars


def test_update_trims_and_same_date_is_idempotent(tmp_path, monkeypatch):
    previous = _pack()
    pack.save_pack(tmp_path, previous)
    snapshot = pd.DataFrame({
        "code": CODES,
        "name": ["平安银行", "*ST样本", "浦发银行"],
        "pe_ratio": [5.1, 1.2, 3.3],
        "list_date": ["1991-04-03", "1991-01-29", "1999-11-10"],
    })
    monkeypatch.setattr(pack, "_latest_snapshot", lambda config: snapshot)
    provider = _DayProvider(_daily(price=20))
    result = pack.update(tmp_path, trade_date="2025-01-09", days=2, provider=provider)
    updated = pack.load_pack(tmp_path)
    assert updated.dates.tolist() == ["2025-01-08", "2025-01-09"]
    np.testing.assert_array_equal(updated.matrices["close"], [previous.matrices["close"][-1], [20] * 3])
    assert updated.meta["name"].tolist() == snapshot["name"].tolist()
    assert updated.meta["is_st"].tolist() == [False, True, False]
    assert result["sources"] == ["synthetic", "test-provider", "snapshot:provided"]
    assert pack.update(tmp_path, trade_date="2025-01-09", days=2, provider=provider) == result
    assert provider.calls == ["2025-01-09"]


def test_update_rejects_truncated_day_even_with_one_day_window(tmp_path, monkeypatch):
    before = pack.save_pack(tmp_path, _pack())
    monkeypatch.setattr(pack, "_latest_snapshot", lambda config: _daily())
    with pytest.raises(pack.PackError, match=r"Truncated.*2025-01-09 \(2 bars, previous day 3\)"):
        pack.update(tmp_path, trade_date="2025-01-09", days=1, provider=_DayProvider(_daily(CODES[:2])))
    assert pack.load_pack(tmp_path).manifest == before


class _Result:
    error_code = "0"
    error_msg = ""

    def __init__(self, rows=(), fields=()):
        self.rows = iter(rows)
        self.fields = list(fields)

    def next(self):
        self.current = next(self.rows, None)
        return self.current is not None

    def get_row_data(self):
        return self.current


def _mock_baostock(monkeypatch, calendar):
    calls = []
    monkeypatch.setattr(bs, "login", lambda: calls.append("login") or _Result())
    monkeypatch.setattr(bs, "logout", lambda: calls.append("logout") or _Result())

    def dates(*, start_date, end_date):
        return _Result((day, is_open) for day, is_open in calendar if start_date <= day <= end_date)

    def query(symbol, fields, *, start_date, end_date, frequency, adjustflag):
        assert pack._BAOSTOCK_LOCK.locked()
        assert frequency == "d" and adjustflag == "3"
        assert "preclose" in fields.split(",") and "tradestatus" in fields.split(",")
        calls.append(symbol)
        return _Result(
            (day, "10", "12", "9", "11", "8", "100", "1100", "0" if symbol == "sz.000002" and day == DATES[0] else "1")
            for day, is_open in calendar if is_open == "1" and start_date <= day <= end_date
        )

    monkeypatch.setattr(bs, "query_trade_dates", dates)
    monkeypatch.setattr(bs, "query_history_k_data_plus", query)
    monkeypatch.setattr(bs, "query_stock_basic", lambda: _Result(
        [("sz.000001", "1990-01-01", "", "1"), ("sh.600000", "1999-01-01", "", "1"),
         ("sh.600002", "1999-01-01", "2010-01-01", "1"), ("sh.000001", "1990-01-01", "", "2")],
        ["code", "ipoDate", "outDate", "type"],
    ))
    return calls


def test_backfill_uses_trading_calendar_and_resumes_exact_range(tmp_path, monkeypatch):
    calls = _mock_baostock(monkeypatch, [(day, "1") for day in (*DATES, "2025-01-09")])
    monkeypatch.setattr(pack, "_latest_snapshot", lambda config: pd.DataFrame({"code": ["000001", "000002"]}))
    limited = pack.backfill(tmp_path, days=3, codes_limit=1, trade_date=DATES[-1])
    assert limited["n_codes"] == 1
    assert calls == ["login", "sz.000001", "logout"]
    full = pack.backfill(tmp_path, days=3, trade_date=DATES[-1])
    assert full["n_codes"] == 3
    assert calls == ["login", "sz.000001", "logout", "login", "sz.000002", "sh.600000", "logout"]
    loaded = pack.load_pack(tmp_path)
    assert loaded.dates.tolist() == list(DATES)
    assert loaded.codes.tolist() == list(CODES)
    assert loaded.history("000002")["date"].tolist() == list(DATES[1:])
    assert loaded.history("000001")["pre_close"].tolist() == [8] * 3
    pack.backfill(tmp_path, days=3, codes_limit=1, trade_date="2025-01-09")
    assert calls[-3:] == ["login", "sz.000001", "logout"]


def test_backfill_retries_codes_missing_from_rejected_session(tmp_path, monkeypatch):
    calendar = [(day, "1") for day in DATES]
    calls = _mock_baostock(monkeypatch, calendar)
    monkeypatch.setattr(pack, "_latest_snapshot", lambda config: _daily())
    query = bs.query_history_k_data_plus

    def incomplete(symbol, fields, **kwargs):
        if symbol != "sh.600000":
            return query(symbol, fields, **kwargs)
        calls.append(symbol)
        return _Result([
            (day, "10", "12", "9", "11", "8", "100", "1100", "1") for day in DATES[:-1]
        ])

    monkeypatch.setattr(bs, "query_history_k_data_plus", incomplete)
    with pytest.raises(pack.PackError, match="Truncated.*2025-01-08"):
        pack.backfill(tmp_path, days=3, trade_date=DATES[-1])
    monkeypatch.setattr(bs, "query_history_k_data_plus", query)
    calls.clear()
    pack.backfill(tmp_path, days=3, trade_date=DATES[-1])
    assert calls == ["login", "sh.600000", "logout"]
    assert pack.load_pack(tmp_path).trade_date == DATES[-1]


@pytest.mark.parametrize("incremental_ok", [True, False])
def test_update_fills_gaps_or_falls_back_for_target(tmp_path, monkeypatch, incremental_ok):
    pack.save_pack(tmp_path, _pack())
    monkeypatch.setattr(pack, "_latest_snapshot", lambda config: _daily())
    calls = _mock_baostock(monkeypatch, [("2025-01-09", "0"), ("2025-01-10", "1"), ("2025-01-13", "1")])
    provider = _DayProvider(_daily(price=20) if incremental_ok else RuntimeError("provider failure"))
    result = pack.update(tmp_path, trade_date="2025-01-13", days=4, provider=provider)
    loaded = pack.load_pack(tmp_path)
    assert loaded.dates.tolist() == [*DATES[1:], "2025-01-10", "2025-01-13"]
    assert calls == ["login", "sz.000001", "sz.000002", "sh.600000", "logout"]
    assert provider.calls == ["2025-01-13"]
    assert "baostock" in result["sources"]
    assert ("test-provider" in result["sources"]) == incremental_ok
    assert loaded.matrices["close"][-1, 0] == (20 if incremental_ok else 11)


class _Response:
    def __init__(self, contents):
        self.contents = contents

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield self.contents


def _release(source, monkeypatch, *, corrupted=None):
    calls = []
    files = {path.name: path.read_bytes() for path in source.iterdir() if path.is_file()}

    def get(url, *, stream, timeout):
        assert stream and timeout
        calls.append(url)
        name = url.rsplit("/", 1)[-1]
        return _Response(b"corrupted" if name == corrupted else files[name])

    monkeypatch.setattr(pack.requests, "get", get)
    return calls


def test_pull_skips_unchanged_assets(tmp_path, monkeypatch):
    remote, local = tmp_path / "remote", tmp_path / "local"
    manifest = pack.save_pack(remote, _pack())
    calls = _release(remote, monkeypatch)
    monkeypatch.setenv("ALPHASIFT_PACK_REPO", "fixture/market-data")
    assert pack.pull(local) == manifest
    assert calls == [
        f"https://github.com/fixture/market-data/releases/download/data-cn/{name}"
        for name in ("manifest.json", "daily.npz", "meta.csv.gz")
    ]
    calls.clear()
    assert pack.pull(local) == manifest
    assert calls == ["https://github.com/fixture/market-data/releases/download/data-cn/manifest.json"]
    assert pack.load_pack(local).manifest == manifest


def test_pull_rejects_corrupted_asset_without_replacing_pack(tmp_path, monkeypatch):
    remote, local = tmp_path / "remote", tmp_path / "local"
    original = pack.save_pack(local, _pack())
    pack.save_pack(remote, _pack((*DATES, "2025-01-09")))
    _release(remote, monkeypatch, corrupted="meta.csv.gz")
    before = {p.name: p.read_bytes() for p in local.iterdir() if p.is_file()}
    with pytest.raises(pack.PackError, match=r"SHA-256 mismatch for meta.csv.gz"):
        pack.pull(local, repo="fixture/market-data", tag="canary")
    assert {p.name: p.read_bytes() for p in local.iterdir() if p.is_file()} == before
    assert pack.load_pack(local).manifest == original


@pytest.fixture
def _tickplus(monkeypatch):
    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2025, 1, 9, 16, tzinfo=tz)

    monkeypatch.setattr(pack, "datetime", _Clock)
    monkeypatch.setenv("TICKPLUS_API_KEY", "fixture+token-secret")
    return "2025-01-09"


def test_tickplus_documented_fields(_tickplus, monkeypatch):
    payload = [dict(t=f"{_tickplus} 15:00:00", code="000001", o=12.9, c=13.1, h=13.3, l=12.8, v=181, a=237000, pc=12.5)]
    requests = []

    class _Connection:
        def __init__(self, host, timeout):
            assert host == "api.tickplus.org" and timeout > 0

        def request(self, method, target):
            parts = urlsplit(target)
            requests.append((method, parts.path, parse_qs(parts.query)))

        def getresponse(self):
            return SimpleNamespace(status=200, read=lambda: json.dumps(payload).encode())

        def close(self):
            pass

    monkeypatch.setattr(pack.http.client, "HTTPConnection", _Connection)
    frame = pack.TickPlusProvider().fetch_day(_tickplus)
    assert requests == [("GET", "/plus/basic/updatedaykline", {
        "symbol": ["stock"], "dividend": ["1"], "tradeDate": [_tickplus], "token": ["fixture+token-secret"],
    })]
    assert list(frame.columns) == ["code", *pack.FIELDS]
    assert frame.loc[0, "code"] == "000001"
    assert frame.loc[0, "volume"] == 18100
    assert frame.loc[0, "amount"] == 237000
    assert frame.loc[0, "pre_close"] == 12.5
    assert frame.loc[0, "close"] == pytest.approx(13.1)


@pytest.mark.parametrize("failure", ["transport", "vendor_body"])
def test_tickplus_redacts_query_and_vendor_errors(_tickplus, failure, monkeypatch, caplog):
    class _Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, method, target):
            self.target = target
            if failure == "transport":
                raise OSError(f"Failed to reach http://api.tickplus.org{target}")

        def getresponse(self):
            payload = json.dumps({"message": f"invalid token fixture+token-secret for {self.target}"})
            return SimpleNamespace(status=200, read=lambda: payload.encode())

        def close(self):
            pass

    monkeypatch.setattr(pack.http.client, "HTTPConnection", _Connection)
    with pytest.raises(pack.PackError, match="TickPlus updatedaykline") as raised:
        pack.TickPlusProvider().fetch_day(_tickplus)
    rendered = "".join(traceback.format_exception(raised.type, raised.value, raised.tb)) + caplog.text
    assert "fixture+token-secret" not in rendered
    assert "fixture%2Btoken-secret" not in rendered
    assert "token=" not in rendered


def test_cli_pack_info_and_build(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ALPHASIFT_PACK_DIR", str(tmp_path))
    pack.save_pack(tmp_path, _pack())
    monkeypatch.setattr(sys, "argv", ["alphasift", "pack", "info", "--trade-date", DATES[-1]])
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["trade_date"] == result["expected_trade_date"] == DATES[-1]
    assert result["fresh"] is True
    calls = []

    def backfill(directory, **kwargs):
        calls.append((directory, kwargs["days"], kwargs["codes_limit"]))
        assert kwargs["source"] == "auto"
        return {"market": "cn"}

    monkeypatch.setattr(pack, "backfill", backfill)
    monkeypatch.setattr(sys, "argv", ["alphasift", "pack", "build", "--days", "10", "--codes-limit", "2"])
    cli.main()
    assert calls == [(tmp_path, 10, 2)]
    assert json.loads(capsys.readouterr().out) == {"market": "cn"}


def test_build_script_dispatches_update(tmp_path, monkeypatch, capsys):
    def update(directory, **kwargs):
        assert directory == tmp_path
        assert kwargs == {"days": 30, "trade_date": "2025-01-10", "source": "daily"}
        return {"market": "cn"}

    monkeypatch.setattr(pack, "update", update)
    monkeypatch.setattr(sys, "argv", [
        "build_pack.py", "update", "--dir", str(tmp_path), "--days", "30", "--trade-date", "2025-01-10",
        "--source", "daily",
    ])
    build_pack.main()
    assert json.loads(capsys.readouterr().out) == {"market": "cn"}
