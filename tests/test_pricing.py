"""Tests für die Preislogik (Zeitfenster, Filter, Sortierung)."""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import pytest

from custom_components.ladekrone.pricing import (
    LOCAL_TZ,
    Filters,
    charge_cost,
    current_price,
    find_offers,
    merge_sites,
    period_matches,
    tiles_for_radius,
    validity_matches,
)
from ladekrone_collector.build import tile_key
from ladekrone_collector.datex import parse_bytes

FIXTURE = Path(__file__).parent / "fixtures" / "afir_static_sample.json"
HOME = (50.1101, 8.6801)


@pytest.fixture(scope="module")
def stations() -> list[dict]:
    return [record for record, _ in parse_bytes(FIXTURE.read_bytes(), "test")]


def _local(hour: int, minute: int = 0, day: int = 27, month: int = 10) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=LOCAL_TZ)


def _station(stations: list[dict], suffix: str) -> dict:
    return next(s for s in stations if s["id"].endswith(suffix))


@pytest.mark.parametrize(
    ("hour", "expected"),
    [(12, 0.59), (6, 0.39), (7, 0.59), (22, 0.59), (23, 0.39), (2, 0.39)],
)
def test_tesla_time_windows(stations: list[dict], hour: int, expected: float) -> None:
    rate = _station(stations, "ST-SC-1")["r"][0]
    assert current_price(rate, _local(hour)).kwh == expected


def test_windows_use_local_time_not_utc(stations: list[dict]) -> None:
    rate = _station(stations, "ST-SC-1")["r"][0]
    # 22:30 UTC im Oktober (Winterzeit ab 25.10.) = 23:30 Ortszeit -> Nachtpreis
    utc = datetime(2026, 10, 27, 22, 30, tzinfo=UTC)
    assert current_price(rate, utc.astimezone(LOCAL_TZ)).kwh == 0.39
    # Im Sommer (MESZ) ist 21:30 UTC ebenfalls 23:30 Ortszeit
    summer = datetime(2026, 7, 1, 21, 30, tzinfo=UTC)
    assert current_price(rate, summer.astimezone(LOCAL_TZ)).kwh == 0.39


def test_minute_fee_is_reported(stations: list[dict]) -> None:
    price = current_price(_station(stations, "ST-HPC-1")["r"][0], _local(12))
    assert price.kwh == 0.79
    assert price.minute_fee == pytest.approx(0.24, abs=0.001)
    assert price.minute_fee_from == 30


def test_published_contract_is_used_only_when_selected(stations: list[dict]) -> None:
    now = _local(12).astimezone(UTC)
    adhoc = find_offers(stations, *HOME, 10, Filters(operators=("enbw",)), now)
    assert adhoc[0].price.kwh == 0.79
    assert adhoc[0].price.tariff == "adHoc"
    contract = find_offers(
        stations, *HOME, 10, Filters(operators=("enbw",), tariff="contract"), now
    )
    assert contract[0].price.kwh == 0.39
    assert contract[0].price.tariff == "contract"
    # Ohne veröffentlichten Vertragstarif bleibt der Ad-hoc-Preis, gekennzeichnet.
    city = find_offers(
        stations, *HOME, 10, Filters(operators=("stadtwerke",), tariff="contract"), now
    )
    assert city[0].price.kwh == 0.49
    assert city[0].price.tariff == "adHoc"


def test_exception_periods_and_days() -> None:
    weekend_only = {"in": [{"d": [5, 6]}]}
    assert validity_matches(weekend_only, _local(12, day=31))  # Samstag
    assert not validity_matches(weekend_only, _local(12, day=27))  # Dienstag
    not_at_night = {"ex": [{"t": [["20:00", "08:00"]]}]}
    assert validity_matches(not_at_night, _local(12))
    assert not validity_matches(not_at_night, _local(21))
    assert not period_matches({"sp": True}, _local(12))
    expired = {"s": "2025-01-01T00:00:00+01:00", "e": "2025-12-31T23:59:59+01:00"}
    assert not validity_matches(expired, _local(12))


def test_foreign_currency_is_skipped() -> None:
    rate = {"cur": "DKK", "p": [{"t": "kwh", "v": 3.5}]}
    assert current_price(rate, _local(12)) is None


def test_free_charging_counts_as_zero() -> None:
    rate = {"p": [{"t": "free", "v": 0.0}]}
    assert current_price(rate, _local(12)).kwh == 0.0


