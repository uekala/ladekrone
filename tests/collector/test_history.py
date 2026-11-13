"""Tests für den Preisverlauf über mehrere Läufe."""

from __future__ import annotations

import json
from argparse import Namespace
from datetime import date
from pathlib import Path

from ladekrone_collector.build import run
from ladekrone_collector.history import (
    empty_state,
    load_state,
    reference_price,
    save_state,
    update,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "afir_static_sample.json"


def _station(sid: str, components: list[dict], **rate) -> dict:
    return {"id": sid, "la": 50.0, "lo": 8.0, "g": [], "r": [{"p": components, **rate}]}


def test_reference_price_is_the_regular_price() -> None:
    night = {"in": [{"t": [["23:00", "07:00"]]}]}
    station = _station(
        "a",
        [
            {"t": "kwh", "v": 0.59},
            {"t": "kwh", "v": 0.39, "w": night},
            {"t": "min", "v": 0.1, "f": 30},
            {"t": "base", "v": 1.0},
        ],
    )
    assert reference_price(station) == 0.59
    # nur Zeitfenster (so meldet Tesla): der Preis außerhalb des günstigen Fensters
    day = {"in": [{"t": [["07:00", "23:00"]]}]}
    windows = [{"t": "kwh", "v": 0.59, "w": day}, {"t": "kwh", "v": 0.39, "w": night}]
    assert reference_price(_station("b", windows)) == 0.59
    assert reference_price(_station("e", [{"t": "min", "v": 0.1}])) is None
    assert reference_price(_station("c", [{"t": "kwh", "v": 0.1}], cur="DKK")) is None
    assert reference_price({"id": "d", "r": []}) is None


def test_history_records_changes_only() -> None:
    state = empty_state()
    station = _station("a", [{"t": "kwh", "v": 0.54}])

    assert update(state, [station], date(2026, 11, 1)) == 0
    assert "h" not in station  # ohne Änderung kein Verlauf
    assert update(state, [station], date(2026, 11, 2)) == 0
    assert state["stations"]["a"]["p"] == [["2026-11-01", 0.54]]

    station = _station("a", [{"t": "kwh", "v": 0.59}])
    assert update(state, [station], date(2026, 11, 3)) == 1
    assert station["h"] == [["2026-11-01", 0.54], ["2026-11-03", 0.59]]


def test_history_keeps_one_change_per_day() -> None:
    state = empty_state()
    update(state, [_station("a", [{"t": "kwh", "v": 0.54}])], date(2026, 11, 1))
    update(state, [_station("a", [{"t": "kwh", "v": 0.59}])], date(2026, 11, 3))
    # zweiter Lauf am selben Tag mit anderem Preis: der Eintrag des Tages wird ersetzt
    station = _station("a", [{"t": "kwh", "v": 0.61}])
    update(state, [station], date(2026, 11, 3))
    assert station["h"] == [["2026-11-01", 0.54], ["2026-11-03", 0.61]]
    # und zurück auf den alten Preis am selben Tag: gar keine Änderung
    station = _station("a", [{"t": "kwh", "v": 0.54}])
    assert update(state, [station], date(2026, 11, 3)) == 0
    assert "h" not in station


def test_history_is_bounded_and_forgets_missing_stations() -> None:
    state = empty_state()
    for day in range(1, 11):
        station = _station("a", [{"t": "kwh", "v": 0.4 + day / 100}])
        update(state, [station], date(2026, 11, day))
    assert len(state["stations"]["a"]["p"]) == 6
    assert len(station["h"]) == 4
    assert station["h"][-1] == ["2026-11-10", 0.5]

    update(state, [_station("b", [{"t": "kwh", "v": 0.5}])], date(2027, 2, 1))
    assert set(state["stations"]) == {"b"}


def test_state_survives_save_and_load(tmp_path: Path) -> None:
    state = empty_state()
    update(state, [_station("a", [{"t": "kwh", "v": 0.54}])], date(2026, 11, 1))
    path = tmp_path / "cache" / "history.json"
    save_state(state, path)
    assert load_state(path) == state
    path.write_text("kaputt", encoding="utf-8")
    assert load_state(path) == empty_state()
    assert load_state(tmp_path / "fehlt.json") == empty_state()


def test_run_carries_history_between_runs(tmp_path: Path) -> None:
    sources = tmp_path / "sources.json"
    sources.write_text(
        json.dumps({"sources": [{"key": "t", "name": "T", "license": "CC0-1.0", "offer": "1"}]}),
        encoding="utf-8",
    )

    def args(source: Path, generated: str) -> Namespace:
        return Namespace(
            sources=str(sources),
            out=str(tmp_path / "public"),
            cache=str(tmp_path / "cache"),
            cert=None,
            key=None,
            subscriptions_env=None,
            input=[f"t={source}"],
            generated=generated,
        )

    def stations() -> list[dict]:
        tiles = (tmp_path / "public" / "v1" / "tiles").glob("*.json")
        return [s for tile in tiles for s in json.loads(tile.read_text("utf-8"))["stations"]]

    assert run(args(FIXTURE, "2026-11-01T02:00:00+00:00")) == 0
    first = stations()
    assert first and not any("h" in s for s in first)
    assert (tmp_path / "cache" / "history.json").is_file()
    assert (tmp_path / "public" / "v1" / "history.json").is_file()

    # Zweiter Lauf: derselbe Datensatz, aber ein Preis von 0,59 ist auf 0,64 gestiegen
    raised = tmp_path / "raised.json"
    text = FIXTURE.read_text(encoding="utf-8")
    assert "0.59" in text
    raised.write_text(text.replace("0.59", "0.64"), encoding="utf-8")
    assert run(args(raised, "2026-11-05T02:00:00+00:00")) == 0
    changed = [s for s in stations() if "h" in s]
    assert changed
    assert all(s["h"][-1][0] == "2026-11-05" for s in changed)
    assert any(s["h"] == [["2026-11-01", 0.59], ["2026-11-05", 0.64]] for s in changed)
