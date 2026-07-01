from pathlib import Path

import pytest

from alphasift.config import Config
from alphasift.models import EvaluationResult, Pick, PickEvaluation, ScreenResult
from alphasift.store import save_evaluation_result, save_screen_result
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
            degradation=["Snapshot source fallback: sina unavailable"],
            picks=[Pick(rank=1, code="000001", name="平安银行", final_score=80, screen_score=80)],
        ),
        data_dir=tmp_path,
    )
    save_screen_result(
        ScreenResult(
            strategy="volume_breakout",
            market="cn",
            strategy_category="trend",
            run_id="run_needs_eval",
            snapshot_source="sina",
            picks=[Pick(rank=1, code="300001", name="特锐德", final_score=88, screen_score=88)],
        ),
        data_dir=tmp_path,
    )
    save_evaluation_result(
        EvaluationResult(
            run_id="run_strategy_card",
            strategy="dual_low",
            market="cn",
            created_at="2026-04-01T09:30:00",
            evaluated_at="2026-04-02T09:30:00",
            average_return_pct=5.0,
            win_rate=100.0,
            picks=[
                PickEvaluation(
                    code="000001",
                    name="平安银行",
                    rank=1,
                    entry_price=10,
                    current_price=10.5,
                    return_pct=5.0,
                    status="ok",
                    final_score=80,
                )
            ],
        ),
        data_dir=tmp_path,
    )

    payload = build_strategy_cards(_config(tmp_path), runs_limit=10)

    assert payload["schema_version"] == 1
    assert payload["summary"]["strategy_count"] >= 10
    assert payload["summary"]["unchecked_strategy_count"] >= 10
    assert payload["summary"]["history_seeded_strategy_count"] == 2
    assert payload["summary"]["evaluated_strategy_count"] == 1
    assert payload["summary"]["needs_history_count"] >= 8
    assert payload["summary"]["needs_evaluation_count"] == 1
    assert payload["summary"]["performance_leader_count"] == 1
    assert payload["summary"]["operational_attention_count"] == 1
    assert payload["lanes"]["performance_leaders"]["cards"][0]["name"] == "dual_low"
    assert payload["lanes"]["attention"]["cards"][0]["name"] == "dual_low"
    assert payload["lanes"]["needs_evaluation"]["cards"][0]["name"] == "volume_breakout"
    assert any(
        item["name"] == "blue_chip_income"
        for item in payload["lanes"]["needs_history"]["cards"]
    )
    by_name = {item["name"]: item for item in payload["cards"]}

    dual_low = by_name["dual_low"]
    assert dual_low["readiness"]["status"] == "skipped"
    assert dual_low["history"]["run_count"] == 1
    assert dual_low["history"]["latest_run_id"] == "run_strategy_card"
    assert dual_low["history"]["source_error_count"] == 1
    assert dual_low["history"]["source_error_samples"] == ["sina: timeout"]
    assert dual_low["history"]["degradation_samples"] == [
        "Snapshot source fallback: sina unavailable"
    ]
    assert dual_low["performance"]["evaluation_count"] == 1
    assert dual_low["performance"]["average_return_pct"] == 5.0
    assert dual_low["performance"]["outcome"] == "strong"
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
    assert blue_chip["performance"]["evaluation_count"] == 0
    assert "Run `alphasift screen blue_chip_income --save-run` to seed history." in blue_chip["actions"]
    assert "Run `alphasift evaluate <run_id> --save` to seed `blue_chip_income` performance." in blue_chip["actions"]


def test_build_strategy_cards_supports_single_strategy_filter(tmp_path):
    payload = build_strategy_cards(_config(tmp_path), strategy_name="blue_chip_income")

    assert payload["strategy_filter"] == "blue_chip_income"
    assert payload["summary"]["strategy_count"] == 1
    assert [item["name"] for item in payload["cards"]] == ["blue_chip_income"]


def test_build_strategy_cards_rejects_unknown_strategy(tmp_path):
    with pytest.raises(ValueError, match="missing"):
        build_strategy_cards(_config(tmp_path), strategy_name="missing")
