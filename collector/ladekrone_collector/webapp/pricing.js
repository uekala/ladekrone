// Preislogik der Web-App: Übertragung von custom_components/ladekrone/pricing.py.
// Beide müssen gleich rechnen; tests/collector/test_webapp_pricing.py prüft das.
// Alle Uhrzeiten in den Daten sind Ortszeit (Europe/Berlin).

const TZ = "Europe/Berlin";
const EARTH_RADIUS_KM = 6371.0088;
export const STEP_MS = 15 * 60 * 1000;
export const HORIZON_STEPS = 96; // 24 Stunden in Viertelstunden
export const TOP_OFFERS = 5;

const CONNECTOR_ALIASES = { ccs: ["ccs"], type2: ["type2"], chademo: ["chademo"] };
const WEEKDAYS = { Mon: 0, Tue: 1, Wed: 2, Thu: 3, Fri: 4, Sat: 5, Sun: 6 };
const END_OF_DAY = 1440 - 1e-8; // "24:00" wie time(23, 59, 59, 999999)

const partsFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: TZ,
  hourCycle: "h23",
  year: "numeric",
  month: "numeric",
  day: "numeric",
  hour: "numeric",
  minute: "numeric",
  second: "numeric",
  weekday: "short",
});

/** Ortszeit-Bestandteile zu einem Zeitpunkt (Millisekunden seit 1970). */
export function localTime(ms) {
  const parts = {};
  for (const { type, value } of partsFormat.formatToParts(new Date(ms))) parts[type] = value;
  const msPart = ((ms % 1000) + 1000) % 1000;
  return {
    t: ms,
    year: +parts.year,
    month: +parts.month,
    day: +parts.day,
    hour: +parts.hour,
    minute: +parts.minute,
    second: +parts.second,
    weekday: WEEKDAYS[parts.weekday],
    tod: +parts.hour * 60 + +parts.minute + +parts.second / 60 + msPart / 60000,
  };
}

function offsetMs(ms) {
  const whole = Math.floor(ms / 1000) * 1000;
  const l = localTime(whole);
  return Date.UTC(l.year, l.month - 1, l.day, l.hour, l.minute, l.second) - whole;
}

/** Ortszeit (Europe/Berlin) ohne Zonenangabe in einen Zeitpunkt umrechnen.
 * Wie zoneinfo mit fold=0: doppelte Stunde -> erste, fehlende Stunde -> alte Abweichung. */
function berlinToMs(y, mo, d, h, mi, s, frac) {
  const naive = Date.UTC(y, mo - 1, d, h, mi, s, frac);
  const before = offsetMs(naive - 6 * 3600000);
  const after = offsetMs(naive + 6 * 3600000);
  const valid = [before, after].map((o) => naive - o).filter((ms) => naive - offsetMs(ms) === ms);
  return valid.length ? Math.min(...valid) : naive - before;
}

const ISO_RE =
  /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d+))?)?)?\s*(Z|[+-]\d{2}(?::?\d{2})?)?$/i;

/** Wie _parse_dt: ISO-Zeitpunkt, ohne Zone als Ortszeit gelesen. */
export function parseDt(value) {
  if (typeof value !== "string") return null;
  const m = ISO_RE.exec(value.trim());
  if (!m) return null;
  const [, y, mo, d, h = "0", mi = "0", s = "0", fracRaw = "", zone] = m;
  const frac = fracRaw ? Math.floor(+`0.${fracRaw}` * 1000) : 0;
  if (+mo < 1 || +mo > 12 || +d < 1 || +d > 31 || +h > 23 || +mi > 59 || +s > 59) return null;
  if (!zone) return berlinToMs(+y, +mo, +d, +h, +mi, +s, frac);
  let offset = 0;
  if (zone.toUpperCase() !== "Z") {
    const sign = zone[0] === "-" ? -1 : 1;
    const digits = zone.slice(1).replace(":", "");
    offset = sign * (+digits.slice(0, 2) * 60 + +(digits.slice(2, 4) || 0)) * 60000;
  }
  return Date.UTC(+y, +mo - 1, +d, +h, +mi, +s, frac) - offset;
}

// --------------------------------------------------------------------------
// Geometrie
// --------------------------------------------------------------------------

const rad = (deg) => (deg * Math.PI) / 180;

export function distanceKm(lat1, lon1, lat2, lon2) {
  const p1 = rad(lat1);
  const p2 = rad(lat2);
  const dp = p2 - p1;
  const dl = rad(lon2 - lon1);
  const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(a)));
}

export function tilesForRadius(lat, lon, radiusKm, tileDeg) {
  const dlat = radiusKm / 111.32;
  const dlon = radiusKm / (111.32 * Math.max(0.01, Math.cos(rad(lat))));
  const keys = [];
  for (let y = Math.floor((lat - dlat) / tileDeg); y <= Math.floor((lat + dlat) / tileDeg); y++) {
    for (let x = Math.floor((lon - dlon) / tileDeg); x <= Math.floor((lon + dlon) / tileDeg); x++) {
      keys.push(`${y}_${x}`);
    }
  }
  return keys;
}

// --------------------------------------------------------------------------
// Feiertage: Übertragung von custom_components/ladekrone/holidays.py
// --------------------------------------------------------------------------

// [Monat, Tag, Name, Bundesländer oder null für bundesweit, ab Jahr]
const FIXED_HOLIDAYS = [
  [1, 1, "Neujahr", null, 0],
  [1, 6, "Heilige Drei Könige", ["BW", "BY", "ST"], 0],
  [3, 8, "Internationaler Frauentag", ["BE"], 2019],
  [3, 8, "Internationaler Frauentag", ["MV"], 2023],
  [5, 1, "Tag der Arbeit", null, 0],
  [8, 15, "Mariä Himmelfahrt", ["SL"], 0],
  [9, 20, "Weltkindertag", ["TH"], 2019],
  [10, 3, "Tag der Deutschen Einheit", null, 1990],
  [10, 31, "Reformationstag", ["BB", "MV", "SN", "ST", "TH"], 0],
  [10, 31, "Reformationstag", ["HB", "HH", "NI", "SH"], 2018],
  [11, 1, "Allerheiligen", ["BW", "BY", "NW", "RP", "SL"], 0],
  [12, 25, "1. Weihnachtstag", null, 0],
  [12, 26, "2. Weihnachtstag", null, 0],
];
// [Tage nach Ostersonntag, Name, Bundesländer oder null für bundesweit]
const EASTER_HOLIDAYS = [
  [-2, "Karfreitag", null],
  [0, "Ostersonntag", ["BB", "HE"]],
  [1, "Ostermontag", null],
  [39, "Christi Himmelfahrt", null],
  [49, "Pfingstsonntag", ["BB", "HE"]],
  [50, "Pfingstmontag", null],
  [60, "Fronleichnam", ["BW", "BY", "HE", "NW", "RP", "SL"]],
];

const dayKey = (y, m, d) => y * 10000 + m * 100 + d;

function shiftDay(y, m, d, days) {
  const t = new Date(Date.UTC(y, m - 1, d + days));
  return [t.getUTCFullYear(), t.getUTCMonth() + 1, t.getUTCDate()];
}

/** Ostersonntag als [Monat, Tag] (gregorianisch, anonymer Algorithmus). */
export function easterSunday(year) {
  const a = year % 19;
  const b = Math.floor(year / 100);
  const c = year % 100;
  const d = Math.floor(b / 4);
  const e = b % 4;
  const f = Math.floor((b + 8) / 25);
  const g = Math.floor((b - f + 1) / 3);
  const h = (19 * a + b - d - g + 15) % 30;
  const i = Math.floor(c / 4);
  const k = c % 4;
  const m = (32 + 2 * e + 2 * i - h - k) % 7;
  const n = Math.floor((a + 11 * h + 22 * m) / 451);
  const total = h + m - 7 * n + 114;
  return [Math.floor(total / 31), (total % 31) + 1];
}

const applies = (states, state) => states === null || (state != null && states.includes(state));
const holidayCache = new Map();

/** Feiertage eines Jahres als Map dayKey -> Name; ohne Bundesland nur die bundesweiten. */
export function holidays(year, state = null) {
  const cacheKey = `${year}:${state ?? ""}`;
  const cached = holidayCache.get(cacheKey);
  if (cached) return cached;
  const result = new Map();
  for (const [month, day, name, states, since] of FIXED_HOLIDAYS) {
    if (year >= since && applies(states, state)) result.set(dayKey(year, month, day), name);
  }
  const [em, ed] = easterSunday(year);
  for (const [offset, name, states] of EASTER_HOLIDAYS) {
    if (applies(states, state)) result.set(dayKey(...shiftDay(year, em, ed, offset)), name);
  }
  if (state === "SN") {
    // Buß- und Bettag: Mittwoch vor dem 23. November
    const weekday = (new Date(Date.UTC(year, 10, 22)).getUTCDay() + 6) % 7;
    result.set(dayKey(...shiftDay(year, 11, 22, -((((weekday - 2) % 7) + 7) % 7))), "Buß- und Bettag");
  }
  holidayCache.set(cacheKey, result);
  return result;
}

