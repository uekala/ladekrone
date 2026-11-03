"""Tests für die Ladekrone-Karte (Auslieferung und Anmeldung im Frontend)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, Mock

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.core import HomeAssistant

from custom_components.ladekrone.card import (
    CARD_FILE,
    CARD_PATH,
    FRONTEND_DIR,
    URL_BASE,
    async_register_card,
    async_sync_resource,
)


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


class _Resources:
    """Nachbau der Ressourcen-Sammlung von Lovelace (Speicher-Modus)."""

    def __init__(self, items: list[dict]) -> None:
        self.loaded = False
        self.items = [dict(item) for item in items]

    async def async_load(self) -> None:
        self.loaded = True

    def async_items(self) -> list[dict]:
        return self.items

    async def async_create_item(self, data: dict) -> None:
        self.items.append(
            {"id": f"neu{len(self.items)}", "type": data["res_type"], "url": data["url"]}
        )

    async def async_update_item(self, item_id: str, data: dict) -> None:
        item = next(i for i in self.items if i["id"] == item_id)
        item.update(type=data["res_type"], url=data["url"])

    async def async_delete_item(self, item_id: str) -> None:
        self.items = [i for i in self.items if i["id"] != item_id]


def _lovelace(hass: HomeAssistant, items: list[dict], mode: str = "storage") -> _Resources:
    resources = _Resources(items)
    hass.data["lovelace"] = Mock(resource_mode=mode, resources=resources)
    return resources


OTHER = {"id": "a", "type": "module", "url": "/hacsfiles/button-card/button-card.js"}


async def test_resource_created(hass: HomeAssistant) -> None:
    resources = _lovelace(hass, [OTHER])
    await async_sync_resource(hass, f"{CARD_PATH}?v=1.0.0")
    assert resources.loaded
    assert resources.items == [
        OTHER,
        {"id": "neu1", "type": "module", "url": f"{CARD_PATH}?v=1.0.0"},
    ]


async def test_resource_follows_version_and_drops_duplicates(hass: HomeAssistant) -> None:
    resources = _lovelace(
        hass,
        [
            {"id": "b", "type": "module", "url": f"{CARD_PATH}?v=0.4.2"},
            OTHER,
            {"id": "c", "type": "module", "url": CARD_PATH},
        ],
    )
    await async_sync_resource(hass, f"{CARD_PATH}?v=1.0.0")
    assert resources.items == [{"id": "b", "type": "module", "url": f"{CARD_PATH}?v=1.0.0"}, OTHER]


async def test_resource_left_alone_in_yaml_mode(hass: HomeAssistant) -> None:
    resources = _lovelace(hass, [OTHER], mode="yaml")
    await async_sync_resource(hass, f"{CARD_PATH}?v=1.0.0")
    assert resources.items == [OTHER]


async def test_resource_without_lovelace(hass: HomeAssistant) -> None:
    hass.data.pop("lovelace", None)
    await async_sync_resource(hass, f"{CARD_PATH}?v=1.0.0")
