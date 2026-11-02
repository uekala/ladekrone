"""Ladekrone-Karte für Dashboards: liefert die Karte aus und meldet sie im Frontend an."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN

URL_BASE = f"/{DOMAIN}_static"
CARD_FILE = "ladekrone-card.js"
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
    add_extra_js_url(hass, f"{URL_BASE}/{CARD_FILE}?v={integration.version}")