const isHoliday = (y, m, d, state) => holidays(y, state).has(dayKey(y, m, d));

export function holidayName(y, m, d, state = null) {
  return holidays(y, state).get(dayKey(y, m, d)) ?? null;
}

/** Trifft ein DATEX-II-Sondertag (specialDayType) zu? Wie is_special_day. */
export function isSpecialDay(kind, y, m, d, state = null) {
  if (kind === "publicHoliday") return isHoliday(y, m, d, state);
  if (kind === "dayBeforePublicHoliday") return isHoliday(...shiftDay(y, m, d, 1), state);
  if (kind === "dayFollowingPublicHoliday") return isHoliday(...shiftDay(y, m, d, -1), state);
  return false;
}

// --------------------------------------------------------------------------
// Zeitliche Gültigkeit
// --------------------------------------------------------------------------

function parseClock(value) {
  if (typeof value !== "string") return null;
  const [h, m] = value.split(":");
  if (!/^\s*[+-]?\d+\s*$/.test(h ?? "") || !/^\s*[+-]?\d+\s*$/.test(m ?? "")) return null;
  const hour = parseInt(h, 10);
  const minute = parseInt(m, 10);
  if (hour === 24 && minute === 0) return END_OF_DAY;
  if (!(hour >= 0 && hour < 24 && minute >= 0 && minute < 60)) return null;
  return hour * 60 + minute;
}

function inWindow(now, start, end) {
  if (start === end) return true;
  if (start < end) return start <= now && now < end;
  return now >= start || now < end; // über Mitternacht
}

const filled = (list) => Array.isArray(list) && list.length > 0;

const letters = (text) => text.toLowerCase().replace(/ß/g, "ss").replace(/[^\p{L}\p{N}]/gu, "");

function specialMatches(entry, local, state) {
  const region = entry.r || state;
  if (region === "-") return false; // Gebiet außerhalb Deutschlands
  if (!isSpecialDay(entry.k, local.year, local.month, local.day, region)) return false;
  if (!entry.n) return true;
  // Ein bestimmter Feiertag: nur bei eindeutig gleichem Namen
  const a = letters(entry.n);
  const b = letters(holidayName(local.year, local.month, local.day, region) || "");
  return Boolean(a && b) && (a.includes(b) || b.includes(a));
}

/** Wochentage und Sondertage einer Periode, wie _day_matches. */
function dayMatches(period, local, state) {
  let matched = filled(period.d) ? period.d.includes(local.weekday) : null;
  const raw = period.sp;
  let special = Array.isArray(raw) ? raw.filter((e) => e && typeof e === "object") : [];
  if (raw && (!Array.isArray(raw) || raw.length) && !special.length) special = [{}];
  const unions = special.filter((e) => !e.x);
  const intersections = special.filter((e) => e.x);
  if (unions.length) matched = Boolean(matched) || unions.some((e) => specialMatches(e, local, state));
  if (intersections.length) {
    matched = matched !== false && intersections.every((e) => specialMatches(e, local, state));
  }
  return matched !== false;
}

export function periodMatches(period, local, state = null) {
  const absolute = period.a;
  if (filled(absolute)) {
    const start = parseDt(absolute[0]);
    const end = parseDt(absolute[1]);
    if (start !== null && local.t < start) return false;
    if (end !== null && local.t >= end) return false;
  }
  if (!dayMatches(period, local, state)) return false;
  if (filled(period.m) && !period.m.includes(local.month)) return false;
  if (filled(period.t)) {
    const matched = period.t.some(([startRaw, endRaw]) => {
      const start = parseClock(startRaw);
      const end = parseClock(endRaw);
      return start !== null && end !== null && inWindow(local.tod, start, end);
    });
    if (!matched) return false;
  }
  return true;
}

export function validityMatches(validity, local, state = null) {
  if (!validity || Object.keys(validity).length === 0) return true;
  const start = parseDt(validity.s);
  const end = parseDt(validity.e);
  if (start !== null && local.t < start) return false;
  if (end !== null && local.t > end) return false;
  if (filled(validity.in) && !validity.in.some((p) => periodMatches(p, local, state))) return false;
  return !(validity.ex || []).some((p) => periodMatches(p, local, state));
}

const restricted = (c) => {
  const w = c.w || {};
  return filled(w.in) || filled(w.ex);
};

/** Zum Zeitpunkt gültiger Ad-hoc-Preis eines Tarifs (wie current_price). */
export function currentPrice(rate, local, state = null) {
  const currency = "cur" in rate ? rate.cur : "EUR";
  if (currency !== "EUR" || !validityMatches(rate.w, local, state)) return null;
  const active = (rate.p || []).filter((c) => validityMatches(c.w, local, state));
  let kwh = active.filter((c) => c.t === "kwh" && !(c.f || 0));
  if (!kwh.length) kwh = active.filter((c) => c.t === "kwh");
  const free = active.some((c) => c.t === "free");
  let energy;
  if (kwh.length) {
    const limited = kwh.filter(restricted);
    energy = Math.max(...(limited.length ? limited : kwh).map((c) => c.v));
  } else if (free) {
    energy = 0;
  } else {
    return null;
  }
  const price = { kwh: energy, updated: rate.u ?? null, minuteFee: null, minuteFeeFrom: null, sessionFee: null };
  const minute = active.filter((c) => c.t === "min");
  if (minute.length) {
    const fee = minute.reduce((a, b) => ((b.f || 0) < (a.f || 0) ? b : a));
    price.minuteFee = fee.v;
    price.minuteFeeFrom = fee.f ?? null;
  }
  const session = active.filter((c) => c.t === "base" || c.t === "flat").map((c) => c.v);
  if (session.length) price.sessionFee = session.reduce((a, b) => a + b, 0);
  return price;
}

// --------------------------------------------------------------------------
// Suche
// --------------------------------------------------------------------------

function groupMatches(group, filters) {
  if (filters.minPowerKw > 0) {
    if (group.kw == null || group.kw < filters.minPowerKw) return false;
  }
  if (filters.current !== "any" && group.c !== filters.current) return false;
  if (filters.connector !== "any") {
    const wanted = CONNECTOR_ALIASES[filters.connector] || [filters.connector];
    if (!wanted.some((k) => (group.k || []).includes(k))) return false;
  }
  return true;
}

function operatorMatches(station, operators) {
  if (!operators.length) return true;
  const haystack = [station.o, station.b].filter(Boolean).join(" ").toLowerCase();
  return operators.some((op) => haystack.includes(op.toLowerCase()));
}

export function normalizeFilters(filters = {}) {
  return {
    minPowerKw: filters.minPowerKw || 0,
    current: filters.current || "any",
    connector: filters.connector || "any",
    operators: filters.operators || [],
    tariff: filters.tariff || "adhoc",
  };
}

const TARIFF_POLICY = { contract: "contract", subscription: "subscription" };

function bestRate(rates, indexes, local, state, policy) {
  let best = null;
  for (const index of indexes || []) {
    if (!(index >= 0 && index < rates.length)) continue;
    const rate = rates[index];
    if (policy && rate.pol !== policy) continue;
    const price = currentPrice(rate, local, state);
    if (price === null) continue;
    price.tariff = rate.pol || "adHoc";
    price.tariffName = rate.n || null;
    if (best === null || price.kwh < best.kwh) best = price;
  }
  return best;
}

/** Günstigstes passendes Angebot einer Station oder null. */
export function bestOffer(station, lat, lon, filters, local) {
  if (!operatorMatches(station, filters.operators)) return null;
  const prefer = TARIFF_POLICY[filters.tariff] || null;
  const state = station.bl ?? null;
  let best = null;
  for (const group of station.g || []) {
    if (!groupMatches(group, filters)) continue;
    let price = prefer ? bestRate(station.x || [], group.x, local, state, prefer) : null;
    if (price === null) price = bestRate(station.r || [], group.r, local, state, null);
    if (price === null) continue;
    if (
      best === null ||
      price.kwh < best.price.kwh ||
      (price.kwh === best.price.kwh && (group.kw || 0) > (best.group.kw || 0))
    ) {
      best = { price, group };
    }
  }
  if (best === null) return null;
  const { price, group } = best;
  return {
    stationId: station.id,
    operator: station.o || station.b || null,
    address: station.a || null,
    latitude: station.la,
    longitude: station.lo,
    distanceKm: distanceKm(lat, lon, station.la, station.lo),
    price,
    powerKw: group.kw ?? null,
    current: group.c ?? null,
    connectors: [...(group.k || [])],
    points: group.n || 0,
    until: null,
    nextPrice: null,
  };
}

const round4 = (x) => Math.round(x * 1e4) / 1e4;

function safe(fn) {
  try {
    return fn();
  } catch {
    return undefined;
  }
}