def test_offers_sorted_by_price_within_radius(stations: list[dict]) -> None:
    now = _local(12).astimezone(UTC)
    offers = find_offers(stations, *HOME, 10, Filters(), now)
    assert [o.operator for o in offers] == ["Stadtwerke Musterstadt", "Tesla", "EnBW mobility+"]
    assert offers[0].price.kwh == 0.49
    assert offers[0].distance_km == pytest.approx(0.65, abs=0.05)


def test_night_changes_the_winner(stations: list[dict]) -> None:
    now = _local(2).astimezone(UTC)
    offers = find_offers(stations, *HOME, 10, Filters(), now)
    assert offers[0].operator == "Tesla"
    assert offers[0].price.kwh == 0.39


@pytest.mark.parametrize(
    ("filters", "operators"),
    [
        (Filters(min_power_kw=50), ["Tesla", "EnBW mobility+"]),
        (Filters(current="ac"), ["Stadtwerke Musterstadt"]),
        (Filters(connector="type2"), ["Stadtwerke Musterstadt"]),
        (Filters(operators=("enbw",)), ["EnBW mobility+"]),
        (Filters(operators=("supercharger",)), ["Tesla"]),
    ],
)
def test_filters(stations: list[dict], filters: Filters, operators: list[str]) -> None:
    now = _local(12).astimezone(UTC)
    assert [o.operator for o in find_offers(stations, *HOME, 10, filters, now)] == operators


def test_large_radius_includes_far_station(stations: list[dict]) -> None:
    now = _local(12).astimezone(UTC)
    offers = find_offers(stations, *HOME, 150, Filters(), now)
    assert offers[0].operator == "Weit Weg AG"


def test_tiles_for_radius_cover_station_tiles() -> None:
    keys = tiles_for_radius(*HOME, 10, 0.25)
    for lat, lon in [(50.1101, 8.6801), (50.1301, 8.7001), (50.19, 8.80), (50.03, 8.56)]:
        assert tile_key(lat, lon) in keys


# --------------------------------------------------------------------------
# Vorschau auf die nächsten 24 Stunden
# --------------------------------------------------------------------------


def test_future_steps_start_at_next_quarter() -> None:
    from custom_components.ladekrone.pricing import future_steps

    steps = future_steps(_local(20, 7))
    assert steps[0].astimezone(LOCAL_TZ) == _local(20, 15)
    assert len(steps) == 96
    assert steps[1] - steps[0] == steps[-1] - steps[-2]


def test_future_steps_across_dst_change() -> None:
    from custom_components.ladekrone.pricing import future_steps

    # In der Nacht der Zeitumstellung (25.10.2026) keine doppelten oder fehlenden Schritte
    steps = future_steps(_local(1, 50, day=25))
    deltas = {b - a for a, b in pairwise(steps)}
    assert len(deltas) == 1
    assert len(set(steps)) == len(steps)


def test_next_change_finds_night_tariff(stations: list[dict]) -> None:
    from custom_components.ladekrone.pricing import future_steps, next_change

    tesla = _station(stations, "ST-SC-1")
    when, price = next_change(tesla, *HOME, Filters(), 0.59, future_steps(_local(20, 7)))
    assert when.astimezone(LOCAL_TZ) == _local(23)
    assert price == 0.39


def test_cheapest_ahead_finds_cheaper_window(stations: list[dict]) -> None:
    from custom_components.ladekrone.pricing import cheapest_ahead, stations_in_radius

    now = _local(20, 7)
    nearby = stations_in_radius(stations, *HOME, 50)
    offers = find_offers(nearby, *HOME, 50, Filters(), now)
    outlook = cheapest_ahead(nearby, offers[0], *HOME, Filters(), now)
    assert outlook.offer.price.kwh == 0.39
    assert outlook.offer.station_id.endswith("ST-SC-1")
    assert outlook.start.astimezone(LOCAL_TZ) == _local(23)
    assert outlook.end.astimezone(LOCAL_TZ) == _local(7, day=28)


def test_cheapest_ahead_keeps_current_when_nothing_cheaper(stations: list[dict]) -> None:
    from custom_components.ladekrone.pricing import cheapest_ahead, stations_in_radius

    now = _local(23, 30)
    nearby = stations_in_radius(stations, *HOME, 50)
    offers = find_offers(nearby, *HOME, 50, Filters(), now)
    assert offers[0].price.kwh == 0.39
    outlook = cheapest_ahead(nearby, offers[0], *HOME, Filters(), now)
    assert outlook.offer is offers[0]
    assert outlook.start == now
    assert outlook.end.astimezone(LOCAL_TZ) == _local(7, day=28)


