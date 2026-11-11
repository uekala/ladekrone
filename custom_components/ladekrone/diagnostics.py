"""Diagnosedaten für Ladekrone (Standort wird ausgeblendet)."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util

from . import LadekroneConfigEntry
from .const import CONF_LOCATION, DOMAIN

TO_REDACT = {CONF_LOCATION, "latitude", "longitude", "address"}
DIAG_TIMEOUT = 10


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LadekroneConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    settings = coordinator.settings
    integration = await async_get_integration(hass, DOMAIN)
    generated = data.generated if data else None
    return {
        "version": str(integration.version),
        "config": async_redact_data({**entry.data, **entry.options}, TO_REDACT),
        "radius_km": settings.radius_km,
        "filters": {
            "min_power_kw": settings.filters.min_power_kw,
            "current": settings.filters.current,
            "connector": settings.filters.connector,
            "operators": list(settings.filters.operators),
        },
        "data_url": settings.data_url,
        "center_source": data.center_source if data else None,
        "networks_from_entity": len(data.networks) if data and data.networks is not None else None,
        "last_update_success": coordinator.last_update_success,
        "last_exception": repr(coordinator.last_exception) if coordinator.last_exception else None,
        "generated": generated.isoformat() if generated else None,
        "data_age_hours": (
            round((dt_util.utcnow() - generated).total_seconds() / 3600, 1) if generated else None
        ),
        "fetch": coordinator.diagnostics(),
        "station_count": data.station_count if data else None,
        "offers": len(data.offers) if data else 0,
        "top_offers": async_redact_data(
            [offer.as_dict() for offer in data.offers[:3]] if data else [], TO_REDACT
        ),
        "outlook": data.outlook is not None if data else False,
        "sources": data.sources if data else [],
        "collector": await _async_collector_report(hass, settings.data_url),
    }


async def _async_collector_report(hass: HomeAssistant, data_url: str) -> dict[str, Any]:
    """Stand des Sammlers aus diag.json: welche Quelle warum fehlt.

    Wird nur beim Herunterladen der Diagnosedaten abgerufen. diag.json liegt
    öffentlich neben meta.json und enthält keine Daten aus Home Assistant.
    """
    url = f"{data_url}/diag.json"
    try:
        async with asyncio.timeout(DIAG_TIMEOUT):
            async with async_get_clientsession(hass).get(url) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        return {"error": f"{type(err).__name__}: {err}"}
    if not isinstance(payload, dict):
        return {"error": "diag.json hat ein unerwartetes Format"}

    sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    by_status: dict[str, list[str]] = {}
    dynamic: dict[str, list[str]] = {}
    errors: dict[str, str] = {}
    for key, diag in sorted(sources.items()):
        if not isinstance(diag, dict):
            continue
        by_status.setdefault(str(diag.get("status", "ok")), []).append(key)
        if diag.get("error"):
            errors[key] = str(diag["error"])
        if isinstance(diag.get("dynamic"), dict):
            dyn = diag["dynamic"]
            dynamic.setdefault(str(dyn.get("status", "ok")), []).append(key)
            if dyn.get("error"):
                errors[f"{key} (dynamisch)"] = str(dyn["error"])
    return {
        "generated": payload.get("generated"),
        "summary": payload.get("summary"),
        "sources_total": len(sources),
        "sources_by_status": by_status,
        "dynamic_by_status": dynamic,
        "errors": errors,
    }
