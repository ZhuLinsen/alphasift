from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _offline_data_side_effects(monkeypatch):
    """Keep tests offline and out of the repo data dir.

    The pipeline backfills A-share industry labels from EastMoney when a
    snapshot has none, and persists snapshot source health. Tests that need
    either behavior opt back in explicitly.
    """
    import alphasift.industry as industry

    def _no_network_industry_rows():
        raise RuntimeError("network disabled in tests")

    monkeypatch.setattr(industry, "_fetch_eastmoney_industry_rows", _no_network_industry_rows)
    monkeypatch.setenv("ALPHASIFT_SOURCE_HEALTH_PATH", "off")
    monkeypatch.setenv("INDUSTRY_AUTO_BACKFILL", "false")
