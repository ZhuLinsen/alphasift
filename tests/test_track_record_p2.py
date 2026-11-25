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
    assert cmp_row["common_days"] == 1
    assert cmp_row["windows"]["5"]["paired_days"] == 1
    assert cmp_row["windows"]["5"]["sample_sufficient"] is False
    assert cmp_row["windows"]["5"]["ai_minus_rules_pct"] is None
    assert "配对" in (cmp_row["windows"]["5"]["delta_hidden_reason"] or "")
    assert "2026-11-19" not in str(summary["trend"].get("cn", {}).get("5", {}).get("dual_low", [])) or all(
        row["track"] != "ai" for row in summary["scorecard"] if row["strategy"] == "dual_low" and "dual_low_same_base_id-ai" in str(summary["trend"])
    )
    assert "dual_low" in summary["trend"].get("cn", {}).get("5", {})
    assert "dual_low" in summary["trend_ai"].get("cn", {}).get("5", {})
    assert summary["trend"]["cn"]["5"]["dual_low"] == [["2026-11-19", 1.0, 1]]
    assert summary["trend_ai"]["cn"]["5"]["dual_low"] == [["2026-11-19", 4.0, 1]]
    assert (site_dir / "patterns.json").is_file()
    assert summary["pattern_board"]["latest"]["trade_date"] == "2026-11-19"


