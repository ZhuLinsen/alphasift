import pytest

from alphasift.config import Config
from alphasift.pipeline import screen


def test_screen_rejects_unknown_market():
    with pytest.raises(ValueError, match="Unsupported market"):
        screen("dual_low", market="xx", config=Config())


@pytest.mark.parametrize("market", ["us", "hk", "jp", "kr", "tw", "in"])
def test_screen_enforces_strategy_market_scope(market):
    # Supported markets pass the market gate, but cn-scoped strategies reject them.
    with pytest.raises(ValueError, match="does not support market"):
        screen("dual_low", market=market, config=Config())
