# -*- coding: utf-8 -*-
"""Tests for P2-2 track-record dual tracks (rules vs AI) and CN pattern board."""

from __future__ import annotations

import dataclasses
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from alphasift.models import Pick, ScreenResult
from alphasift.pack import DailyPack, FIELDS, save_pack

_SPEC = importlib.util.spec_from_file_location(
    "track_record_p2",
    Path(__file__).resolve().parents[1] / "scripts" / "track_record.py",
)
assert _SPEC is not None and _SPEC.loader is not None
track_record = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = track_record
_SPEC.loader.exec_module(track_record)


def _save_small_pack(pack_dir: Path, trade_date: str) -> None:
    n_days = 65
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end=trade_date, periods=n_days)]
    codes = ["000001", "600519"]
    matrices = {field: np.full((n_days, 2), np.nan, dtype=np.float32) for field in FIELDS}
    for j in range(2):
        for t in range(n_days):
            px = 10.0 + 0.05 * t
            matrices["open"][t, j] = px
            matrices["high"][t, j] = px + 0.1
            matrices["low"][t, j] = px - 0.1
            matrices["close"][t, j] = px + 0.04
            matrices["pre_close"][t, j] = px
            matrices["volume"][t, j] = 10_000_000.0
            matrices["amount"][t, j] = 100_000_000.0
    meta = pd.DataFrame([
        {
            "code": c,
            "name": f"样本{c}",
            "industry": "半导体",
            "pe_ratio": 20.0,
            "pb_ratio": 2.0,
            "total_mv": 1e10,
            "circ_mv": 8e9,
            "list_date": "2018-01-01",
            "is_st": False,
        }
        for c in codes
    ])
    save_pack(
        pack_dir,
        DailyPack(
            dates=np.asarray(dates, dtype=str),
            codes=np.asarray(codes, dtype=str),
            matrices=matrices,
            meta=meta,
            sources=("test",),
        ),
    )


def test_fork_without_llm_key_runs_rules_only(tmp_path: Path, monkeypatch) -> None:
    import alphasift.config as config_mod
    import alphasift.pipeline as pipeline_mod

    monkeypatch.setattr(track_record, "_now", lambda: "2026-11-19T10:30:00+00:00")
    monkeypatch.setattr(track_record, "strategies_for", lambda m: ["dual_low"] if m == "cn" else [])
    orig_from_env = config_mod.Config.from_env
    monkeypatch.setattr(
        config_mod.Config,
        "from_env",
        staticmethod(lambda: dataclasses.replace(orig_from_env(), llm_api_key="", llm_channels=[])),
    )

    snap = pd.DataFrame([{"code": "000001", "name": "平安", "price": 10.0}])
    snap.attrs.update(market="cn", quote_date="2026-11-19", snapshot_source="sina")
    monkeypatch.setattr(track_record, "_fetch_market_snapshot", lambda m, s, c: snap)

    calls: list[bool] = []

    def fake_screen(strategy, *, market, use_llm, **kwargs):
        calls.append(bool(use_llm))
        assert not use_llm
        return ScreenResult(
            strategy=strategy,
            market=market,
            run_id="r_rules_only",
            track="rules",
            llm_ranked=False,
            created_at="2026-11-19T10:30:00+00:00",
            picks=[Pick(rank=1, code="000001", name="平安", final_score=80.0, screen_score=80.0, price=10.0)],
        )

    monkeypatch.setattr(pipeline_mod, "screen", fake_screen)
    rc = track_record.main(["screen", "--track", str(tmp_path), "--session", "asia", "--markets", "cn"])
    assert rc == 0
    assert calls == [False]
    saved = list((tmp_path / "data" / "runs").glob("*.json"))
    assert len(saved) == 1
    assert json.loads(saved[0].read_text(encoding="utf-8"))["track"] == "rules"


