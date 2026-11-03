import json
import time
from pathlib import Path

import pandas as pd

import alphasift.industry as industry
import alphasift.snapshot as snapshot
from alphasift.config import Config
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
    assert not any("Portfolio diversity skipped" in item for item in result.degradation)
    assert any("eastmoney industry map fetched" in item for item in result.degradation)


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