def test_only_listed_without_operators_matches_nothing(stations: list[dict]) -> None:
    now = _local(12).astimezone(UTC)
    assert find_offers(stations, *HOME, 10, Filters(only_listed=True), now) == []
    listed = Filters(operators=("tesla",), only_listed=True)
    assert [o.operator for o in find_offers(stations, *HOME, 10, listed, now)] == ["Tesla"]


@pytest.mark.parametrize(
    ("network", "operator", "expected"),
    [
        ("Aral pulse", "Aral AG", True),
        ("E.ON Drive", "E.ON Drive Infrastructure GmbH", True),
        ("EWE Go", "EWE Go GmbH", True),
        ("IONITY", "IONITY GmbH", True),
        ("Allego", "Allego GmbH", True),
        ("Stadtwerke", "Stadtwerke Krefeld AG", True),
        ("Stadtwerke Moers", "Stadtwerke Krefeld AG", False),
        ("bp pulse", "Ebp Energie GmbH", False),
        ("Tesla", "Teslastrom e.K.", False),
        ("Fastned", "EnBW mobility+ AG & Co. KG", False),
    ],
)
def test_networks_from_entity_match_by_words(network: str, operator: str, expected: bool) -> None:
    station = {
        "id": "x",
        "la": HOME[0],
        "lo": HOME[1],
        "o": operator,
        "g": [{"kw": 150, "c": "dc", "k": ["ccs"], "n": 2, "r": [0]}],
        "r": [{"p": [{"t": "kwh", "v": 0.5}]}],
    }
    filters = Filters(networks=(network,), only_listed=True)
    now = _local(12).astimezone(UTC)
    assert bool(find_offers([station], *HOME, 5, filters, now)) is expected


# --------------------------------------------------------------------------
# Rangfolge nach den Kosten einer Ladung
# --------------------------------------------------------------------------


def _plain_station(sid: str, offset: float, kw: float, components: list[dict]) -> dict:
    return {
        "id": sid,
        "la": HOME[0] + offset,
        "lo": HOME[1] + offset,
        "o": sid,
        "g": [{"kw": kw, "c": "dc", "k": ["ccs"], "n": 2, "r": [0]}],
        "r": [{"p": components}],
    }


COST_STATIONS = [
    # billig je kWh, aber 5 € Startgebühr
    _plain_station("start", 0.001, 150, [{"t": "kwh", "v": 0.39}, {"t": "base", "v": 5.0}]),
    # etwas teurer je kWh, sonst nichts
    _plain_station("plain", 0.002, 150, [{"t": "kwh", "v": 0.49}]),
    # langsam: 40 kWh an 50 kW dauern 48 min, ab Minute 30 kostet es 0,20 €/min, höchstens 2 €
    _plain_station(
        "slow", 0.003, 50, [{"t": "kwh", "v": 0.45}, {"t": "min", "v": 0.2, "f": 30, "cap": 2.0}]
    ),
]


def test_charge_cost_adds_session_and_time_fee() -> None:
    now = _local(12)
    start = current_price(COST_STATIONS[0]["r"][0], now)
    slow = current_price(COST_STATIONS[2]["r"][0], now)
    assert charge_cost(start, 40, 150) == pytest.approx(0.39 * 40 + 5.0)
    # 18 Minuten über der Freizeit wären 3,60 €, die Obergrenze kappt auf 2 €
    assert charge_cost(slow, 40, 50) == pytest.approx(0.45 * 40 + 2.0)
    # 20 kWh dauern 24 min: noch in der Freizeit
    assert charge_cost(slow, 20, 50) == pytest.approx(0.45 * 20)
    # ohne bekannte Leistung keine geschätzte Zeitgebühr
    assert charge_cost(slow, 40, None) == pytest.approx(0.45 * 40)


def test_ranking_by_kwh_price_is_the_default() -> None:
    offers = find_offers(COST_STATIONS, *HOME, 5, Filters(), _local(12))
    assert [o.station_id for o in offers] == ["start", "slow", "plain"]
    assert all(o.total_cost is None for o in offers)
    assert "total_cost" not in offers[0].as_dict()


def test_ranking_by_charge_cost() -> None:
    offers = find_offers(COST_STATIONS, *HOME, 5, Filters(charge_kwh=40), _local(12))
    # 19,60 € < 20,00 € < 20,60 €
    assert [o.station_id for o in offers] == ["plain", "slow", "start"]
    assert [round(o.total_cost, 2) for o in offers] == [19.6, 20.0, 20.6]
    data = offers[2].as_dict()
    assert data["price"] == 0.39
    assert data["total_cost"] == 20.6
    assert data["effective_price"] == 0.515
    assert data["charge_kwh"] == 40