def test_evaluate_markets_switchover_cn_pack_raw_limit_and_paired_ai_comparison(
    tmp_path: Path, monkeypatch
) -> None:
    import pytest

    import alphasift.evaluate as eval_mod
    from alphasift.store import save_screen_result

    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-10-01", periods=30)]
    codes = ["000001", "000002"]
    mats = {field: np.full((30, 2), np.nan, dtype=np.float32) for field in FIELDS}
    for t in range(30):
        # 000001 normal daily climb
        px1 = 10.0 + 0.1 * t
        mats["open"][t, 0] = px1
        mats["high"][t, 0] = px1 + 0.15
        mats["low"][t, 0] = px1 - 0.1
        mats["close"][t, 0] = px1 + 0.05
        mats["pre_close"][t, 0] = px1 if t == 0 else mats["close"][t - 1, 0]
        mats["volume"][t, 0] = 10_000_000.0
        mats["amount"][t, 0] = 100_000_000.0

        # 000002 hits exact 1-price limit-up on index 20 (switchover day+1)
        if t < 20:
            p2 = 10.0
        elif t == 20:
            p2 = 11.0  # 10.0 * 1.10 exact 1-price LU!
        else:
            p2 = 11.0
        mats["open"][t, 1] = p2
        mats["high"][t, 1] = p2
        mats["low"][t, 1] = p2
        mats["close"][t, 1] = p2
        mats["pre_close"][t, 1] = 10.0 if t <= 20 else 11.0
        mats["volume"][t, 1] = 5_000_000.0
        mats["amount"][t, 1] = 55_000_000.0

    pack_dir = tmp_path / "cn_pack"
    save_pack(
        pack_dir,
        DailyPack(
            dates=np.asarray(dates, dtype=str),
            codes=np.asarray(codes, dtype=str),
            matrices=mats,
            meta=pd.DataFrame([
                {"code": c, "name": f"N{c}", "industry": "银行", "is_st": False}
                for c in codes
            ]),
            sources=("test",),
        ),
    )

    pre_day = dates[4]
    switch_day = dates[19]
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="r_pre_close",
            track="rules",
            created_at=f"{pre_day}T18:30:00+08:00",
            picks=[Pick(rank=1, code="000001", name="N1", final_score=80.0, screen_score=80.0, price=10.5)],
        ),
        data_dir=tmp_path / "data",
    )
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            run_id="r_post_next_open",
            track="rules",
            created_at=f"{switch_day}T18:30:00+08:00",
            picks=[
                Pick(rank=1, code="000001", name="N1", final_score=82.0, screen_score=82.0, price=11.9),
                Pick(rank=2, code="000002", name="N2", final_score=81.0, screen_score=81.0, price=10.0),
            ],
        ),
        data_dir=tmp_path / "data",
    )

    monkeypatch.setattr(
        eval_mod,
        "fetch_daily_history",
        lambda *a, **kw: pytest.fail("CN pack evaluation should not fetch daily history over network"),
    )
    bench_df = pd.DataFrame({"date": dates, "open": [3000.0] * len(dates), "close": [3000.0] * len(dates)})
    monkeypatch.setattr(eval_mod, "_fetch_benchmark_path", lambda market, lookback_days=250: bench_df)

    payload = track_record.evaluate_markets(
        tmp_path, ["cn"], pack_dir=pack_dir, entry_mode="auto", next_open_from=switch_day
    )
    assert payload["entry_mode_switch_date"] == switch_day
    assert payload["runs"]["r_pre_close"]["windows"]["5"]["entry_mode"] == "close"
    w5_post = payload["runs"]["r_post_next_open"]["windows"]["5"]
    assert w5_post["entry_mode"] == "next_open"
    assert w5_post["picks"]["000001"]["status"] == "ok"
    assert w5_post["picks"]["000002"]["status"] == "untradable_limit_up"
    assert w5_post["untradable"] == 1

    # Paired AI comparison with >=10 common signal days vs 1 missing AI day after first_ai_date
    runs_list = []
    eval_map = {}
    cmp_dates = [f"2026-10-{d:02d}" for d in range(1, 13)]
    for i, d in enumerate(cmp_dates):
        rid_r = f"cmp_r_{i}"
        runs_list.append({
            "market": "cn", "strategy": "balanced_alpha", "track": "rules",
            "run_id": rid_r, "date": d,
            "picks": [
                {"code": "000001", "name": "平安银行"},
                {"code": "000002", "name": "万科A"},
            ],
        })
        dropped_ret = -3.0 if i == 2 else (2.5 if i == 3 else 0.0)
        eval_map[rid_r] = {"windows": {"5": {
            "entry_mode": "next_open",
            "picks": {
                "000001": {"status": "ok", "return_pct": 1.0, "excess_return_pct": 1.0},
                "000002": {"status": "ok", "return_pct": dropped_ret, "excess_return_pct": dropped_ret},
            },
        }}}
        if i == 11:
            continue  # 1 missing AI day out of 12 -> 1/12 = 8.3%
        rid_a = f"cmp_a_{i}"
        runs_list.append({
            "market": "cn", "strategy": "balanced_alpha", "track": "ai",
            "run_id": rid_a, "date": d,
            "picks": [
                {"code": "000001", "name": "平安银行"},
                {"code": "000003", "name": "国农科技"},
            ],
        })
        ai_ret = -1.5 if i == 4 else 4.0
        eval_map[rid_a] = {"windows": {"5": {
            "entry_mode": "next_open",
            "picks": {
                "000001": {"status": "ok", "return_pct": 1.0, "excess_return_pct": 1.0},
                "000003": {"status": "ok", "return_pct": ai_ret, "excess_return_pct": ai_ret},
            },
        }}}

    [cmp] = track_record.track_comparison(runs_list, eval_map)
    assert cmp["common_days"] == 11
    assert cmp["ai_missing_days"] == 1
    assert cmp["ai_missing_rate_pct"] == 8.3
    assert cmp["avg_pick_overlap_pct"] == pytest.approx(33.3, abs=0.1)
    w5_cmp = cmp["windows"]["5"]
    assert w5_cmp["paired_days"] == 11
    assert w5_cmp["sample_sufficient"] is True
    assert w5_cmp["ai_minus_rules_pct"] > 0
    cases = w5_cmp["ai_case_studies"]
    assert cases["best_ai_adds"][0]["code"] == "000003"
    assert cases["best_ai_adds"][0]["name"] == "国农科技"
    assert cases["worst_ai_adds"][0]["excess_return_pct"] == -1.5
    assert cases["best_ai_avoids"][0]["code"] == "000002"
    assert cases["best_ai_avoids"][0]["excess_return_pct"] == -3.0
    assert cases["missed_by_ai"][0]["excess_return_pct"] == 2.5


def test_track_record_page_html_js_syntax_and_drilldown_hooks(tmp_path: Path) -> None:
    import re
    import shutil
    import subprocess

    page_path = Path(__file__).resolve().parents[1] / "scripts" / "track_record_page.html"
    html = page_path.read_text(encoding="utf-8")
    for token in (
        "drillDownStrategy",
        "strat-drill-btn",
        "explorer-clear-btn",
        "sc_drill_title",
        "clear_filter",
        "wf-cli-btn",
        "copyPlainText",
        "wf_cli_copied",
        "renderJointCliCell",
        "purged_by_exit_date",
        "wf_unverified_note",
    ):
        assert token in html, f"missing hook {token}"

    scripts = re.findall(r"<script(?![^>]*src=)[^>]*>(.*?)</script>", html, flags=re.DOTALL)
    assert scripts
    node = shutil.which("node")
    if node is not None:
        js_file = tmp_path / "track_record_page.js"
        js_file.write_text(scripts[-1], encoding="utf-8")
        proc = subprocess.run([node, "--check", str(js_file)], capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stderr
