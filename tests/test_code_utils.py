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

    pkg_dir = Path(__file__).resolve().parents[1] / "alphasift"
    raw_callers = []
    for path in sorted(pkg_dir.glob("*.py")):
        if path.name == "jsonutil.py":
            continue
        if re.search(r"\bjson\.dumps\s*\(", path.read_text(encoding="utf-8")):
            raw_callers.append(path.name)
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
