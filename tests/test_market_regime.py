# -*- coding: utf-8 -*-
"""Tests for CN market regime, limit-up ladder, and objective stage classification."""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd
import pytest

from alphasift.cli import main as cli_main
from alphasift.market_regime import (
    classify_regime_stage,
    cn_price_limit_pct,
    compute_limit_masks,
    compute_market_regime,
    compute_market_regime_series,
    round_cn_tick,
    summarize_regime_distribution,
)
from alphasift.pack import DailyPack, FIELDS, save_pack


def _make_pack(
    dates: list[str],
    codes: list[str],
    *,
    meta_rows: list[dict] | None = None,
) -> DailyPack:
    t_len, n_codes = len(dates), len(codes)
    matrices = {field: np.full((t_len, n_codes), np.nan, dtype=np.float32) for field in FIELDS}
    if meta_rows is None:
        meta_rows = [
            {
                "code": c,
                "name": f"股票{c}",
                "industry": "电子",
                "pe_ratio": 20.0,
                "pb_ratio": 2.0,
                "total_mv": 1e10,
                "circ_mv": 8e9,
                "list_date": "2015-01-01",
                "is_st": False,
            }
            for c in codes
        ]
    meta = pd.DataFrame(meta_rows)
    return DailyPack(
        dates=np.asarray(dates, dtype=str),
        codes=np.asarray(codes, dtype=str),
        matrices=matrices,
        meta=meta,
        sources=("test",),
    )


def _set_bar(
    pack: DailyPack,
    t: int,
    j: int,
    *,
    o: float,
    h: float,
    lo: float,
    c: float,
    pc: float,
    v: float = 1_000_000.0,
    a: float = 20_000_000.0,
) -> None:
    pack.matrices["open"][t, j] = o
    pack.matrices["high"][t, j] = h
    pack.matrices["low"][t, j] = lo
    pack.matrices["close"][t, j] = c
    pack.matrices["pre_close"][t, j] = pc
    pack.matrices["volume"][t, j] = v
    pack.matrices["amount"][t, j] = a


def test_cn_price_limit_rules_and_half_up_rounding() -> None:
    assert cn_price_limit_pct("600519") == 0.10
    assert cn_price_limit_pct("000001") == 0.10
    assert cn_price_limit_pct("300750") == 0.20
    assert cn_price_limit_pct("301001", is_st=True) == 0.20
    assert cn_price_limit_pct("688981", is_st=True) == 0.20
    assert cn_price_limit_pct("689009") == 0.20
    assert cn_price_limit_pct("920002", is_st=True) == 0.30
    assert cn_price_limit_pct("830799") == 0.30
    assert cn_price_limit_pct("000002", is_st=True) == 0.05
    assert cn_price_limit_pct("600001", name="*ST示范") == 0.05

    # 10.05 * 1.10 = 11.055 -> half-up rounds to 11.06, NOT 11.05.
    assert float(round_cn_tick(10.05 * 1.10)) == 11.06
    assert float(round_cn_tick(10.05 * 0.90)) == 9.05


