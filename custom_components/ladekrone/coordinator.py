"""Datenabruf und Auswertung für Ladekrone."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CONNECTOR,
    CONF_CURRENT,
    CONF_DATA_URL,
    CONF_LOCATION,
    CONF_LOCATION_ENTITY,
    CONF_MIN_POWER,
    CONF_OPERATORS,
    CONF_OPERATORS_ENTITY,
    CONF_TARIFF,
    DEFAULT_DATA_URL,
    DEFAULT_RADIUS_M,
    DOMAIN,
    FETCH_INTERVAL,
    MAX_CACHED_TILES,
    MOVE_THRESHOLD_KM,
    REQUEST_TIMEOUT,
    SUPPORTED_FORMAT,
    TOP_OFFERS,
    UPDATE_INTERVAL,
)
from .pricing import (
    Filters,
    Offer,
    Outlook,
    annotate_changes,
    cheapest_ahead,
    count_stations,
    distance_km,
    find_offers,
    future_steps,
    stations_in_radius,
    tiles_for_radius,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class SearchSettings:
    """Aufbereitete Einstellungen eines Eintrags."""

    latitude: float
    longitude: float
    radius_km: float
    filters: Filters
    data_url: str
    location_entity: str | None = None
    operators_entity: str | None = None

    @classmethod
    def from_entry(cls, entry: ConfigEntry) -> SearchSettings:
        config: dict[str, Any] = {**entry.data, **entry.options}
        location = config.get(CONF_LOCATION) or {}
        operators = tuple(
            part.strip()
            for part in str(config.get(CONF_OPERATORS) or "").split(",")
            if part.strip()
        )
        operators_entity = config.get(CONF_OPERATORS_ENTITY) or None
        return cls(
            latitude=float(location["latitude"]),
            longitude=float(location["longitude"]),
            radius_km=float(location.get("radius", DEFAULT_RADIUS_M)) / 1000,
            filters=Filters(
                min_power_kw=float(config.get(CONF_MIN_POWER) or 0),
                current=config.get(CONF_CURRENT) or "any",
                connector=config.get(CONF_CONNECTOR) or "any",
                operators=operators,
                only_listed=operators_entity is not None,
                tariff=config.get(CONF_TARIFF) or "adhoc",
            ),
            data_url=str(config.get(CONF_DATA_URL) or DEFAULT_DATA_URL).rstrip("/"),
            location_entity=config.get(CONF_LOCATION_ENTITY) or None,
            operators_entity=operators_entity,
        )


def operator_names(state: State | None) -> tuple[str, ...] | None:
    """Ladenetze aus dem Attribut ``operators`` einer Entität.

    Erlaubt sind eine Liste aus Namen oder aus Einträgen mit ``name`` (so liefert es
    z. B. Ladecockpit) und ein kommagetrennter Text. None heißt: gerade nichts
    Verwertbares, die zuletzt bekannte Liste gilt weiter.
    """
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    raw = state.attributes.get("operators")
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, (list, tuple)):
        return None
    names: list[str] = []
    for item in raw:
        name = item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return tuple(dict.fromkeys(names))


@dataclass
class LadekroneData:
    """Ergebnis einer Auswertung."""

    offers: list[Offer]
    station_count: int
    generated: datetime | None
    attribution: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    outlook: Outlook | None = None
    center: tuple[float, float] | None = None
    center_source: str | None = None
    networks: tuple[str, ...] | None = None


def evaluate(
    stations: list[dict], settings: SearchSettings, now: datetime, with_outlook: bool = True
) -> tuple[list[Offer], int, Outlook | None]:
    """Preise jetzt und (optional) für die nächsten 24 Stunden (läuft im Executor)."""
    lat, lon, filters = settings.latitude, settings.longitude, settings.filters
    nearby = stations_in_radius(stations, lat, lon, settings.radius_km)
    offers = find_offers(nearby, lat, lon, settings.radius_km, filters, now)
    steps = future_steps(now)
    by_id = {station["id"]: station for station in nearby if "id" in station}
    annotate_changes(offers[:TOP_OFFERS], by_id, lat, lon, filters, steps)
    outlook = None
    if with_outlook:
        current = offers[0] if offers else None
        outlook = cheapest_ahead(nearby, current, lat, lon, filters, now, steps)
    count = count_stations(nearby, lat, lon, settings.radius_km, filters)
    return offers, count, outlook


class LadekroneCoordinator(DataUpdateCoordinator[LadekroneData]):
    """Lädt die Kacheln selten neu und wertet die Preise alle paar Minuten aus,
    damit tageszeitabhängige Preise (z. B. Tesla-Nachttarif) rechtzeitig wechseln."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.settings = SearchSettings.from_entry(entry)
        self._session = async_get_clientsession(hass)
        self._meta: dict[str, Any] | None = None
        self._tiles: dict[str, list[dict]] = {}
        self._etags: dict[str, str] = {}
        self._last_fetch: datetime | None = None
        self._outlook_key: tuple | None = None
        self._outlook: Outlook | None = None
        # Ladenetze aus einer Entität; gemerkt, damit sie einen Neustart überstehen,
        # auch wenn die Entität erst später wieder einen Wert hat.
        self._entity_operators: tuple[str, ...] = ()
        self._operators_store: Store[dict[str, Any]] = Store(
            hass, 1, f"{DOMAIN}.{entry.entry_id}.operators"
        )

    async def async_load_operators(self) -> None:
        """Zuletzt bekannte Ladenetze der Entität laden."""
        if not self.settings.operators_entity:
            return
        stored = await self._operators_store.async_load() or {}
        names = stored.get("operators")
        if isinstance(names, list):
            self._entity_operators = tuple(str(name) for name in names)
        self._refresh_entity_operators()

    def _refresh_entity_operators(self) -> bool:
        """Liste aus der Entität übernehmen; True, wenn sie sich geändert hat."""
        entity_id = self.settings.operators_entity
        if not entity_id:
            return False
        names = operator_names(self.hass.states.get(entity_id))
        if names is None or names == self._entity_operators:
            return False
        self._entity_operators = names
        self._operators_store.async_delay_save(
            lambda: {"operators": list(self._entity_operators)}, 1
        )
        return True

    def operators_changed(self) -> bool:
        """Für den Listener: hat die Entität eine neue Liste?"""
        return self._refresh_entity_operators()

    @property
    def entity_operators(self) -> tuple[str, ...]:
        return self._entity_operators

    def _current_filters(self) -> Filters:
        filters = self.settings.filters
        if not self.settings.operators_entity:
            return filters
        self._refresh_entity_operators()
        return replace(filters, networks=self._entity_operators)

    def center(self) -> tuple[float, float, str]:
        """Mittelpunkt der Suche: Standort-Entität, sonst der feste Ort."""
        settings = self.settings
        if settings.location_entity and (state := self.hass.states.get(settings.location_entity)):
            lat = state.attributes.get("latitude")
            lon = state.attributes.get("longitude")
            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                return float(lat), float(lon), settings.location_entity
        return settings.latitude, settings.longitude, "fixed"

    def moved_far(self) -> bool:
        """True, wenn sich der Mittelpunkt seit der letzten Auswertung merklich bewegt hat."""
        if self.data is None or self.data.center is None:
            return True
        lat, lon, source = self.center()
        if source != self.data.center_source:
            return True
        return distance_km(lat, lon, *self.data.center) >= MOVE_THRESHOLD_KM

    async def _async_update_data(self) -> LadekroneData:
        now = dt_util.utcnow()
        lat, lon, center_source = self.center()
        if self._last_fetch is None or now - self._last_fetch >= FETCH_INTERVAL:
            try:
                await self._async_fetch(lat, lon)
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                if self._meta is None:
                    raise UpdateFailed(f"Ladepreise nicht abrufbar: {err}") from err
                _LOGGER.warning("Abruf fehlgeschlagen, nutze vorhandene Daten: %s", err)
            else:
                self._last_fetch = now
        else:
            try:
                await self._async_fetch_missing(lat, lon)
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                _LOGGER.warning("Kacheln für den neuen Standort nicht abrufbar: %s", err)

        stations = [station for tile in self._tiles.values() for station in tile]
        # Die 24-Stunden-Vorschau ändert sich nur zur nächsten Viertelstunde oder
        # mit neuen Daten; dazwischen wird sie nicht neu berechnet.
        settings = replace(
            self.settings, latitude=lat, longitude=lon, filters=self._current_filters()
        )
        outlook_key = (future_steps(now)[0], self._last_fetch, settings, len(self._tiles))
        fresh = outlook_key != self._outlook_key
        offers, count, outlook = await self.hass.async_add_executor_job(
            evaluate, stations, settings, now, fresh
        )
        if fresh:
            self._outlook_key, self._outlook = outlook_key, outlook
        outlook = self._outlook
        meta = self._meta or {}
        return LadekroneData(
            offers=offers,
            station_count=count,
            generated=dt_util.parse_datetime(meta.get("generated") or ""),
            attribution=_attribution(meta),
            sources=list(meta.get("sources") or []),
            outlook=outlook,
            center=(lat, lon),
            center_source=center_source,
            networks=settings.filters.networks if settings.operators_entity else None,
        )

    def _wanted_tiles(self, lat: float, lon: float, meta: dict[str, Any]) -> list[str]:
        available = set(meta.get("tiles") or [])
        return [
            key
            for key in tiles_for_radius(
                lat, lon, self.settings.radius_km, float(meta.get("tile_deg", 0.25))
            )
            if key in available
        ]

    async def _async_fetch_missing(self, lat: float, lon: float) -> None:
        """Lädt nur die Kacheln nach, die für einen neuen Standort fehlen."""
        if self._meta is None:
            return
        missing = [k for k in self._wanted_tiles(lat, lon, self._meta) if k not in self._tiles]
        if not missing:
            return
        url = self.settings.data_url
        results = await asyncio.gather(
            *(self._async_get_json(f"{url}/tiles/{key}.json", key) for key in missing)
        )
        for key, payload in zip(missing, results, strict=True):
            self._tiles[key] = list((payload or {}).get("stations") or [])
        if len(self._tiles) > MAX_CACHED_TILES:
            keep = set(self._wanted_tiles(lat, lon, self._meta))
            for key in [k for k in self._tiles if k not in keep]:
                self._tiles.pop(key, None)
                self._etags.pop(key, None)

    async def _async_fetch(self, lat: float, lon: float) -> None:
        settings = self.settings
        meta = await self._async_get_json(f"{settings.data_url}/meta.json", "meta")
        if meta is None:
            if self._meta is None:
                raise ValueError("meta.json nicht verfügbar")
            meta = self._meta
        if int(meta.get("v", 0)) != SUPPORTED_FORMAT:
            raise ValueError(f"Datenformat v{meta.get('v')} wird nicht unterstützt")

        wanted = self._wanted_tiles(lat, lon, meta)
        results = await asyncio.gather(
            *(self._async_get_json(f"{settings.data_url}/tiles/{key}.json", key) for key in wanted)
        )
        tiles: dict[str, list[dict]] = {}
        for key, payload in zip(wanted, results, strict=True):
            if payload is None:
                tiles[key] = self._tiles.get(key, [])
            else:
                tiles[key] = list(payload.get("stations") or [])
        self._meta = meta
        self._tiles = tiles

    async def _async_get_json(self, url: str, cache_key: str) -> dict[str, Any] | None:
        """Lädt JSON; None bedeutet 'unverändert' (304) bzw. Kachel fehlt (404)."""
        headers = {}
        if etag := self._etags.get(cache_key):
            headers["If-None-Match"] = etag
        async with asyncio.timeout(REQUEST_TIMEOUT):
            async with self._session.get(url, headers=headers) as response:
                if response.status == 304:
                    return None
                if response.status == 404 and cache_key != "meta":
                    self._etags.pop(cache_key, None)
                    return {"stations": []}
                response.raise_for_status()
                payload = await response.json(content_type=None)
                if etag := response.headers.get("ETag"):
                    self._etags[cache_key] = etag
        if not isinstance(payload, dict):
            raise ValueError(f"Unerwartete Antwort von {url}")
        return payload


def _attribution(meta: dict[str, Any]) -> str:
    parts = [
        f"{source.get('attribution') or source.get('name')} ({source.get('license')})"
        for source in meta.get("sources") or []
        if source.get("stations")
    ]
    text = "Daten: Mobilithek / AFIR-Angebote der Betreiber"
    return f"{text}: {', '.join(parts)}" if parts else text
