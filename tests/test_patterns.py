# -*- coding: utf-8 -*-
"""Tests for stateless CN patterns, schema validation, zero look-ahead, and next_open replay."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

from alphasift.cli import main as cli_main
from alphasift.pack import DailyPack, FIELDS, save_pack
from alphasift.pattern_replay import (
    _benjamini_hochberg_q_values,
    _evaluate_graduation,
    _newey_west_t_stat,
    _summarize_horizon_obs,
    _summarize_stability,
    load_cn_benchmark,
    render_replay_markdown,
    replay_patterns,
)
from alphasift.patterns import (
    PatternSpec,
    build_pattern_context,
    compute_overhead_supply_10pct_row,
    evaluate_pattern_matrix,
    list_patterns,
    load_pattern,
    scan_patterns,
)


def _dates(n: int) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-01-05", periods=n)]


def _make_ohlcv_pack(
    series_by_code: dict[str, list[tuple[float, float, float, float, float, float]]],
    *,
    is_st_map: dict[str, bool] | None = None,
    dates: list[str] | None = None,
) -> DailyPack:
    codes = sorted(series_by_code.keys())
    t_len = len(next(iter(series_by_code.values())))
    date_list = dates if dates is not None else _dates(t_len)
    matrices = {field: np.full((t_len, len(codes)), np.nan, dtype=np.float32) for field in FIELDS}
    for j, code in enumerate(codes):
        for t, (op, hi, lo, cl, pc, vol) in enumerate(series_by_code[code]):
            matrices["open"][t, j] = op
            matrices["high"][t, j] = hi
            matrices["low"][t, j] = lo
            matrices["close"][t, j] = cl
            matrices["pre_close"][t, j] = pc
            matrices["volume"][t, j] = vol
            matrices["amount"][t, j] = cl * vol
    meta = pd.DataFrame([
        {
            "code": c,
            "name": f"N{c}",
            "industry": "半导体",
            "pe_ratio": 25.0,
            "pb_ratio": 2.5,
            "total_mv": 1e10,
            "circ_mv": 8e9,
            "list_date": "2018-01-01",
            "is_st": bool((is_st_map or {}).get(c, False)),
        }
        for c in codes
    ])
    return DailyPack(
        dates=np.asarray(date_list, dtype=str),
        codes=np.asarray(codes, dtype=str),
        matrices=matrices,
        meta=meta,
        sources=("test",),
    )


def _flat_bars(n: int, price: float = 10.0, vol: float = 10_000_000.0) -> list[tuple[float, float, float, float, float, float]]:
    return [(price, price + 0.12, price - 0.12, price, price, vol) for _ in range(n)]


def _to_pack_bars(
    rows: list[tuple[float, float, float, float, float]],
) -> list[tuple[float, float, float, float, float, float]]:
    out = []
    prev_c = rows[0][3]
    for op, hi, lo, cl, vol in rows:
        out.append((op, hi, lo, cl, prev_c, vol))
        prev_c = cl
    return out


def test_pattern_yaml_mirror_sync_and_schema_validation(tmp_path: Path) -> None:
    repo_dir = Path("patterns")
    bundled_dir = Path("alphasift/patterns")
    repo_files = sorted(repo_dir.glob("*.yaml"))
    assert len(repo_files) == 9
    for rf in repo_files:
        bf = bundled_dir / rf.name
        assert bf.is_file(), f"Missing bundled mirror {bf}"
        assert rf.read_bytes() == bf.read_bytes()

    specs = list_patterns(include_experimental=True)
    assert len(specs) == 9
    assert len(list_patterns(include_experimental=False)) >= 2
    assert all(spec.family in {"bottom_reversal", "trend_continuation", "breakout"} for spec in specs)
    assert all(spec.market_scope == ("cn",) for spec in specs)

    bad_relay = tmp_path / "bad_relay.yaml"
    bad_relay.write_text(
        "name: bad_relay\nfamily: relay\nstatus: experimental\nmode: direct\nmarket_scope: [cn]\n"
        "conditions:\n  - feature: body_atr\n    min: 1.0\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Invalid family"):
        load_pattern(bad_relay)

    bad_key = tmp_path / "bad_key.yaml"
    bad_key.write_text(
        "name: bad_key\nfamily: breakout\nmode: direct\nmarket_scope: [cn]\nunknown_top: 1\n"
        "conditions:\n  - feature: body_atr\n    min: 1.0\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Unknown top-level keys"):
        load_pattern(bad_key)

    bad_feat = tmp_path / "bad_feat.yaml"
    bad_feat.write_text(
        "name: bad_feat\nfamily: breakout\nmode: direct\nmarket_scope: [cn]\n"
        "conditions:\n  - feature: nonexistent_metric\n    min: 1.0\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Invalid or disallowed feature"):
        load_pattern(bad_feat)


def test_all_six_patterns_trigger_on_synthetic_fixtures() -> None:
    # Build deterministic 75-bar fixtures cleanly isolating each of the 6 patterns.
    # 1) bottom_volume_yang: decline from 20 -> 10, consolidate near 10, strong 2.5x vol yang on day 74
    r_bvy = [(19.5 - 0.16 * i, 19.7 - 0.16 * i, 19.3 - 0.16 * i, 19.5 - 0.16 * i, 12_000_000.0) for i in range(60)]
    r_bvy += [(10.0, 10.15, 9.90, 10.0, 10_000_000.0) for _ in range(14)]
    r_bvy.append((10.0, 10.82, 9.98, 10.78, 30_000_000.0))

    # 2) double_bottom_breakout: decline 16 -> 10, T1 @ idx=38, peak @ idx=52 (11.5), T2 @ idx=66 (10.05), break 11.5 on idx=74
    r_dbb = [(16.0 - 0.20 * i, 16.2 - 0.20 * i, 15.8 - 0.20 * i, 16.0 - 0.20 * i, 10_000_000.0) for i in range(30)]
    path_w = np.interp(
        np.arange(45),
        [0, 8, 22, 36, 43, 44],
        [10.8, 9.8, 11.6, 9.9, 11.45, 11.95],
    )
    for k, px in enumerate(path_w):
        if k == 44:
            r_dbb.append((11.40, 12.10, 11.35, 11.95, 25_000_000.0))
        else:
            r_dbb.append((float(px), float(px) + 0.15, float(px) - 0.15, float(px), 10_000_000.0))

    # 3) ma20_shrink_pullback: steady uptrend 10 -> 16.2, pull back smoothly onto MA20 (~15.7) with half volume
    r_pull = [(10.0 + 0.09 * i, 10.12 + 0.09 * i, 9.88 + 0.09 * i, 10.0 + 0.09 * i, 12_000_000.0) for i in range(70)]
    for drop in [16.15, 16.05, 15.95, 15.88, 15.82]:
        r_pull.append((drop + 0.04, drop + 0.12, drop - 0.18, drop, 6_000_000.0))

    # 4) single_yang_hold: thrusting yang on idx=70, hold above open for idx=71..73, firm close on idx=74
    r_syh = [(10.0, 10.10, 9.90, 10.0, 10_000_000.0) for _ in range(70)]
    r_syh.append((10.05, 10.85, 10.00, 10.80, 28_000_000.0))  # idx 70 observe
    r_syh.extend([(10.75, 10.85, 10.60, 10.70, 9_000_000.0) for _ in range(3)])  # idx 71..73 hold
    r_syh.append((10.68, 10.88, 10.65, 10.84, 12_000_000.0))  # idx 74 confirm (lag=4)

    # 5) box_breakout: tight range [9.9..10.15] for 74 bars, then break above 10.15 with vol
    r_box = [(10.0, 10.14, 9.90, 10.02, 10_000_000.0) for _ in range(74)]
    r_box.append((10.05, 10.72, 10.02, 10.65, 25_000_000.0))

    # 6) shooting_star_confirm: uptrend + long upper shadow @ idx=72, hold @ idx=73, close > obs high @ idx=74
    r_ss = [(10.0 + 0.05 * i, 10.10 + 0.05 * i, 9.90 + 0.05 * i, 10.0 + 0.05 * i, 10_000_000.0) for i in range(72)]
    r_ss.append((13.65, 14.35, 13.55, 13.75, 22_000_000.0))  # idx 72 observe (upper shadow = 0.60, range=0.80)
    r_ss.append((13.75, 13.95, 13.65, 13.85, 11_000_000.0))  # idx 73 hold
    r_ss.append((13.90, 14.60, 13.88, 14.55, 24_000_000.0))  # idx 74 confirm > 14.35 (lag=2)

    # 7) steady_trend_breakout: steady low-vol uptrend (MA20 > MA60), mild vol breakout above prev 20d high on idx=74
    r_stb = [(10.0 + 0.10 * i, 10.15 + 0.10 * i, 9.85 + 0.10 * i, 10.0 + 0.10 * i, 12_000_000.0) for i in range(55)]
    for k in range(19):
        px = 15.42 + 0.01 * k
        r_stb.append((px - 0.02, px + 0.15, px - 0.15, px, 11_000_000.0))
    r_stb.append((15.62, 15.98, 15.60, 15.94, 22_000_000.0))

    # 8) three_white_soldiers: decline -> base -> 3 steady bullish bars on idx=72..74
    r_tws = [(12.5 - 0.045 * i, 12.62 - 0.045 * i, 12.38 - 0.045 * i, 12.5 - 0.045 * i, 10_000_000.0) for i in range(56)]
    r_tws += [(10.0, 10.12, 9.88, 10.0, 10_000_000.0) for _ in range(16)]
    r_tws.append((10.02, 10.22, 10.00, 10.20, 14_000_000.0))
    r_tws.append((10.12, 10.36, 10.10, 10.34, 16_000_000.0))
    r_tws.append((10.24, 10.52, 10.22, 10.50, 18_000_000.0))

    # 9) three_white_soldiers_pullback: 3 soldiers on idx=70..72, hold on 73, confirm on 74
    r_twsp = [(12.5 - 0.046 * i, 12.62 - 0.046 * i, 12.38 - 0.046 * i, 12.5 - 0.046 * i, 10_000_000.0) for i in range(54)]
    r_twsp += [(10.0, 10.12, 9.88, 10.0, 10_000_000.0) for _ in range(16)]
    r_twsp.append((10.02, 10.22, 10.00, 10.20, 14_000_000.0))
    r_twsp.append((10.12, 10.36, 10.10, 10.34, 16_000_000.0))
    r_twsp.append((10.24, 10.52, 10.22, 10.50, 18_000_000.0))
    r_twsp.append((10.48, 10.50, 10.38, 10.42, 8_000_000.0))
    r_twsp.append((10.40, 10.60, 10.39, 10.58, 12_000_000.0))

    pack = _make_ohlcv_pack({
        "000001": _to_pack_bars(r_bvy),
        "000002": _to_pack_bars(r_dbb),
        "000003": _to_pack_bars(r_pull),
        "000004": _to_pack_bars(r_syh),
        "000005": _to_pack_bars(r_box),
        "000006": _to_pack_bars(r_ss),
        "000007": _to_pack_bars(r_stb),
        "000008": _to_pack_bars(r_tws),
        "000009": _to_pack_bars(r_twsp),
    })

    scan = scan_patterns(pack, include_experimental=True)
    assert [s.code for s in scan.signals_by_pattern["bottom_volume_yang"]] == ["000001"]
    assert "000002" in [s.code for s in scan.signals_by_pattern["double_bottom_breakout"]]
    assert [s.code for s in scan.signals_by_pattern["ma20_shrink_pullback"]] == ["000003"]
    syh_hits = scan.signals_by_pattern["single_yang_hold"]
    assert [s.code for s in syh_hits] == ["000004"]
    assert syh_hits[0].observe_lag_days == 4
    assert [s.code for s in scan.signals_by_pattern["box_breakout"]] == ["000005"]
    ss_hits = scan.signals_by_pattern["shooting_star_confirm"]
    assert [s.code for s in ss_hits] == ["000006"]
    assert ss_hits[0].observe_lag_days == 2
    assert "000007" in [s.code for s in scan.signals_by_pattern["steady_trend_breakout"]]
    assert "000008" in [s.code for s in scan.signals_by_pattern["three_white_soldiers"]]
    twsp_hits = scan.signals_by_pattern["three_white_soldiers_pullback"]
    assert [s.code for s in twsp_hits] == ["000009"]
    assert twsp_hits[0].observe_lag_days == 2


def test_observe_confirm_invalidation_and_zero_lookahead_with_future_split() -> None:
    # Construct single_yang_hold observe on day 70, confirm on day 74:
    # - 000001 holds cleanly -> fires on day 74
    # - 000002 breaches observe_open on day 72, recovers by day 74 -> must NOT fire
    hold_bars = [(10.0, 10.10, 9.90, 10.0, 10_000_000.0) for _ in range(70)]
    hold_bars.append((10.05, 10.85, 10.00, 10.80, 28_000_000.0))  # idx 70
    hold_bars.extend([(10.75, 10.85, 10.60, 10.70, 9_000_000.0) for _ in range(3)])
    hold_bars.append((10.68, 10.88, 10.65, 10.84, 12_000_000.0))  # idx 74 confirm

    breach_bars = list(hold_bars)
    breach_bars[72] = (10.70, 10.75, 9.50, 9.60, 12_000_000.0)  # close 9.60 < 10.05 - 0.2*atr

    # Append 5 future days AFTER idx 74 with a 50% ex-rights event on idx 75!
    p_hold = _to_pack_bars(hold_bars)
    p_breach = _to_pack_bars(breach_bars)
    for k in range(5):
        pc_val = p_hold[-1][3] if k > 0 else 5.42  # half pre_close triggers dynamic qfq scale 0.5x!
        p_hold.append((5.42, 5.50, 5.35, 5.45, pc_val, 10_000_000.0))
        pc_b = p_breach[-1][3] if k > 0 else 5.42
        p_breach.append((5.42, 5.50, 5.35, 5.45, pc_b, 10_000_000.0))

    full_pack = _make_ohlcv_pack({"000001": p_hold, "000002": p_breach})
    trunc_pack = DailyPack(
        dates=full_pack.dates[:75],
        codes=full_pack.codes,
        matrices={k: v[:75] for k, v in full_pack.matrices.items()},
        meta=full_pack.meta,
        sources=full_pack.sources,
    )

    scan_as_of = scan_patterns(full_pack, patterns=["single_yang_hold"], as_of_index=74)
    scan_trunc = scan_patterns(trunc_pack, patterns=["single_yang_hold"], as_of_index=-1)

    hits_as_of = scan_as_of.signals_by_pattern["single_yang_hold"]
    hits_trunc = scan_trunc.signals_by_pattern["single_yang_hold"]
    assert [h.code for h in hits_as_of] == ["000001"]
    assert hits_as_of == hits_trunc


def test_overhead_supply_10pct_feature_no_veto() -> None:
    # 75 bars with consistent pre_close (no spurious ex-rights gap):
    # bars 10..68 trade at 10.50 (vol 20M), bars 69..74 trade at 10.0 (vol 10M).
    raw = [(10.0, 10.12, 9.88, 10.0, 10_000_000.0) for _ in range(75)]
    for i in range(10, 69):
        raw[i] = (10.5, 10.6, 10.4, 10.5, 20_000_000.0)
    pack = _make_ohlcv_pack({"000001": _to_pack_bars(raw)})
    ctx = build_pattern_context(pack)
    ov = compute_overhead_supply_10pct_row(ctx, 74, np.asarray([0]))
    # From row 14..73 (60 bars): rows 14..68 (55 bars) @ 10.5 with vol 20M, rows 69..73 (5 bars) @ 10.0 with vol 10M
    expected = (55 * 20_000_000.0) / (55 * 20_000_000.0 + 5 * 10_000_000.0) * 100.0
    assert ov[0] == pytest.approx(expected, rel=1e-4)

    # Ensure high overhead supply does not veto a valid direct pattern
    raw_sig = [(10.0, 10.12, 9.88, 10.0, 10_000_000.0) for _ in range(75)]
    for i in range(15, 55):
        raw_sig[i] = (10.5, 10.55, 10.45, 10.5, 15_000_000.0)
    raw_sig[74] = (10.05, 10.75, 10.02, 10.70, 30_000_000.0)
    p2 = _make_ohlcv_pack({"000001": _to_pack_bars(raw_sig)})
    spec = PatternSpec(
        name="tmp_ov",
        display_name="TMP",
        family="breakout",
        status="experimental",
        version="1.0",
        description="",
        mode="direct",
        min_history_days=60,
        universe={"exclude_st": True, "proxy_amount_min": 50_000_000},
        conditions=[{"feature": "body_pct", "min": 4.0}],
    )
    ctx2 = build_pattern_context(p2)
    mask, _ = evaluate_pattern_matrix(ctx2, spec)
    assert bool(mask[74, 0]) is True


def test_replay_next_open_tradability_limit_down_roll_and_graduation(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    # Create 80 sessions: warm up 60, signal on day 62 for 3 stocks:
    # - 000001: normal T+1 open=10.0 -> T+5 close=11.0 (+10%) -> scored
    # - 000002: T+1 one-price limit-up (open=low=11.0, pc=10.0) -> untradable excluded!
    # - 000003: T+1 open=10.0, T+5 one-price limit-down (open=high=close=limit), T+6 sells at close=8.5
    dates = _dates(80)
    b1 = _flat_bars(80, price=10.0, vol=10_000_000.0)
    b2 = _flat_bars(80, price=10.0, vol=10_000_000.0)
    b3 = _flat_bars(80, price=10.0, vol=10_000_000.0)

    # Signal bar at idx=62: big body >= 4%
    b1[62] = (10.0, 10.6, 9.95, 10.5, 10.0, 20_000_000.0)
    b2[62] = (10.0, 10.6, 9.95, 10.5, 10.0, 20_000_000.0)
    b3[62] = (10.0, 10.6, 9.95, 10.5, 10.0, 20_000_000.0)

    # Entry bar T+1 = idx=63
    b1[63] = (10.0, 10.3, 9.9, 10.2, 10.5, 15_000_000.0)
    for k in range(64, 68):
        prev_px = b1[k - 1][3]
        b1[k] = (prev_px, prev_px + 0.25, prev_px - 0.1, prev_px + 0.2, prev_px, 12_000_000.0)
    b1[67] = (10.9, 11.1, 10.8, 11.0, b1[66][3], 12_000_000.0)  # T+5 exit @ 11.0 (+10% vs 10.0 open)

    # 000002 one-price limit up on T+1 (10.5 * 1.10 = 11.55)
    b2[63] = (11.55, 11.55, 11.55, 11.55, 10.5, 1_000_000.0)

    # 000003 T+1 open 10.0, T+5 (idx 67) one-price LD (9.0 = 10.0 * 0.90), T+6 (idx 68) sells at 8.5 (-15%)
    b3[63] = (10.0, 10.1, 9.8, 10.0, 10.5, 12_000_000.0)
    for k in range(64, 67):
        b3[k] = (10.0, 10.1, 9.9, 10.0, 10.0, 10_000_000.0)
    b3[67] = (9.0, 9.0, 9.0, 9.0, 10.0, 500_000.0)  # 1-price LD!
    b3[68] = (8.4, 8.6, 8.3, 8.5, 9.0, 18_000_000.0)  # deferred exit (-15%)

    pack = _make_ohlcv_pack({"000001": b1, "000002": b2, "000003": b3}, dates=dates)
    bench = pd.DataFrame({
        "date": dates,
        "open": [3000.0] * len(dates),
        "close": [3000.0] * len(dates),
    })

    pat_dir = tmp_path / "patterns"
    pat_dir.mkdir()
    (pat_dir / "body_test.yaml").write_text(
        "name: body_test\ndisplay_name: 测试\nfamily: breakout\nstatus: experimental\n"
        "mode: direct\nmarket_scope: [cn]\nmin_history_days: 60\n"
        "universe:\n  exclude_st: true\n  proxy_amount_min: 50000000\n"
        "conditions:\n  - feature: body_pct\n    min: 4.0\n",
        encoding="utf-8",
    )

    rep = replay_patterns(pack, benchmark_df=bench, warmup_days=60, patterns_dir=pat_dir)
    item = rep["patterns"][0]
    assert item["total_signals"] == 3
    assert item["untradable_count"] == 1
    assert item["untradable_share_pct"] == pytest.approx(33.33, abs=0.02)
    h5 = item["horizons"]["t5"]
    assert h5["scored"] == 2
    assert h5["exit_delayed_count"] == 1
    # (+10% + -15%) / 2 = -2.5%
    assert h5["raw_mean_pct"] == pytest.approx(-2.5, abs=0.05)
    assert h5["excess_mean_pct"] == pytest.approx(-2.5, abs=0.05)
    # 2 < 200 samples -> stays experimental
    assert item["graduation"]["passed"] is False
    assert item["graduation"]["recommended_status"] == "experimental"
    assert rep["universe_baseline"]["t5"]["sessions"] > 0
    assert rep["universe_baseline"]["t5"]["equal_weight_raw_mean_pct"] is not None
    assert "全A等权超额" in render_replay_markdown(rep)

    # CLI patterns list smoke test
    pack_dir = tmp_path / "pack"
    save_pack(pack_dir, pack)
    monkeypatch.setattr(sys, "argv", ["alphasift", "patterns", "list", "--include-experimental", "--json"])
    cli_main()
    listed = json.loads(capsys.readouterr().out)
    assert len(listed) == 9


def test_cli_patterns_scan_json(tmp_path: Path, monkeypatch, capsys) -> None:
    pack = _make_ohlcv_pack({"000001": _flat_bars(65)})
    pack_dir = tmp_path / "pack"
    save_pack(pack_dir, pack)

    monkeypatch.setattr(
        sys,
        "argv",
        ["alphasift", "patterns", "scan", "--pack-dir", str(pack_dir), "--include-experimental", "--json"],
    )
    cli_main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["trade_date"] == pack.trade_date
    assert len(payload["patterns_evaluated"]) == 9
    assert payload["usage_policy"] == "cn_only_regime_slice_only"


def test_split_half_stability_and_sign_flip_rejection() -> None:
    mid = "2026-06-15"
    h1_dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-03-01", periods=16)]
    h2_dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-07-01", periods=16)]
    stable_obs = [
        {"date": h1_dates[i % 16], "horizons": {"t5": {"status": "ok", "excess_return_pct": 1.2 + (i % 3) * 0.4}}}
        for i in range(55)
    ] + [
        {"date": h2_dates[i % 16], "horizons": {"t5": {"status": "ok", "excess_return_pct": 1.1 + (i % 3) * 0.4}}}
        for i in range(55)
    ]
    st_ok = _summarize_stability(stable_obs, mid_date=mid, horizon=5)
    assert st_ok["n"] == 110
    assert st_ok["signal_days"] == 32
    assert st_ok["h1_n"] == 55 and st_ok["h2_n"] == 55
    assert st_ok["h1_days"] == 16 and st_ok["h2_days"] == 16
    assert st_ok["sign_consistent"] is True
    assert st_ok["stable_direction"] == "positive"
    assert st_ok["t_stat"] is not None and st_ok["t_stat"] > 1.96
    assert st_ok["stability_ready"] is True

    # Same 110 signals crammed onto only 2 dates must NOT qualify under date-clustered stability.
    clustered_2d = [
        {"date": "2026-04-01" if i < 55 else "2026-08-01", "horizons": {"t5": {"status": "ok", "excess_return_pct": 1.5 + (i % 3) * 0.2}}}
        for i in range(110)
    ]
    st_clust = _summarize_stability(clustered_2d, mid_date=mid, horizon=5)
    assert st_clust["pooled_t_stat"] > 1.96
    assert st_clust["signal_days"] == 2
    assert st_clust["stability_ready"] is False

    flipped_obs = [
        {"date": h1_dates[i % 16], "horizons": {"t5": {"status": "ok", "excess_return_pct": 2.0}}}
        for i in range(60)
    ] + [
        {"date": h2_dates[i % 16], "horizons": {"t5": {"status": "ok", "excess_return_pct": -1.0}}}
        for i in range(60)
    ]
    st_flip = _summarize_stability(flipped_obs, mid_date=mid, horizon=5)
    assert st_flip["mean_pct"] == 0.5
    assert st_flip["sign_consistent"] is False
    assert st_flip["stable_direction"] == "mixed_or_insufficient"
    assert st_flip["stability_ready"] is False


def test_graduation_requires_benchmark_matched_samples_and_benchmark_fallback(monkeypatch) -> None:
    # 250 ok trades where only 40 matched benchmark -> must NOT graduate!
    obs = [
        {
            "date": f"2026-05-{(i % 20) + 1:02d}",
            "horizons": {"t5": {
                "status": "ok",
                "raw_return_pct": 3.0,
                "excess_return_pct": 2.0 if i < 40 else None,
                "exit_delayed": False,
            }},
        }
        for i in range(250)
    ]
    t5 = _summarize_horizon_obs(obs, 5)
    assert t5["scored"] == 250
    assert t5["excess_scored"] == 40
    assert t5["unmatched_benchmark"] == 210

    dummy_spec = PatternSpec(
        name="tmp_grad", display_name="G", family="breakout", status="experimental",
        version="1.0", description="", mode="direct", min_history_days=60, universe={}, conditions=[],
    )
    grad = _evaluate_graduation(dummy_spec, t5)
    assert grad["passed"] is False
    assert grad["recommended_status"] == "experimental"
    assert grad["t5_excess_scored"] == 40

    # load_cn_benchmark falls back cleanly from Tencent failure to Sina
    monkeypatch.setattr("alphasift.pattern_replay._time.sleep", lambda s: None)
    monkeypatch.setattr(
        "alphasift.pattern_replay._fetch_daily_tencent",
        lambda sym, lookback_days=360: (_ for _ in ()).throw(TimeoutError("tencent down")),
    )
    monkeypatch.setattr(
        "alphasift.pattern_replay._fetch_daily_sina",
        lambda sym, lookback_days=360: pd.DataFrame([{"date": "2026-11-20", "open": 4000.0, "close": 4020.0}]),
    )
    bench = load_cn_benchmark(lookback_days=30)
    assert len(bench) == 1 and bench.loc[0, "close"] == 4020.0


def test_three_white_soldiers_suspension_gap_cooldown_and_lookahead() -> None:
    # Clean 3 soldiers firing on idx=74 and a 4th soldier on idx=75 (must be suppressed by cooldown_days=3)
    base = [(12.5 - 0.045 * i, 12.62 - 0.045 * i, 12.38 - 0.045 * i, 12.5 - 0.045 * i, 10_000_000.0) for i in range(56)]
    base += [(10.0, 10.12, 9.88, 10.0, 10_000_000.0) for _ in range(16)]
    soldiers = [
        (10.02, 10.22, 10.00, 10.20, 14_000_000.0),  # idx 72
        (10.12, 10.36, 10.10, 10.34, 16_000_000.0),  # idx 73
        (10.24, 10.52, 10.22, 10.50, 18_000_000.0),  # idx 74 -> fires
        (10.38, 10.70, 10.36, 10.68, 20_000_000.0),  # idx 75 -> 4th soldier suppressed by cooldown
    ]
    clean_bars = _to_pack_bars(base + soldiers)

    # Stock 000002 has a 1-day zero-volume suspension at idx=71 right before soldier #1 (or between #1 and #2 at idx=73)
    susp_bars = list(clean_bars)
    susp_bars[72] = (10.20, 10.20, 10.20, 10.20, susp_bars[71][3], 0.0)  # suspended gap

    # Appending ex-rights future splits must not perturb earlier as_of_index evaluation
    clean_with_split = list(clean_bars[:4] + clean_bars[4:])
    clean_with_split.append((5.34, 5.45, 5.28, 5.40, 5.34, 12_000_000.0))  # idx 76 50% split
    susp_with_split = list(susp_bars)
    susp_with_split.append((5.34, 5.45, 5.28, 5.40, 5.34, 12_000_000.0))

    pack = _make_ohlcv_pack({"000001": clean_with_split, "000002": susp_with_split})
    spec = load_pattern("three_white_soldiers")
    ctx = build_pattern_context(pack, end_index=75)
    mask, _ = evaluate_pattern_matrix(ctx, spec)
    assert bool(mask[74, 0]) is True
    assert bool(mask[75, 0]) is False  # cooldown suppresses day-4 consecutive fire
    assert bool(mask[74, 1]) is False and bool(mask[75, 1]) is False  # suspension breaks valid_streak

    trunc = DailyPack(
        dates=pack.dates[:75],
        codes=pack.codes,
        matrices={k: v[:75] for k, v in pack.matrices.items()},
        meta=pack.meta,
        sources=pack.sources,
    )
    scan_as_of = scan_patterns(pack, patterns=["three_white_soldiers"], as_of_index=74)
    scan_trunc = scan_patterns(trunc, patterns=["three_white_soldiers"], as_of_index=-1)
    assert [s.code for s in scan_as_of.signals_by_pattern["three_white_soldiers"]] == ["000001"]
    assert scan_as_of.signals_by_pattern["three_white_soldiers"] == scan_trunc.signals_by_pattern["three_white_soldiers"]


def test_strict_graduation_checks_net_cost_baseline_and_stability() -> None:
    dummy_spec = PatternSpec(
        name="tmp_strict", display_name="严格", family="trend_continuation", status="experimental",
        version="1.0", description="", mode="direct", min_history_days=60, universe={}, conditions=[],
    )
    ok_stab = {"sign_consistent": True, "stable_direction": "positive", "t_stat": 2.4}
    beatable_base = {"equal_weight_excess_mean_pct": 0.10}

    # 1) Gross +0.15% fails 25bp net cost (-0.10%)
    obs_thin = [{"date": f"2026-05-{(i % 20) + 1:02d}", "horizons": {"t5": {"status": "ok", "raw_return_pct": 0.15, "excess_return_pct": 0.15, "exit_delayed": False}}} for i in range(250)]
    t5_thin = _summarize_horizon_obs(obs_thin, 5, net_cost_bps=25.0, applied_cost_bps=0.0)
    assert t5_thin["gross_excess_mean_pct"] == pytest.approx(0.15)
    assert t5_thin["net_excess_mean_pct"] == pytest.approx(-0.10)
    g1 = _evaluate_graduation(dummy_spec, t5_thin, stability=ok_stab, universe_baseline_t5=beatable_base)
    assert g1["passed"] is False and g1["checks"]["net_excess_ok"] is False

    # 2) Strong net +0.30% fails when equal-weight universe baseline is +0.40%
    obs_strong = [{"date": f"2026-05-{(i % 20) + 1:02d}", "horizons": {"t5": {"status": "ok", "raw_return_pct": 0.55, "excess_return_pct": 0.55, "exit_delayed": False}}} for i in range(250)]
    t5_strong = _summarize_horizon_obs(obs_strong, 5, net_cost_bps=25.0, applied_cost_bps=0.0)
    assert t5_strong["net_excess_mean_pct"] == pytest.approx(0.30)
    g2 = _evaluate_graduation(dummy_spec, t5_strong, stability=ok_stab, universe_baseline_t5={"equal_weight_excess_mean_pct": 0.40})
    assert g2["passed"] is False and g2["checks"]["beats_universe_ok"] is False

    # 3) Fails split-half / clustered t-stat check even when net excess > universe
    bad_stab = {"sign_consistent": False, "stable_direction": "mixed_or_insufficient", "t_stat": 0.4}
    g3 = _evaluate_graduation(dummy_spec, t5_strong, stability=bad_stab, universe_baseline_t5=beatable_base)
    assert g3["passed"] is False and g3["checks"]["stability_ok"] is False

    # 4) Passes only when samples, net excess, universe beat, AND split-half t-stat all satisfy gate
    g4 = _evaluate_graduation(dummy_spec, t5_strong, stability=ok_stab, universe_baseline_t5=beatable_base)
    assert g4["passed"] is True and g4["recommended_status"] == "active"
    assert all(g4["checks"][k] for k in ("samples_ok", "net_excess_ok", "beats_universe_ok", "stability_ok"))

    # 5) Fail-closed when stability or equal-weight baseline are missing
    g_no_stab = _evaluate_graduation(dummy_spec, t5_strong, stability=None, universe_baseline_t5=beatable_base)
    assert g_no_stab["passed"] is False and g_no_stab["checks"]["stability_ok"] is False
    g_no_ew = _evaluate_graduation(dummy_spec, t5_strong, stability=ok_stab, universe_baseline_t5=None)
    assert g_no_ew["passed"] is False and g_no_ew["checks"]["beats_universe_ok"] is False

    # 6) Matched-day EW check overrides aggregate baseline and rejects small-cap timing bias
    ew_fail_stab = {
        "sign_consistent": True,
        "stable_direction": "positive",
        "t_stat": 2.6,
        "h1_days": 16,
        "h2_days": 16,
        "h1_n": 120,
        "h2_n": 130,
        "daily_mean_pct": 0.65,
        "ew_daily_mean_pct": -0.05,
        "ew_sign_consistent": False,
        "ew_stable_direction": "mixed_or_insufficient",
        "ew_t_stat": -0.2,
    }
    g_ew_fail = _evaluate_graduation(dummy_spec, t5_strong, stability=ew_fail_stab, universe_baseline_t5=beatable_base)
    assert g_ew_fail["passed"] is False
    assert g_ew_fail["checks"]["beats_universe_ok"] is False
    assert g_ew_fail["checks"]["matched_date_ew_used"] is True

    # 7) Half-sample day threshold enforces >= 15 days per half
    short_half_stab = {
        "sign_consistent": True,
        "stable_direction": "positive",
        "t_stat": 2.6,
        "h1_days": 12,
        "h2_days": 16,
        "h1_n": 100,
        "h2_n": 150,
    }
    g_short = _evaluate_graduation(dummy_spec, t5_strong, stability=short_half_stab, universe_baseline_t5=beatable_base)
    assert g_short["passed"] is False and g_short["checks"]["stability_ok"] is False

    # 8) BH-FDR gate rejects discovery when q > 0.05
    g_fdr = _evaluate_graduation(
        dummy_spec,
        t5_strong,
        stability=ok_stab,
        universe_baseline_t5=beatable_base,
        multiple_testing={"bh_q_value_csi300": 0.12, "bh_q_value_ew": 0.02, "bh_fdr_pass": False},
    )
    assert g_fdr["passed"] is False and g_fdr["checks"]["bh_fdr_ok"] is False


def test_newey_west_deflates_autocorrelation_and_bh_fdr() -> None:
    # Positively autocorrelated overlapping 5d series yields smaller HAC |t| than IID naive t
    series = [0.6 + 0.5 * np.sin(i / 4.0) for i in range(40)]
    cal = list(range(40))
    naive_t = float(np.mean(series) / (np.std(series, ddof=1) / np.sqrt(len(series))))
    nw_t = _newey_west_t_stat(series, cal, max_lag=4)
    assert nw_t is not None and 0.0 < nw_t < naive_t

    q_vals = _benjamini_hochberg_q_values([0.004, 0.04, 0.25])
    assert q_vals == [pytest.approx(0.012), pytest.approx(0.06), pytest.approx(0.25)]
