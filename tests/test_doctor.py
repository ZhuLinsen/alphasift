import json
import sys
from pathlib import Path

import pandas as pd
import pytest

from alphasift.cli import main
from alphasift.config import Config
from alphasift.doctor import doctor_data_sources
from alphasift.snapshot import (
    _SOURCE_HEALTH,
    _record_source_failure,
    snapshot_source_health_snapshot,
)


def test_snapshot_source_health_snapshot_reports_disabled_failures(monkeypatch):
    _SOURCE_HEALTH.clear()
    monkeypatch.setattr("alphasift.snapshot.time.monotonic", lambda: 100.0)

    _record_source_failure("sina")
    _record_source_failure("sina")
    _record_source_failure("sina")

    health = snapshot_source_health_snapshot(["sina", "efinance"])

    assert health["sina"]["failures"] == 3.0
    assert health["sina"]["total_failures"] == 3.0
    assert health["sina"]["disabled"] is True
    assert health["efinance"]["disabled"] is False
    _SOURCE_HEALTH.clear()


def test_doctor_data_sources_aggregates_snapshot_and_daily(monkeypatch, tmp_path):
    config = Config(
        snapshot_source_priority=["sina", "efinance"],
        daily_source="auto",
        fallback_snapshot_path=tmp_path / "snapshot.last_good.json",
        daily_history_cache_dir=tmp_path / "daily_history",
    )

    def fake_snapshot(sources, **kwargs):
        assert sources == ["sina", "efinance"]
        df = pd.DataFrame([{"code": "000001", "name": "平安银行", "price": 10.0}])
        df.attrs["snapshot_source"] = "sina"
        df.attrs["fallback_used"] = False
        df.attrs["stale"] = False
        df.attrs["source_errors"] = []
        return df

    def fake_daily(code, **kwargs):
        assert code == "000001"
        assert kwargs["source"] == "auto"
        df = pd.DataFrame([{"date": "2026-01-01", "close": 10.0}])
        df.attrs["daily_source"] = "tencent"
        df.attrs["source_errors"] = ["tushare after 1 attempts: no token"]
        return df

    monkeypatch.setattr("alphasift.doctor.fetch_snapshot_with_fallback", fake_snapshot)
    monkeypatch.setattr("alphasift.doctor.fetch_daily_history", fake_daily)

    result = doctor_data_sources(config)
    payload = result.to_dict()

    assert payload["status"] == "ok"
    assert payload["snapshot"]["source"] == "sina"
    assert payload["snapshot"]["rows"] == 1
    assert payload["daily"]["source"] == "tencent"
    assert payload["daily"]["fallback_used"] is True
    assert "source_health" in payload
    assert "health_summary" in payload
    assert payload["health_summary"]["snapshot"]["selected_source"] == "sina"
    assert payload["health_summary"]["daily"]["selected_source"] == "tencent"
    assert "TUSHARE_TOKEN" not in json.dumps(payload, ensure_ascii=False)


def test_doctor_data_sources_health_summary_reports_disabled_sources(monkeypatch, tmp_path):
    _SOURCE_HEALTH.clear()
    monkeypatch.setattr("alphasift.snapshot.time.monotonic", lambda: 100.0)
    _record_source_failure("sina", "timeout")
    _record_source_failure("sina", "timeout")
    _record_source_failure("sina", "timeout")
    config = Config(
        snapshot_source_priority=["sina", "efinance"],
        daily_source="auto",
        fallback_snapshot_path=tmp_path / "snapshot.last_good.json",
        daily_history_cache_dir=tmp_path / "daily_history",
    )

    result = doctor_data_sources(config, run_live=False)
    payload = result.to_dict()

    snapshot_summary = payload["health_summary"]["snapshot"]
    assert snapshot_summary["disabled_sources"] == ["sina"]
    assert snapshot_summary["never_seen_sources"] == ["efinance"]
    assert snapshot_summary["available_source_count"] == 1
    assert snapshot_summary["last_errors"][0]["source"] == "sina"
    assert "Snapshot health guard disabled sources: sina" in " | ".join(payload["recommendations"])
    _SOURCE_HEALTH.clear()


