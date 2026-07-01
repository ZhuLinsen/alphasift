from pathlib import Path

import pytest

from alphasift.config import Config
from alphasift.models import Pick, ScreenResult
from alphasift.store import save_screen_result
from alphasift.strategy_cards import build_strategy_cards


def _config(tmp_path):
    return Config(
        strategies_dir=Path("strategies"),
        data_dir=tmp_path,
        snapshot_source_priority=["sina"],
        daily_source="auto",
        fallback_snapshot_path=tmp_path / "snapshot.last_good.json",
        daily_history_cache_dir=tmp_path / "daily_history",
    )


def test_build_strategy_cards_joins_catalog_readiness_and_history(tmp_path):
    save_screen_result(
        ScreenResult(
            strategy="dual_low",
            market="cn",
            strategy_category="value",
            run_id="run_strategy_card",
            snapshot_source="sina",
            source_errors=["sina: timeout"],
            picks=[Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80)],
        ),
        data_dir=tmp_path,
    )

    payload = build_strategy_cards(_config(tmp_path), runs_limit=10)

    assert payload["schema_version"] == 1
    assert payload["summary"]["strategy_count"] >= 10
    assert payload["summary"]["unchecked_strategy_count"] >= 10
    by_name = {item["name"]: item for item in payload["cards"]}

    dual_low = by_name["dual_low"]
    assert dual_low["readiness"]["status"] == "skipped"
    assert dual_low["history"]["run_count"] == 1
    assert dual_low["history"]["latest_run_id"] == "run_strategy_card"
    assert dual_low["history"]["source_error_count"] == 1
    assert dual_low["data"]["requirements"] == ["snapshot"]
    assert dual_low["scoring"]["top_factors"][0] == {"name": "value", "weight": 0.34}
    assert (
        "Run `alphasift doctor data-sources --strategy dual_low --explain`."
        in dual_low["actions"]
    )

    blue_chip = by_name["blue_chip_income"]
    assert blue_chip["category"] == "income"
    assert blue_chip["use_case"]["execution_style"] == "income_quality"
    assert blue_chip["data"]["requires_daily_features"] is False
    assert blue_chip["scoring"]["top_factors"][0] == {"name": "value", "weight": 0.30}
    assert blue_chip["history"]["run_count"] == 0
    assert "Run `alphasift screen blue_chip_income --save-run` to seed history." in blue_chip["actions"]


def test_build_strategy_cards_supports_single_strategy_filter(tmp_path):
    payload = build_strategy_cards(_config(tmp_path), strategy_name="blue_chip_income")

    assert payload["strategy_filter"] == "blue_chip_income"
    assert payload["summary"]["strategy_count"] == 1
    assert [item["name"] for item in payload["cards"]] == ["blue_chip_income"]


def test_build_strategy_cards_rejects_unknown_strategy(tmp_path):
    with pytest.raises(ValueError, match="missing"):
        build_strategy_cards(_config(tmp_path), strategy_name="missing")
