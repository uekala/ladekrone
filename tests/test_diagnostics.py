"""Tests für die Diagnosedaten."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.ladekrone.const import DOMAIN
from custom_components.ladekrone.diagnostics import async_get_config_entry_diagnostics

from .conftest import DATA_URL

LOCATION = {"latitude": 50.1101, "longitude": 8.6801, "radius": 10000}
MANIFEST = Path(__file__).resolve().parents[1] / "custom_components" / "ladekrone" / "manifest.json"
COLLECTOR_DIAG = {
    "generated": "2026-10-27T03:00:00+00:00",
    "summary": {"sources_total": 4, "sources_loaded": 2},
    "sources": {
        "tesla": {"name": "Tesla Supercharger", "status": "ok", "stations": 3},
        "qwello": {
            "name": "Qwello",
            "status": "ok",
            "stations": 2,
            "dynamic": {"status": "no_prices", "point_status": 12},
        },
        "ladenetz": {"name": "ladenetz.de", "status": "no_subscription"},
        "ionity": {"name": "IONITY", "status": "error", "error": "HTTP 502"},
    },
}


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Ladekrone",
        data={
            "location": LOCATION,
            "min_power": "0",
            "current_type": "any",
            "connector": "any",
            "operators": "",
        },
        options={"data_url": DATA_URL},
    )
    entry.add_to_hass(hass)
    return entry


def _mock_data(aioclient_mock: AiohttpClientMocker, published_data, diag=COLLECTOR_DIAG) -> None:
    meta, tiles = published_data
    aioclient_mock.get(f"{DATA_URL}/meta.json", json=meta)
    for key, tile in tiles.items():
        aioclient_mock.get(f"{DATA_URL}/tiles/{key}.json", json=tile)
    if diag is None:
        aioclient_mock.get(f"{DATA_URL}/diag.json", status=404)
    else:
        aioclient_mock.get(f"{DATA_URL}/diag.json", json=diag)


async def test_diagnostics_show_fetch_state_and_collector_report(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    published_data,
) -> None:
    freezer.move_to(datetime(2026, 10, 27, 11, 0, tzinfo=UTC))
    _mock_data(aioclient_mock, published_data)
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Direkt aufgerufen: Mit eingefrorener Zeit wäre das Zugangs-Token der
    # HTTP-Schnittstelle ungültig. Den Weg über HTTP prüft der nächste Test.
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["version"] == json.loads(MANIFEST.read_text())["version"]
    assert diagnostics["config"]["location"] == "**REDACTED**"
    assert "50.11" not in json.dumps(diagnostics, default=str)
    assert diagnostics["center_source"] == "fixed"
    assert diagnostics["last_update_success"] is True
    assert diagnostics["last_exception"] is None
    assert diagnostics["data_age_hours"] == 8.0

    fetch = diagnostics["fetch"]
    assert fetch["format"] == 1
    assert fetch["last_fetch"] == "2026-10-27T11:00:00+00:00"
    assert fetch["last_fetch_error"] is None
    assert fetch["fetch_interval_hours"] == 6
    assert fetch["tiles_wanted"] >= 1
    assert fetch["tiles_loaded"] == fetch["tiles_wanted"]
    assert fetch["tiles_missing"] == []
    assert fetch["stations_loaded"] > 0

    collector = diagnostics["collector"]
    assert collector["sources_total"] == 4
    assert collector["summary"] == {"sources_total": 4, "sources_loaded": 2}
    assert collector["sources_by_status"] == {
        "error": ["ionity"],
        "no_subscription": ["ladenetz"],
        "ok": ["qwello", "tesla"],
    }
    assert collector["dynamic_by_status"] == {"no_prices": ["qwello"]}
    assert collector["errors"] == {"ionity": "HTTP 502"}


async def test_missing_collector_report_is_named_not_fatal(
    hass: HomeAssistant,
    hass_client,
    aioclient_mock: AiohttpClientMocker,
    published_data,
) -> None:
    _mock_data(aioclient_mock, published_data, diag=None)
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diagnostics["collector"]["error"].startswith("ClientResponseError")
    assert diagnostics["fetch"]["last_fetch_error"] is None
    assert diagnostics["config"]["location"] == "**REDACTED**"


async def test_failed_refetch_is_visible_while_old_data_is_used(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    published_data,
) -> None:
    freezer.move_to(datetime(2026, 10, 27, 11, 0, tzinfo=UTC))
    _mock_data(aioclient_mock, published_data)
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{DATA_URL}/meta.json", status=503)
    aioclient_mock.get(f"{DATA_URL}/diag.json", json=COLLECTOR_DIAG)
    freezer.tick(timedelta(hours=6, minutes=1))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    fetch = diagnostics["fetch"]
    assert fetch["last_fetch"] == "2026-10-27T11:00:00+00:00"
    assert fetch["last_fetch_attempt"] == "2026-10-27T17:01:00+00:00"
    assert fetch["last_fetch_error"].startswith("ClientResponseError")
    assert diagnostics["last_update_success"] is True
    assert diagnostics["offers"] > 0
