"""Deutsch und Englisch der Web-App müssen dieselben Texte abdecken."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
WEBAPP = ROOT / "collector" / "ladekrone_collector" / "webapp"
RUNNER = Path(__file__).parent / "webapp_i18n.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js fehlt")


@pytest.fixture(scope="module")
def result() -> dict:
    run = subprocess.run(
        ["node", str(RUNNER), str(WEBAPP / "i18n.js")], capture_output=True, text=True, check=True
    )
    return json.loads(run.stdout)


def test_both_languages_have_the_same_texts(result: dict) -> None:
    assert result["langs"] == ["de", "en"]
    # gleiche Schlüssel, gleiche Art, bei Funktionen gleich viele Argumente
    assert result["de"] == result["en"]


def test_every_text_is_used_and_every_use_exists(result: dict) -> None:
    app = (WEBAPP / "app.js").read_text(encoding="utf-8")
    used = set(re.findall(r"\bT\.([A-Za-z0-9]+)", app))
    assert used - {"page"} == set(result["de"])


def test_english_page_texts_match_the_page(result: dict) -> None:
    html = (WEBAPP / "index.html").read_text(encoding="utf-8")
    page = result["page"]
    for key in page["text"] + page["html"]:
        assert f'data-t="{key}"' in html, key
    for key in page["attrs"]:
        assert f'data-t="{key}"' in html or f'id="{key}"' in html, key
    for select, options in page["options"].items():
        block = html[html.index(f'<select id="{select}"') :]
        block = block[: block.index("</select>")]
        values = re.findall(r'<option value="([^"]*)"', block)
        # f-operator wird zur Laufzeit gefüllt, alle anderen müssen vollständig übersetzt sein
        assert sorted(values) == sorted(options), select
    assert 'id="lang"' in html


def test_language_choice(result: dict) -> None:
    assert result["pick"] == ["de", "de", "en", "en", "de", "de", "de"]


def test_privacy_page_exists_in_both_languages() -> None:
    german = (WEBAPP / "datenschutz.html").read_text(encoding="utf-8")
    english = (WEBAPP / "privacy.html").read_text(encoding="utf-8")
    assert 'href="privacy.html"' in german
    assert 'href="datenschutz.html"' in english
    assert german.count("<h2>") == english.count("<h2>")
    worker = (WEBAPP / "sw.js").read_text(encoding="utf-8")
    for name in ("i18n.js", "privacy.html"):
        assert f'"{name}"' in worker


def test_map_loads_only_on_request() -> None:
    """Kartenbibliothek und Kartendienst dürfen erst nach dem Tippen auf „Karte“ geladen werden."""
    html = (WEBAPP / "index.html").read_text(encoding="utf-8")
    worker = (WEBAPP / "sw.js").read_text(encoding="utf-8")
    for page in (html, worker):
        assert "maplibre" not in page
        assert "openfreemap" not in page
    app = (WEBAPP / "app.js").read_text(encoding="utf-8")
    assert app.count("tiles.openfreemap.org") == 1
    assert app.count("loadMapLibrary()") == 2  # Definition und der Aufruf in updateMap
    for name in ("maplibre-gl.js", "maplibre-gl.css", "maplibre-gl.LICENSE.txt"):
        assert (WEBAPP / "vendor" / name).is_file()
    for name in ("datenschutz.html", "privacy.html"):
        assert "OpenFreeMap" in (WEBAPP / name).read_text(encoding="utf-8")
