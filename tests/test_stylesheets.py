"""Stylesheets von Karte und Web-App: keine kaputten Stellen."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
APP_CSS = ROOT / "collector" / "ladekrone_collector" / "webapp" / "app.css"
CARD_JS = ROOT / "custom_components" / "ladekrone" / "frontend" / "ladekrone-card.js"


def _card_style() -> str:
    match = re.search(r"const STYLE = `(.*?)`;", CARD_JS.read_text(encoding="utf-8"), re.S)
    assert match, "STYLE der Karte nicht gefunden"
    return match.group(1)


STYLES = {"web-app": APP_CSS.read_text(encoding="utf-8"), "karte": _card_style()}


@pytest.mark.parametrize("css", STYLES.values(), ids=STYLES.keys())
def test_no_literal_escape_between_rules(css: str) -> None:
    # Ein wörtliches „\n“ statt eines Zeilenumbruchs macht in CSS die folgende Regel unwirksam.
    assert "\\n" not in css


@pytest.mark.parametrize("css", STYLES.values(), ids=STYLES.keys())
def test_braces_are_balanced(css: str) -> None:
    assert css.count("{") == css.count("}")
