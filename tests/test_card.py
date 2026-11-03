"""Tests für die Ladekrone-Karte (Auslieferung und Anmeldung im Frontend)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, Mock

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.core import HomeAssistant

from custom_components.ladekrone.card import CARD_FILE, FRONTEND_DIR, URL_BASE, async_register_card


def test_card_files_are_shipped() -> None:
    assert (FRONTEND_DIR / CARD_FILE).is_file()
    for font in ("atkinson-400.woff2", "atkinson-700.woff2", "bricolage.woff2"):
        assert (FRONTEND_DIR / "fonts" / font).is_file()
    # Die Karte lädt die Schriften relativ zu ihrer eigenen Adresse.
    script = (FRONTEND_DIR / CARD_FILE).read_text(encoding="utf-8")
    assert 'registry.define("ladekrone-card"' in script
    # Erst nach dem Start von HA anmelden, sonst landet die Karte in einer Registry,
    # die HA beim Start ersetzt.
    assert "whenDefined(host.localName)" in script
    assert "fonts/bricolage.woff2" in script


async def test_card_registered_with_version(hass: HomeAssistant) -> None:
    urls: set[str] = set()
    hass.data[DATA_EXTRA_MODULE_URL] = urls
    hass.config.components.add("frontend")
    hass.http = Mock(async_register_static_paths=AsyncMock())
    try:
        await async_register_card(hass)
    finally:
        http, hass.http = hass.http, None

    (paths,), _ = http.async_register_static_paths.call_args
    assert paths[0].url_path == URL_BASE
    assert paths[0].path == str(FRONTEND_DIR)
    manifest = FRONTEND_DIR.parent / "manifest.json"
    version = json.loads(manifest.read_text(encoding="utf-8"))["version"]
    assert urls == {f"{URL_BASE}/{CARD_FILE}?v={version}"}


async def test_card_skipped_without_frontend(hass: HomeAssistant) -> None:
    hass.http = None
    await async_register_card(hass)
    assert DATA_EXTRA_MODULE_URL not in hass.data
