import os
import sys
import threading
import time
import types

import pandas as pd
import pytest

from alphasift.daily import compute_daily_features, daily_source_health_snapshot, enrich_daily_features, fetch_daily_history
from alphasift.daily import (
    _SOURCE_HEALTH,
    _normalize_tushare_adj,
    _rank_daily_sources_by_health,
    _record_source_failure,
    _record_source_success,
    _source_disabled_reason,
    _to_baostock_code,
    _to_tencent_code,
    _to_tushare_code,
)


@pytest.fixture(autouse=True)
def clear_daily_source_health():
    _SOURCE_HEALTH.clear()
    yield
    _SOURCE_HEALTH.clear()


def test_compute_daily_features_adds_trend_fields():
    closes = [10 + i * 0.1 for i in range(80)]
    hist = pd.DataFrame({
        "日期": pd.date_range("2026-01-01", periods=80).astype(str),
        "开盘": [value - 0.1 for value in closes],
        "最高": [value + 0.2 for value in closes],
        "最低": [value - 0.2 for value in closes],
        "收盘": closes,
        "成交量": [1000] * 79 + [1800],
    })

    features = compute_daily_features(hist)

    assert features["daily_data_points"] == 80
    assert features["change_60d"] > 0
    assert features["ma_bullish"] is True
    assert features["price_above_ma20"] is True
    assert features["signal_score"] >= 65
    assert -1.0 <= features["breakout_20d_pct"] <= 0.0
    assert features["range_20d_pct"] < 20
    assert features["volume_ratio_20d"] == 1.8
    assert features["body_pct"] > 0
    assert features["pullback_to_ma20_pct"] > 0
    assert features["consolidation_days_20d"] >= 8
    assert float(features["volatility_20d_pct"]) >= 0
    assert float(features["max_drawdown_20d_pct"]) <= 0
    assert float(features["atr_20_pct"]) > 0
    assert features["daily_quality_score"] == 100.0
    assert features["daily_quality_flags"] == ""


def test_compute_daily_features_flags_short_stale_fallback_history():
    hist = pd.DataFrame({
        "日期": pd.date_range("2026-01-01", periods=25).astype(str),
        "收盘": [10 + i * 0.1 for i in range(25)],
    })
    hist.attrs["daily_stale"] = True
    hist.attrs["source_errors"] = ["tencent offline", "sina offline"]

    features = compute_daily_features(hist)

    assert float(features["daily_quality_score"]) < 60
    flags = str(features["daily_quality_flags"])
    assert "short_history_lt30" in flags
    assert "stale_cache" in flags
    assert "fallback_errors" in flags


def test_compute_daily_features_flags_invalid_ohlcv_quality():
    hist = pd.DataFrame({
        "日期": pd.date_range("2026-01-01", periods=35).astype(str),
        "开盘": [10] * 35,
        "最高": [11] * 34 + [8],
        "最低": [9] * 35,
        "收盘": [10] * 35,
        "成交量": [1000] * 34 + [-1],
    })

    features = compute_daily_features(hist)

    flags = str(features["daily_quality_flags"])
    assert "invalid_ohlc" in flags
    assert "negative_volume" in flags
    assert float(features["daily_quality_score"]) < 60


