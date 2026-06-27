import json
import sys

from alphasift.cli import _append_industry_cache_history, _write_industry_cache_metadata, main
from alphasift.hotspot import (
    HotspotDetail,
    HotspotRouteItem,
    HotspotStock,
    HotspotSummary,
    TimelineEvent,
    save_hotspots_json,
)


def test_write_industry_cache_metadata_supports_output_without_suffix(tmp_path):
    output = tmp_path / "industry_map"

    metadata_path = _write_industry_cache_metadata(
        output,
        provider="akshare",
        max_boards=3,
        rows=12,
        notes=["ok"],
        generated_at="2026-04-28T10:00:00",
        history_path=tmp_path / "industry_map.history.jsonl",
    )

    data = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata_path.name == "industry_map.meta.json"
    assert data["provider"] == "akshare"
    assert data["max_boards"] == 3
    assert data["rows"] == 12
    assert data["history_path"].endswith("industry_map.history.jsonl")


def test_append_industry_cache_history_groups_board_summaries(tmp_path):
    output = tmp_path / "industry_map.csv"

    history_path = _append_industry_cache_history(
        output,
        mapping={
            "000001": {"board_heat_summary": "银行:+1.20%:rank=3", "board_heat_score": 72.5},
            "600000": {"board_heat_summary": "银行:+1.20%:rank=3", "board_heat_score": 70.0},
            "000002": {"board_heat_summary": "地产:+0.50%:rank=8", "board_heat_score": 55.0},
        },
        generated_at="2026-04-28T10:00:00",
    )

    rows = [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_board = {row["board"]: row for row in rows}
    assert history_path.name == "industry_map.csv.history.jsonl"
    assert by_board["银行"]["code_count"] == 2
    assert by_board["银行"]["max_board_heat_score"] == 72.5
    assert by_board["地产"]["code_count"] == 1


def test_cli_hotspots_provider_none_explain_does_not_call_network(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["alphasift", "hotspots", "--provider", "none", "--explain"])

    main()

    out = capsys.readouterr().out
    assert "hotspots=0 provider=none" in out


def test_cli_hotspots_explain_shows_fallback_and_source_errors(monkeypatch, tmp_path, capsys):
    cache = tmp_path / "hotspots.json"
    save_hotspots_json(
        cache,
        [HotspotSummary(topic="AI算力", source="concept", rank=1, heat_score=82, leaders=["算力龙头"])],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "alphasift",
            "hotspots",
            "--provider",
            "unknown,none",
            "--fallback-cache",
            str(cache),
            "--explain",
        ],
    )

    main()

    out = capsys.readouterr().out
    assert "fallback=True" in out
    assert "source_errors=" in out
    assert "unknown provider" in out


def test_cli_hotspot_explain_formats_detail(monkeypatch, capsys):
    def fake_detail(topic, **kwargs):
        assert topic == "AI算力"
        assert kwargs["top_stocks"] == 1
        return HotspotDetail(
            summary=HotspotSummary(
                topic=topic,
                source="concept",
                rank=1,
                heat_score=82,
                stage="加速主升",
                sample_stock_count=1,
                leaders=["算力龙头"],
                provider_used="last_good_cache",
                fallback_used=True,
                stale=True,
                source_errors=["akshare: disconnected"],
            ),
            stocks=[
                HotspotStock(
                    code="300001",
                    name="算力龙头",
                    role="核心龙头",
                    hot_stock_score=95,
                    change_pct=10,
                )
            ],
            timeline=[
                TimelineEvent(
                    date="2026-06-05",
                    source="公告",
                    title="订单落地",
                    event_type="order",
                    impact_score=8,
                    related_codes=["300001"],
                )
            ],
            route=[
                HotspotRouteItem(
                    date="2026-06-05",
                    source="notice",
                    title="Order catalyst",
                    description="short catalyst summary",
                    event_type="order",
                    impact_score=8,
                )
            ],
        )

    monkeypatch.setattr("alphasift.cli.get_hotspot_detail", fake_detail)
    monkeypatch.setattr(
        sys,
        "argv",
        ["alphasift", "hotspot", "AI算力", "--top-stocks", "1", "--timeline", "--explain"],
    )

    main()

    out = capsys.readouterr().out
    assert "topic=AI算力" in out
    assert "核心龙头" in out
    assert "订单落地" in out
    assert "Order catalyst" in out
    assert "short catalyst summary" in out
    assert "fallback=True" in out
    assert "source_errors=akshare: disconnected" in out


