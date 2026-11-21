from dataclasses import fields
import json
from pathlib import Path
from typing import cast

from alphasift.models import Pick, ScreenResult
from alphasift.result_schema import SCREEN_RESULT_SCHEMA_VERSION, screen_result_schema
from alphasift.store import load_screen_result


def test_screen_result_schema_matches_core_dataclass_fields():
    schema = screen_result_schema()
    top_level_fields = cast(list[str], schema["top_level_fields"])
    pick_schema_fields = cast(list[str], schema["pick_fields"])

    assert schema["schema_version"] == SCREEN_RESULT_SCHEMA_VERSION
    assert "degradation" in top_level_fields
    assert "snapshot_source" in top_level_fields
    assert "source_errors" in top_level_fields
    assert "portfolio_topic_exposure" in top_level_fields
    assert "overconcentrated_topics" in top_level_fields
    assert "replacement_candidates" in top_level_fields
    assert "risk_flags" in pick_schema_fields
    assert "daily_quality_flags" in pick_schema_fields
    assert "post_analysis_status" in pick_schema_fields
    assert "deep_analysis_status" in pick_schema_fields
    assert "topic_alignment_status" in pick_schema_fields
    assert "topic_alignment_role" in pick_schema_fields
    assert "matched_topics" in pick_schema_fields

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
    assert "topic_alignment" in ui_card_fields
    assert "portfolio_exposure" in ui_card_fields
    assert "watch" in ui_card_fields
    assert "post_analysis" in ui_card_fields
    assert "daily_quality_flags" in ui_card_fields["source_health"]
    assert "risk_flags" in ui_card_fields["risk"]
    assert any("does not execute trades" in item for item in non_goals)
    assert any("DSA is optional" in item for item in non_goals)


def test_screen_result_contract_fixture_and_legacy_roundtrip(tmp_path):
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "screen_result_contract.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    schema = screen_result_schema()
    result_data = fixture["result"]

    for field_name in cast(list[str], schema["top_level_fields"]):
        assert field_name in result_data
    for pick_data in result_data["picks"]:
        for field_name in cast(list[str], schema["pick_fields"]):
            assert field_name in pick_data

    # Current fixture loads cleanly through store.load_screen_result
    cur_file = tmp_path / "runs" / "contract01.json"
    cur_file.parent.mkdir(parents=True, exist_ok=True)
    cur_file.write_text(json.dumps(result_data, ensure_ascii=False), encoding="utf-8")
    loaded = load_screen_result(cur_file, data_dir=tmp_path)
    assert loaded.overconcentrated_topics == []
    assert loaded.picks[0].topic_alignment_status == "aligned"
    assert loaded.picks[0].matched_topics == ["白酒"]

    # Legacy pre-P4/P5 payload omitting new fields still loads seamlessly with defaults
    legacy_payload = {
        "strategy": "dual_low",
        "market": "cn",
        "picks": [{"rank": 1, "code": "000001", "name": "平安银行", "final_score": 80.0, "screen_score": 80.0}],
    }
    leg_file = tmp_path / "runs" / "legacy01.json"
    leg_file.write_text(json.dumps(legacy_payload), encoding="utf-8")
    loaded_legacy = load_screen_result(leg_file, data_dir=tmp_path)
    assert loaded_legacy.portfolio_topic_exposure == {}
    assert loaded_legacy.picks[0].topic_alignment_status == ""

    # Live ScreenResult serialization matches schema metadata + positional saved_path backwards-compatible
    from dataclasses import asdict
    import pandas as pd
    from alphasift.config import Config
    from alphasift.pipeline import screen

    pos = ScreenResult(
        "dual_low",
        "cn",
        "1.0",
        "framework",
        10,
        2,
        [],
        "run01",
        "rules",
        False,
        "",
        "",
        "",
        None,
        [],
        [],
        "em",
        [],
        False,
        [],
        False,
        0,
        True,
        True,
        [],
        "/tmp/run01.json",
        "2026-11-21T00:00:00Z",
    )
    assert pos.saved_path == "/tmp/run01.json"
    assert pos.created_at == "2026-11-21T00:00:00Z"
    assert pos.portfolio_topic_exposure == {}

    snap = pd.DataFrame([
        {
            "code": "600519",
            "name": "贵州茅台",
            "price": 1520.0,
            "amount": 2_000_000_000,
            "total_mv": 1_800_000_000_000,
            "pe_ratio": 22.0,
            "pb_ratio": 7.0,
            "change_pct": 1.2,
            "turnover_rate": 0.4,
            "volume_ratio": 1.1,
            "industry": "白酒",
            "concepts": "高股息",
        }
    ])
    live = screen("balanced_alpha", market="cn", max_output=1, use_llm=False, daily_enrich=False, config=Config(data_dir=tmp_path), snapshot_df=snap)
    live_dict = asdict(live)
    for field_name in cast(list[str], schema["top_level_fields"]):
        assert field_name in live_dict
    for pick_dict in live_dict["picks"]:
        for field_name in cast(list[str], schema["pick_fields"]):
            assert field_name in pick_dict
