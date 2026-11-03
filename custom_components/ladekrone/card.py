"""Ladekrone-Karte für Dashboards: liefert die Karte aus und meldet sie im Frontend an."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.loader import async_get_integration

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

URL_BASE = f"/{DOMAIN}_static"
CARD_FILE = "ladekrone-card.js"
CARD_PATH = f"{URL_BASE}/{CARD_FILE}"
FRONTEND_DIR = Path(__file__).parent / "frontend"


async def async_register_card(hass: HomeAssistant) -> None:
    """Karte unter /ladekrone_static ausliefern und in jedes Dashboard laden."""
    if hass.http is None or "frontend" not in hass.config.components:
        return
    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(URL_BASE, str(FRONTEND_DIR), True)]
    )
    # Die Version im Pfad sorgt dafür, dass Browser nach einem Update die neue Karte laden.
    url = f"{CARD_PATH}?v={integration.version}"
    add_extra_js_url(hass, url)
    try:
        await async_sync_resource(hass, url)
    except HomeAssistantError as err:
        _LOGGER.warning("Ladekrone-Karte nicht als Dashboard-Ressource eingetragen: %s", err)


async def async_sync_resource(hass: HomeAssistant, url: str) -> None:
    """Karte zusätzlich als Dashboard-Ressource eintragen und die Version aktuell halten.

    Über die Ressourcen lädt ein Dashboard die Karte erst, wenn die Oberfläche steht, wie
    Karten aus HACS. Das hilft Handy-Apps, bei denen das Zusatzmodul allein nicht greift.
    Dashboards im YAML-Modus verwalten ihre Ressourcen selbst und bleiben unberührt.
    """
    data = hass.data.get("lovelace")
    resources: Any = getattr(data, "resources", None)
    if resources is None or getattr(data, "resource_mode", None) != "storage":
        return
    if not getattr(resources, "loaded", True):
        await resources.async_load()
        resources.loaded = True

    ours = [
        item
        for item in resources.async_items()
        if str(item.get("url", "")).split("?", 1)[0] == CARD_PATH
    ]
    if not ours:
        await resources.async_create_item({"res_type": "module", "url": url})
        return
    first, *duplicates = ours
    if first.get("url") != url or first.get("type") != "module":
        await resources.async_update_item(first["id"], {"res_type": "module", "url": url})
    for item in duplicates:
        await resources.async_delete_item(item["id"])
