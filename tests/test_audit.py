from pathlib import Path

from alphasift.audit import audit_project


def test_audit_reports_profile_coverage_for_builtin_strategies():
    result = audit_project(Path("strategies"))

    assert result["strategy_count"] == 10
    assert result["profile_coverage"]["scoring_profile"]["configured"] == 10
    assert result["profile_coverage"]["risk_profile"]["configured"] == 10
    assert result["profile_coverage"]["portfolio_profile"]["configured"] == 10
    assert result["profile_coverage"]["scorecard_profile"]["configured"] == 10
    assert result["project_gaps"]


def test_audit_flags_trend_strategy_without_daily_validation(tmp_path):
    path = tmp_path / "snapshot_breakout.yaml"
    path.write_text(
        "\n".join([
            "name: snapshot_breakout",
            "display_name: 快照突破",
            "description: demo",
            "category: trend",
            "tags: [breakout]",
            "screening:",
            "  enabled: true",
            "  market_scope: [cn]",
            "  ranking_hints: demo",
            "  hard_filters:",
            "    amount_min: 100000000",
        ]),
        encoding="utf-8",
    )

    result = audit_project(tmp_path)

    assert any(
        item["strategy"] == "snapshot_breakout"
        and item["area"] == "l1_shape_validation"
        for item in result["strategy_findings"]
    )