def test_fetch_daily_history_retries_transient_source_errors(monkeypatch):
    calls = {"count": 0}

    class FakeAkshare:
        @staticmethod
        def stock_zh_a_hist(**kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise ConnectionError("temporary disconnect")
            return pd.DataFrame({
                "日期": pd.date_range("2026-01-01", periods=40).astype(str),
                "收盘": [10 + i * 0.1 for i in range(40)],
            })

    monkeypatch.setitem(__import__("sys").modules, "akshare", FakeAkshare)
    monkeypatch.setattr("alphasift.daily.time.sleep", lambda seconds: None)

    result = fetch_daily_history("000001", retries=1)

    assert calls["count"] == 2
    assert len(result) == 40


def test_fetch_daily_history_reports_retry_count(monkeypatch):
    class FakeAkshare:
        @staticmethod
        def stock_zh_a_hist(**kwargs):
            raise ConnectionError("temporary disconnect")

    monkeypatch.setitem(__import__("sys").modules, "akshare", FakeAkshare)
    monkeypatch.setattr("alphasift.daily.time.sleep", lambda seconds: None)

    with pytest.raises(RuntimeError, match="after 2 attempts"):
        fetch_daily_history("000001", retries=1)


def test_fetch_daily_history_times_out_wrapper_sources(monkeypatch):
    class FakeAkshare:
        @staticmethod
        def stock_zh_a_hist(**kwargs):
            time.sleep(0.05)
            return pd.DataFrame({
                "日期": pd.date_range("2026-01-01", periods=40).astype(str),
                "收盘": [10] * 40,
            })

    monkeypatch.setenv("ALPHASIFT_DAILY_CALL_TIMEOUT_SEC", "0.001")
    monkeypatch.setitem(sys.modules, "akshare", FakeAkshare)

    with pytest.raises(RuntimeError, match="daily source akshare timed out"):
        fetch_daily_history("000001", source="akshare", retries=0)

    health = daily_source_health_snapshot()
    assert health["akshare"]["failures"] == 1.0
    assert "timed out" in health["akshare"]["last_error"]
    assert health["akshare"]["last_failure_at"] > 0


def test_daily_source_health_temporarily_disables_repeated_failures(monkeypatch):
    _SOURCE_HEALTH.clear()
    monkeypatch.setattr("alphasift.daily.time.monotonic", lambda: 100.0)

    _record_source_failure("akshare")
    _record_source_failure("akshare")
    assert _source_disabled_reason("akshare") is None
    _record_source_failure("akshare")

    assert "temporarily disabled" in str(_source_disabled_reason("akshare"))
    _record_source_success("akshare")
    assert _source_disabled_reason("akshare") is None


def test_daily_source_health_tracks_success_failure_and_rows(monkeypatch):
    _SOURCE_HEALTH.clear()
    monkeypatch.setattr("alphasift.daily.time.monotonic", lambda: 100.0)
    _record_source_failure("tencent")
    _record_source_success("tencent", rows=40)
    _record_source_success("sina", rows=30)

    snapshot = daily_source_health_snapshot()

    assert snapshot["tencent"]["successes"] == 1.0
    assert snapshot["tencent"]["failures"] == 0.0
    assert snapshot["tencent"]["total_failures"] == 1.0
    assert snapshot["tencent"]["last_rows"] == 40.0
    assert snapshot["tencent"]["disabled"] is False
    assert snapshot["sina"]["avg_rows"] == 30.0


def test_daily_source_health_reorders_auto_sources(monkeypatch):
    _SOURCE_HEALTH.clear()
    monkeypatch.setattr("alphasift.daily.time.monotonic", lambda: 100.0)
    _record_source_failure("tencent")
    _record_source_failure("tencent")
    _record_source_success("sina", rows=60)

    ranked, notes = _rank_daily_sources_by_health(("tencent", "sina", "akshare"))

    assert ranked == ("sina", "akshare", "tencent")
    assert notes == ["daily source order adjusted by health: sina,akshare,tencent"]


def test_daily_source_health_does_not_promote_later_success_above_neutral_source(monkeypatch):
    _SOURCE_HEALTH.clear()
    monkeypatch.setattr("alphasift.daily.time.monotonic", lambda: 100.0)
    _record_source_success("sina", rows=60)

    ranked, notes = _rank_daily_sources_by_health(("tushare", "tencent", "sina"))

    assert ranked == ("tushare", "tencent", "sina")
    assert notes == []


def test_fetch_daily_history_uses_cache_until_ttl(tmp_path, monkeypatch):
    calls = {"count": 0}

    class FakeAkshare:
        @staticmethod
        def stock_zh_a_hist(**kwargs):
            calls["count"] += 1
            return pd.DataFrame({
                "日期": pd.date_range("2026-01-01", periods=40).astype(str),
                "收盘": [10 + calls["count"]] * 40,
            })

    monkeypatch.setitem(__import__("sys").modules, "akshare", FakeAkshare)

    first = fetch_daily_history(
        "SZ000001",
        lookback_days=45,
        source="akshare",
        retries=0,
        cache_dir=tmp_path / "daily_history",
        cache_ttl_seconds=3600,
    )
    second = fetch_daily_history(
        "1",
        lookback_days=45,
        source="AKSHARE",
        retries=0,
        cache_dir=tmp_path / "daily_history",
        cache_ttl_seconds=3600,
    )

    assert calls["count"] == 1
    assert list(first["收盘"]) == list(second["收盘"])
    assert first.attrs["daily_source"] == "akshare"
    assert second.attrs["daily_source"] == "akshare"
    assert second.attrs["daily_requested_source"] == "akshare"
    assert second.attrs["daily_source_order"] == ["akshare"]
    assert second.attrs["daily_source_order_notes"] == []
    assert second.attrs["daily_source_health"]["akshare"]["successes"] == 1.0
    assert second.attrs["daily_source_health"]["akshare"]["last_rows"] == 40.0
    assert len(list((tmp_path / "daily_history").glob("*.json"))) == 1


def test_fetch_daily_history_refetches_after_cache_expiry(tmp_path, monkeypatch):
    calls = {"count": 0}

    class FakeAkshare:
        @staticmethod
        def stock_zh_a_hist(**kwargs):
            calls["count"] += 1
            return pd.DataFrame({
                "日期": pd.date_range("2026-01-01", periods=40).astype(str),
                "收盘": [10 + calls["count"]] * 40,
            })

    monkeypatch.setitem(__import__("sys").modules, "akshare", FakeAkshare)
    cache_dir = tmp_path / "daily_history"

    first = fetch_daily_history(
        "000001",
        lookback_days=45,
        source="akshare",
        retries=0,
        cache_dir=cache_dir,
        cache_ttl_seconds=60,
    )
    cache_file = next(cache_dir.glob("*.json"))
    expired = time.time() - 120
    os.utime(cache_file, (expired, expired))
    second = fetch_daily_history(
        "000001",
        lookback_days=45,
        source="akshare",
        retries=0,
        cache_dir=cache_dir,
        cache_ttl_seconds=60,
    )

    assert calls["count"] == 2
    assert first["收盘"].iloc[-1] == 11
    assert second["收盘"].iloc[-1] == 12


def test_fetch_daily_history_uses_stale_cache_after_live_sources_fail(tmp_path, monkeypatch):
    calls = {"count": 0}

    class FakeAkshare:
        @staticmethod
        def stock_zh_a_hist(**kwargs):
            calls["count"] += 1
            if calls["count"] > 1:
                raise ConnectionError("offline")
            return pd.DataFrame({
                "日期": pd.date_range("2026-01-01", periods=40).astype(str),
                "收盘": [11] * 40,
            })

    monkeypatch.setitem(__import__("sys").modules, "akshare", FakeAkshare)
    cache_dir = tmp_path / "daily_history"

    fetch_daily_history(
        "000001",
        lookback_days=45,
        source="akshare",
        retries=0,
        cache_dir=cache_dir,
        cache_ttl_seconds=60,
    )
    cache_file = next(cache_dir.glob("*.json"))
    expired = time.time() - 120
    os.utime(cache_file, (expired, expired))

    stale = fetch_daily_history(
        "000001",
        lookback_days=45,
        source="akshare",
        retries=0,
        cache_dir=cache_dir,
        cache_ttl_seconds=60,
    )

    assert calls["count"] == 2
    assert stale.attrs["daily_stale"] is True
    assert stale.attrs["source_errors"] == ["akshare after 1 attempts: offline"]
    assert stale["收盘"].iloc[-1] == 11


def test_fetch_daily_history_without_cache_dir_preserves_live_fetch(monkeypatch):
    calls = {"count": 0}

    class FakeAkshare:
        @staticmethod
        def stock_zh_a_hist(**kwargs):
            calls["count"] += 1
            return pd.DataFrame({
                "日期": pd.date_range("2026-01-01", periods=40).astype(str),
                "收盘": [10 + calls["count"]] * 40,
            })

    monkeypatch.setitem(__import__("sys").modules, "akshare", FakeAkshare)

    first = fetch_daily_history("000001", retries=0)
    second = fetch_daily_history("000001", retries=0)

    assert calls["count"] == 2
    assert first["收盘"].iloc[-1] == 11
    assert second["收盘"].iloc[-1] == 12


def test_fetch_daily_history_uses_tushare_qfq_source(monkeypatch):
    calls = {}

    class FakePro:
        _DataApi__http_url = ""

        def daily(self, **kwargs):
            calls["daily"] = kwargs
            return pd.DataFrame({
                "ts_code": ["000001.SZ", "000001.SZ"],
                "trade_date": ["20260428", "20260429"],
                "open": [10.0, 10.4],
                "high": [10.5, 10.6],
                "low": [9.9, 10.3],
                "close": [10.4, 10.5],
                "vol": [12345.0, 12300.0],
                "amount": [100000.0, 100500.0],
            })

        def adj_factor(self, **kwargs):
            calls["adj_factor"] = kwargs
            return pd.DataFrame({
                "trade_date": ["20260429", "20260428"],
                "adj_factor": [2.0, 1.0],
            })

    class FakeTushare(types.SimpleNamespace):
        @staticmethod
        def pro_api(token=None):
            calls["token"] = token
            return FakePro()

    monkeypatch.setenv("TUSHARE_TOKEN", "token")
    monkeypatch.setitem(sys.modules, "tushare", FakeTushare)

    result = fetch_daily_history("1", source="tushare", retries=0)

    assert calls["token"] == "token"
    assert calls["daily"]["ts_code"] == "000001.SZ"
    assert calls["adj_factor"]["ts_code"] == "000001.SZ"
    assert list(result.columns) == [
        "ts_code",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    ]
    assert list(result["date"]) == ["20260428", "20260429"]
    assert list(result["volume"]) == [12345.0, 12300.0]
    assert result["close"].iloc[0] == 5.2
    assert result["close"].iloc[1] == 10.5


def test_fetch_daily_history_auto_prefers_tushare_when_token_exists(monkeypatch):
    class FakePro:
        def daily(self, **kwargs):
            return pd.DataFrame({
                "trade_date": ["20260429"],
                "open": [10.0],
                "high": [10.5],
                "low": [9.9],
                "close": [10.4],
                "vol": [12345.0],
                "amount": [100000.0],
            })

        def adj_factor(self, **kwargs):
            return pd.DataFrame({
                "trade_date": ["20260429"],
                "adj_factor": [1.0],
            })

    class FakeTushare(types.SimpleNamespace):
        @staticmethod
        def pro_api(token=None):
            return FakePro()

    class FakeAkshare:
        @staticmethod
        def stock_zh_a_hist(**kwargs):
            raise AssertionError("akshare should not be called when tushare succeeds")

    monkeypatch.setenv("TUSHARE_TOKEN", "token")
    monkeypatch.setitem(sys.modules, "tushare", FakeTushare)
    monkeypatch.setitem(sys.modules, "akshare", FakeAkshare)

    result = fetch_daily_history("000001", source="auto", retries=0)

    assert result["close"].iloc[-1] == 10.4


def test_fetch_daily_history_supports_tencent_direct_http(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "code": 0,
                "data": {
                    "sz000001": {
                        "qfqday": [
                            ["2026-04-28", "10.0", "10.4", "10.5", "9.9", "12345.0"],
                            ["2026-04-29", "10.4", "10.5", "10.6", "10.3", "12300.0"],
                        ]
                    }
                },
            }

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr("alphasift.daily.requests.get", fake_get)

    result = fetch_daily_history("1", source="tencent", retries=0)

    assert captured["params"] == {"param": "sz000001,day,,,120,qfq"}
    assert captured["headers"]["User-Agent"] == "Mozilla/5.0"
    assert list(result.columns) == ["date", "open", "close", "high", "low", "volume", "amount"]
    assert list(result["date"]) == ["2026-04-28", "2026-04-29"]
    assert result["close"].iloc[-1] == 10.5
    assert pd.isna(result["amount"].iloc[-1])
    assert result.attrs["daily_source"] == "tencent"
    assert result.attrs["daily_requested_source"] == "tencent"


def test_fetch_daily_history_auto_uses_tencent_before_wrapper_sources(monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "code": 0,
                "data": {
                    "sh600519": {
                        "qfqday": [["2026-04-29", "100", "101", "102", "99", "123"]]
                    }
                },
            }

    class FakeAkshare:
        @staticmethod
        def stock_zh_a_hist(**kwargs):
            raise AssertionError("akshare should not be called when tencent succeeds")

    def fake_get(*args, **kwargs):
        calls.append(kwargs)
        return FakeResponse()

    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.delenv("TUSHARE_API_TOKEN", raising=False)
    monkeypatch.setattr("alphasift.daily.requests.get", fake_get)
    monkeypatch.setitem(sys.modules, "akshare", FakeAkshare)

    result = fetch_daily_history("600519", source="auto", retries=0)

    assert calls[0]["params"] == {"param": "sh600519,day,,,120,qfq"}
    assert result["close"].iloc[-1] == 101


def test_fetch_daily_history_supports_sina_direct_http(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "result": {
                    "data": [
                        {"day": "2026-04-28", "open": "10.0", "high": "10.5", "low": "9.9", "close": "10.4", "volume": "12345"},
                        {"day": "2026-04-29", "open": "10.4", "high": "10.6", "low": "10.3", "close": "10.5", "volume": "12300"},
                    ]
                }
            }

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr("alphasift.daily.requests.get", fake_get)

    result = fetch_daily_history("000001", source="sina", retries=0)

    assert "CN_MarketDataService.getKLineData" in captured["url"]
    assert captured["params"] == {"symbol": "sz000001", "scale": 240, "ma": "no", "datalen": 120}
    assert list(result.columns) == ["date", "open", "close", "high", "low", "volume", "amount"]
    assert list(result["date"]) == ["2026-04-28", "2026-04-29"]
    assert result["close"].iloc[-1] == 10.5


def test_fetch_daily_history_auto_falls_back_from_tencent_to_sina(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if "fqkline" in url:
            return FakeResponse({"code": 0, "data": {}})
        return FakeResponse({
            "result": {
                "data": [
                    {"day": "2026-04-29", "open": "10", "high": "11", "low": "9", "close": "10.5", "volume": "1000"}
                ]
            }
        })

    class FakeAkshare:
        @staticmethod
        def stock_zh_a_hist(**kwargs):
            raise AssertionError("akshare should not be called when sina succeeds")

    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.delenv("TUSHARE_API_TOKEN", raising=False)
    monkeypatch.setattr("alphasift.daily.requests.get", fake_get)
    monkeypatch.setitem(sys.modules, "akshare", FakeAkshare)

    result = fetch_daily_history("000001", source="auto", retries=0)

    assert "fqkline" in calls[0][0]
    assert "CN_MarketDataService.getKLineData" in calls[1][0]
    assert result["close"].iloc[-1] == 10.5
    assert result.attrs["daily_source"] == "sina"
    assert result.attrs["daily_requested_source"] == "auto"
    assert result.attrs["source_errors"][0].startswith("tencent after 1 attempts")


def test_enrich_daily_features_keeps_successful_rows_when_one_fetch_fails(monkeypatch):
    candidates = pd.DataFrame([
        {"code": "000001", "name": "平安银行"},
        {"code": "600000", "name": "浦发银行"},
    ])

    def fake_fetch_daily_history(code, **kwargs):
        if code == "600000":
            raise ConnectionError("remote disconnected")
        hist = pd.DataFrame({
            "日期": pd.date_range("2026-01-01", periods=80).astype(str),
            "收盘": [10 + i * 0.1 for i in range(80)],
        })
        hist.attrs["daily_source"] = "akshare"
        hist.attrs["daily_source_order_notes"] = ["daily source order adjusted by health: akshare"]
        hist.attrs["daily_source_health"] = {"akshare": {"successes": 1.0}}
        return hist

    monkeypatch.setattr("alphasift.daily.fetch_daily_history", fake_fetch_daily_history)

    result = enrich_daily_features(candidates, max_rows=2)

    assert result.attrs["daily_success_count"] == 1
    assert len(result.attrs["daily_errors"]) == 1
    assert "600000" in result.attrs["daily_errors"][0]
    assert result.loc[0, "daily_data_points"] == 80
    assert result.loc[0, "daily_source"] == "akshare"
    assert result.loc[0, "daily_quality_score"] == 88.0
    assert result.loc[0, "daily_quality_flags"] == "missing_volume"
    assert result.attrs["daily_source_counts"] == {"akshare": 1}
    assert result.attrs["daily_quality_flag_counts"] == {"missing_volume": 1, "fetch_failed": 1}
    assert result.attrs["daily_source_order_notes"] == ["daily source order adjusted by health: akshare"]
    assert result.attrs["daily_source_health"] == {"akshare": {"successes": 1.0}}
    assert pd.isna(result.loc[1, "daily_data_points"])
    assert result.loc[1, "daily_quality_score"] == 0.0
    assert result.loc[1, "daily_quality_flags"] == "fetch_failed"


def test_enrich_daily_features_fetches_rows_concurrently_preserving_index(monkeypatch):
    candidates = pd.DataFrame(
        [
            {"code": "000003", "name": "招商银行"},
            {"code": "000001", "name": "平安银行"},
            {"code": "600000", "name": "浦发银行"},
        ],
        index=["row_c", "row_a", "row_b"],
    )
    candidates.attrs["snapshot_source"] = "test"
    candidates.attrs["source_errors"] = ["primary fallback"]
    active = 0
    max_active = 0
    lock = threading.Lock()
    overlap_seen = threading.Event()

    def fake_fetch_daily_history(code, **kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            if active >= 2:
                overlap_seen.set()
        try:
            overlap_seen.wait(timeout=0.25)
            return pd.DataFrame({"code": [code]})
        finally:
            with lock:
                active -= 1

    def fake_compute_daily_features(hist):
        code = str(hist.loc[0, "code"])
        return {"daily_data_points": int(code[-1]), "signal_score": int(code[-1]) * 10}

    monkeypatch.setattr("alphasift.daily.fetch_daily_history", fake_fetch_daily_history)
    monkeypatch.setattr("alphasift.daily.compute_daily_features", fake_compute_daily_features)

    result = enrich_daily_features(candidates, max_rows=3, max_workers=2)

    assert max_active >= 2
    assert list(result.index) == ["row_c", "row_a", "row_b"]
    assert list(result["code"]) == ["000003", "000001", "600000"]
    assert result.loc["row_c", "daily_data_points"] == 3
    assert result.loc["row_a", "daily_data_points"] == 1
    assert result.loc["row_b", "daily_data_points"] == 0
    assert result.attrs["snapshot_source"] == "test"
    assert result.attrs["source_errors"] == ["primary fallback"]
    assert result.attrs["daily_success_count"] == 3
    assert result.attrs["daily_errors"] == []


def test_enrich_daily_features_serializes_baostock_queries(monkeypatch):
    candidates = pd.DataFrame(
        [
            {"code": "000001", "name": "平安银行"},
            {"code": "600000", "name": "浦发银行"},
        ]
    )
    active_queries = 0
    max_active_queries = 0
    lock = threading.Lock()

    class FakeRS:
        error_code = "0"
        error_msg = ""

        def __init__(self):
            self._rows = [
                ["2026-04-28", "10.0", "10.5", "9.9", "10.4", "12345", "100000"],
                ["2026-04-29", "10.4", "10.6", "10.3", "10.5", "12300", "100500"],
            ]

        def next(self):
            return bool(self._rows)

        def get_row_data(self):
            return self._rows.pop(0)

    class FakeBaostock:
        @staticmethod
        def login():
            return None

        @staticmethod
        def logout():
            return None

        @staticmethod
        def query_history_k_data_plus(*args, **kwargs):
            nonlocal active_queries, max_active_queries
            with lock:
                active_queries += 1
                max_active_queries = max(max_active_queries, active_queries)
            try:
                time.sleep(0.02)
                return FakeRS()
            finally:
                with lock:
                    active_queries -= 1

    monkeypatch.setitem(__import__("sys").modules, "baostock", FakeBaostock)

    result = enrich_daily_features(candidates, max_rows=2, source="baostock", fetch_retries=0)

    assert max_active_queries == 1
    assert result.attrs["daily_success_count"] == 2
    assert result.attrs["daily_errors"] == []


def test_enrich_daily_features_short_circuits_baostock_network_outage(monkeypatch):
    candidates = pd.DataFrame(
        [
            {"code": "000001", "name": "平安银行"},
            {"code": "600000", "name": "浦发银行"},
        ]
    )
    queries = {"count": 0}

    class FakeLoginResult:
        error_code = "0"
        error_msg = ""

    class FakeRS:
        error_code = "10002007"
        error_msg = "网络接收错误。"

    class FakeBaostock:
        @staticmethod
        def login():
            return FakeLoginResult()

        @staticmethod
        def logout():
            return None

        @staticmethod
        def query_history_k_data_plus(*args, **kwargs):
            queries["count"] += 1
            return FakeRS()

    monkeypatch.setitem(__import__("sys").modules, "baostock", FakeBaostock)
    monkeypatch.setattr("alphasift.daily._BAOSTOCK_OUTAGE_ERROR", None)

    result = enrich_daily_features(candidates, max_rows=2, source="baostock", fetch_retries=0)

    assert queries["count"] == 1
    assert result.attrs["daily_success_count"] == 0
    assert len(result.attrs["daily_errors"]) == 2
    assert "baostock error 10002007" in result.attrs["daily_errors"][0]
    assert "baostock error 10002007" in result.attrs["daily_errors"][1]


def test_to_baostock_code_handles_main_boards():
    assert _to_baostock_code("600519") == "sh.600519"
    assert _to_baostock_code("000001") == "sz.000001"
    assert _to_baostock_code("300750") == "sz.300750"
    assert _to_baostock_code("688981") == "sh.688981"
    assert _to_baostock_code("1") == "sz.000001"


def test_to_tushare_code_handles_exchange_suffixes():
    assert _to_tushare_code("600519") == "600519.SH"
    assert _to_tushare_code("000001") == "000001.SZ"
    assert _to_tushare_code("300750") == "300750.SZ"
    assert _to_tushare_code("688981") == "688981.SH"
    assert _to_tushare_code("830799") == "830799.BJ"
    assert _to_tushare_code("920593") == "920593.BJ"
    assert _to_tushare_code("1") == "000001.SZ"


def test_to_tencent_code_handles_exchange_prefixes():
    assert _to_tencent_code("600519") == "sh600519"
    assert _to_tencent_code("000001") == "sz000001"
    assert _to_tencent_code("300750") == "sz300750"
    assert _to_tencent_code("688981") == "sh688981"
    assert _to_tencent_code("830799") == "bj830799"
    assert _to_tencent_code("920593") == "bj920593"
    assert _to_tencent_code("1") == "sz000001"


def test_normalize_tushare_adj_accepts_qfq_and_none():
    assert _normalize_tushare_adj("qfq") == "qfq"
    assert _normalize_tushare_adj("hfq") == "hfq"
    assert _normalize_tushare_adj("none") is None
    assert _normalize_tushare_adj("") is None


def test_fetch_daily_history_auto_falls_back_to_baostock(monkeypatch):
    class FakeAkshare:
        @staticmethod
        def stock_zh_a_hist(**kwargs):
            raise ConnectionError("akshare temporarily unavailable")

    def fake_tencent_get(*args, **kwargs):
        raise ConnectionError("tencent temporarily unavailable")

    rows = [
        ["2026-04-28", "10.0", "10.5", "9.9", "10.4", "12345", "100000"],
        ["2026-04-29", "10.4", "10.6", "10.3", "10.5", "12300", "100500"],
    ]

    class FakeRS:
        def __init__(self):
            self.error_code = "0"
            self.error_msg = ""
            self._rows = list(rows)

        def next(self):
            return bool(self._rows)

        def get_row_data(self):
            return self._rows.pop(0)

    class FakeBaostock:
        @staticmethod
        def login():
            return None

        @staticmethod
        def logout():
            return None

        @staticmethod
        def query_history_k_data_plus(*args, **kwargs):
            return FakeRS()

    monkeypatch.setitem(__import__("sys").modules, "akshare", FakeAkshare)
    monkeypatch.setitem(__import__("sys").modules, "baostock", FakeBaostock)
    monkeypatch.setattr("alphasift.daily.requests.get", fake_tencent_get)
    monkeypatch.setattr("alphasift.daily.time.sleep", lambda seconds: None)

    df = fetch_daily_history("600519", source="auto", retries=0)

    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume", "amount"]
    assert len(df) == 2


def test_enrich_daily_features_preserves_us_ticker_codes(monkeypatch):
    candidates = pd.DataFrame([
        {"code": "AAPL", "name": "Apple"},
        {"code": "000001", "name": "平安银行"},
    ])

    captured_codes = []

    def spy_fetch(code, **kwargs):
        captured_codes.append(code)
        return pd.DataFrame({
            "日期": pd.date_range("2026-01-01", periods=40).astype(str),
            "收盘": [10 + i * 0.1 for i in range(40)],
        })

    monkeypatch.setattr("alphasift.daily.fetch_daily_history", spy_fetch)

    enrich_daily_features(candidates, max_rows=2, source="akshare", fetch_retries=0)

    assert "AAPL" in captured_codes
    assert "000001" in captured_codes


def test_fetch_daily_history_yfinance_flattens_multiindex(monkeypatch):
    closes = [150.0 + i for i in range(40)]
    multi_cols = pd.MultiIndex.from_tuples([
        ("Close", "AAPL"), ("High", "AAPL"), ("Low", "AAPL"),
        ("Open", "AAPL"), ("Volume", "AAPL"),
    ], names=["Price", "Ticker"])
    hist_df = pd.DataFrame(
        {
            ("Close", "AAPL"): closes,
            ("High", "AAPL"): [c + 1 for c in closes],
            ("Low", "AAPL"): [c - 1 for c in closes],
            ("Open", "AAPL"): [c - 0.5 for c in closes],
            ("Volume", "AAPL"): [1_000_000] * 40,
        },
        index=pd.date_range("2026-03-01", periods=40),
    )
    hist_df.columns = multi_cols

    fake_yf = types.ModuleType("yfinance")
    fake_yf.download = lambda *a, **kw: hist_df
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    from alphasift.snapshot_us import fetch_daily_history_yfinance
    result = fetch_daily_history_yfinance("AAPL", lookback_days=30)

    assert "收盘" in result.columns
    assert "日期" in result.columns
    assert len(result) == 30