def test_limit_masks_streaks_ladder_broken_boards_and_exclusions() -> None:
    dates = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"]
    codes = [
        "000001",  # 0: normal non-ST -> broken board then recovery
        "000002",  # 1: main ST 5% limit-up (excluded from non-ST counts)
        "000003",  # 2: 3-board streak non-ST
        "300001",  # 3: ChiNext 20% one-price limit-up on day 2
        "600001",  # 4: IPO listed inside window with +50% jump (must be excluded)
        "600002",  # 5: one-price limit-down on day 2
        "920001",  # 6: BSE 30% limit-up on day 2
    ]
    meta_rows = []
    for c in codes:
        meta_rows.append({
            "code": c,
            "name": "*ST样本" if c == "000002" else f"N{c}",
            "industry": "机械",
            "pe_ratio": 15.0,
            "pb_ratio": 1.5,
            "total_mv": 5e9,
            "circ_mv": 4e9,
            "list_date": "2026-11-02" if c == "600001" else "2018-01-01",
            "is_st": c == "000002",
        })
    pack = _make_pack(dates, codes, meta_rows=meta_rows)

    # Day 0: seed bars
    _set_bar(pack, 0, 0, o=10.0, h=10.1, lo=9.9, c=10.0, pc=10.0)
    _set_bar(pack, 0, 1, o=10.0, h=10.1, lo=9.9, c=10.0, pc=10.0)
    _set_bar(pack, 0, 2, o=10.0, h=11.0, lo=10.0, c=11.0, pc=10.0)  # 1-board
    _set_bar(pack, 0, 3, o=10.0, h=10.2, lo=9.9, c=10.0, pc=10.0)
    _set_bar(pack, 0, 4, o=10.0, h=15.0, lo=10.0, c=15.0, pc=10.0)  # IPO +50%
    _set_bar(pack, 0, 5, o=10.0, h=10.1, lo=9.9, c=10.0, pc=10.0)
    _set_bar(pack, 0, 6, o=10.0, h=10.2, lo=9.9, c=10.0, pc=10.0)

    # Day 1
    _set_bar(pack, 1, 0, o=10.0, h=11.0, lo=10.0, c=11.0, pc=10.0)  # 1-board
    _set_bar(pack, 1, 1, o=10.0, h=10.5, lo=10.0, c=10.5, pc=10.0)  # ST 5% LU
    _set_bar(pack, 1, 2, o=11.2, h=12.1, lo=11.2, c=12.1, pc=11.0)  # 2-board
    _set_bar(pack, 1, 3, o=10.0, h=10.3, lo=9.9, c=10.0, pc=10.0)
    _set_bar(pack, 1, 4, o=15.0, h=16.5, lo=15.0, c=16.5, pc=15.0)  # IPO day 2 (+10% within 5d window)
    _set_bar(pack, 1, 5, o=10.0, h=10.1, lo=9.8, c=10.0, pc=10.0)
    _set_bar(pack, 1, 6, o=10.0, h=10.2, lo=9.8, c=10.0, pc=10.0)

    # Day 2 (test target)
    _set_bar(pack, 2, 0, o=11.3, h=12.1, lo=11.0, c=11.5, pc=11.0)  # broken board! (prev LU -> +4.55%)
    _set_bar(pack, 2, 1, o=10.5, h=10.6, lo=10.4, c=10.6, pc=10.5)  # ST normal
    _set_bar(pack, 2, 2, o=12.5, h=13.31, lo=12.4, c=13.31, pc=12.1)  # 3-board LU (+10%)
    _set_bar(pack, 2, 3, o=12.0, h=12.0, lo=12.0, c=12.0, pc=10.0)  # 20% one-price LU
    _set_bar(pack, 2, 4, o=16.5, h=16.8, lo=16.2, c=16.5, pc=16.5)  # IPO day 3
    _set_bar(pack, 2, 5, o=9.0, h=9.0, lo=9.0, c=9.0, pc=10.0)     # 10% one-price LD
    _set_bar(pack, 2, 6, o=11.0, h=13.0, lo=10.8, c=13.0, pc=10.0)  # BSE 30% LU

    # Day 3: suspended day (volume=0 on col 2)
    _set_bar(pack, 3, 2, o=13.31, h=13.31, lo=13.31, c=13.31, pc=13.31, v=0.0, a=0.0)

    masks = compute_limit_masks(pack, end_index=2)
    assert bool(masks["is_broken_board"][2, 0]) is True
    assert bool(masks["is_limit_up"][1, 1]) is True  # ST 5% detected
    assert int(masks["consecutive_limit_up"][2, 2]) == 3
    assert bool(masks["is_one_price_limit_up"][2, 3]) is True
    assert bool(masks["has_price_limit"][0, 4]) is False  # IPO outlier excluded
    assert bool(masks["has_price_limit"][1, 4]) is False  # IPO first-5-day excluded
    assert bool(masks["is_one_price_limit_down"][2, 5]) is True
    assert bool(masks["is_limit_up"][2, 6]) is True

    snap = compute_market_regime(pack, trade_date="2026-11-04")
    assert snap.non_st_limit_up_count == 3  # 000003 (3-board), 300001 (20%), 920001 (30%)
    assert snap.limit_up_count == 3
    assert snap.one_price_limit_up_count == 1
    assert snap.non_st_broken_board_count == 1  # 000001
    assert snap.seal_rate_pct == 75.0  # 3 / (3 + 1) * 100
    assert snap.non_st_limit_down_count == 1  # 600002
    assert snap.one_price_limit_down_count == 1
    assert snap.max_consecutive_limit_up == 3
    assert snap.consecutive_board_ladder == {3: 1}
    # Yesterday's non-ST limit-ups: 000001 (promoted? No -> +4.55%) & 000003 (3-board +10%).
    assert snap.prev_limit_up_count == 2
    assert snap.prev_limit_up_promoted_count == 1
    assert snap.prev_limit_up_promotion_rate_pct == 50.0
    assert snap.prev_limit_up_win_rate_pct == 100.0
    assert snap.prev_limit_up_avg_return_pct == pytest.approx(7.27, abs=0.02)
    assert snap.usage_policy == "reporting_and_slice_only"
    assert snap.median_return_pct is not None
    assert sum(snap.return_distribution.values()) == snap.traded_count
    assert set(snap.return_distribution) == {"le_neg7", "neg7_neg3", "neg3_0", "flat", "pos0_3", "pos3_7", "ge_pos7"}

    # Suspended bar on day 3 is excluded from active mask and streaks
    masks_all = compute_limit_masks(pack)
    assert bool(masks_all["active"][3, 2]) is False
    assert int(masks_all["consecutive_limit_up"][3, 2]) == 0


