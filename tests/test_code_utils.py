from alphasift.normalize import normalize_code


def test_normalize_code_accepts_numeric_suffixed_and_prefixed_codes():
    assert normalize_code(1.0) == "000001"
    assert normalize_code("SZ000001") == "000001"
    assert normalize_code("000001.SZ") == "000001"
    assert normalize_code("sh600000") == "600000"
    assert normalize_code("证券代码:300750") == "300750"


def test_normalize_code_drops_tickers_by_default():
    assert normalize_code("AAPL") == ""
    assert normalize_code("BRK-B") == ""


def test_normalize_code_allow_ticker_passes_us_tickers_through():
    assert normalize_code("AAPL", allow_ticker=True) == "AAPL"
    assert normalize_code("brk-b", allow_ticker=True) == "BRK-B"


def test_normalize_code_allow_ticker_keeps_a_share_rules_first():
    assert normalize_code("SZ000001", allow_ticker=True) == "000001"
    assert normalize_code("000001.SZ", allow_ticker=True) == "000001"
    assert normalize_code("sh600000", allow_ticker=True) == "600000"
    assert normalize_code(1.0, allow_ticker=True) == "000001"


def test_normalize_code_allow_ticker_rejects_non_ascii_text():
    assert normalize_code("亏损", allow_ticker=True) == ""
    assert normalize_code("暂无", allow_ticker=True) == ""


def test_only_jsonutil_calls_raw_json_dumps():
    from pathlib import Path
    import re

    repo_root = Path(__file__).resolve().parents[1]
    raw_callers = []
    for folder in ("alphasift", "scripts"):
        for path in sorted((repo_root / folder).glob("*.py")):
            if folder == "alphasift" and path.name == "jsonutil.py":
                continue
            if re.search(r"\bjson\.dumps\s*\(", path.read_text(encoding="utf-8")):
                raw_callers.append(f"{folder}/{path.name}")
    assert raw_callers == []


def test_store_persistence_sanitizes_nonfinite_and_numpy(tmp_path):
    import json
    import numpy as np
    from alphasift.models import Pick, ScreenResult
    from alphasift.store import save_screen_result

    res = ScreenResult(
        strategy="dual_low",
        market="cn",
        run_id="strict_json_run",
        created_at="2026-11-25T10:00:00+08:00",
        snapshot_count=100,
        after_filter_count=1,
        picks=[
            Pick(
                rank=1,
                code="000001",
                name="平安银行",
                final_score=np.float64(88.5),
                screen_score=float("nan"),
                price=float("inf"),
            )
        ],
    )

    def _reject_constant(token):
        raise AssertionError(f"Invalid RFC-8259 JSON constant: {token}")

    json_path = save_screen_result(res, data_dir=tmp_path)
    loaded = json.loads(json_path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    assert loaded["picks"][0]["final_score"] == 88.5
    assert loaded["picks"][0]["screen_score"] is None
    assert loaded["picks"][0]["price"] is None

    jsonl_path = tmp_path / "strict.jsonl"
    save_screen_result(res, data_dir=tmp_path, path=jsonl_path, jsonl=True)
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        json.loads(line, parse_constant=_reject_constant)


def test_atomic_write_helpers_preserve_prior_content_on_error(tmp_path):
    import pytest
    from alphasift.jsonutil import atomic_write_strict_json, atomic_write_text

    target = tmp_path / "nested" / "state.json"
    atomic_write_strict_json(target, {"ok": True, "score": float("nan")}, indent=2, trailing_newline=True)
    original = target.read_text(encoding="utf-8")
    assert '"score": null' in original
    assert original.endswith("\n")
    assert [p.name for p in target.parent.iterdir()] == ["state.json"]

    class _Explode:
        def __str__(self):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        atomic_write_strict_json(target, {"bad": _Explode()})
    assert target.read_text(encoding="utf-8") == original
    assert [p.name for p in target.parent.iterdir()] == ["state.json"]

    text_target = tmp_path / "notes.txt"
    atomic_write_text(text_target, "v1")
    atomic_write_text(text_target, "v2")
    assert text_target.read_text(encoding="utf-8") == "v2"
    assert [p.name for p in text_target.parent.iterdir() if p.name.endswith(".tmp")] == []


def test_cache_writers_persist_atomically_without_tmp_leftovers(tmp_path):
    import json
    import pandas as pd
    from alphasift.daily import _write_daily_history_cache
    from alphasift.hotspot import HotspotSummary, save_hotspots_json
    from alphasift.industry import _write_akshare_board_cache, save_industry_map
    from alphasift.snapshot import _save_persisted_source_health, _write_last_good_snapshot

    health_path = tmp_path / "health.json"
    _save_persisted_source_health(health_path, {"sina": {"ok": True, "calls": 1}}, touched={"sina"})
    assert json.loads(health_path.read_text(encoding="utf-8"))["sources"]["sina"]["ok"] is True

    snap_df = pd.DataFrame([{"code": "000001", "name": "平安银行", "price": 10.5}])
    snap_path = tmp_path / "snap.json"
    _write_last_good_snapshot(snap_path, snap_df)
    assert snap_path.is_file()

    daily_path = tmp_path / "daily.json"
    _write_daily_history_cache(
        daily_path,
        pd.DataFrame([{"date": "2026-11-25", "close": 10.5}]),
        code="000001",
        source="test",
        lookback_days=30,
    )
    assert daily_path.is_file()

    ind_cache = tmp_path / "industry.json"
    _write_akshare_board_cache(ind_cache, {"000001": {"industry": "银行"}}, max_boards=10)
    ind_export = tmp_path / "industry_export.json"
    save_industry_map({"000001": {"industry": "银行"}}, ind_export)
    assert json.loads(ind_export.read_text(encoding="utf-8"))[0]["industry"] == "银行"
    ind_csv = tmp_path / "industry_export.csv"
    save_industry_map({"000001": {"industry": "银行"}}, ind_csv)
    assert "银行" in ind_csv.read_text(encoding="utf-8")

    hs_path = tmp_path / "hotspots.json"
    save_hotspots_json(hs_path, [HotspotSummary(topic="算力", name="算力", source="test", rank=1)])
    assert hs_path.is_file()
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


def test_cli_metadata_and_no_non_staging_write_text_dumps_strict_json(tmp_path):
    from pathlib import Path
    import re
    from alphasift.cli import _write_hotspot_cache_metadata, _write_industry_cache_metadata

    repo_root = Path(__file__).resolve().parents[1]
    direct_writes = []
    for folder in ("alphasift", "scripts"):
        for path in sorted((repo_root / folder).glob("*.py")):
            if folder == "alphasift" and path.name in {"jsonutil.py", "pack.py"}:
                continue
            if re.search(r"\.write_text\(\s*dumps_strict_json\s*\(", path.read_text(encoding="utf-8")):
                direct_writes.append(f"{folder}/{path.name}")
    assert direct_writes == []

    ind_meta = _write_industry_cache_metadata(
        tmp_path / "ind.json", provider="eastmoney", max_boards=10, rows=5, notes=[]
    )
    hs_meta = _write_hotspot_cache_metadata(
        tmp_path / "hs.json", provider="eastmoney", max_boards=10, rows=3
    )
    assert ind_meta.is_file() and hs_meta.is_file()
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []
