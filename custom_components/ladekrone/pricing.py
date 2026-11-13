"""Preislogik: Zeitfenster auswerten und günstigste Ladepunkte finden.

Reines Python ohne Home-Assistant-Abhängigkeiten, damit es sich gut testen lässt.
Alle Uhrzeiten aus den Daten sind Ortszeit (Europe/Berlin). Feiertage zählen nach
dem Bundesland der Station (``bl``), ohne Bundesland nur die bundesweiten.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from .holidays import holiday_name, is_special_day

LOCAL_TZ = ZoneInfo("Europe/Berlin")
EARTH_RADIUS_KM = 6371.0088
STEP = timedelta(minutes=15)
HORIZON = timedelta(hours=24)

CONNECTOR_ALIASES = {
    "ccs": {"ccs"},
    "type2": {"type2"},
    "chademo": {"chademo"},
}

# Suchgebiet-Auswahl -> DATEX ratePolicy. Ad-hoc ist der Standard und hat keinen Eintrag.
TARIFF_POLICIES = {
    "contract": "contract",
    "subscription": "subscription",
}


@dataclass(frozen=True)
class Filters:
    """Suchkriterien aus der Konfiguration."""

    min_power_kw: float = 0
    current: str = "any"  # any | ac | dc
    connector: str = "any"  # any | ccs | type2 | chademo
    operators: tuple[str, ...] = ()
    # Ladenetze aus einer Entität, z. B. „Ladenetze, an denen MultiPass funktioniert hat“.
    # Sie werden großzügiger verglichen als die eingetippten (siehe _network_matches).
    networks: tuple[str, ...] = ()
    # True: ohne bekannte Ladenetze passt keine Station (statt alle).
    only_listed: bool = False
    # adhoc | contract | subscription. Zusatztarif nur, wo der Betreiber ihn veröffentlicht.
    tariff: str = "adhoc"
    # Größe einer typischen Ladung in kWh. Größer 0: Rangfolge nach den Kosten
    # dieser Ladung (Energie, Startgebühr, Zeitgebühr) statt nach dem kWh-Preis.
    charge_kwh: float = 0


@dataclass
class Price:
    """Aktuell gültiger Ad-hoc-Preis eines Tarifs."""

    kwh: float
    minute_fee: float | None = None
    minute_fee_from: int | None = None
    minute_fee_cap: float | None = None
    session_fee: float | None = None
    updated: str | None = None
    tariff: str = "adHoc"
    tariff_name: str | None = None


@dataclass
class Offer:
    """Günstigstes passendes Angebot einer Station."""

    station_id: str
    operator: str | None
    address: str | None
    latitude: float
    longitude: float
    distance_km: float
    price: Price
    power_kw: float | None
    current: str | None
    connectors: list[str] = field(default_factory=list)
    points: int = 0
    until: datetime | None = None
    next_price: float | None = None
    charge_kwh: float = 0
    total_cost: float | None = None

    @property
    def rank(self) -> float:
        """Sortierwert: Kosten der Ladung, sonst der kWh-Preis."""
        return self.total_cost if self.total_cost is not None else self.price.kwh

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "operator": self.operator,
            "address": self.address,
            "distance_km": round(self.distance_km, 1),
            "price": round(self.price.kwh, 2),
            "power_kw": self.power_kw,
            "current_type": self.current,
            "connectors": self.connectors,
            "points": self.points,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }
        if self.price.minute_fee is not None:
            data["minute_fee"] = round(self.price.minute_fee, 2)
            data["minute_fee_from"] = self.price.minute_fee_from
        if self.price.session_fee is not None:
            data["session_fee"] = round(self.price.session_fee, 2)
        if self.total_cost is not None and self.charge_kwh > 0:
            data["charge_kwh"] = self.charge_kwh
            data["total_cost"] = round(self.total_cost, 2)
            data["effective_price"] = round(self.total_cost / self.charge_kwh, 3)
        data["tariff"] = self.price.tariff
        if self.price.tariff_name:
            data["tariff_name"] = self.price.tariff_name
        if self.until is not None:
            data["until"] = self.until
            data["next_price"] = round(self.next_price, 2) if self.next_price is not None else None
        return data


# --------------------------------------------------------------------------
# Geometrie
# --------------------------------------------------------------------------


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def tiles_for_radius(lat: float, lon: float, radius_km: float, tile_deg: float) -> list[str]:
    """Alle Kachelschlüssel, die den Suchkreis berühren."""
    dlat = radius_km / 111.32
    dlon = radius_km / (111.32 * max(0.01, math.cos(math.radians(lat))))
    lat_min, lat_max = math.floor((lat - dlat) / tile_deg), math.floor((lat + dlat) / tile_deg)
    lon_min, lon_max = math.floor((lon - dlon) / tile_deg), math.floor((lon + dlon) / tile_deg)
    return [f"{y}_{x}" for y in range(lat_min, lat_max + 1) for x in range(lon_min, lon_max + 1)]


# --------------------------------------------------------------------------
# Zeitliche Gültigkeit
# --------------------------------------------------------------------------


def _parse_clock(value: str) -> time | None:
    try:
        hour, minute = (int(part) for part in value.split(":")[:2])
    except (ValueError, AttributeError):
        return None
    if hour == 24 and minute == 0:
        return time(23, 59, 59, 999999)
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None
    return time(hour, minute)


def _in_window(now: time, start: time, end: time) -> bool:
    if start == end:
        return True
    if start < end:
        return start <= now < end
    return now >= start or now < end  # über Mitternacht


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)
    return parsed


def _letters(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def _special_matches(entry: dict, local: datetime, state: str | None) -> bool:
    """Ein Sondertag aus ``sp``: ``k`` Art, ``r`` Bundesland, ``n`` Name des Feiertags."""
    region = entry.get("r") or state
    if region == "-":  # Gebiet außerhalb Deutschlands
        return False
    if not is_special_day(entry.get("k"), local.date(), region):
        return False
    wanted = entry.get("n")
    if not wanted:
        return True
    # Ein bestimmter Feiertag: nur bei eindeutig gleichem Namen
    name = holiday_name(local.date(), region) or ""
    a, b = _letters(wanted), _letters(name)
    return bool(a and b) and (a in b or b in a)


def _day_matches(period: dict, local: datetime, state: str | None) -> bool:
    """Wochentage und Sondertage einer Periode.

    Mit ``intersectWithApplicableDays`` (``x``) gilt die Periode nur an Sondertagen,
    die auf die angegebenen Wochentage fallen; ohne kommen die Sondertage zu den
    Wochentagen hinzu. Sondertage, die sich nicht bestimmen lassen (Ferien,
    Veranstaltungen), treffen nie zu.
    """
    days = period.get("d")
    matched: bool | None = (local.weekday() in days) if days else None
    raw = period.get("sp")
    special = [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []
    if raw and not special:
        special = [{}]  # nur als vorhanden gekennzeichnet, Art unbekannt
    unions = [e for e in special if not e.get("x")]
    intersections = [e for e in special if e.get("x")]
    if unions:
        matched = bool(matched) or any(_special_matches(e, local, state) for e in unions)
    if intersections:
        matched = matched is not False and all(
            _special_matches(e, local, state) for e in intersections
        )
    return matched is not False


def period_matches(period: dict, local: datetime, state: str | None = None) -> bool:
    """Alle angegebenen Kriterien einer Periode müssen zutreffen."""
    absolute = period.get("a")
    if absolute:
        start, end = _parse_dt(absolute[0]), _parse_dt(absolute[1])
        if start and local < start:
            return False
        if end and local >= end:
            return False
    if not _day_matches(period, local, state):
        return False
    if (months := period.get("m")) and local.month not in months:
        return False
    windows = period.get("t")
    if windows:
        now = local.time()
        matched = False
        for start_raw, end_raw in windows:
            start, end = _parse_clock(start_raw), _parse_clock(end_raw)
            if start is not None and end is not None and _in_window(now, start, end):
                matched = True
                break
        if not matched:
            return False
    return True


def validity_matches(validity: dict | None, local: datetime, state: str | None = None) -> bool:
    if not validity:
        return True
    start, end = _parse_dt(validity.get("s")), _parse_dt(validity.get("e"))
    if start and local < start:
        return False
    if end and local > end:
        return False
    valid = validity.get("in")
    if valid and not any(period_matches(p, local, state) for p in valid):
        return False
    return not any(period_matches(p, local, state) for p in validity.get("ex") or [])


def _restricted(component: dict) -> bool:
    validity = component.get("w") or {}
    return bool(validity.get("in") or validity.get("ex"))


def current_price(rate: dict, local: datetime, state: str | None = None) -> Price | None:
    """Ermittelt den zum Zeitpunkt gültigen Preis eines Ad-hoc-Tarifs.

    Mehrere kWh-Preise werden über ihre Zeitfenster aufgelöst. Greifen
    mehrere gleichzeitig, gewinnt der zeitlich eingeschränkte und davon der
    höhere – lieber etwas zu teuer anzeigen als zu günstig.
    """
    if rate.get("cur", "EUR") != "EUR" or not validity_matches(rate.get("w"), local, state):
        return None
    active = [c for c in rate.get("p", []) if validity_matches(c.get("w"), local, state)]

    kwh = [c for c in active if c["t"] == "kwh" and not (c.get("f") or 0)]
    if not kwh:
        kwh = [c for c in active if c["t"] == "kwh"]
    free = any(c["t"] == "free" for c in active)
    if kwh:
        restricted = [c for c in kwh if _restricted(c)]
        energy_price = max(c["v"] for c in (restricted or kwh))
    elif free:
        energy_price = 0.0
    else:
        return None

    price = Price(kwh=energy_price, updated=rate.get("u"))
    minute = [c for c in active if c["t"] == "min"]
    if minute:
        fee = min(minute, key=lambda c: c.get("f") or 0)
        price.minute_fee = fee["v"]
        price.minute_fee_from = fee.get("f")
        price.minute_fee_cap = fee.get("cap")
    session = [c["v"] for c in active if c["t"] in ("base", "flat")]
    if session:
        price.session_fee = sum(session)
    return price


def charge_cost(price: Price, kwh: float, power_kw: float | None) -> float:
    """Kosten einer Ladung mit ``kwh``: Energie, Startgebühr und Zeitgebühr.

    Die Ladedauer wird aus der Leistung des Ladepunkts geschätzt; das Auto kann
    langsamer laden. Die Zeitgebühr zählt erst ab ihrer Freiminute und höchstens
    bis zu ihrer Obergrenze.
    """
    total = price.kwh * kwh + (price.session_fee or 0)
    if price.minute_fee and power_kw and power_kw > 0:
        minutes = kwh / power_kw * 60
        fee = max(0.0, minutes - (price.minute_fee_from or 0)) * price.minute_fee
        if price.minute_fee_cap is not None:
            fee = min(fee, price.minute_fee_cap)
        total += fee
    return total


def _rank(price: Price, group: dict, filters: Filters) -> float:
    if filters.charge_kwh > 0:
        return charge_cost(price, filters.charge_kwh, group.get("kw"))
    return price.kwh


# --------------------------------------------------------------------------
# Suche
# --------------------------------------------------------------------------


def _group_matches(group: dict, filters: Filters) -> bool:
    if filters.min_power_kw > 0:
        power = group.get("kw")
        if power is None or power < filters.min_power_kw:
            return False
    if filters.current != "any" and group.get("c") != filters.current:
        return False
    if filters.connector != "any":
        wanted = CONNECTOR_ALIASES.get(filters.connector, {filters.connector})
        if not wanted & set(group.get("k", [])):
            return False
    return True


# Erste Wörter, die allein nichts über ein Ladenetz sagen
GENERIC_WORDS = frozenset(
    {
        "stadtwerke",
        "mobility",
        "energie",
        "energy",
        "charging",
        "charge",
        "laden",
        "ladenetz",
        "strom",
        "power",
        "e",
        "the",
        "die",
        "der",
    }
)


@lru_cache(maxsize=8192)
def _words(text: str) -> str:
    """' aral pulse ' – nur Buchstaben und Ziffern, mit Leerzeichen an den Rändern."""
    return " " + " ".join(re.findall(r"[^\W_]+", text.casefold())) + " "


def _network_matches(name: str, station_words: str) -> bool:
    """Ladenetz aus einer Liste wie „Aral pulse“ gegen den gemeldeten Betreiber.

    Passt, wenn der ganze Name als Wortfolge vorkommt, oder wenn sein erstes Wort
    (mindestens drei Zeichen, nicht allgemein wie „Stadtwerke“) als Wort vorkommt.
    So findet „Aral pulse“ auch „Aral AG“ und „E.ON Drive“ „E.ON Drive Infrastructure“.
    """
    words = _words(name)
    parts = words.split()
    if not parts:
        return False
    if words in station_words:
        return True
    first = parts[0]
    return len(first) >= 3 and first not in GENERIC_WORDS and f" {first} " in station_words


def _operator_matches(station: dict, filters: Filters) -> bool:
    if not filters.operators and not filters.networks:
        return not filters.only_listed
    raw = " ".join(filter(None, (station.get("o"), station.get("b"))))
    haystack = raw.casefold()
    if any(op.casefold() in haystack for op in filters.operators):
        return True
    if filters.networks:
        station_words = _words(raw)
        return any(_network_matches(name, station_words) for name in filters.networks)
    return False


def _best_indexed(
    rates: list[dict],
    indexes: list[int],
    local: datetime,
    state: str | None,
    policy: str | None,
    rank: Callable[[Price], float],
) -> Price | None:
    """Günstigster gerade gültiger Tarif aus ``indexes``. ``policy`` filtert ``pol``."""
    best: Price | None = None
    for index in indexes:
        if not 0 <= index < len(rates):
            continue
        rate = rates[index]
        if policy is not None and rate.get("pol") != policy:
            continue
        price = current_price(rate, local, state)
        if price is None:
            continue
        price.tariff = rate.get("pol") or "adHoc"
        price.tariff_name = rate.get("n")
        if best is None or rank(price) < rank(best):
            best = price
    return best


def best_offer(
    station: dict, lat: float, lon: float, filters: Filters, local: datetime
) -> Offer | None:
    """Günstigstes passendes Angebot einer Station oder None.

    Ist ein Zusatztarif gewählt und der Betreiber hat ihn veröffentlicht, gilt der.
    Sonst der Ad-hoc-Preis; das Angebot ist dann mit ``tariff`` ``adHoc`` markiert.
    """
    if not _operator_matches(station, filters):
        return None
    prefer = TARIFF_POLICIES.get(filters.tariff)
    state = station.get("bl")
    best: tuple[Price, dict, float] | None = None
    for group in station.get("g", []):
        if not _group_matches(group, filters):
            continue
        price = None

        def rank(candidate: Price, group: dict = group) -> float:
            return _rank(candidate, group, filters)

        if prefer:
            price = _best_indexed(
                station.get("x") or [], group.get("x") or [], local, state, prefer, rank
            )
        if price is None:
            price = _best_indexed(
                station.get("r") or [], group.get("r") or [], local, state, None, rank
            )
        if price is None:
            continue
        value = rank(price)
        if (
            best is None
            or value < best[2]
            or (value == best[2] and (group.get("kw") or 0) > (best[1].get("kw") or 0))
        ):
            best = (price, group, value)
    if best is None:
        return None
    price, group, value = best
    return Offer(
        station_id=station["id"],
        operator=station.get("o") or station.get("b"),
        address=station.get("a"),
        latitude=station["la"],
        longitude=station["lo"],
        distance_km=distance_km(lat, lon, station["la"], station["lo"]),
        price=price,
        power_kw=group.get("kw"),
        current=group.get("c"),
        connectors=list(group.get("k", [])),
        points=group.get("n", 0),
        charge_kwh=filters.charge_kwh,
        total_cost=value if filters.charge_kwh > 0 else None,
    )


def find_offers(
    stations: list[dict],
    lat: float,
    lon: float,
    radius_km: float,
    filters: Filters,
    now: datetime,
) -> list[Offer]:
    """Alle passenden Angebote im Umkreis, nach Preis (oder Ladekosten) und Entfernung."""
    local = now.astimezone(LOCAL_TZ)
    offers: list[Offer] = []
    for station in stations:
        try:
            if distance_km(lat, lon, station["la"], station["lo"]) > radius_km:
                continue
            offer = best_offer(station, lat, lon, filters, local)
        except (KeyError, TypeError, ValueError):
            continue
        if offer is not None:
            offers.append(offer)
    offers.sort(key=lambda o: (round(o.rank, 4), o.distance_km))
    return offers


def count_stations(
    stations: list[dict], lat: float, lon: float, radius_km: float, filters: Filters
) -> int:
    """Passende Stationen im Umkreis, mit oder ohne gemeldeten Preis."""
    total = 0
    for station in stations:
        try:
            if distance_km(lat, lon, station["la"], station["lo"]) > radius_km:
                continue
        except (KeyError, TypeError):
            continue
        if _operator_matches(station, filters) and any(
            _group_matches(g, filters) for g in station.get("g", [])
        ):
            total += 1
    return total


def stations_in_radius(
    stations: list[dict], lat: float, lon: float, radius_km: float
) -> list[dict]:
    """Stationen innerhalb des Suchkreises."""
    nearby: list[dict] = []
    for station in stations:
        try:
            if distance_km(lat, lon, station["la"], station["lo"]) <= radius_km:
                nearby.append(station)
        except (KeyError, TypeError):
            continue
    return nearby


# --------------------------------------------------------------------------
# Vorschau: Preiswechsel in den nächsten 24 Stunden
# --------------------------------------------------------------------------


def _has_time(validity: dict | None) -> bool:
    return bool(
        validity
        and (validity.get("in") or validity.get("ex") or validity.get("s") or validity.get("e"))
    )


def is_time_dependent(station: dict) -> bool:
    """True, wenn sich der Preis einer Station mit der Zeit ändern kann."""
    for rate in [*(station.get("r") or []), *(station.get("x") or [])]:
        if _has_time(rate.get("w")):
            return True
        if any(_has_time(c.get("w")) for c in rate.get("p", [])):
            return True
    return False


def future_steps(now: datetime, horizon: timedelta = HORIZON) -> list[datetime]:
    """Viertelstunden-Zeitpunkte ab der nächsten vollen Viertelstunde (UTC).

    Gerechnet wird in UTC, damit die Zeitumstellung keine Schritte verschluckt
    oder doppelt; ausgewertet wird jeweils in Ortszeit.
    """
    base = now.astimezone(UTC).replace(second=0, microsecond=0)
    step_min = int(STEP.total_seconds() // 60)
    first = base.replace(minute=0) + timedelta(minutes=(base.minute // step_min + 1) * step_min)
    return [first + i * STEP for i in range(int(horizon / STEP))]


def _price_at(
    station: dict, lat: float, lon: float, filters: Filters, when: datetime
) -> Offer | None:
    return best_offer(station, lat, lon, filters, when.astimezone(LOCAL_TZ))


def next_change(
    station: dict,
    lat: float,
    lon: float,
    filters: Filters,
    current_kwh: float,
    steps: list[datetime],
) -> tuple[datetime | None, float | None]:
    """Erster Zeitpunkt, an dem sich der Preis ändert, und der neue Preis.

    Ein neuer Preis None heißt: Ab dann gibt es dort keinen Ad-hoc-Preis mehr.
    """
    for when in steps:
        offer = _price_at(station, lat, lon, filters, when)
        price = offer.price.kwh if offer else None
        if price is None or round(price, 4) != round(current_kwh, 4):
            return when, price
    return None, None


def annotate_changes(
    offers: list[Offer],
    stations_by_id: dict[str, dict],
    lat: float,
    lon: float,
    filters: Filters,
    steps: list[datetime],
) -> None:
    """Ergänzt bei zeitabhängigen Angeboten, bis wann der Preis gilt."""
    for offer in offers:
        station = stations_by_id.get(offer.station_id)
        if station is None or not is_time_dependent(station):
            continue
        offer.until, offer.next_price = next_change(
            station, lat, lon, filters, offer.price.kwh, steps
        )


@dataclass
class Outlook:
    """Günstigstes Angebot in den nächsten 24 Stunden."""

    offer: Offer
    start: datetime
    end: datetime | None


def cheapest_ahead(
    nearby: list[dict],
    current: Offer | None,
    lat: float,
    lon: float,
    filters: Filters,
    now: datetime,
    steps: list[datetime] | None = None,
) -> Outlook | None:
    """Sucht das günstigste Angebot bis 24 Stunden im Voraus.

    Stationen mit festem Preis können später nicht günstiger werden als jetzt;
    durchgerechnet werden deshalb nur die zeitabhängigen.
    """
    steps = steps if steps is not None else future_steps(now)
    best, start = current, now
    dependent = [s for s in nearby if is_time_dependent(s)]
    for when in steps:
        for station in dependent:
            try:
                offer = _price_at(station, lat, lon, filters, when)
            except (KeyError, TypeError, ValueError):
                continue
            if offer is not None and (best is None or offer.rank < best.rank - 1e-9):
                best, start = offer, when
    if best is None:
        return None
    station = next((s for s in nearby if s.get("id") == best.station_id), None)
    end = None
    if station is not None and is_time_dependent(station):
        end, _ = next_change(
            station, lat, lon, filters, best.price.kwh, [t for t in steps if t > start]
        )
    return Outlook(best, start, end)
