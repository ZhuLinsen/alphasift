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
            "patterns": [{"pattern": "box_breakout", "display_name": "箱体突破", "graduation": {"recommended_status": "experimental"}, "multiple_testing": {"n_patterns_tested": 9, "bh_q_value_csi300": 0.42, "bh_q_value_ew": 0.51, "bh_fdr_pass": False}}],
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
    assert summary["artifacts"]["patterns"]["exists"] is True
    assert summary["artifacts"]["report"]["exists"] is False
    assert summary["artifacts"]["daily_report_html"]["exists"] is False
    assert summary["integrity"]["algorithm"] == "sha256"
    assert len(summary["integrity"]["runs_sha256"]) == 64
    manifest_file = tmp_path / "site" / "manifest.sha256"
    assert manifest_file.is_file()
    manifest_text = manifest_file.read_text(encoding="utf-8")
    assert "summary.json" in manifest_text
    assert "patterns.json" in manifest_text
    if shutil.which("sha256sum") is not None:
        proc_sum = subprocess.run(
            ["sha256sum", "-c", "manifest.sha256"],
            cwd=tmp_path / "site",
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc_sum.returncode == 0, proc_sum.stderr
    assert summary["artifacts"]["patterns"]["pack_is_stale"] is False
    site_patterns = json.loads((tmp_path / "site" / "patterns.json").read_text(encoding="utf-8"))
    assert site_patterns["replay"]["cost_bps"] == 0.0 or "graduation_rule" in site_patterns["replay"]

    site_patterns = json.loads((tmp_path / "site" / "patterns.json").read_text(encoding="utf-8"))
    box_hits = site_patterns["latest"]["signals_by_pattern"]["box_breakout"]
    assert box_hits and len(box_hits[0]["kline"]) == 20
    assert site_patterns["replay"]["patterns"][0]["pattern"] == "box_breakout"
    assert site_patterns["replay"]["patterns"][0]["multiple_testing"]["bh_q_value_csi300"] == 0.42

    # 3) Valid Atom 1.0 RSS feed written alongside summary.json
    import xml.etree.ElementTree as ET
    feed_path = tmp_path / "site" / "feed.xml"
    assert feed_path.is_file()
    feed_root = ET.fromstring(feed_path.read_text(encoding="utf-8"))
    assert feed_root.tag == "{http://www.w3.org/2005/Atom}feed"
    assert feed_root.find("{http://www.w3.org/2005/Atom}title") is not None


def test_dashboard_html_p3_sections_and_docs(tmp_path: Path) -> None:
    html_path = Path(__file__).resolve().parents[1] / "scripts" / "track_record_page.html"
    html = html_path.read_text(encoding="utf-8")
    for marker in (
        "量化形态观测与回测基准",
        "https://github.com/ZhuLinsen/alphasift",
        "computeClientConsensus",
        "kpi-strip",
        "pick-search",
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
        "walk_forward_regime_audit",
        "walk-forward-wrap",
        "openRadarAccordionsForHash",
        "pat-summary-badge",
        "replay-summary-badge",
        "muted-cell",
        "ai-attr-filter",
        "aiAttrFilter",
        "wf_note",
        "--allowed-regimes",
        "--exclude-regimes",
        "nav_github",
        "gh-short",
        "star-callout",
        "star_callout_text",
        "utm_source=dashboard_leaderboard",
        "footer_discussions",
        "btn_deploy",
        "utm_source=dashboard",
        "h2_non_adverse_low_overhead",
        "wf_tip_joint",
        "site/patterns.json",
        "site/report.json",
        "site/feed.xml",
        "lang-switch",
        "SUPPORTED_LANGS",
        "Quantitative Discovery",
        "health-strip",
        "status-ok",
        "chart-crosshair",
        "three_white_soldiers",
        "renderHitSparkline",
        "restoreQueryState",
        "footer-manifest-link",
        "t5_net_excess_mean_pct",
        "data:image/svg+xml",
        "og:image",
        "twitter:card",
        "trend-density",
        "news-strip",
        "degradation_notes",
        "application/ld+json",
        "btn-share",
        "Post-Close Brief: ",
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

    # data-pack.yml exposes workflow_call with strictly string inputs, explicit secrets, strict doctor gates, and uses private Actions cache.
    dp_data, dp_text = loaded["data-pack.yml"]
    dp_on = dp_data.get("on") if "on" in dp_data else dp_data[True]
    wf_call_inputs = dp_on["workflow_call"]["inputs"]
    assert all(spec["type"] == "string" for spec in wf_call_inputs.values())
    assert "TICKPLUS_API_KEY" in (dp_on["workflow_call"].get("secrets") or {})
    assert "persist-credentials: false" in dp_text
    assert "--strict-pack" in dp_text and "--require-fresh" in dp_text
    assert "${{ inputs." not in dp_text.split("run:")[-1]
    assert "gh release create" not in dp_text and "gh release upload" not in dp_text
    assert "actions/cache" in dp_text
    assert "alphasift pack pull" not in dp_text

    # track-record.yml chains pack -> record with explicit secret scope, holiday-aware freshness gate before staging, and zero persisted tokens.
    tr_data, tr_text = loaded["track-record.yml"]
    assert "pack" in tr_data["jobs"]
    assert tr_data["jobs"]["pack"]["uses"] == "./.github/workflows/data-pack.yml"
    assert "secrets: inherit" not in tr_text
    assert tr_text.count("persist-credentials: false") >= 2
    assert "cn_market_state" in tr_text and "skipped_holiday" in tr_text
    assert "logs[-1]" not in tr_text
    assert "CN_TRADE_DATE" in tr_text and "pat_fresh" in tr_text and "rep_fresh" in tr_text
    assert "${{ github.repository }}" not in tr_text.split("name: Build site data")[1].split("Commit to track-record")[0].split("run:")[-1]
    assert tr_data["jobs"]["record"]["needs"] == ["pack"]
    deploy_if = str(tr_data["jobs"]["deploy"].get("if") or "")
    assert "needs.record.result == 'success'" in deploy_if and "!cancelled()" in deploy_if
    assert "github.repository == 'ZhuLinsen/alphasift'" in deploy_if
    assert "ALPHASIFT_ENABLE_PAGES" in deploy_if
    assert "ALPHASIFT_ENABLE_PAGES" in tr_text
    assert "NOTIFY_URLS" in tr_text
    assert "LLM_CANDIDATE_CONTEXT_ENABLED" in tr_text
    assert "gh release create" not in tr_text and "gh release upload" not in tr_text
    assert "actions/cache/restore" in tr_text
    assert "alphasift pack pull" not in tr_text
    step_names = [s.get("name", "") for s in tr_data["jobs"]["record"]["steps"]]
    assert step_names.index("Daily report and optional IM push") < step_names.index("Build site data")
    assert step_names.index("Publish health & artifact gate") < step_names.index("Stage the dashboard")
    assert "evaluate --track track --markets" in tr_text and '--pack-dir "$ALPHASIFT_PACK_DIR"' in tr_text
    assert "--output-html track/site/daily_report.html" in tr_text
    assert "--ai-brief auto" in tr_text
    assert "Publish health & artifact gate" in tr_text
    assert "GITHUB_STEP_SUMMARY" in tr_text
    assert "missing_pack_streak" in tr_text
    assert "social-preview.png" in tr_text
    assert "session == 'rebuild'" in tr_text
    assert "push_flag" in tr_text
    assert "robots.txt" in tr_text
    assert "sitemap.xml" in tr_text
    assert "CF_WEB_ANALYTICS_TOKEN" in tr_text


def test_workflows_actions_pinned_to_sha_and_dependabot_valid() -> None:
    import re

    gh_dir = Path(__file__).resolve().parents[1] / ".github"
    workflows = sorted((gh_dir / "workflows").glob("*.yml"))
    assert workflows

    pin_re = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}$")
    for wf in workflows:
        text = wf.read_text(encoding="utf-8")
        for match in re.finditer(r"^\s*-?\s*uses:\s*(.+)$", text, flags=re.MULTILINE):
            ref = match.group(1).split("#", 1)[0].strip().strip("'\"")
            if ref.startswith("./"):
                continue
            assert pin_re.fullmatch(ref), f"Unpinned GitHub Action in {wf.name}: {ref}"

    dependabot_path = gh_dir / "dependabot.yml"
    assert dependabot_path.is_file()
    dep = yaml.safe_load(dependabot_path.read_text(encoding="utf-8"))
    assert dep["version"] == 2
    ecosystems = {u["package-ecosystem"] for u in dep.get("updates", [])}
    assert {"github-actions", "pip"}.issubset(ecosystems)


def test_dashboard_page_i18n_race_guard_url_sync_and_js_syntax(tmp_path) -> None:
    import re
    import subprocess

    page_path = Path(__file__).resolve().parents[1] / "scripts" / "track_record_page.html"
    html_text = page_path.read_text(encoding="utf-8")

    # 1. Race guard and query-param history.replaceState sync exist
    assert "dayReqId: 0" in html_text
    assert 'replayStatus[name] || (items[0] ? items[0].status : "experimental")' in html_text
    assert "const reqId = ++state.dayReqId" in html_text
    assert "if (reqId !== state.dayReqId) return;" in html_text
    assert "window.history.replaceState" in html_text
    assert "syncQueryState();" in html_text

    # 2. Hardcoded untranslated literals & raw tooltip sinks removed from renderers
    assert '<span class="chip">Rules Benchmark</span>' not in html_text
    assert 't("live_7mkt")' in html_text
    assert 't("live_latest_fmt"' in html_text
    assert "tHiddenReason(x.delta_hidden_reason" in html_text
    assert "indname(" in html_text
    assert "tStatus(e.status)" in html_text
    assert "rule_hl_fmt:" in html_text
    assert "rule_hl_noreg_fmt:" in html_text
    assert "esc(c.dataset.label)" in html_text
    assert "if (!res.ok)" in html_text
    assert "renderDay(days[0] || \"\")" in html_text

    # 3. Extract script block and verify JS syntax + full zh/en/ja I18N key parity with node
    m = re.search(r"<script>([\s\S]*)</script>", html_text)
    assert m is not None
    js_path = tmp_path / "track_record.js"
    js_path.write_text(m.group(1), encoding="utf-8")
    subprocess.run(["node", "--check", str(js_path)], check=True)

    check_js = tmp_path / "check_i18n.js"
    dict_match = re.search(r"(const I18N = \{[\s\S]*?\n\};)", html_text)
    assert dict_match is not None
    check_js.write_text(
        dict_match.group(1)
        + """
const zhKeys = Object.keys(I18N.zh).sort();
const enKeys = Object.keys(I18N.en).sort();
const jaKeys = Object.keys(I18N.ja).sort();
for (const k of new Set([...zhKeys, ...enKeys, ...jaKeys])) {
  if (!zhKeys.includes(k)) { console.error("Missing in ZH:", k); process.exit(1); }
  if (!enKeys.includes(k)) { console.error("Missing in EN:", k); process.exit(2); }
  if (!jaKeys.includes(k)) { console.error("Missing in JA:", k); process.exit(3); }
}
for (const lang of ["en", "ja"]) {
  for (const [k, v] of Object.entries(I18N[lang])) {
    if (k === "rule_sub_cons" || k === "rule_sub_sec") continue;
    if (typeof v === "string" && /[\\u4e00-\\u9fff]/.test(v) && lang === "en") {
      console.error("CJK in EN:", k, v);
      process.exit(4);
    }
  }
}
console.log("I18N_PARITY_OK", zhKeys.length);
""",
        encoding="utf-8",
    )
    out = subprocess.run(["node", str(check_js)], check=True, capture_output=True, text=True)
    assert "I18N_PARITY_OK" in out.stdout


def test_build_site_emits_robots_txt_and_fork_safe_sitemap(tmp_path: Path, monkeypatch) -> None:
    import xml.etree.ElementTree as ET

    runs_dir = tmp_path / "data" / "runs"
    runs_dir.mkdir(parents=True)
    run_payload = {
        "run_id": "2026-11-20-cn-dual_low-1",
        "market": "cn",
        "strategy": "dual_low",
        "created_at": "2026-11-20T18:30:00+08:00",
        "picks": [
            {"rank": 1, "code": "601997", "name": "贵阳银行", "price": 5.8, "final_score": 82.0},
        ],
    }
    (runs_dir / "2026-11-20-cn-dual_low-1.json").write_text(json.dumps(run_payload), encoding="utf-8")
    (tmp_path / "site").mkdir(exist_ok=True)
    (tmp_path / "site" / "daily_report.html").write_text("<html><body>ok</body></html>", encoding="utf-8")
    (tmp_path / "site" / "report.json").write_text(
        json.dumps({"trade_date": "2026-11-20", "market_summary": {"up": 100}}),
        encoding="utf-8",
    )

    monkeypatch.setenv("ALPHASIFT_DASHBOARD_URL", "https://forkuser.github.io/alphasift")
    track_record.build_site(tmp_path)

    robots = (tmp_path / "robots.txt").read_text(encoding="utf-8")
    assert "User-agent: *" in robots
    assert "Sitemap: https://forkuser.github.io/alphasift/sitemap.xml" in robots

    sitemap_text = (tmp_path / "sitemap.xml").read_text(encoding="utf-8")
    root = ET.fromstring(sitemap_text)
    assert root.tag == "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset"
    locs = [el.text for el in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    assert locs == [
        "https://forkuser.github.io/alphasift/",
        "https://forkuser.github.io/alphasift/site/daily_report.html",
        "https://forkuser.github.io/alphasift/site/feed.xml",
    ]
    assert "alphasift.zhulinsen.tech" not in robots
    assert "alphasift.zhulinsen.tech" not in sitemap_text