def test_doctor_data_sources_reports_strategy_requirements_without_live(tmp_path):
    config = Config(
        strategies_dir=Path("strategies"),
        snapshot_source_priority=["sina"],
        daily_source="auto",
        fallback_snapshot_path=tmp_path / "snapshot.last_good.json",
        daily_history_cache_dir=tmp_path / "daily_history",
    )

    result = doctor_data_sources(
        config,
        strategy_name="low_volatility_quality",
        run_live=False,
    )
    payload = result.to_dict()

    assert payload["status"] == "skipped"
    assert payload["strategy_requirements"]["strategy"] == "low_volatility_quality"
    assert payload["strategy_requirements"]["style"]["risk_profile"] == "defensive"
    assert "pb_ratio" in payload["snapshot"]["required_fields"]
    assert "volatility_20d_pct" in payload["daily"]["required_fields"]


def test_doctor_data_sources_reports_all_strategy_coverage_without_live(tmp_path):
    config = Config(
        strategies_dir=Path("strategies"),
        snapshot_source_priority=["sina"],
        daily_source="auto",
        fallback_snapshot_path=tmp_path / "snapshot.last_good.json",
        daily_history_cache_dir=tmp_path / "daily_history",
    )

    result = doctor_data_sources(
        config,
        all_strategies=True,
        run_live=False,
    )
    payload = result.to_dict()
    coverage = {item["strategy"]: item for item in payload["strategy_coverage"]}

    assert payload["status"] == "skipped"
    assert payload["strategy_requirements"]["mode"] == "all"
    assert payload["strategy_requirements"]["strategy_count"] >= 9
    assert "volume_ratio" in payload["snapshot"]["required_fields"]
    assert "volatility_20d_pct" in payload["daily"]["required_fields"]
    assert coverage["low_volatility_quality"]["status"] == "skipped"
    assert coverage["low_volatility_quality"]["style"]["holding_period"] == "swing"
    assert "pb_ratio" in coverage["low_volatility_quality"]["required_snapshot_fields"]
    assert "volatility_20d_pct" in coverage["low_volatility_quality"]["required_daily_fields"]


def test_cli_doctor_data_sources_no_live_json(monkeypatch, tmp_path, capsys):
    output = tmp_path / "doctor.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "alphasift",
            "doctor",
            "data-sources",
            "--no-live",
            "--snapshot-source",
            "sina,efinance",
            "--daily-source",
            "auto",
            "--output",
            str(output),
            "--json",
        ],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "skipped"
    assert payload["snapshot"]["status"] == "skipped"
    assert payload["daily"]["status"] == "skipped"
    assert "health_summary" in payload
    assert payload["config"]["snapshot_source_priority"] == ["sina", "efinance"]
    assert saved["source_health"] == payload["source_health"]
    assert saved["health_summary"] == payload["health_summary"]


def test_cli_doctor_data_sources_strategy_explain(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "alphasift",
            "doctor",
            "data-sources",
            "--strategy",
            "low_volatility_quality",
            "--no-live",
            "--explain",
        ],
    )

    main()

    out = capsys.readouterr().out
    assert "strategy=low_volatility_quality" in out
    assert "snapshot_required=" in out
    assert "pb_ratio" in out
    assert "daily_required=" in out
    assert "volatility_20d_pct" in out
    assert "snapshot_health" in out
    assert "daily_health" in out


def test_cli_doctor_data_sources_all_strategies_explain(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "alphasift",
            "doctor",
            "data-sources",
            "--all-strategies",
            "--no-live",
            "--explain",
        ],
    )

    main()

    out = capsys.readouterr().out
    assert "strategy_scope=all" in out
    assert "strategy_coverage:" in out
    assert "low_volatility_quality status=skipped" in out
    assert "daily_fields=6" in out


def test_cli_doctor_data_sources_unknown_strategy_errors(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "alphasift",
            "doctor",
            "data-sources",
            "--strategy",
            "missing_strategy",
            "--no-live",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "Strategy 'missing_strategy' not found" in err


def test_cli_doctor_data_sources_rejects_strategy_with_all_strategies(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "alphasift",
            "doctor",
            "data-sources",
            "--strategy",
            "dual_low",
            "--all-strategies",
            "--no-live",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "--strategy and --all-strategies cannot be combined" in err
