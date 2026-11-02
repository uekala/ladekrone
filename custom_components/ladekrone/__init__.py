"""Ladekrone – günstigste Ad-hoc-Ladepreise in der Umgebung (AFIR/Mobilithek)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.typing import ConfigType

from .card import async_register_card
from .const import DOMAIN
from .coordinator import LadekroneCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type LadekroneConfigEntry = ConfigEntry[LadekroneCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    await async_register_card(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LadekroneConfigEntry) -> bool:
    coordinator = LadekroneCoordinator(hass, entry)
    await coordinator.async_load_operators()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    if operators_entity := coordinator.settings.operators_entity:

        @callback
        def _operators_changed(event: Event[EventStateChangedData]) -> None:
            # Neue Ladenetze in der Liste (z. B. erste MultiPass-Ladung bei EnBW)
            if coordinator.operators_changed():
                hass.async_create_task(coordinator.async_request_refresh())

        entry.async_on_unload(
            async_track_state_change_event(hass, [operators_entity], _operators_changed)
        )

    if entity_id := coordinator.settings.location_entity:

        @callback
        def _location_changed(event: Event[EventStateChangedData]) -> None:
            # Erst neu auswerten, wenn sich der Mittelpunkt merklich bewegt hat
            if coordinator.moved_far():
                hass.async_create_task(coordinator.async_request_refresh())

        entry.async_on_unload(async_track_state_change_event(hass, [entity_id], _location_changed))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LadekroneConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: LadekroneConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