def test_classify_regime_stage_all_six_buckets() -> None:
    s1, l1, _ = classify_regime_stage(
        advance_ratio_pct=18.0,
        non_st_limit_up_count=18,
        non_st_limit_down_count=40,
        non_st_broken_board_count=20,
        seal_rate_pct=47.0,
        max_consecutive_limit_up=3,
        prev_limit_up_avg_return_pct=-2.5,
    )
    assert (s1, l1) == ("freezing", "冰点")

    s2, l2, _ = classify_regime_stage(
        advance_ratio_pct=34.0,
        non_st_limit_up_count=35,
        non_st_limit_down_count=22,
        non_st_broken_board_count=20,
        seal_rate_pct=63.0,
        max_consecutive_limit_up=4,
        prev_limit_up_avg_return_pct=-1.2,
    )
    assert (s2, l2) == ("ebb", "退潮")

    s3, l3, _ = classify_regime_stage(
        advance_ratio_pct=75.0,
        non_st_limit_up_count=90,
        non_st_limit_down_count=1,
        non_st_broken_board_count=20,
        seal_rate_pct=81.8,
        max_consecutive_limit_up=6,
        prev_limit_up_avg_return_pct=2.8,
    )
    assert (s3, l3) == ("main_up", "主升")

    s4, l4, _ = classify_regime_stage(
        advance_ratio_pct=64.0,
        non_st_limit_up_count=52,
        non_st_limit_down_count=2,
        non_st_broken_board_count=15,
        seal_rate_pct=77.6,
        max_consecutive_limit_up=4,
        prev_limit_up_avg_return_pct=0.8,
    )
    assert (s4, l4) == ("startup", "启动")

    s5, l5, _ = classify_regime_stage(
        advance_ratio_pct=42.0,
        non_st_limit_up_count=55,
        non_st_limit_down_count=5,
        non_st_broken_board_count=35,
        seal_rate_pct=61.1,
        max_consecutive_limit_up=7,
        prev_limit_up_avg_return_pct=0.4,
    )
    assert (s5, l5) == ("divergence", "分歧")

    s6, l6, _ = classify_regime_stage(
        advance_ratio_pct=48.0,
        non_st_limit_up_count=38,
        non_st_limit_down_count=4,
        non_st_broken_board_count=12,
        seal_rate_pct=76.0,
        max_consecutive_limit_up=3,
        prev_limit_up_avg_return_pct=0.3,
    )
    assert (s6, l6) == ("neutral", "震荡")


def test_series_distribution_and_cli_market_stats(tmp_path, monkeypatch, capsys) -> None:
    dates = ["2026-11-18", "2026-11-19", "2026-11-20"]
    codes = ["000001", "000002", "600000"]
    pack = _make_pack(dates, codes)
    for t in range(3):
        for j in range(3):
            base = 10.0 + 0.2 * t
            _set_bar(pack, t, j, o=base, h=base + 0.2, lo=base - 0.1, c=base + 0.1, pc=base)

    series = compute_market_regime_series(pack)
    assert len(series) == 3
    dist = summarize_regime_distribution(series)
    assert sum(item["days"] for item in dist.values()) == 3

    pack_dir = tmp_path / "cn_pack"
    save_pack(pack_dir, pack)

    monkeypatch.setattr(
        sys,
        "argv",
        ["alphasift", "market-stats", "--pack-dir", str(pack_dir), "--days", "2", "--json"],
    )
    cli_main()
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 2
    assert payload[-1]["trade_date"] == "2026-11-20"
    assert payload[-1]["usage_policy"] == "reporting_and_slice_only"
