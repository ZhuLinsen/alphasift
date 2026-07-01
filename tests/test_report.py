import json
import sys

from alphasift.cli import main
from alphasift.models import EvaluationResult, Pick, PickEvaluation, ScreenResult
from alphasift.report import (
    build_run_report_payload,
    render_run_report_markdown,
    write_run_report,
)
from alphasift.store import save_screen_result


def _sample_run() -> ScreenResult:
    return ScreenResult(
        strategy="low_volatility_quality",
        market="cn",
        strategy_version="1.0",
        strategy_category="quality",
        snapshot_count=3000,
        after_filter_count=12,
        run_id="run_report",
        llm_ranked=True,
        llm_coverage=0.8,
        degradation=["Daily K-line source health: tushare missing token"],
        snapshot_source="sina",
        source_errors=["akshare: timeout"],
        post_analyzers=["scorecard"],
        daily_enriched=True,
        daily_enrich_count=12,
        created_at="2026-07-01T09:30:00",
        picks=[
            Pick(
                rank=1,
                code="000001",
                name="平安银行",
                final_score=82.34567,
                screen_score=80.0,
                ranking_reason="低波动质量较好",
                price=10.5,
                industry="银行",
                concepts="金融",
                board_heat_score=62.5,
                daily_quality_score=91.2,
                daily_quality_flags="ok",
                daily_source="tencent",
                risk_level="medium",
                risk_flags=["valuation_watch"],
                portfolio_flags=["sector_cap"],
                post_analysis_tags=["value_quality"],
            )
        ],
    )


def test_build_run_report_payload_and_markdown():
    evaluation = EvaluationResult(
        run_id="run_report",
        strategy="low_volatility_quality",
        market="cn",
        created_at="2026-07-01T09:30:00",
        evaluated_at="2026-07-02T09:30:00",
        elapsed_days=1,
        snapshot_source="sina",
        average_return_pct=2.5,
        median_return_pct=2.5,
        win_rate=100.0,
        picks=[
            PickEvaluation(
                rank=1,
                code="000001",
                name="平安银行",
                entry_price=10.0,
                current_price=10.25,
                return_pct=2.5,
                status="ok",
                shape_status="follow_through",
                max_drawdown_pct=-1.0,
                max_runup_pct=3.0,
            )
        ],
    )

    payload = build_run_report_payload(_sample_run(), evaluation=evaluation, max_picks=5)
    markdown = render_run_report_markdown(payload)

    assert payload["schema_version"] == 1
    assert payload["object"] == "RunReport"
    assert payload["run"]["strategy"] == "low_volatility_quality"
    assert payload["source_health"]["snapshot_source"] == "sina"
    assert payload["top_picks"][0]["final_score"] == 82.3457
    assert payload["evaluation"]["average_return_pct"] == 2.5
    assert "# AlphaSift Run Report" in markdown
    assert "low_volatility_quality" in markdown
    assert "valuation_watch" in markdown
    assert "## Evaluation" in markdown


def test_write_run_report_markdown_and_json(tmp_path):
    payload = build_run_report_payload(_sample_run(), max_picks=1)
    markdown_path = tmp_path / "report.md"
    json_path = tmp_path / "report.json"

    write_run_report(markdown_path, payload)
    write_run_report(json_path, payload, json_output=True)

    assert markdown_path.read_text(encoding="utf-8").startswith("# AlphaSift Run Report")
    saved = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved["run"]["run_id"] == "run_report"


def test_cli_report_outputs_json_from_saved_run(monkeypatch, tmp_path, capsys):
    save_screen_result(_sample_run(), data_dir=tmp_path)
    monkeypatch.setenv("ALPHASIFT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["alphasift", "report", "run_report", "--json"])

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["object"] == "RunReport"
    assert payload["run"]["run_id"] == "run_report"
    assert payload["top_picks"][0]["code"] == "000001"


def test_cli_report_writes_markdown(monkeypatch, tmp_path):
    save_screen_result(_sample_run(), data_dir=tmp_path)
    output = tmp_path / "report.md"
    monkeypatch.setenv("ALPHASIFT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        sys,
        "argv",
        ["alphasift", "report", "run_report", "--output", str(output)],
    )

    main()

    text = output.read_text(encoding="utf-8")
    assert "# AlphaSift Run Report" in text
    assert "平安银行" in text


def test_cli_report_unknown_run_errors(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ALPHASIFT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["alphasift", "report", "missing_run", "--json"])

    try:
        main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("report should exit for missing run")

    assert "Saved run not found: missing_run" in capsys.readouterr().err
