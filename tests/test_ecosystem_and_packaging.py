from pathlib import Path
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
