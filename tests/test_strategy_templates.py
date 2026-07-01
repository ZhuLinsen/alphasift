from pathlib import Path

import pytest

from alphasift import get_strategy_template, list_strategy_templates
from alphasift.strategy import load_strategy
from alphasift.strategy_templates import render_strategy_template


def test_list_strategy_templates_returns_lightweight_catalog():
    templates = list_strategy_templates()

    names = [item["name"] for item in templates]
    assert names == [
        "defensive_value_quality",
        "momentum_breakout_daily",
        "oversold_reversal_snapshot",
    ]
    assert all("yaml" not in item for item in templates)
    assert templates[0]["data_requirements"] == ["snapshot"]
    assert templates[1]["style"]["execution_style"] == "breakout"


def test_strategy_template_yaml_can_be_loaded_as_strategy(tmp_path):
    for item in list_strategy_templates():
        payload = get_strategy_template(str(item["name"]))
        path = tmp_path / f"{item['name']}.yaml"
        path.write_text(str(payload["yaml"]), encoding="utf-8")

        strategy = load_strategy(path)

        assert strategy.screening.enabled is True
        assert strategy.display_name
        assert strategy.style.risk_profile == payload["style"]["risk_profile"]
        assert sum(strategy.screening.factor_weights.values()) == pytest.approx(1.0)


def test_daily_breakout_template_exposes_daily_k_dependency(tmp_path):
    yaml_text = render_strategy_template("momentum_breakout_daily")
    path = tmp_path / "momentum_breakout_daily.yaml"
    path.write_text(yaml_text, encoding="utf-8")

    strategy = load_strategy(Path(path))

    assert strategy.name == "my_momentum_breakout"
    assert strategy.screening.hard_filters.require_price_above_ma20 is True
    assert strategy.screening.hard_filters.breakout_20d_pct_min == pytest.approx(-1.0)
    assert "theme_heat" in strategy.screening.factor_weights


def test_get_strategy_template_rejects_unknown_name():
    with pytest.raises(ValueError, match="available: defensive_value_quality"):
        get_strategy_template("missing")
