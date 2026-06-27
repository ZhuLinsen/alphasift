from dataclasses import fields
from typing import cast

from alphasift.models import Pick, ScreenResult
from alphasift.result_schema import SCREEN_RESULT_SCHEMA_VERSION, screen_result_schema


def test_screen_result_schema_matches_core_dataclass_fields():
    schema = screen_result_schema()
    top_level_fields = cast(list[str], schema["top_level_fields"])
    pick_schema_fields = cast(list[str], schema["pick_fields"])

    assert schema["schema_version"] == SCREEN_RESULT_SCHEMA_VERSION
    assert "degradation" in top_level_fields
    assert "snapshot_source" in top_level_fields
    assert "source_errors" in top_level_fields
    assert "risk_flags" in pick_schema_fields
    assert "daily_quality_flags" in pick_schema_fields
    assert "post_analysis_status" in pick_schema_fields
    assert "deep_analysis_status" in pick_schema_fields

    screen_fields = {field.name for field in fields(ScreenResult)}
    pick_fields = {field.name for field in fields(Pick)}
    assert set(top_level_fields).issubset(screen_fields)
    assert set(pick_schema_fields).issubset(pick_fields)


def test_result_schema_declares_ui_card_groups_and_non_goals():
    schema = screen_result_schema()
    ui_card_fields = cast(dict[str, list[str]], schema["ui_card_fields"])
    non_goals = cast(list[str], schema["non_goals"])

    assert "source_health" in ui_card_fields
    assert "risk" in ui_card_fields
    assert "watch" in ui_card_fields
    assert "post_analysis" in ui_card_fields
    assert "daily_quality_flags" in ui_card_fields["source_health"]
    assert "risk_flags" in ui_card_fields["risk"]
    assert any("does not execute trades" in item for item in non_goals)
    assert any("DSA is optional" in item for item in non_goals)
