from pathlib import Path
import json
import subprocess
import sys
import yaml

import alphasift


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_docker_and_compose_hardening() -> None:
    root = _repo_root()
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    assert "USER alphasift" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "8765" in dockerfile
    assert "API_KEY" not in dockerfile and "SECRET" not in dockerfile

    dockerignore_lines = [ln.strip() for ln in (root / ".dockerignore").read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")]
    assert dockerignore_lines[0] == "*"
    assert "!/alphasift" in dockerignore_lines
    assert "!/pyproject.toml" in dockerignore_lines
    assert "!.env" not in dockerignore_lines
    assert "!/.env" not in dockerignore_lines

    compose = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))
    svc = compose["services"]["alphasift"]
    assert "127.0.0.1:8765:8765" in svc["ports"]
    assert "alphasift_data:/app/data" in svc["volumes"]
    assert "alphasift_data" in compose["volumes"]


def test_community_health_citation_and_ecosystem_docs() -> None:
    root = _repo_root()
    cff = yaml.safe_load((root / "CITATION.cff").read_text(encoding="utf-8"))
    assert str(cff["version"]) == alphasift.__version__
    assert cff["license"] == "Apache-2.0"
    assert cff["repository-code"] == "https://github.com/ZhuLinsen/alphasift"

    for rel in (
        "CONTRIBUTING.md",
        "SECURITY.md",
        ".github/ISSUE_TEMPLATE/bug_report.md",
        ".github/ISSUE_TEMPLATE/strategy_proposal.md",
        ".github/PULL_REQUEST_TEMPLATE.md",
        "docs/ecosystem.md",
    ):
        assert (root / rel).is_file(), f"Missing {rel}"

    eco = (root / "docs" / "ecosystem.md").read_text(encoding="utf-8")
    assert "ZhuLinsen/daily_stock_analysis" in eco
    assert "ZhuLinsen/alphaevo" in eco
    assert "alphasift mcp" in eco


def test_root_and_package_strategy_yamls_are_byte_identical() -> None:
    root = _repo_root()
    root_yamls = {p.name: p.read_bytes() for p in sorted((root / "strategies").glob("*.yaml"))}
    pkg_yamls = {p.name: p.read_bytes() for p in sorted((root / "alphasift" / "strategies").glob("*.yaml"))}
    assert root_yamls and root_yamls.keys() == pkg_yamls.keys()
    for name, payload in root_yamls.items():
        assert payload == pkg_yamls[name], f"YAML parity mismatch in {name}"


def test_skill_mirror_publish_workflow_and_benchmark_smoke() -> None:
    root = _repo_root()
    assert (root / "SKILL.md").read_bytes() == (root / ".github" / "skills" / "alphasift" / "SKILL.md").read_bytes()

    pub = yaml.safe_load((root / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8"))
    trigger = pub[True] if True in pub else pub["on"]
    assert "workflow_dispatch" in trigger
    assert "push" not in trigger
    assert pub["permissions"] == {"contents": "read"}
    assert pub["jobs"]["publish"]["permissions"]["id-token"] == "write"
    assert pub["jobs"]["publish"]["needs"] == "build"

    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / "benchmark_smoke.py"), "--rows", "120", "--json"],
        cwd=str(root),
        text=True,
        capture_output=True,
        timeout=30,
        check=True,
    )
    payload = json.loads(proc.stdout)
    timings = payload["timings_ms"]
    for key in (
        "doctor_no_live_ms",
        "apply_hard_filters_ms",
        "hard_filter_waterfall_ms",
        "compute_screen_scores_ms",
        "summarize_portfolio_exposure_ms",
        "daily_cache_miss_ms",
        "daily_cache_hit_ms",
    ):
        assert timings[key] >= 0.0
    assert payload["cache_checks"]["hit_source"] == "tencent"
    assert payload["cache_checks"]["hit_stale"] is False
    assert payload["cache_checks"]["stale_cache_flagged"] is True


def test_top_level_public_api_exports_and_import_order() -> None:
    import importlib

    all_exports = alphasift.__all__
    assert len(all_exports) == len(set(all_exports))
    assert len(all_exports) == 39
    for sym in all_exports:
        assert getattr(alphasift, sym, None) is not None, f"Missing or None export: {sym}"

    expected_origin = {
        "build_cross_strategy_synthesis": "alphasift.daily_brief",
        "resolve_strategy_display_names": "alphasift.daily_brief",
        "load_daily_report_runs": "alphasift.daily_report",
        "render_daily_im_card": "alphasift.daily_report",
        "write_daily_report_html": "alphasift.daily_report_html",
        "build_markets_digest": "alphasift.market_digest",
        "load_multi_market_runs": "alphasift.market_digest",
        "render_market_digest_im_card": "alphasift.market_digest",
        "MCPServer": "alphasift.mcp",
        "serve_mcp": "alphasift.mcp",
        "load_cn_benchmark": "alphasift.pattern_replay",
        "render_replay_markdown": "alphasift.pattern_replay",
        "replay_patterns": "alphasift.pattern_replay",
    }
    for sym, mod_name in expected_origin.items():
        assert sym in all_exports
        mod = importlib.import_module(mod_name)
        assert getattr(alphasift, sym) is getattr(mod, sym)

    root = _repo_root()
    for code in (
        "import alphasift; assert alphasift.MCPServer is not None",
        "import alphasift.mcp; import alphasift; assert alphasift.MCPServer is alphasift.mcp.MCPServer",
    ):
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(root),
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr


def test_server_json_and_readme_zh_cn_quickstart_contract():
    import json

    root = _repo_root()
    server_path = root / "server.json"
    data = json.loads(server_path.read_text(encoding="utf-8"))
    assert data["name"] == "io.github.ZhuLinsen/alphasift"
    assert data["version"] == alphasift.__version__
    assert data["packages"][0]["registryType"] == "pypi"
    assert data["packages"][0]["identifier"] == "alphasift"
    assert data["packages"][0]["transport"]["type"] == "stdio"

    zh_stub = (root / "README.zh-CN.md").read_text(encoding="utf-8")
    assert "alphasift run " not in zh_stub
    assert "alphasift quickstart" in zh_stub
    assert "<!-- mcp-name: io.github.ZhuLinsen/alphasift -->" in (root / "README.md").read_text(
        encoding="utf-8"
    )