export function stationsInRadius(stations, lat, lon, radiusKm) {
  return stations.filter((s) => {
    const d = safe(() => distanceKm(lat, lon, s.la, s.lo));
    return d !== undefined && d <= radiusKm;
  });
}

export function findOffers(stations, lat, lon, radiusKm, filters, nowMs) {
  const local = localTime(nowMs);
  const offers = [];
  for (const station of stations) {
    if (!(distanceKm(lat, lon, station.la, station.lo) <= radiusKm)) continue;
    const offer = safe(() => bestOffer(station, lat, lon, filters, local));
    if (offer) offers.push(offer);
  }
  offers.sort((a, b) => round4(a.price.kwh) - round4(b.price.kwh) || a.distanceKm - b.distanceKm);
  return offers;
}

export function countStations(stations, lat, lon, radiusKm, filters) {
  let total = 0;
  for (const station of stations) {
    if (!(distanceKm(lat, lon, station.la, station.lo) <= radiusKm)) continue;
    if (operatorMatches(station, filters.operators) && (station.g || []).some((g) => groupMatches(g, filters))) {
      total += 1;
    }
  }
  return total;
}

// --------------------------------------------------------------------------
// Vorschau: Preiswechsel in den nächsten 24 Stunden
// --------------------------------------------------------------------------

const hasTime = (w) => Boolean(w && (filled(w.in) || filled(w.ex) || w.s || w.e));

export function isTimeDependent(station) {
  const rates = [...(station.r || []), ...(station.x || [])];
  return rates.some((rate) => hasTime(rate.w) || (rate.p || []).some((c) => hasTime(c.w)));
}

/** Viertelstunden ab der nächsten vollen Viertelstunde, wie future_steps. */
export function futureSteps(nowMs, count = HORIZON_STEPS) {
  const minute = Math.floor(nowMs / 60000) * 60000;
  const hour = Math.floor(minute / 3600000) * 3600000;
  const minutes = (minute - hour) / 60000;
  const first = hour + (Math.floor(minutes / 15) + 1) * STEP_MS;
  return Array.from({ length: count }, (_, i) => first + i * STEP_MS);
}

function stepLocals(steps) {
  return steps.map((t) => localTime(t));
}

export function nextChange(station, lat, lon, filters, currentKwh, locals) {
  for (const local of locals) {
    const offer = bestOffer(station, lat, lon, filters, local);
    const price = offer ? offer.price.kwh : null;
    if (price === null || round4(price) !== round4(currentKwh)) return [local.t, price];
  }
  return [null, null];
}

export function annotateChanges(offers, byId, lat, lon, filters, locals) {
  for (const offer of offers) {
    const station = byId.get(offer.stationId);
    if (!station || !isTimeDependent(station)) continue;
    [offer.until, offer.nextPrice] = nextChange(station, lat, lon, filters, offer.price.kwh, locals);
  }
}

export function cheapestAhead(nearby, current, lat, lon, filters, nowMs, locals) {
  let best = current;
  let start = nowMs;
  const dependent = nearby.filter(isTimeDependent);
  for (const local of locals) {
    for (const station of dependent) {
      const offer = safe(() => bestOffer(station, lat, lon, filters, local));
      if (offer && (best === null || offer.price.kwh < best.price.kwh - 1e-9)) {
        best = offer;
        start = local.t;
      }
    }
  }
  if (best === null) return null;
  const station = nearby.find((s) => s.id === best.stationId);
  let end = null;
  if (station && isTimeDependent(station)) {
    [end] = nextChange(station, lat, lon, filters, best.price.kwh, locals.filter((l) => l.t > start));
  }
  return { offer: best, start, end };
}

/** Alles für eine Anzeige: Angebote (Top 5 mit Zeitfenster), Vorschau, Anzahl. */
export function evaluate(stations, lat, lon, radiusKm, rawFilters, nowMs, annotate = TOP_OFFERS) {
  const filters = normalizeFilters(rawFilters);
  const nearby = stationsInRadius(stations, lat, lon, radiusKm);
  const offers = findOffers(nearby, lat, lon, radiusKm, filters, nowMs);
  const locals = stepLocals(futureSteps(nowMs));
  const byId = new Map(nearby.filter((s) => "id" in s).map((s) => [s.id, s]));
  annotateChanges(offers.slice(0, annotate), byId, lat, lon, filters, locals);
  const outlook = cheapestAhead(nearby, offers[0] || null, lat, lon, filters, nowMs, locals);
  const count = countStations(nearby, lat, lon, radiusKm, filters);
  return { offers, outlook, count };
}
