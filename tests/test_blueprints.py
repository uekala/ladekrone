"""Die mitgelieferten Blueprints müssen Home Assistant als Automationen genügen."""

from __future__ import annotations

from pathlib import Path

import pytest
from homeassistant.components.automation.config import (
    AUTOMATION_BLUEPRINT_SCHEMA,
    async_validate_config_item,
)
from homeassistant.components.blueprint.models import Blueprint, BlueprintInputs
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml_dict

BLUEPRINTS = Path(__file__).parents[1] / "blueprints" / "automation" / "ladekrone"
INPUTS = {
    "preisalarm.yaml": {"price_sensor": "sensor.ladekrone_cheapest_price"},
    "akku_niedrig.yaml": {
        "price_sensor": "sensor.ladekrone_cheapest_price",
        "battery_sensor": "sensor.auto_akku",
    },
}


@pytest.mark.parametrize("name", sorted(INPUTS))
async def test_blueprint_is_valid_automation(hass: HomeAssistant, name: str) -> None:
    assert await async_setup_component(hass, "automation", {})
    blueprint = Blueprint(
        load_yaml_dict(str(BLUEPRINTS / name)),
        expected_domain="automation",
        path=name,
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )
    assert blueprint.metadata["source_url"].endswith(f"/blueprints/automation/ladekrone/{name}")

    inputs = BlueprintInputs(blueprint, {"use_blueprint": {"path": name, "input": INPUTS[name]}})
    inputs.validate()
    config = inputs.async_substitute()
    validated = await async_validate_config_item(hass, f"test_{name}", config)
    assert validated is not None
    assert validated.validation_status == "ok", validated.validation_error


def test_all_blueprints_are_covered() -> None:
    assert sorted(p.name for p in BLUEPRINTS.glob("*.yaml")) == sorted(INPUTS)
