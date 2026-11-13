"""Preisverlauf: merkt sich über die Läufe hinweg, wann sich ein Preis geändert hat.

Festgehalten wird je Station der reguläre Ad-hoc-Preis je kWh. Bei Tageszeit-Tarifen
ist das der Preis außerhalb der günstigen Fenster, damit der tägliche Wechsel nicht
als Verlauf zählt. Gespeichert werden nur Änderungen, höchstens eine pro Tag.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any

STATE_VERSION = 1
MAX_ENTRIES = 6
PUBLISHED_ENTRIES = 4
FORGET_AFTER = timedelta(days=60)
FETCH_TIMEOUT = 30

_LOGGER = logging.getLogger("ladekrone")


def reference_price(record: dict) -> float | None:
    """Regulärer Ad-hoc-Preis je kWh einer Station oder None.

    Je Tarif zählt der höchste kWh-Preis: Bei Tageszeit-Tarifen ist das der normale
    Preis außerhalb der günstigen Fenster. Über mehrere Tarife gilt der günstigste.
    """
    best: float | None = None
    for rate in record.get("r") or []:
        if rate.get("cur", "EUR") != "EUR":
            continue
        prices = [c["v"] for c in rate.get("p", []) if c.get("t") == "kwh" and not c.get("f")]
        if not prices:
            continue
        price = round(max(prices), 4)
        if best is None or price < best:
            best = price
    return best


def empty_state() -> dict[str, Any]:
    return {"v": STATE_VERSION, "stations": {}}


def _valid(state: Any) -> bool:
    return (
        isinstance(state, dict)
        and state.get("v") == STATE_VERSION
        and isinstance(state.get("stations"), dict)
    )


def load_state(path: Path, fallback_url: str | None = None) -> dict[str, Any]:
    """Lädt den Verlauf aus dem Cache, sonst aus der letzten Veröffentlichung."""
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if _valid(state):
            return state
        _LOGGER.warning("Preisverlauf im Cache unbrauchbar – beginne neu")
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as err:
        _LOGGER.warning("Preisverlauf im Cache nicht lesbar: %s", err)
    if fallback_url and fallback_url.startswith("https://"):
        try:
            with urllib.request.urlopen(fallback_url, timeout=FETCH_TIMEOUT) as response:
                state = json.loads(response.read().decode("utf-8"))
            if _valid(state):
                _LOGGER.info("Preisverlauf aus der letzten Veröffentlichung übernommen")
                return state
        except (OSError, ValueError) as err:
            _LOGGER.warning("Veröffentlichter Preisverlauf nicht abrufbar: %s", err)
    return empty_state()


def update(state: dict[str, Any], stations: list[dict], today: date) -> int:
    """Trägt die heutigen Grundpreise ein und hängt den Verlauf an die Stationen.

    Stationen mit mindestens einer Änderung bekommen ``h``: die letzten Einträge
    ``[Datum, Preis]``, der jüngste zuletzt. Gibt die Zahl der Stationen mit ``h`` zurück.
    """
    known: dict[str, Any] = state["stations"]
    day = today.isoformat()
    with_history = 0
    for record in stations:
        price = reference_price(record)
        if price is None:
            continue
        entry = known.get(record["id"])
        if not isinstance(entry, dict) or not isinstance(entry.get("p"), list) or not entry["p"]:
            entry = known[record["id"]] = {"p": [[day, price]]}
        else:
            points = entry["p"]
            if points[-1][1] != price:
                if points[-1][0] == day:
                    points[-1][1] = price
                    # Zurück beim Preis davor: Das war kein Wechsel.
                    if len(points) > 1 and points[-2][1] == price:
                        points.pop()
                else:
                    points.append([day, price])
                del points[:-MAX_ENTRIES]
        entry["s"] = day
        if len(entry["p"]) > 1:
            record["h"] = [list(point) for point in entry["p"][-PUBLISHED_ENTRIES:]]
            with_history += 1
    limit = (today - FORGET_AFTER).isoformat()
    for station_id in [k for k, v in known.items() if str(v.get("s", "")) < limit]:
        del known[station_id]
    return with_history


def save_state(state: dict[str, Any], *paths: Path) -> None:
    text = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