def test_cli_hotspot_cache_writes_json_history_and_metadata(monkeypatch, tmp_path, capsys):
    output = tmp_path / "hotspots.json"
    history = tmp_path / "hotspot.history.jsonl"

    def fake_discover(**kwargs):
        assert kwargs["provider"] == "none"
        return [
            HotspotSummary(
                topic="AI算力",
                source="concept",
                rank=1,
                heat_score=80,
                leaders=["算力龙头"],
            )
        ]

    monkeypatch.setattr("alphasift.cli.discover_hotspots", fake_discover)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "alphasift",
            "hotspot-cache",
            "--provider",
            "none",
            "--output",
            str(output),
            "--history-path",
            str(history),
            "--explain",
        ],
    )

    main()

    assert "rows=1" in capsys.readouterr().out
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert payload["hotspots"][0]["topic"] == "AI算力"
    history_rows = [
        json.loads(line)
        for line in history.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert history_rows[0]["board"] == "AI算力"
    assert history_rows[0]["max_board_heat_score"] == 80
    metadata = json.loads((tmp_path / "hotspots.json.meta.json").read_text(encoding="utf-8"))
    assert metadata["schema_version"] == 2
    assert metadata["history_path"] == str(history)


def test_cli_hotspot_cache_does_not_overwrite_non_empty_cache_with_empty_provider(
    monkeypatch,
    tmp_path,
    capsys,
):
    output = tmp_path / "hotspots.json"
    history = tmp_path / "hotspot.history.jsonl"
    save_hotspots_json(
        output,
        [HotspotSummary(topic="AI算力", source="concept", rank=1, heat_score=82, leaders=["算力龙头"])],
    )
    original_cache = output.read_text(encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "alphasift",
            "hotspot-cache",
            "--provider",
            "none",
            "--output",
            str(output),
            "--history-path",
            str(history),
            "--explain",
        ],
    )

    main()

    out = capsys.readouterr().out
    assert "fallback=True" in out
    assert output.read_text(encoding="utf-8") == original_cache
    assert not history.exists()
    metadata = json.loads((tmp_path / "hotspots.json.meta.json").read_text(encoding="utf-8"))
    assert metadata["fallback_used"] is True
    assert metadata["history_appended"] is False
    assert metadata["rows"] == 1


def test_cli_doctor_dsa_readiness_missing_url_writes_json(monkeypatch, tmp_path, capsys):
    output = tmp_path / "dsa-readiness.json"
    monkeypatch.delenv("DSA_API_URL", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["alphasift", "doctor", "dsa-readiness", "--json", "--output", str(output)],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    written = json.loads(output.read_text(encoding="utf-8"))
    assert payload["available"] is False
    assert payload["status"] == "missing_url"
    assert written == payload


def test_cli_doctor_dsa_readiness_explain_uses_configured_url(monkeypatch, capsys):
    def fake_get(url, timeout):
        class FakeResponse:
            status_code = 405
            text = ""

        assert url == "http://localhost:8000/api/v1/analysis/analyze"
        assert timeout == 1.0
        return FakeResponse()

    monkeypatch.setattr("alphasift.dsa.requests.get", fake_get)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "alphasift",
            "doctor",
            "dsa-readiness",
            "--api-url",
            "http://localhost:8000",
            "--timeout-sec",
            "1",
            "--explain",
        ],
    )

    main()

    out = capsys.readouterr().out
    assert "dsa status=route_present available=True" in out
    assert "http://localhost:8000/api/v1/analysis/analyze" in out
