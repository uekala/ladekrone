"""Teilen-Link und Tarif-Vergleich der Web-App."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).parents[2]
APP_JS = ROOT / "collector" / "ladekrone_collector" / "webapp" / "app.js"
RUNNER = Path(__file__).parent / "webapp_app.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js fehlt")


@pytest.fixture(scope="module")
def result() -> dict:
    run = subprocess.run(
        ["node", str(RUNNER), str(APP_JS)], capture_output=True, text=True, check=True
    )
    return json.loads(run.stdout)


def test_share_url_carries_place_and_filters(result: dict) -> None:
    parts = urlsplit(result["url"])
    assert parts.path == "/ladekrone/app/"
    assert parts.fragment == ""
    query = parse_qs(parts.query)
    assert "alt" not in query
    # Koordinaten auf drei Stellen gerundet (etwa 100 m)
    assert query["lat"] == ["51.335"]
    assert query["lon"] == ["6.567"]
    assert query["ort"] == ["Krefeld & Umgebung"]
    assert query["netz"] == ["Netz A/B"]
    assert (query["r"], query["kw"], query["kwh"]) == (["25"], ["150"], ["40"])


def test_share_url_roundtrip(result: dict) -> None:
    back = result["back"]
    assert back["place"] == {
        "lat": 51.335,
        "lon": 6.567,
        "label": "Krefeld & Umgebung",
        "gps": False,
    }
    assert back["filters"] == {
        "radius": 25,
        "power": 150,
        "operator": "Netz A/B",
        "connector": "ccs",
        "tariff": "subscription",
        "charge": 40,
    }


def test_share_url_omits_defaults_and_own_location_label(result: dict) -> None:
    assert set(parse_qs(urlsplit(result["plain"]).query)) == {"lat", "lon"}
    assert result["defaults"]["place"]["label"] == "Geteilte Suche"
    assert result["defaults"]["filters"]["radius"] == 10


def test_shared_search_is_validated(result: dict) -> None:
    assert result["none"] is None
    assert result["bad"] == [None, None, None]
    hostile = result["hostile"]
    assert hostile["filters"] == {
        "radius": 10,
        "power": 0,
        "operator": "",
        "connector": "any",
        "tariff": "adhoc",
        "charge": 0,
    }
    assert len(hostile["place"]["label"]) == 80


def test_break_even(result: dict) -> None:
    even = result["even"]
    assert even[0] == pytest.approx(9.99 / 0.2)
    assert even[1:] == [None, None, None]


def test_new_data_arrives_without_reload(result: dict) -> None:
    first, early, late, same, offline = result["refresh"]
    assert (first["price"], first["meta"], first["failed"]) == (0.49, 1, 0)
    assert first["tiles"] > 0
    # Innerhalb von 15 Minuten kein neuer Abruf
    assert (early["price"], early["meta"], early["tiles"]) == (0.49, 1, first["tiles"])
    # Danach: neuer Datenstand, die Kacheln werden neu geladen
    assert (late["price"], late["meta"], late["tiles"]) == (0.29, 2, 2 * first["tiles"])
    # Unveränderter Datenstand: meta.json ja, Kacheln nein
    assert (same["price"], same["meta"], same["tiles"]) == (0.29, 3, late["tiles"])
    # Ohne Netz weiter mit dem bisherigen Stand statt Fehler
    assert (offline["price"], offline["failed"], offline["tiles"]) == (0.29, 0, late["tiles"])
