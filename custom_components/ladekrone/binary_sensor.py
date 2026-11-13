"""Binärsensor „Jetzt günstig“ für Ladekrone."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import LadekroneConfigEntry
from .const import DOMAIN
from .coordinator import LadekroneCoordinator, LadekroneData


def cheap_now(data: LadekroneData, limit: float | None) -> bool | None:
    """Mit Preisgrenze: günstigster Preis liegt darunter oder gleich.

    Ohne Preisgrenze: In den nächsten 24 Stunden wird es nicht günstiger.
    None, wenn es im Suchgebiet gerade keinen Preis gibt.
    """
    if not data.offers:
        return None
    if limit is not None:
        return data.offers[0].price.kwh <= limit + 1e-9
    if data.outlook is None:
        return True
    return data.outlook.start <= dt_util.utcnow()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LadekroneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([LadekroneCheapNow(entry.runtime_data)])


class LadekroneCheapNow(CoordinatorEntity[LadekroneCoordinator], BinarySensorEntity):
    """An, solange sich das Laden im Suchgebiet gerade lohnt."""

    _attr_has_entity_name = True
    _attr_translation_key = "cheap_now"

    def __init__(self, coordinator: LadekroneCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_cheap_now"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Ladekrone",
            model="AFIR-Ad-hoc-Preise (Mobilithek)",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://github.com/uekala/ladekrone",
        )

    @property
    def is_on(self) -> bool | None:
        return cheap_now(self.coordinator.data, self.coordinator.settings.price_limit)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        limit = self.coordinator.settings.price_limit
        attrs: dict[str, Any] = {
            "mode": "price_limit" if limit is not None else "cheapest_in_24h",
            "price_limit": limit,
        }
        if data.offers:
            best = data.offers[0]
            attrs.update(
                price=round(best.price.kwh, 2),
                operator=best.operator,
                address=best.address,
                distance_km=round(best.distance_km, 1),
                latitude=best.latitude,
                longitude=best.longitude,
            )
        return attrs

    @property
    def attribution(self) -> str | None:
        return self.coordinator.data.attribution
