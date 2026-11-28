"""Tests für den Verlauf: große und ständig wechselnde Attribute bleiben draußen."""

from __future__ import annotations

import pytest
from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.ladekrone.const import DOMAIN

from .conftest import DATA_URL

LOCATION = {"latitude": 50.1101, "longitude": 8.6801, "radius": 10000}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock: Recorder, enable_custom_integrations):
    """Die Datenbank muss vor Home Assistant bereitstehen."""
    return


async def test_offers_and_price_age_are_not_recorded(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    published_data,
) -> None:
    meta, tiles = published_data
    aioclient_mock.get(f"{DATA_URL}/meta.json", json=meta)
    for key, tile in tiles.items():
        aioclient_mock.get(f"{DATA_URL}/tiles/{key}.json", json=tile)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Ladekrone",
        data={"location": LOCATION, "min_power": "0", "current_type": "any", "connector": "any"},
        options={"data_url": DATA_URL},
    )
    entry.add_to_hass(hass)
    start = dt_util.utcnow()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    price = hass.states.get("sensor.ladekrone_cheapest_price")
    # Am Sensor selbst bleibt alles da
    assert "offers" in price.attributes
    assert "price_age_hours" in price.attributes

    await async_wait_recording_done(hass)
    entity_ids = ["sensor.ladekrone_cheapest_price", "sensor.ladekrone_cheapest_price_within_24_h"]
    history = await hass.async_add_executor_job(
        get_significant_states, hass, start, None, entity_ids
    )
    recorded = [state for entity_id in entity_ids for state in history[entity_id]]
    assert recorded
    for state in recorded:
        assert "offers" not in state.attributes
        assert "price_age_hours" not in state.attributes
    best = history["sensor.ladekrone_cheapest_price"][-1]
    assert best.attributes["operator"] == price.attributes["operator"]
    assert best.attributes["price_freshness"] == price.attributes["price_freshness"]
