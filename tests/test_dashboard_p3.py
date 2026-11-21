# -*- coding: utf-8 -*-
"""Tests for P3 dashboard (mini K-line extraction, untradable share, HTML slices, deployment docs)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd
import yaml

from alphasift.pack import DailyPack, FIELDS, save_pack
from alphasift.patterns import extract_mini_kline_bars

_SPEC = importlib.util.spec_from_file_location(
    "track_record_p3",
    Path(__file__).resolve().parents[1] / "scripts" / "track_record.py",
)
assert _SPEC is not None and _SPEC.loader is not None
track_record = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = track_record
_SPEC.loader.exec_module(track_record)


def _pack_with_split(n_days: int = 75) -> DailyPack:
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-07-01", periods=n_days)]
    codes = ["000001", "600519"]
    matrices = {field: np.full((n_days, 2), np.nan, dtype=np.float32) for field in FIELDS}
    for j in range(2):
        for t in range(n_days):
            px = 10.0
            matrices["open"][t, j] = px
            matrices["high"][t, j] = px + 0.12
            matrices["low"][t, j] = px - 0.12
            matrices["close"][t, j] = px + 0.02
            matrices["pre_close"][t, j] = px if t == 0 else matrices["close"][t - 1, j]
            matrices["volume"][t, j] = 10_000_000.0
            matrices["amount"][t, j] = 100_000_000.0
    # Box breakout on idx = n_days - 6, and a future ex-rights drop on idx = n_days - 2.
    sig_t = n_days - 6
    matrices["open"][sig_t, 0] = 10.05
    matrices["high"][sig_t, 0] = 10.72
    matrices["low"][sig_t, 0] = 10.02
    matrices["close"][sig_t, 0] = 10.65
    matrices["volume"][sig_t, 0] = 30_000_000.0
    matrices["amount"][sig_t, 0] = 320_000_000.0
    for k in range(sig_t + 1, n_days):
        matrices["pre_close"][k, 0] = matrices["close"][k - 1, 0]

    # Inject suspended day (volume=0) on idx = sig_t - 3 for 600519
    matrices["volume"][sig_t - 3, 1] = 0.0

    # Future 50% ex-rights on n_days - 2 for 000001
    sp = n_days - 2
    matrices["pre_close"][sp, 0] = matrices["close"][sp - 1, 0] * 0.5
    for k in range(sp, n_days):
        matrices["open"][k, 0] *= 0.5
        matrices["high"][k, 0] *= 0.5
        matrices["low"][k, 0] *= 0.5
        matrices["close"][k, 0] *= 0.5
        if k > sp:
            matrices["pre_close"][k, 0] = matrices["close"][k - 1, 0]

    meta = pd.DataFrame([
        {
            "code": c,
            "name": f"N{c}",
            "industry": "电子",
            "pe_ratio": 20.0,
            "pb_ratio": 2.0,
            "total_mv": 1e10,
            "circ_mv": 8e9,
            "list_date": "2018-01-01",
            "is_st": False,
        }
        for c in codes
    ])
    return DailyPack(
        dates=np.asarray(dates, dtype=str),
        codes=np.asarray(codes, dtype=str),
        matrices=matrices,
        meta=meta,
        sources=("test",),
    )


def test_extract_mini_kline_bars_zero_lookahead_and_suspension_skip() -> None:
    pack = _pack_with_split(75)
    sig_t = 69
    sig_date = str(pack.dates[sig_t])

    trunc = DailyPack(
        dates=pack.dates[: sig_t + 1],
        codes=pack.codes,
        matrices={k: v[: sig_t + 1] for k, v in pack.matrices.items()},
        meta=pack.meta,
        sources=pack.sources,
    )
    bars_as_of = extract_mini_kline_bars(pack, ["000001", "600519"], trade_date=sig_date, bars=20)
    bars_trunc = extract_mini_kline_bars(trunc, ["000001", "600519"], as_of_index=-1, bars=20)

    assert len(bars_as_of["000001"]) == 20
    assert all(len(bar) == 4 for bar in bars_as_of["000001"])
    assert bars_as_of["000001"] == bars_trunc["000001"]
    assert len(bars_as_of["600519"]) == 20


def test_scorecard_untradable_share_and_pattern_board_replay_klines(tmp_path: Path) -> None:
    # 1) Scorecard untradable share computation
    runs_dir = tmp_path / "data" / "runs"
    runs_dir.mkdir(parents=True)
    run_payload = {
        "run_id": "r_unt",
        "market": "cn",
        "strategy": "dual_low",
        "created_at": "2026-11-04T18:30:00+08:00",
        "picks": [
            {"rank": 1, "code": "000001", "name": "A", "price": 10.0, "final_score": 80.0},
            {"rank": 2, "code": "000002", "name": "B", "price": 10.0, "final_score": 78.0},
            {"rank": 3, "code": "000003", "name": "C", "price": 10.0, "final_score": 76.0},
        ],
    }
    (runs_dir / "r_unt.json").write_text(json.dumps(run_payload), encoding="utf-8")
    runs = track_record.load_runs(tmp_path)
    evaluation = {
        "r_unt": {
            "windows": {
                "5": {
                    "picks": {
                        "000001": {"status": "ok", "return_pct": 3.0, "excess_return_pct": 2.0},
                        "000002": {"status": "untradable_limit_up", "return_pct": None, "excess_return_pct": None},
                        "000003": {"status": "ok", "return_pct": -1.0, "excess_return_pct": -2.0},
                    }
                }
            }
        }
    }
    [row] = track_record.scorecard(runs, evaluation)
    w5 = row["windows"]["5"]
    assert w5["evaluated"] == 2
    assert w5["untradable"] == 1
    assert w5["untradable_share_pct"] == 33.33

    # 2) Pattern board attaches mini K-lines + replay into site/patterns.json
    pack = _pack_with_split(75)
    pack_dir = tmp_path / "pack"
    save_pack(pack_dir, pack)
    fake_replay = tmp_path / "replay_in.json"
    fake_replay.write_text(
        json.dumps({
            "pack_summary": {"eval_start_date": "2026-09-25", "eval_end_date": "2026-10-08", "eval_sessions": 10},
            "patterns": [{"pattern": "box_breakout", "display_name": "箱体突破", "graduation": {"recommended_status": "experimental"}}],
        }),
        encoding="utf-8",
    )
    track_record.record_cn_patterns(
        tmp_path,
        pack_dir=pack_dir,
        trade_date=str(pack.dates[69]),
        replay_json_path=fake_replay,
    )
    (tmp_path / "site").mkdir(exist_ok=True)
    (tmp_path / "site" / "evaluation.json").write_text(json.dumps({"runs": evaluation}), encoding="utf-8")
    summary = track_record.build_site(tmp_path)
    assert summary["pattern_board"]["has_replay"] is True

    site_patterns = json.loads((tmp_path / "site" / "patterns.json").read_text(encoding="utf-8"))
    box_hits = site_patterns["latest"]["signals_by_pattern"]["box_breakout"]
    assert box_hits and len(box_hits[0]["kline"]) == 20
    assert site_patterns["replay"]["patterns"][0]["pattern"] == "box_breakout"


def test_dashboard_html_p3_sections_and_docs(tmp_path: Path) -> None:
    html_path = Path(__file__).resolve().parents[1] / "scripts" / "track_record_page.html"
    html = html_path.read_text(encoding="utf-8")
    for marker in (
        "量化形态观测与回测基准",
        "renderCnHero",
        "renderReturnDistSvg",
        "renderMiniKline",
        "renderPatternRadar",
        "renderTrackComparison",
        "untradable_share_pct",
        "未评估",
        "样本不足",
        "trend_ai",
        "ai_case_studies",
        "ai_brief",
        "site/daily_report.html",
        "universe_baseline",
        "by_overhead_supply",
        "muted-cell",
        "site/patterns.json",
        "site/report.json",
    ):
        assert marker in html

    # Syntax-check the embedded JS script if Node.js is installed in the test environment.
    node = shutil.which("node")
    if node is not None:
        match = re.search(r"<script>(.*)</script>", html, flags=re.DOTALL)
        assert match is not None
        js_file = tmp_path / "dashboard.js"
        js_file.write_text(match.group(1), encoding="utf-8")
        proc = subprocess.run([node, "--check", str(js_file)], capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stderr

    dep_doc = Path(__file__).resolve().parents[1] / "docs" / "deployment.md"
    assert dep_doc.is_file()
    dep_text = dep_doc.read_text(encoding="utf-8")
    assert "Cloudflare Pages" in dep_text
    assert "track-record" in dep_text
    assert "doctor radar" in dep_text
    assert "ALPHASIFT_DASHBOARD_URL" in dep_text


def test_workflows_valid_yaml_and_no_secret_echo() -> None:
    root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    loaded: dict[str, dict] = {}
    for name in ("data-pack.yml", "track-record.yml"):
        wf_path = root / name
        assert wf_path.is_file()
        text = wf_path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        assert isinstance(data, dict)
        assert True in data or "on" in data
        assert "jobs" in data and data["jobs"]
        assert "echo ${{ secrets." not in text
        assert 'echo "$TICKPLUS_API_KEY"' not in text
        loaded[name] = (data, text)

    # data-pack.yml exposes workflow_call with strictly string inputs for reuse.
    dp_data, _ = loaded["data-pack.yml"]
    dp_on = dp_data.get("on") if "on" in dp_data else dp_data[True]
    wf_call_inputs = dp_on["workflow_call"]["inputs"]
    assert all(spec["type"] == "string" for spec in wf_call_inputs.values())

    # track-record.yml chains pack -> record, evaluates with --pack-dir, and builds after daily-report.
    tr_data, tr_text = loaded["track-record.yml"]
    assert "pack" in tr_data["jobs"]
    assert tr_data["jobs"]["pack"]["uses"] == "./.github/workflows/data-pack.yml"
    assert tr_data["jobs"]["record"]["needs"] == ["pack"]
    step_names = [s.get("name", "") for s in tr_data["jobs"]["record"]["steps"]]
    assert step_names.index("Daily report and optional IM push") < step_names.index("Build site data")
    assert "evaluate --track track --markets" in tr_text and '--pack-dir "$ALPHASIFT_PACK_DIR"' in tr_text
    assert "--output-html track/site/daily_report.html" in tr_text
    assert "--ai-brief auto" in tr_text