def test_small_charge_makes_session_fee_weigh_more() -> None:
    big = find_offers(COST_STATIONS, *HOME, 5, Filters(charge_kwh=80), _local(12))
    # bei 80 kWh lohnt sich der niedrige kWh-Preis trotz Startgebühr
    assert big[0].station_id == "start"


def test_last_change_from_history() -> None:
    station = _plain_station("hist", 0.001, 150, [{"t": "kwh", "v": 0.59}])
    station["h"] = [["2026-10-01", 0.54], ["2026-10-20", 0.59]]
    offer = find_offers([station], *HOME, 5, Filters(), _local(12))[0]
    assert (offer.previous_price, offer.price_since) == (0.54, "2026-10-20")
    data = offer.as_dict()
    assert data["previous_price"] == 0.54
    assert data["price_since"] == "2026-10-20"


def test_history_is_ignored_when_another_price_applies() -> None:
    night = {"in": [{"t": [["23:00", "07:00"]]}]}
    station = _plain_station(
        "night", 0.001, 150, [{"t": "kwh", "v": 0.59}, {"t": "kwh", "v": 0.39, "w": night}]
    )
    station["h"] = [["2026-10-01", 0.54], ["2026-10-20", 0.59]]
    offer = find_offers([station], *HOME, 5, Filters(), _local(2))[0]
    assert offer.price.kwh == 0.39
    assert offer.previous_price is None
    assert "previous_price" not in offer.as_dict()
    # kaputter Verlauf stört nicht
    station["h"] = [["x"], "y"]
    assert find_offers([station], *HOME, 5, Filters(), _local(12))[0].previous_price is None


# --------------------------------------------------------------------------
# Standorte, die ein Ladenetz als mehrere Stationen meldet
# --------------------------------------------------------------------------


def _site(sid: str, kw: float, price: float, address: str, **extra) -> dict:
    station = _plain_station(sid, 0.001, kw, [{"t": "kwh", "v": price}])
    station.update({"o": "ENBW", "a": address}, **extra)
    return station


def test_merge_sites_combines_stations_of_one_site() -> None:
    stations = [
        _site("a", 150, 0.79, "Hof 1, 12345 Ort"),
        _site("b", 300, 0.79, "Hof 1,  12345 ort"),
        _site("c", 300, 0.79, "Hof 1, 12345 Ort"),
        _site("d", 150, 0.79, "Weg 2, 12345 Ort"),  # anderer Standort
        _site("e", 50, 0.59, "Hof 1, 12345 Ort"),  # anderer Preis am selben Standort
        _site("f", 150, 0.79, "Hof 1, 12345 Ort", o="Allego"),  # anderes Ladenetz
    ]
    offers = find_offers(stations, *HOME, 5, Filters(), _local(12))
    assert len(offers) == 6
    sites = merge_sites(offers)
    assert [(o.station_id, o.merged) for o in sites] == [
        ("e", 1),
        ("a", 3),
        ("d", 1),
        ("f", 1),
    ]
    site = sites[1]
    assert (site.power_kw, site.points) == (300, 6)
    assert site.as_dict()["stations"] == 3
    assert "stations" not in sites[0].as_dict()
    # die Eingabe bleibt unverändert, zweimal Zusammenfassen ändert nichts mehr
    assert all(o.merged == 1 and o.points == 2 for o in offers)
    again = merge_sites(sites)
    assert [(o.station_id, o.merged, o.points) for o in again] == [
        (o.station_id, o.merged, o.points) for o in sites
    ]


def test_merge_sites_keeps_ac_and_dc_apart_and_falls_back_to_coordinates() -> None:
    ac = _site("ac", 22, 0.59, "Hof 1, 12345 Ort")
    ac["g"][0].update(c="ac", k=["type2"])
    dc = _site("dc", 150, 0.59, "Hof 1, 12345 Ort")
    no_address = [_site("x", 150, 0.6, ""), _site("y", 300, 0.6, "")]
    offers = find_offers([ac, dc, *no_address], *HOME, 5, Filters(), _local(12))
    sites = merge_sites(offers)
    assert sorted((o.station_id, o.merged) for o in sites) == [("ac", 1), ("dc", 1), ("x", 2)]
