"""Sondertage (Feiertage) in Tarifen: Sammler und Preislogik zusammen."""

from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path

import pytest

from custom_components.ladekrone.pricing import LOCAL_TZ, Filters, best_offer, current_price
from ladekrone_collector.datex import (
    _iter_dicts,
    _period,
    _special_day,
    diagnose,
    load_document,
    parse_document,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "afir_static_sample.json"

HOLIDAY = {
    "comSpecialDay": {
        "intersectWithApplicableDays": False,
        "specialDayType": {"value": "publicHoliday"},
    }
}


def _local(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=LOCAL_TZ)


def test_special_day_variants() -> None:
    assert _special_day(HOLIDAY) == {"k": "publicHoliday"}
    assert _special_day(
        {
            "comPublicHoliday": {
                "intersectWithApplicableDays": True,
                "specialDayType": {"value": "publicHoliday"},
                "publicHolidayName": {"values": [{"lang": "de", "value": "Neujahr"}]},
                "namedArea": [
                    {"locIsoNamedArea": {"country": "DE", "subdivisionCode": "NW"}},
                ],
            }
        }
    ) == {"k": "publicHoliday", "x": True, "r": "NW", "n": "Neujahr"}
    nuts = {"locNutsNamedArea": {"nutsCode": "DE2"}}
    assert (
        _special_day({"comSpecialDay": {**HOLIDAY["comSpecialDay"], "namedArea": [nuts]}})["r"]
        == "BY"
    )
    foreign = {"locNamedArea": {"country": "AT", "areaName": {"values": [{"value": "Tirol"}]}}}
    assert (
        _special_day({"comSpecialDay": {**HOLIDAY["comSpecialDay"], "namedArea": [foreign]}})["r"]
        == "-"
    )
    plain = {"areaName": {"values": [{"lang": "de", "value": "Sachsen"}]}}
    assert (
        _special_day({"comSpecialDay": {**HOLIDAY["comSpecialDay"], "namedArea": [plain]}})["r"]
        == "SN"
    )
    assert _special_day({"comSpecialDay": {"intersectWithApplicableDays": False}}) is None


def test_period_keeps_days_and_special_days() -> None:
    period = _period(
        {
            "recurringDayWeekMonthPeriod": [
                {"applicableDay": [{"value": "saturday"}, {"value": "sunday"}]}
            ],
            "recurringSpecialDay": [HOLIDAY],
        }
    )
    assert period == {"d": [5, 6], "sp": [{"k": "publicHoliday"}]}


def _document_with_holiday_tariff() -> dict:
    """Beispiel mit einem Supercharger-Tarif: werktags 0,59 €, an Feiertagen 0,29 €."""
    document = copy.deepcopy(load_document(FIXTURE.read_bytes()))
    for item in _iter_dicts(document):
        if item.get("ratePolicy") == {"value": "adHoc"} and item.get("energyPrice"):
            item["energyPrice"] = [
                {
                    "priceType": {"value": "pricePerKWh"},
                    "value": 0.59,
                    "taxIncluded": True,
                    "overallPeriod": {"exceptionPeriod": [{"recurringSpecialDay": [HOLIDAY]}]},
                },
                {
                    "priceType": {"value": "pricePerKWh"},
                    "value": 0.29,
                    "taxIncluded": True,
                    "overallPeriod": {"validPeriod": [{"recurringSpecialDay": [HOLIDAY]}]},
                },
            ]
            return document
    raise AssertionError("kein Ad-hoc-Tarif im Beispiel")


def test_station_with_holiday_tariff_gets_state() -> None:
    records = [r for r, _ in parse_document(_document_with_holiday_tariff(), "test")]
    with_holidays = [r for r in records if "bl" in r]
    assert with_holidays
    assert {r["bl"] for r in with_holidays} == {"HE"}  # Beispielstationen bei Frankfurt
    plain = [r for r, _ in parse_document(load_document(FIXTURE.read_bytes()), "test")]
    assert not any("bl" in r for r in plain)


def test_holiday_tariff_end_to_end() -> None:
    records = [r for r, _ in parse_document(_document_with_holiday_tariff(), "test")]
    station = next(r for r in records if "bl" in r)
    rate = station["r"][0]
    assert current_price(rate, _local(2026, 10, 27), "HE").kwh == 0.59  # Dienstag
    assert current_price(rate, _local(2026, 12, 25), "HE").kwh == 0.29
    assert current_price(rate, _local(2026, 6, 4), "HE").kwh == 0.29  # Fronleichnam in Hessen
    assert current_price(rate, _local(2026, 6, 4), "NI").kwh == 0.59
    offer = best_offer(station, station["la"], station["lo"], Filters(), _local(2026, 6, 4))
    assert offer is not None
    assert offer.price.kwh == 0.29


def test_diagnose_counts_special_days_only_in_rates() -> None:
    document = _document_with_holiday_tariff()
    result = diagnose(document)
    assert result["special_days"] == {"publicHoliday": 2}
    plain = diagnose(load_document(FIXTURE.read_bytes()))
    assert plain["special_days"] == {}


@pytest.mark.parametrize(
    ("period", "day", "state", "expected"),
    [
        # Wochenende oder Feiertag (Vereinigung)
        ({"d": [5, 6], "sp": [{"k": "publicHoliday"}]}, (2026, 10, 31), "NI", True),  # Samstag
        ({"d": [5, 6], "sp": [{"k": "publicHoliday"}]}, (2026, 12, 25), None, True),  # Freitag
        ({"d": [5, 6], "sp": [{"k": "publicHoliday"}]}, (2026, 10, 27), None, False),
        # nur Feiertage, die auf Werktage fallen (Schnittmenge)
        (
            {"d": [0, 1, 2, 3, 4], "sp": [{"k": "publicHoliday", "x": True}]},
            (2026, 12, 25),
            None,
            True,
        ),
        (
            {"d": [0, 1, 2, 3, 4], "sp": [{"k": "publicHoliday", "x": True}]},
            (2026, 12, 26),
            None,
            False,
        ),
        (
            {"d": [0, 1, 2, 3, 4], "sp": [{"k": "publicHoliday", "x": True}]},
            (2026, 10, 27),
            None,
            False,
        ),
        # Schnittmenge ohne Wochentage: nur der Feiertag
        ({"sp": [{"k": "publicHoliday", "x": True}]}, (2026, 12, 26), None, True),
        # Bundesland aus dem Tarif geht vor dem der Station
        ({"sp": [{"k": "publicHoliday", "r": "NW"}]}, (2026, 11, 1), "HE", True),
        ({"sp": [{"k": "publicHoliday"}]}, (2026, 11, 1), "HE", False),
        ({"sp": [{"k": "publicHoliday", "r": "-"}]}, (2026, 12, 25), None, False),
        # bestimmter Feiertag
        ({"sp": [{"k": "publicHoliday", "n": "Neujahr"}]}, (2027, 1, 1), None, True),
        ({"sp": [{"k": "publicHoliday", "n": "Neujahr"}]}, (2026, 12, 25), None, False),
        # nicht bestimmbar: Ferien, nur gekennzeichnete Sondertage (ältere Kacheln)
        ({"sp": [{"k": "schoolHolidays"}]}, (2026, 10, 27), None, False),
        ({"d": [1], "sp": [{"k": "schoolHolidays"}]}, (2026, 10, 27), None, True),
        ({"sp": True}, (2026, 12, 25), None, False),
        ({"sp": [{"k": "dayBeforePublicHoliday"}]}, (2026, 12, 24), None, True),
    ],
)
def test_special_day_rules(
    period: dict, day: tuple[int, int, int], state: str | None, expected: bool
) -> None:
    from custom_components.ladekrone.pricing import period_matches

    assert period_matches(period, _local(*day), state) is expected
