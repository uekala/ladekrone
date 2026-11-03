"""Bundesland zu einer Koordinate, für Tarife mit Feiertagsregeln.

Die Grenzen stammen aus Natural Earth (Admin 1, 1:10 Mio., gemeinfrei) und sind
auf etwa 300 m vereinfacht. Für Stationen direkt an einer Landesgrenze kann das
Ergebnis deshalb danebenliegen; für die Feiertage reicht die Genauigkeit.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

DATA_FILE = Path(__file__).with_name("data") / "bundeslaender.json"
NEAR_DEG = 0.03  # etwa 3 km

# Stadtstaaten zuerst: Bremen liegt in einem Loch von Niedersachsen, Berlin in
# einem von Brandenburg. Die Löcher sind in den Daten nicht enthalten.
CHECK_FIRST = ("BE", "HB", "HH")

# ISO 3166-2 (zweiter Teil) und NUTS-1 der Bundesländer
STATES = (
    "BW", "BY", "BE", "BB", "HB", "HH", "HE", "MV", "NI", "NW", "RP", "SL", "SN", "ST", "SH", "TH",
)  # fmt: skip
NUTS1 = {
    "DE1": "BW",
    "DE2": "BY",
    "DE3": "BE",
    "DE4": "BB",
    "DE5": "HB",
    "DE6": "HH",
    "DE7": "HE",
    "DE8": "MV",
    "DE9": "NI",
    "DEA": "NW",
    "DEB": "RP",
    "DEC": "SL",
    "DED": "SN",
    "DEE": "ST",
    "DEF": "SH",
    "DEG": "TH",
}
NAMES = {
    "baden-württemberg": "BW",
    "bayern": "BY",
    "bavaria": "BY",
    "berlin": "BE",
    "brandenburg": "BB",
    "bremen": "HB",
    "hamburg": "HH",
    "hessen": "HE",
    "hesse": "HE",
    "mecklenburg-vorpommern": "MV",
    "niedersachsen": "NI",
    "lower saxony": "NI",
    "nordrhein-westfalen": "NW",
    "north rhine-westphalia": "NW",
    "rheinland-pfalz": "RP",
    "rhineland-palatinate": "RP",
    "saarland": "SL",
    "sachsen": "SN",
    "saxony": "SN",
    "sachsen-anhalt": "ST",
    "saxony-anhalt": "ST",
    "schleswig-holstein": "SH",
    "thüringen": "TH",
    "thuringia": "TH",
}

Ring = tuple[tuple[float, float], ...]


@lru_cache(maxsize=1)
def _polygons() -> list[tuple[str, tuple[float, float, float, float], Ring]]:
    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    order = [*CHECK_FIRST, *(code for code in raw if code not in CHECK_FIRST)]
    result = []
    for code in order:
        for flat in raw.get(code, []):
            ring = tuple(zip(flat[0::2], flat[1::2], strict=True))
            lons = [p[0] for p in ring]
            lats = [p[1] for p in ring]
            result.append((code, (min(lons), min(lats), max(lons), max(lats)), ring))
    return result


def _inside(lon: float, lat: float, ring: Ring) -> bool:
    """Strahlverfahren: Punkt im Polygon."""
    inside = False
    x1, y1 = ring[-1]
    for x2, y2 in ring:
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
        x1, y1 = x2, y2
    return inside


def _edge_distance(lon: float, lat: float, ring: Ring, scale: float) -> float:
    """Kleinster Abstand zum Rand, in Breitengrad (Längengrade mit ``scale`` gestaucht)."""
    best = math.inf
    x0, y0 = lon * scale, lat
    x1, y1 = ring[-1][0] * scale, ring[-1][1]
    for px, py in ring:
        x2, y2 = px * scale, py
        dx, dy = x2 - x1, y2 - y1
        length = dx * dx + dy * dy
        t = 0.0 if length == 0 else max(0.0, min(1.0, ((x0 - x1) * dx + (y0 - y1) * dy) / length))
        best = min(best, math.hypot(x0 - (x1 + t * dx), y0 - (y1 + t * dy)))
        x1, y1 = x2, y2
    return best


def state_at(lat: float, lon: float) -> str | None:
    """Kürzel des Bundeslands (z. B. ``NW``) oder None außerhalb Deutschlands.

    Liegt der Punkt knapp außerhalb aller Flächen (Grenzfluss, Seeufer, kleine
    Insel), zählt das nächste Bundesland bis etwa ``NEAR_DEG`` Entfernung.
    """
    polygons = _polygons()
    for code, (min_lon, min_lat, max_lon, max_lat), ring in polygons:
        if min_lon <= lon <= max_lon and min_lat <= lat <= max_lat and _inside(lon, lat, ring):
            return code
    scale = math.cos(math.radians(lat))
    reach = NEAR_DEG / max(scale, 0.1)
    nearest: tuple[float, str] | None = None
    for code, (min_lon, min_lat, max_lon, max_lat), ring in polygons:
        if not (
            min_lon - reach <= lon <= max_lon + reach
            and min_lat - NEAR_DEG <= lat <= max_lat + NEAR_DEG
        ):
            continue
        distance = _edge_distance(lon, lat, ring, scale)
        if distance <= NEAR_DEG and (nearest is None or distance < nearest[0]):
            nearest = (distance, code)
    return nearest[1] if nearest else None


def state_from_code(value: str | None) -> str | None:
    """Bundesland aus ``DE-NW``, ``NW``, einem NUTS-Code (``DEA``, ``DEA1``) oder dem Namen."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    upper = text.upper()
    if upper.startswith("DE-"):
        upper = upper[3:]
    if upper in STATES:
        return upper
    if upper[:3] in NUTS1:
        return NUTS1[upper[:3]]
    return NAMES.get(text.casefold())
