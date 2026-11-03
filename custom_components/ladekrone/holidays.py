"""Gesetzliche Feiertage in Deutschland, bundesweit und je Bundesland.

Reines Python ohne Abhängigkeiten. Die Web-App rechnet dasselbe in
``collector/ladekrone_collector/webapp/pricing.js``.

Nicht enthalten sind Feiertage, die nur in einzelnen Gemeinden gelten
(Mariä Himmelfahrt in Teilen Bayerns, Fronleichnam in Teilen Sachsens und
Thüringens, Augsburger Friedensfest) und einmalige Feiertage.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

# (Monat, Tag, Name, Bundesländer oder None für bundesweit, ab Jahr)
FIXED: tuple[tuple[int, int, str, frozenset[str] | None, int], ...] = (
    (1, 1, "Neujahr", None, 0),
    (1, 6, "Heilige Drei Könige", frozenset({"BW", "BY", "ST"}), 0),
    (3, 8, "Internationaler Frauentag", frozenset({"BE"}), 2019),
    (3, 8, "Internationaler Frauentag", frozenset({"MV"}), 2023),
    (5, 1, "Tag der Arbeit", None, 0),
    (8, 15, "Mariä Himmelfahrt", frozenset({"SL"}), 0),
    (9, 20, "Weltkindertag", frozenset({"TH"}), 2019),
    (10, 3, "Tag der Deutschen Einheit", None, 1990),
    (10, 31, "Reformationstag", frozenset({"BB", "MV", "SN", "ST", "TH"}), 0),
    (10, 31, "Reformationstag", frozenset({"HB", "HH", "NI", "SH"}), 2018),
    (11, 1, "Allerheiligen", frozenset({"BW", "BY", "NW", "RP", "SL"}), 0),
    (12, 25, "1. Weihnachtstag", None, 0),
    (12, 26, "2. Weihnachtstag", None, 0),
)

# (Tage nach Ostersonntag, Name, Bundesländer oder None für bundesweit)
EASTER: tuple[tuple[int, str, frozenset[str] | None], ...] = (
    (-2, "Karfreitag", None),
    (0, "Ostersonntag", frozenset({"BB", "HE"})),
    (1, "Ostermontag", None),
    (39, "Christi Himmelfahrt", None),
    (49, "Pfingstsonntag", frozenset({"BB", "HE"})),
    (50, "Pfingstmontag", None),
    (60, "Fronleichnam", frozenset({"BW", "BY", "HE", "NW", "RP", "SL"})),
)


def easter_sunday(year: int) -> date:
    """Ostersonntag nach dem gregorianischen Kalender (anonymer Algorithmus)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


def _applies(states: frozenset[str] | None, state: str | None) -> bool:
    return states is None or (state is not None and state in states)


@lru_cache(maxsize=64)
def holidays(year: int, state: str | None = None) -> dict[date, str]:
    """Alle Feiertage eines Jahres; ohne Bundesland nur die bundesweiten."""
    result: dict[date, str] = {}
    for month, day, name, states, since in FIXED:
        if year >= since and _applies(states, state):
            result[date(year, month, day)] = name
    easter = easter_sunday(year)
    for offset, name, states in EASTER:
        if _applies(states, state):
            result[easter + timedelta(days=offset)] = name
    if state == "SN":
        # Buß- und Bettag: Mittwoch vor dem 23. November
        nov22 = date(year, 11, 22)
        result[nov22 - timedelta(days=(nov22.weekday() - 2) % 7)] = "Buß- und Bettag"
    return result


def holiday_name(day: date, state: str | None = None) -> str | None:
    return holidays(day.year, state).get(day)


def is_holiday(day: date, state: str | None = None) -> bool:
    return day in holidays(day.year, state)


def is_special_day(kind: str | None, day: date, state: str | None = None) -> bool:
    """Trifft ein DATEX-II-Sondertag (``specialDayType``) auf den Tag zu?

    Ausgewertet werden Feiertage sowie die Tage davor und danach. Alles andere
    (Schultage, Ferien, Veranstaltungen) lässt sich nicht bestimmen und gilt als
    nicht zutreffend.
    """
    if kind == "publicHoliday":
        return is_holiday(day, state)
    if kind == "dayBeforePublicHoliday":
        return is_holiday(day + timedelta(days=1), state)
    if kind == "dayFollowingPublicHoliday":
        return is_holiday(day - timedelta(days=1), state)
    return False
