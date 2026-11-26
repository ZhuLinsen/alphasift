import time

import pytest

from alphasift.snapshot_yahoo import _int_env, _num
from alphasift.source_guard import (
    SourceCallTimeout,
    call_with_timeout,
    parse_source_timeout_seconds,
)


def test_parse_source_timeout_seconds_handles_fallback_disable_and_bad_values(monkeypatch):
    monkeypatch.delenv("ALPHASIFT_SINA_TIMEOUT_SEC", raising=False)
    monkeypatch.delenv("ALPHASIFT_SOURCE_CALL_TIMEOUT_SEC", raising=False)
    assert parse_source_timeout_seconds("ALPHASIFT_SINA_TIMEOUT_SEC", default=12.5) == 12.5

    # Blank specific env falls back to shared source timeout env rather than disabling guarding
    monkeypatch.setenv("ALPHASIFT_SINA_TIMEOUT_SEC", "  ")
    monkeypatch.setenv("ALPHASIFT_SOURCE_CALL_TIMEOUT_SEC", "25")
    assert parse_source_timeout_seconds("ALPHASIFT_SINA_TIMEOUT_SEC", default=12.5) == 25.0

    # When both are blank, safe default is preserved
    monkeypatch.setenv("ALPHASIFT_SOURCE_CALL_TIMEOUT_SEC", "")
    assert parse_source_timeout_seconds("ALPHASIFT_SINA_TIMEOUT_SEC", default=12.5) == 12.5

    # Explicit disable tokens turn timeout off even if fallback has a number
    monkeypatch.setenv("ALPHASIFT_SOURCE_CALL_TIMEOUT_SEC", "25")
    for token in ("0", "-3", "false", "OFF", "None", "disabled"):
        monkeypatch.setenv("ALPHASIFT_SINA_TIMEOUT_SEC", token)
        assert parse_source_timeout_seconds("ALPHASIFT_SINA_TIMEOUT_SEC", default=12.5) is None

    # Non-finite or unparseable values fall back safely to default
    for bad in ("nan", "inf", "-Infinity", "not-a-number"):
        monkeypatch.setenv("ALPHASIFT_SINA_TIMEOUT_SEC", bad)
        assert parse_source_timeout_seconds("ALPHASIFT_SINA_TIMEOUT_SEC", default=12.5) == 12.5


def test_call_with_timeout_bounds_and_nonfinite_safety():
    assert call_with_timeout(lambda x: x + 1, 41, timeout_sec=1.0, label="ok") == 42

    for direct in (None, 0, -1.0, float("nan"), float("inf")):
        assert call_with_timeout(lambda: "done", timeout_sec=direct, label="direct") == "done"

    with pytest.raises(ValueError, match="bool"):
        call_with_timeout(lambda: "bad", timeout_sec=True, label="bool")

    with pytest.raises(SourceCallTimeout, match="slow_op timed out"):
        call_with_timeout(lambda: time.sleep(0.3), timeout_sec=0.05, label="slow_op")


def test_snapshot_yahoo_num_and_int_env_reject_bad_values(monkeypatch):
    for bad in (None, "", True, False, float("nan"), float("inf"), float("-inf"), "inf"):
        assert _num(bad) is None
    assert _num("12.5") == 12.5

    monkeypatch.setenv("ALPHASIFT_YAHOO_MAX_ROWS", "bad-int")
    assert _int_env("ALPHASIFT_YAHOO_MAX_ROWS", 4000) == 4000
    monkeypatch.setenv("ALPHASIFT_YAHOO_MAX_ROWS", "0")
    assert _int_env("ALPHASIFT_YAHOO_MAX_ROWS", 4000) == 1
