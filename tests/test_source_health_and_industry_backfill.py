import json
import time
from pathlib import Path

import pandas as pd

import alphasift.industry as industry
import alphasift.snapshot as snapshot
from alphasift.config import Config, _resolve_source_health_path
from alphasift.industry import _fetch_eastmoney_industry_rows as _real_eastmoney_rows
from alphasift.pipeline import _industry_coverage, screen
from alphasift.snapshot import _order_sources_by_persisted_health, fetch_snapshot_with_fallback


def _snapshot_rows(industry_labels=None):
    rows = []
    for i, code in enumerate(["601229", "601169", "600016", "000001", "600519", "000858"]):
        rows.append(
            {
                "code": code,
                "name": f"stock{i}",
                "price": 10.0 + i,
                "change_pct": 0.5,
                "amount": 500_000_000,
                "turnover_rate": 1.0,
                "volume_ratio": 1.0,
                "pe_ratio": 6.0 + i,
                "pb_ratio": 0.6 + i * 0.1,
                "total_mv": 100_000_000_000,
                "circ_mv": 100_000_000_000,
            }
        )
    df = pd.DataFrame(rows)
    if industry_labels is not None:
        df["industry"] = industry_labels
    df.attrs["snapshot_source"] = "test"
    return df


def test_order_sources_demotes_recent_failures_only():
    now = time.time()
    health = {
        "sina": {"consecutive_failures": 2, "last_failure_at": now - 60, "last_success_at": 0},
        "efinance": {"consecutive_failures": 1, "last_failure_at": now - 7 * 3600, "last_success_at": 0},
        "em_datacenter": {"consecutive_failures": 0, "last_success_at": now - 30},
    }

    ordered, notes = _order_sources_by_persisted_health(
        ["sina", "efinance", "em_datacenter"], health, now=now
    )

    # sina failed a minute ago -> demoted; efinance's failure aged out of the TTL.
    assert ordered == ["efinance", "em_datacenter", "sina"]
    assert notes and "recently failed: sina" in notes[0]


def test_order_sources_keeps_order_when_everything_is_failing():
    now = time.time()
    health = {
        name: {"consecutive_failures": 1, "last_failure_at": now - 10}
        for name in ("sina", "em_datacenter")
    }

    ordered, notes = _order_sources_by_persisted_health(["sina", "em_datacenter"], health, now=now)

    assert ordered == ["sina", "em_datacenter"]
    assert notes == []


def test_fetch_snapshot_persists_health_and_reorders_next_run(monkeypatch, tmp_path):
    calls = []

    def fake_fetch(source):
        calls.append(source)
        if source == "sina":
            raise RuntimeError("read timed out")
        return _snapshot_rows()

    monkeypatch.setattr(snapshot, "fetch_cn_snapshot", fake_fetch)
    monkeypatch.setattr(snapshot, "_SOURCE_HEALTH", {})
    health_path = tmp_path / "source_health.json"

    first = fetch_snapshot_with_fallback(
        ["sina", "em_datacenter"], fallback_snapshot_path=None, source_health_path=health_path
    )
    assert calls == ["sina", "em_datacenter"]
    assert first.attrs["source_order_notes"] == []

    saved = json.loads(health_path.read_text(encoding="utf-8"))
    assert saved["sources"]["sina"]["consecutive_failures"] == 1
    assert saved["sources"]["em_datacenter"]["consecutive_failures"] == 0

    calls.clear()
    second = fetch_snapshot_with_fallback(
        ["sina", "em_datacenter"], fallback_snapshot_path=None, source_health_path=health_path
    )
    # A fresh process would start from the persisted file; the healthy source wins first.
    assert calls == ["em_datacenter"]
    assert second.attrs["snapshot_source"] == "test"
    assert "recently failed: sina" in second.attrs["source_order_notes"][0]


def test_fetch_snapshot_without_health_path_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshot, "fetch_cn_snapshot", lambda source: _snapshot_rows())
    fetch_snapshot_with_fallback(["em_datacenter"], fallback_snapshot_path=None, source_health_path=None)
    assert list(tmp_path.iterdir()) == []


def test_eastmoney_industry_map_uses_fresh_cache_then_stale_cache(monkeypatch, tmp_path):
    calls = []

    def fake_rows():
        calls.append(1)
        return {"601229": {"industry": "银行"}}

    monkeypatch.setattr(industry, "_fetch_eastmoney_industry_rows", fake_rows)
    mapping, notes = industry.fetch_eastmoney_industry_map(cache_dir=tmp_path)
    assert mapping == {"601229": {"industry": "银行"}}
    assert calls == [1]

    mapping, notes = industry.fetch_eastmoney_industry_map(cache_dir=tmp_path)
    assert calls == [1]
    assert "cache hit" in notes[0]

    def failing_rows():
        raise RuntimeError("blocked")

    monkeypatch.setattr(industry, "_fetch_eastmoney_industry_rows", failing_rows)
    mapping, notes = industry.fetch_eastmoney_industry_map(cache_dir=tmp_path, cache_ttl_seconds=0)
    assert mapping["601229"]["industry"] == "银行"
    assert "expired cache" in notes[0]


def test_industry_coverage():
    assert _industry_coverage(_snapshot_rows()) == 0.0
    assert _industry_coverage(_snapshot_rows(["银行", "银行", "", "", "", ""])) == 1 / 3


def _screen_config(tmp_path, **overrides):
    values = dict(
        llm_api_key="",
        snapshot_source_priority=["test"],
        strategies_dir=Path("strategies"),
        industry_provider_cache_dir=tmp_path,
        post_analyzers=[],
    )
    values.update(overrides)
    return Config(**values)