def test_ai_track_isolation_timeout_resilience_and_pattern_board(tmp_path: Path, monkeypatch) -> None:
    import alphasift.config as config_mod
    import alphasift.pipeline as pipeline_mod

    monkeypatch.setattr(track_record, "_now", lambda: "2026-11-19T10:30:00+00:00")
    monkeypatch.setattr(
        track_record,
        "strategies_for",
        lambda m: ["dual_low", "balanced_alpha"] if m == "cn" else [],
    )
    orig_from_env = config_mod.Config.from_env
    monkeypatch.setattr(
        config_mod.Config,
        "from_env",
        staticmethod(lambda: dataclasses.replace(orig_from_env(), llm_api_key="test-key")),
    )

    pack_dir = tmp_path / "cn_pack"
    _save_small_pack(pack_dir, "2026-11-19")

    snap = pd.DataFrame([{"code": "000001", "name": "平安", "price": 10.0}])
    snap.attrs.update(market="cn", quote_date="2026-11-19", snapshot_source="sina")
    monkeypatch.setattr(track_record, "_fetch_market_snapshot", lambda m, s, c: snap)

    # AI fails on balanced_alpha (llm_ranked=False / timeout), succeeds on dual_low.
    def fake_screen(strategy, *, market, use_llm, **kwargs):
        if use_llm and strategy == "balanced_alpha":
            raise TimeoutError("llm timeout")
        if use_llm:
            return ScreenResult(
                strategy=strategy,
                market=market,
                run_id=f"{strategy}_same_base_id",
                llm_ranked=True,
                created_at="2026-11-19T10:30:00+00:00",
                picks=[Pick(rank=1, code="600519", name="茅台", final_score=91.0, screen_score=85.0, price=1500.0)],
            )
        return ScreenResult(
            strategy=strategy,
            market=market,
            run_id=f"{strategy}_same_base_id",
            llm_ranked=False,
            created_at="2026-11-19T10:30:00+00:00",
            picks=[Pick(rank=1, code="000001", name="平安", final_score=85.0, screen_score=85.0, price=10.0)],
        )

    monkeypatch.setattr(pipeline_mod, "screen", fake_screen)

    rc = track_record.main([
        "screen", "--track", str(tmp_path), "--session", "asia", "--markets", "cn", "--pack-dir", str(pack_dir),
    ])
    assert rc == 0

    runs = track_record.load_runs(tmp_path)
    tracks_by_strat = {(r["strategy"], r["track"]): r["run_id"] for r in runs}
    assert tracks_by_strat == {
        ("dual_low", "rules"): "dual_low_same_base_id",
        ("dual_low", "ai"): "dual_low_same_base_id-ai",
        ("balanced_alpha", "rules"): "balanced_alpha_same_base_id",
    }
    assert (tmp_path / "data" / "patterns" / "2026-11-19.json").is_file()

    # Evaluate and build site -> check scorecard, track_comparison, and site/patterns.json
    site_dir = tmp_path / "site"
    site_dir.mkdir(exist_ok=True)
    eval_data = {
        "runs": {
            "dual_low_same_base_id": {"final": True, "windows": {"5": {"picks": {
                "000001": {"status": "ok", "return_pct": 2.0, "excess_return_pct": 1.0},
            }}}},
            "dual_low_same_base_id-ai": {"final": True, "windows": {"5": {"picks": {
                "600519": {"status": "ok", "return_pct": 5.0, "excess_return_pct": 4.0},
            }}}},
        }
    }
    (site_dir / "evaluation.json").write_text(json.dumps(eval_data), encoding="utf-8")
    summary = track_record.build_site(tmp_path)

    assert len(summary["track_comparison"]) == 1
    cmp_row = summary["track_comparison"][0]
    assert cmp_row["strategy"] == "dual_low"
    assert cmp_row["windows"]["5"]["ai_minus_rules_pct"] == 3.0
    assert (site_dir / "patterns.json").is_file()
    assert summary["pattern_board"]["latest"]["trade_date"] == "2026-11-19"
