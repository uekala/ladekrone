"""Tests für die Zuordnung von Koordinaten zu Bundesländern."""

from __future__ import annotations

import pytest

from ladekrone_collector.regions import state_at, state_from_code


@pytest.mark.parametrize(
    ("lat", "lon", "state"),
    [
        (51.333, 6.567, "NW"),  # Krefeld
        (49.993, 8.247, "RP"),  # Mainz
        (50.078, 8.240, "HE"),  # Wiesbaden, gegenüber am Rhein
        (48.398, 9.991, "BW"),  # Ulm
        (48.392, 10.011, "BY"),  # Neu-Ulm
        (53.079, 8.801, "HB"),  # Bremen, liegt in Niedersachsen
        (53.540, 8.581, "HB"),  # Bremerhaven
        (52.520, 13.405, "BE"),  # Berlin, liegt in Brandenburg
        (52.391, 13.064, "BB"),  # Potsdam
        (53.551, 9.994, "HH"),
        (49.487, 8.466, "BW"),  # Mannheim
        (49.477, 8.435, "RP"),  # Ludwigshafen
        (47.660, 9.175, "BW"),  # Konstanz am Seeufer
        (54.182, 7.886, "SH"),  # Helgoland
        (51.153, 14.987, "SN"),  # Görlitz an der Neiße
        (51.340, 12.375, "SN"),  # Leipzig
        (51.483, 11.970, "ST"),  # Halle
        (50.978, 11.029, "TH"),  # Erfurt
        (54.092, 12.099, "MV"),  # Rostock
        (49.234, 6.997, "SL"),  # Saarbrücken
        (48.137, 11.575, "BY"),
        (52.376, 9.732, "NI"),
    ],
)
def test_state_at(lat: float, lon: float, state: str) -> None:
    assert state_at(lat, lon) == state


@pytest.mark.parametrize(("lat", "lon"), [(48.21, 16.37), (52.37, 4.90), (48.86, 2.35)])
def test_outside_germany(lat: float, lon: float) -> None:
    assert state_at(lat, lon) is None


@pytest.mark.parametrize(
    ("value", "state"),
    [
        ("DE-NW", "NW"),
        ("nw", "NW"),
        ("DEA", "NW"),
        ("DEA1", "NW"),
        ("DE2", "BY"),
        ("Nordrhein-Westfalen", "NW"),
        ("Bavaria", "BY"),
        ("DE", None),
        ("", None),
        (None, None),
        ("Wien", None),
    ],
)
def test_state_from_code(value: str | None, state: str | None) -> None:
    assert state_from_code(value) == state