def test_screen_backfills_missing_industry_and_restores_diversity(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "alphasift.pipeline.fetch_snapshot_with_fallback", lambda sources, **kwargs: _snapshot_rows()
    )
    monkeypatch.setattr(
        industry,
        "_fetch_eastmoney_industry_rows",
        lambda: {
            "601229": {"industry": "银行"},
            "601169": {"industry": "银行"},
            "600016": {"industry": "银行"},
            "000001": {"industry": "银行"},
            "600519": {"industry": "酿酒行业"},
            "000858": {"industry": "酿酒行业"},
        },
    )

    result = screen("dual_low", use_llm=False, config=_screen_config(tmp_path))

    assert all(pick.industry for pick in result.picks)
    # A successful routine backfill must not mark the run as degraded.
    assert not any("Portfolio diversity skipped" in item for item in result.degradation)
    assert not any("Industry" in item for item in result.degradation)


def test_screen_reports_failed_backfill_as_degradation(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "alphasift.pipeline.fetch_snapshot_with_fallback", lambda sources, **kwargs: _snapshot_rows()
    )

    result = screen("dual_low", use_llm=False, config=_screen_config(tmp_path))

    assert any("Industry auto-backfill: eastmoney industry provider failed" in item for item in result.degradation)
    assert any("Portfolio diversity skipped" in item for item in result.degradation)


def test_screen_reports_skipped_diversity_when_backfill_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "alphasift.pipeline.fetch_snapshot_with_fallback", lambda sources, **kwargs: _snapshot_rows()
    )

    result = screen(
        "dual_low",
        use_llm=False,
        config=_screen_config(tmp_path, industry_auto_backfill=False),
    )

    assert result.picks
    assert any("Portfolio diversity skipped" in item for item in result.degradation)


def test_missing_required_columns_does_not_demote_source(monkeypatch, tmp_path):
    def fake_fetch(source):
        df = _snapshot_rows()
        if source == "sina":
            df = df.drop(columns=["volume_ratio"])
        return df

    monkeypatch.setattr(snapshot, "fetch_cn_snapshot", fake_fetch)
    monkeypatch.setattr(snapshot, "_SOURCE_HEALTH", {})
    health_path = tmp_path / "source_health.json"

    result = fetch_snapshot_with_fallback(
        ["sina", "em_datacenter"],
        required_columns=["volume_ratio"],
        fallback_snapshot_path=None,
        source_health_path=health_path,
    )

    assert result.attrs["source_errors"] == ["sina: missing required columns volume_ratio"]
    saved = json.loads(health_path.read_text(encoding="utf-8"))
    assert "sina" not in saved["sources"]
    assert list(tmp_path.glob("*.tmp")) == []


def test_malformed_health_file_fails_open(monkeypatch, tmp_path):
    health_path = tmp_path / "source_health.json"
    health_path.write_text(
        json.dumps(
            {
                "version": 1,
                "sources": {
                    "sina": {"last_failure_at": "invalid", "consecutive_failures": 2},
                    "efinance": "not-a-dict",
                },
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_fetch(source):
        calls.append(source)
        return _snapshot_rows()

    monkeypatch.setattr(snapshot, "fetch_cn_snapshot", fake_fetch)

    result = fetch_snapshot_with_fallback(
        ["sina", "efinance"], fallback_snapshot_path=None, source_health_path=health_path
    )

    assert calls == ["sina"]
    assert not result.empty


def test_save_merges_other_runs_updates(monkeypatch, tmp_path):
    health_path = tmp_path / "source_health.json"
    # Another process recorded efinance after this run loaded the file.
    other = {"efinance": {"consecutive_failures": 1, "last_failure_at": time.time()}}
    health_path.write_text(json.dumps({"version": 1, "sources": other}), encoding="utf-8")

    mine = {"sina": {"consecutive_failures": 0, "last_success_at": time.time()}}
    snapshot._save_persisted_source_health(health_path, mine, {"sina"})

    saved = json.loads(health_path.read_text(encoding="utf-8"))["sources"]
    assert set(saved) == {"sina", "efinance"}
    assert saved["efinance"]["consecutive_failures"] == 1


def test_eastmoney_industry_rows_stop_on_empty_page(monkeypatch):
    pages = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, params=None, **kwargs):
        pages.append(params["p"])
        if params["p"] == "1":
            return FakeResponse(
                {"success": True, "result": {"count": 9000, "data": [{"SECURITY_CODE": "000001", "INDUSTRY": "银行"}]}}
            )
        return FakeResponse({"success": True, "result": {"count": 9000, "data": None}})

    monkeypatch.setattr(snapshot, "_eastmoney_get", fake_get)

    mapping = _real_eastmoney_rows()
    assert mapping == {"000001": {"industry": "银行"}}
    assert pages == ["1", "2"]


def test_config_defaults_enable_health_and_backfill(monkeypatch, tmp_path):
    monkeypatch.delenv("ALPHASIFT_SOURCE_HEALTH_PATH", raising=False)
    monkeypatch.delenv("INDUSTRY_AUTO_BACKFILL", raising=False)
    monkeypatch.setenv("ALPHASIFT_DATA_DIR", str(tmp_path))

    config = Config.from_env()

    assert config.source_health_path == tmp_path / "source_health.json"
    assert config.industry_auto_backfill is True


def test_source_health_path_can_be_disabled(monkeypatch, tmp_path):
    for value in ("off", "none", "0", ""):
        monkeypatch.setenv("ALPHASIFT_SOURCE_HEALTH_PATH", value)
        assert _resolve_source_health_path(tmp_path) is None
