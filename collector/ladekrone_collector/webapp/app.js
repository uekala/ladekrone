import { evaluate, localTime, tilesForRadius, distanceKm, offerRank } from "./pricing.js";
import { TEXT, pickLang } from "./i18n.js";

const DATA = "../v1/";
const SHOWN = 30; // so viele Stationen höchstens in der Liste
const $ = (id) => document.getElementById(id);

const store = {
  get(key, fallback) {
    try {
      const raw = localStorage.getItem(`ladekrone.${key}`);
      return raw === null ? fallback : JSON.parse(raw);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(`ladekrone.${key}`, JSON.stringify(value));
    } catch {
      /* privater Modus: dann eben ohne Merken */
    }
  },
};

// Sprache: gespeicherte Wahl, sonst die des Browsers
// (ohne Seite, etwa in Tests, immer Deutsch)
const lang = pickLang(store.get("lang", null), typeof document === "undefined" ? [] : navigator.languages);
const T = TEXT[lang];

const euro = new Intl.NumberFormat(T.locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const one = new Intl.NumberFormat(T.locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const whole = new Intl.NumberFormat(T.locale);
const clock = new Intl.DateTimeFormat(T.locale, { timeZone: "Europe/Berlin", hour: "2-digit", minute: "2-digit" });
const dateLong = new Intl.DateTimeFormat(T.locale, {
  timeZone: "Europe/Berlin", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit",
});
const dateShort = new Intl.DateTimeFormat(T.locale, {
  timeZone: "Europe/Berlin", day: "2-digit", month: "2-digit", year: "numeric",
});
// Betreiber melden einen Tarif meist nur bei einer Änderung neu; wie in der
// Integration gilt ein Preis erst nach 30 Tagen ohne Meldung als alt.
const PRICE_STALE_MS = 30 * 24 * 3600 * 1000;
// Bleibt die App lange offen (installiert im Hintergrund), soll ein neuer Datenstand
// des Sammlers trotzdem ankommen: meta.json höchstens so lange wiederverwenden.
const META_MAX_AGE_MS = 15 * 60 * 1000;
const CONNECTORS = { ccs: "CCS", type2: T.type2, chademo: "CHAdeMO" };

// ---------------------------------------------------------------------------
// Zustand und Einstellungen (nur auf diesem Gerät)
// ---------------------------------------------------------------------------


const state = {
  meta: null,
  metaFetched: 0,
  tiles: new Map(),
  place: null, // {lat, lon, label, gps}
  filters: { power: 0, radius: 10, operator: "", connector: "any", tariff: "adhoc", charge: 0, ...store.get("filters", {}) },
  quarter: null,
  offline: false,
  check: null, // Preise für den Tarif-Vergleich des Gewinners
};

// ---------------------------------------------------------------------------
// Hilfen
// ---------------------------------------------------------------------------

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);

function splitAddress(address) {
  if (!address) return { street: "", city: "" };
  const parts = address.split(", ");
  const last = parts.length > 1 ? parts.pop() : "";
  return { street: parts.join(", "), city: last.replace(/^\d{5}\s+/, "") };
}

function when(ms) {
  const now = localTime(Date.now());
  const then = localTime(ms);
  const sameDay = now.year === then.year && now.month === then.month && now.day === then.day;
  const tomorrow = localTime(ms - 86400000);
  const isTomorrow = tomorrow.year === now.year && tomorrow.month === now.month && tomorrow.day === now.day;
  const prefix = sameDay ? "" : isTomorrow ? T.tomorrow : T.dayAfter;
  return `${prefix}${T.clock(clock.format(ms))}`;
}

function routeUrl(lat, lon) {
  const apple = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  return apple
    ? `https://maps.apple.com/?daddr=${lat},${lon}`
    : `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`;
}

function facts(offer) {
  const items = [T.away(one.format(offer.distanceKm))];
  if (offer.powerKw) items.push(`${whole.format(Math.round(offer.powerKw))} kW`);
  const plugs = offer.connectors.map((k) => CONNECTORS[k] || k).join(", ");
  const kind = [offer.current ? offer.current.toUpperCase() : "", plugs].filter(Boolean).join(" ");
  if (kind) items.push(kind);
  if (offer.points > 1) items.push(T.points(offer.points));
  return items;
}

function feeText(price) {
  const parts = [];
  if (price.sessionFee) parts.push(T.sessionFee(euro.format(price.sessionFee)));
  if (price.minuteFee) {
    parts.push(
      price.minuteFeeFrom
        ? T.blockFee(euro.format(price.minuteFee), price.minuteFeeFrom)
        : T.timeFee(euro.format(price.minuteFee)),
    );
  }
  return parts.join(". ");
}

function untilText(offer) {
  if (!offer.until) return "";
  if (offer.nextPrice === null) return T.untilNone(when(offer.until));
  return T.untilNext(when(offer.until), euro.format(offer.nextPrice));
}

function note(text, kind = "") {
  const el = $("note");
  el.textContent = text;
  el.className = `note ${kind}`;
  el.hidden = !text;
}

// ---------------------------------------------------------------------------
// Daten laden
// ---------------------------------------------------------------------------

async function getJson(path) {
  const response = await fetch(DATA + path);
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  if (response.headers.get("x-ladekrone-cache") === "1") state.offline = true;
  return response.json();
}

async function loadMeta() {
  if (state.meta && Date.now() - state.metaFetched < META_MAX_AGE_MS) return state.meta;
  let meta;
  try {
    meta = await getJson("meta.json");
  } catch (error) {
    if (state.meta) return state.meta; // ohne Netz mit dem bisherigen Stand weiter
    throw error;
  }
  // Neuer Datenstand: geladene Kacheln verwerfen, sonst blieben alte Preise stehen.
  if (state.meta && state.meta.generated !== meta.generated) state.tiles.clear();
  meta.tileSet = new Set(meta.tiles);
  state.meta = meta;
  state.metaFetched = Date.now();
  $("stand").textContent = T.stand(dateLong.format(new Date(meta.generated)));
  return meta;
}

export async function loadTiles(lat, lon, radius) {
  const meta = await loadMeta();
  const keys = tilesForRadius(lat, lon, radius, meta.tile_deg).filter((k) => meta.tileSet.has(k));
  const missing = keys.filter((k) => !state.tiles.has(k));
  const results = await Promise.allSettled(missing.map((k) => getJson(`tiles/${k}.json`)));
  let failed = 0;
  results.forEach((result, i) => {
    if (result.status === "fulfilled") state.tiles.set(missing[i], result.value.stations || []);
    else failed += 1;
  });
  return { stations: keys.flatMap((k) => state.tiles.get(k) || []), failed };
}

// Ortsverzeichnis für Suche und "In der Nähe von …"
let placesPromise = null;
function loadPlaces() {
  placesPromise ??= getJson("places.json").then(({ places }) => buildPlaceIndex(places)).catch(() => {
    placesPromise = null;
    return null;
  });
  return placesPromise;
}

const fold = (s) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/ß/g, "ss");
const foldUmlaut = (s) =>
  s.toLowerCase().replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss")
    .normalize("NFD").replace(/[̀-ͯ]/g, "");

function buildPlaceIndex(rows) {
  const postcodes = rows.map(([plz, city, lat, lon, n]) => ({ plz, city, lat, lon, n }));
  // Gleichnamige Orte zusammenfassen, solange sie nah beieinander liegen (Berlin hat viele PLZ).
  const byName = new Map();
  for (const p of postcodes) {
    const key = fold(p.city);
    const clusters = byName.get(key) || [];
    let cluster = clusters.find((c) => distanceKm(c.lat, c.lon, p.lat, p.lon) < 25);
    if (!cluster) {
      cluster = { city: p.city, lat: 0, lon: 0, n: 0, plz: p.plz, top: 0 };
      clusters.push(cluster);
    }
    cluster.lat = (cluster.lat * cluster.n + p.lat * p.n) / (cluster.n + p.n);
    cluster.lon = (cluster.lon * cluster.n + p.lon * p.n) / (cluster.n + p.n);
    cluster.n += p.n;
    if (p.n > cluster.top) {
      cluster.top = p.n;
      cluster.plz = p.plz;
    }
    byName.set(key, clusters);
  }
  const cities = [];
  for (const clusters of byName.values()) {
    for (const c of clusters) {
      const hint = clusters.length > 1 ? T.plzHint(c.plz.slice(0, 2)) : "";
      const words = [c.city, ...c.city.split(/[\s-]+/).slice(1)];
      cities.push({ ...c, hint, keys: words.flatMap((w) => [fold(w), foldUmlaut(w)]) });
    }
  }
  cities.sort((a, b) => b.n - a.n);
  return { postcodes, cities };
}

function searchPlaces(index, query) {
  const q = query.trim();
  if (!q) return [];
  if (/^\d+$/.test(q)) {
    return index.postcodes
      .filter((p) => p.plz.startsWith(q))
      .slice(0, 8)
      .map((p) => ({ label: `${p.plz} ${p.city}`, hint: "", lat: p.lat, lon: p.lon }));
  }
  const a = fold(q);
  const b = foldUmlaut(q);
  return index.cities
    .filter((c) => c.keys.some((k) => k.startsWith(a) || k.startsWith(b)))
    .slice(0, 8)
    .map((c) => ({ label: c.city, hint: c.hint, lat: c.lat, lon: c.lon }));
}

function nearestCity(index, lat, lon) {
  let best = null;
  for (const p of index.postcodes) {
    const d = distanceKm(lat, lon, p.lat, p.lon);
    if (d < 15 && (!best || d < best.d)) best = { d, city: p.city };
  }
  return best?.city || null;
}

// ---------------------------------------------------------------------------
// Anzeige
// ---------------------------------------------------------------------------

function oldPriceDate(price) {
  const updated = Date.parse(price.updated ?? "");
  if (Number.isNaN(updated) || Date.now() - updated <= PRICE_STALE_MS) return "";
  return dateShort.format(updated);
}

function totalText(offer, short = false) {
  if (offer.totalCost == null || !offer.chargeKwh) return "";
  return (short ? T.totalShort : T.total)(whole.format(offer.chargeKwh), euro.format(offer.totalCost));
}

function trendText(offer) {
  if (offer.previousPrice == null || !offer.priceSince) return "";
  const since = Date.parse(`${offer.priceSince}T12:00:00Z`);
  const cents = Math.round((offer.price.kwh - offer.previousPrice) * 100);
  if (Number.isNaN(since) || !cents) return "";
  return T.trend(cents > 0, dateShort.format(since), whole.format(Math.abs(cents)), euro.format(offer.previousPrice));
}

/** Ab wie vielen kWh im Monat sich ein Tarif mit Grundgebühr gegenüber ad hoc lohnt. */
export function breakEvenKwh(monthlyFee, adhocKwh, tariffKwh) {
  const saving = adhocKwh - tariffKwh;
  if (!(monthlyFee > 0) || !(saving > 1e-9)) return null;
  return monthlyFee / saving;
}

function renderTariffCheck(offer, adhoc) {
  if (offer.price.tariff === "adHoc" || !adhoc) return "";
  const saving = adhoc.price.kwh - offer.price.kwh;
  if (!(saving > 1e-9)) {
    return `<aside class="check"><strong>${esc(T.noBenefit)}</strong>
      <p>${esc(T.adhocCosts(euro.format(adhoc.price.kwh)))}</p></aside>`;
  }
  const fee = Number(store.get("monthlyFee", 0)) || 0;
  const even = breakEvenKwh(fee, adhoc.price.kwh, offer.price.kwh);
  const result = even === null ? T.enterFee : T.worthFrom(whole.format(Math.ceil(even)));
  return `<aside class="check" aria-label="${esc(T.checkLabel)}">
    <strong>${esc(T.cheaperBy(whole.format(Math.round(saving * 100)), euro.format(adhoc.price.kwh)))}</strong>
    <label>${esc(T.monthlyFee)}
      <input id="monthly-fee" type="number" inputmode="decimal" min="0" max="99" step="0.01" value="${fee || ""}" placeholder="${esc(T.feePlaceholder)}"> €</label>
    <p id="check-result">${esc(result)}</p>
  </aside>`;
}

function priceNote(offer) {
  const kind = offer.price.tariff;
  if (kind && kind !== "adHoc") {
    const label = offer.price.tariffName || { contract: T.contract, subscription: T.subscription }[kind] || kind;
    return `<p class="price-note"><strong>${esc(label)}</strong>${esc(T.tariffNote)}</p>`;
  }
  return `<p class="price-note"><strong>${esc(T.adhocStrong)}</strong>${esc(T.adhocNote)}</p>`;
}

function renderWinner(offer) {
  const { street, city } = splitAddress(offer.address);
  const fees = feeText(offer.price);
  return `<article class="winner" aria-labelledby="winner-price">
    <p class="label"><img src="icons/icon-192.png" alt="">${esc(T.cheapestNow)}</p>
    <p class="price" id="winner-price"><span class="num">${euro.format(offer.price.kwh)}</span><span class="unit">€/kWh</span></p>
    ${totalText(offer) ? `<p class="total">${esc(totalText(offer))}</p>` : ""}
    ${priceNote(offer)}
    ${oldPriceDate(offer.price) ? `<p class="price-old">${esc(T.oldPrice(oldPriceDate(offer.price)))}</p>` : ""}
    ${trendText(offer) ? `<p class="trend">${esc(trendText(offer))}</p>` : ""}
    <p class="who">${esc(offer.operator || T.unknownNetwork)}</p>
    <p class="addr">${esc([street, city].filter(Boolean).join(", "))}</p>
    <ul class="facts">${facts(offer).map((f) => `<li>${esc(f)}</li>`).join("")}</ul>
    ${offer.until ? `<p class="until">${esc(untilText(offer))}</p>` : ""}
    ${fees ? `<p class="fees">${esc(fees)}</p>` : ""}
    <div class="actions"><a class="btn primary" href="${routeUrl(offer.latitude, offer.longitude)}" target="_blank" rel="noopener">${esc(T.route)}</a></div>
  </article>`;
}

const CLOCK_ICON =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2a10 10 0 1 1 0 20 10 10 0 0 1 0-20Zm0 2a8 8 0 1 0 0 16 8 8 0 0 0 0-16Zm0 2.2a1 1 0 0 1 1 1v4.4l3 1.8a1 1 0 1 1-1 1.7l-3.5-2.1a1 1 0 0 1-.5-.9V7.2a1 1 0 0 1 1-1Z"/></svg>';

function renderLater(outlook, current) {
  if (!outlook || !current || outlook.start === null || offerRank(outlook.offer) >= offerRank(current) - 1e-9) return "";
  const o = outlook.offer;
  const { city } = splitAddress(o.address);
  const text = T.laterText(when(outlook.start), outlook.end ? when(outlook.end) : "", o.operator || T.unknown, city, one.format(o.distanceKm));
  return `<aside class="later" aria-label="${esc(T.laterLabel)}">${CLOCK_ICON}
    <strong>${esc(T.laterTitle(euro.format(o.price.kwh)))}</strong>
    <p>${esc(text)}</p>
  </aside>`;
}

function renderList(offers) {
  if (!offers.length) return "";
  const rows = offers.map((o) => {
    const { street, city } = splitAddress(o.address);
    const fees = feeText(o.price);
    const head = [city || street, `${one.format(o.distanceKm)} km`, o.powerKw ? `${whole.format(Math.round(o.powerKw))} kW` : ""]
      .filter(Boolean)
      .join(", ");
    return `<li><details>
      <summary>
        <span class="op">${esc(o.operator || T.unknownNetwork)}</span>
        <span class="p">${euro.format(o.price.kwh)}<small>€/kWh</small></span>
        <span class="sub">${esc(head)}</span>
        ${o.until ? `<span class="change">${esc(untilText(o))}</span>` : ""}
        ${oldPriceDate(o.price) ? `<span class="change old">${esc(T.oldShort(oldPriceDate(o.price)))}</span>` : ""}
        ${totalText(o, true) ? `<span class="change old">${esc(totalText(o, true))}</span>` : ""}
      </summary>
      <div class="detail">
        <p>${esc([street, city].filter(Boolean).join(", "))}</p>
        <p>${esc(facts(o).slice(1).join(", "))}</p>
        ${fees ? `<p>${esc(fees)}</p>` : ""}
        ${trendText(o) ? `<p>${esc(trendText(o))}</p>` : ""}
        <a class="btn" href="${routeUrl(o.latitude, o.longitude)}" target="_blank" rel="noopener">${esc(T.route)}</a>
      </div>
    </details></li>`;
  });
  return `<section class="more" aria-labelledby="more-title"><h3 id="more-title">${esc(T.more)}</h3>
    <ul class="list">${rows.join("")}</ul></section>`;
}

function renderEmpty(count) {
  const radius = state.filters.radius;
  const text = count
    ? T.emptyNoPrice(radius, whole.format(count))
    : T.emptyNone(radius);
  const bigger = [5, 10, 25, 50].find((r) => r > radius);
  const f = state.filters;
  const filtered = f.power > 0 || f.operator || f.connector !== "any";
  return `<div class="empty"><p>${esc(text)}</p><div class="actions">${
    bigger ? `<button class="btn" type="button" data-radius="${bigger}">${esc(T.bigger(bigger))}</button>` : ""
  }${filtered ? `<button class="btn ghost" type="button" data-reset>${esc(T.reset)}</button>` : ""}</div></div>`;
}

function updateOperatorOptions(stations) {
  const select = $("f-operator");
  const counts = new Map();
  for (const s of stations) {
    const name = s.o || s.b;
    if (name && (s.r || []).length) counts.set(name, (counts.get(name) || 0) + 1);
  }
  const names = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 40).map(([n]) => n);
  const chosen = state.filters.operator;
  if (chosen && !names.includes(chosen)) names.unshift(chosen);
  names.sort((a, b) => a.localeCompare(b, lang));
  select.innerHTML =
    `<option value="">${esc(T.allNetworks)}</option>` + names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
  select.value = chosen;
}

function syncFilterControls() {
  const f = state.filters;
  $("f-power").value = String(f.power);
  $("f-radius").value = String(f.radius);
  $("f-connector").value = f.connector;
  $("f-tariff").value = f.tariff || "adhoc";
  $("f-charge").value = String(f.charge || 0);
  $("f-charge").classList.toggle("set", (f.charge || 0) > 0);
  $("f-power").classList.toggle("set", f.power > 0);
  $("f-operator").classList.toggle("set", Boolean(f.operator));
  $("f-connector").classList.toggle("set", f.connector !== "any");
  $("f-tariff").classList.toggle("set", (f.tariff || "adhoc") !== "adhoc");
}

let renderToken = 0;
async function render() {
  const place = state.place;
  if (!place) return;
  const token = ++renderToken;
  state.offline = !navigator.onLine;
  document.body.classList.add("has-place");
  $("results").hidden = false;
  $("place-title").textContent = place.label;
  syncFilterControls();
  const f = state.filters;
  if (!$("winner").innerHTML) {
    $("winner").innerHTML = `<p class="loading">${esc(T.loading)}</p>`;
  }
  let loaded;
  try {
    loaded = await loadTiles(place.lat, place.lon, f.radius);
  } catch {
    if (token !== renderToken) return;
    $("winner").innerHTML = "";
    $("later").innerHTML = "";
    $("more").innerHTML = "";
    $("summary").textContent = "";
    note(T.loadError, "error");
    return;
  }
  if (token !== renderToken) return;
  const now = Date.now();
  state.quarter = Math.floor(now / 900000);
  const filters = {
    minPowerKw: f.power,
    connector: f.connector,
    operators: f.operator ? [f.operator] : [],
    tariff: f.tariff || "adhoc",
    chargeKwh: f.charge || 0,
  };
  const { offers, outlook, count } = evaluate(loaded.stations, place.lat, place.lon, f.radius, filters, now, SHOWN + 1);
  renderPlaceTools();
  updateOperatorOptions(loaded.stations);
  if (loaded.failed) note(T.partial, "error");
  else if (state.offline) note(T.offline);
  else note("");
  mapState.offers = offers;
  updateMap();
  if (!offers.length) {
    $("winner").innerHTML = renderEmpty(count);
    $("later").innerHTML = "";
    $("more").innerHTML = "";
    $("summary").textContent = "";
    return;
  }
  let adhoc = null;
  if (offers[0].price.tariff !== "adHoc") {
    // Zum Vergleich: der Ad-hoc-Preis an derselben Station
    const plain = evaluate(loaded.stations, place.lat, place.lon, f.radius, { ...filters, tariff: "adhoc", chargeKwh: 0 }, now, 0);
    adhoc = plain.offers.find((o) => o.stationId === offers[0].stationId) || null;
  }
  state.check = adhoc ? { adhoc: adhoc.price.kwh, tariff: offers[0].price.kwh } : null;
  $("winner").innerHTML = renderWinner(offers[0]) + renderTariffCheck(offers[0], adhoc);
  $("later").innerHTML = renderLater(outlook, offers[0]);
  $("more").innerHTML = renderList(offers.slice(1, SHOWN + 1));
  $("summary").textContent =
    T.summary(whole.format(offers.reduce((sum, o) => sum + o.merged, 0)), whole.format(count), f.radius);
}

// ---------------------------------------------------------------------------
// Merken und Teilen
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Karte (erst auf Wunsch: lädt dann die Kartenbibliothek und Kartendaten von OpenFreeMap)
// ---------------------------------------------------------------------------

const MAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";
const MAP_MARKERS = 40;
const mapState = { open: false, map: null, markers: [], loading: null, offers: [], drawn: "" };

function loadMapLibrary() {
  mapState.loading ??= new Promise((resolve, reject) => {
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = "vendor/maplibre-gl.css";
    document.head.append(css);
    const script = document.createElement("script");
    script.src = "vendor/maplibre-gl.js";
    script.onload = () => (window.maplibregl ? resolve(window.maplibregl) : reject(new Error("maplibre")));
    script.onerror = () => reject(new Error("maplibre"));
    document.head.append(script);
  }).catch((error) => {
    mapState.loading = null;
    throw error;
  });
  return mapState.loading;
}

function popupContent(offer) {
  const box = document.createElement("div");
  box.className = "map-popup";
  const title = document.createElement("strong");
  title.textContent = offer.operator || T.unknownNetwork;
  const price = document.createElement("p");
  price.textContent = `${euro.format(offer.price.kwh)} €/kWh · ${facts(offer).slice(1).join(", ")}`;
  const address = document.createElement("p");
  address.textContent = offer.address || "";
  const route = document.createElement("a");
  route.href = routeUrl(offer.latitude, offer.longitude);
  route.target = "_blank";
  route.rel = "noopener";
  route.textContent = T.route;
  box.append(title, price, address, route);
  return box;
}

function drawMarkers(lib) {
  const { map } = mapState;
  const place = state.place;
  if (!map || !place) return;
  // Nur neu zeichnen, wenn sich Ort oder Angebote geändert haben: Sonst spränge die
  // Karte bei jeder Aktualisierung zurück, während jemand sie verschiebt.
  const key = JSON.stringify([place.lat, place.lon, mapState.offers.slice(0, MAP_MARKERS).map((o) => [o.stationId, o.price.kwh])]);
  if (key === mapState.drawn) return;
  mapState.drawn = key;
  mapState.markers.forEach((marker) => marker.remove());
  mapState.markers = [];
  const bounds = new lib.LngLatBounds([place.lon, place.lat], [place.lon, place.lat]);
  const here = document.createElement("div");
  here.className = "map-here";
  here.setAttribute("aria-label", place.label);
  mapState.markers.push(new lib.Marker({ element: here }).setLngLat([place.lon, place.lat]).addTo(map));
  // Rückwärts einsetzen, damit der günstigste Preis oben liegt.
  mapState.offers.slice(0, MAP_MARKERS).reverse().forEach((offer, index, list) => {
    const best = index === list.length - 1;
    const pin = document.createElement("button");
    pin.type = "button";
    pin.className = best ? "map-pin best" : "map-pin";
    pin.textContent = euro.format(offer.price.kwh);
    pin.setAttribute("aria-label", `${offer.operator || T.unknownNetwork}, ${euro.format(offer.price.kwh)} €/kWh`);
    const popup = new lib.Popup({ offset: 18, maxWidth: "220px" }).setDOMContent(popupContent(offer));
    const position = [offer.longitude, offer.latitude];
    mapState.markers.push(new lib.Marker({ element: pin }).setLngLat(position).setPopup(popup).addTo(map));
    bounds.extend(position);
  });
  map.fitBounds(bounds, { padding: 48, maxZoom: 14, duration: 0 });
}

async function updateMap() {
  const box = $("map");
  box.hidden = !mapState.open;
  const toggle = $("map-toggle");
  toggle.textContent = mapState.open ? T.mapHide : T.map;
  toggle.setAttribute("aria-pressed", String(mapState.open));
  if (!mapState.open || !state.place) return;
  try {
    const lib = await loadMapLibrary();
    if (!mapState.map) {
      mapState.map = new lib.Map({
        container: box,
        style: MAP_STYLE,
        center: [state.place.lon, state.place.lat],
        zoom: 11,
        attributionControl: { compact: true },
        cooperativeGestures: true, // Seite bleibt mit einem Finger scrollbar
      });
      mapState.map.addControl(new lib.NavigationControl({ showCompass: false }), "top-right");
      mapState.map.on("error", () => $("map-note").hidden = false);
    }
    mapState.map.resize();
    drawMarkers(lib);
  } catch {
    mapState.open = false;
    box.hidden = true;
    toggle.textContent = T.map;
    toggle.setAttribute("aria-pressed", "false");
    note(T.mapError, "error");
  }
}

function setupMap() {
  $("map-note").textContent = T.mapNote;
  $("map-toggle").addEventListener("click", () => {
    mapState.open = !mapState.open;
    $("map-note").hidden = true;
    updateMap();
  });
}

const MAX_FAVORITES = 8;
const samePlace = (a, b) => Math.abs(a.lat - b.lat) < 1e-4 && Math.abs(a.lon - b.lon) < 1e-4;

function favorites() {
  const list = store.get("favorites", []);
  return Array.isArray(list) ? list.filter((p) => p && typeof p.lat === "number" && typeof p.lon === "number") : [];
}

function renderFavorites() {
  const list = favorites();
  const box = $("favorites");
  box.hidden = !list.length;
  box.innerHTML = list
    .map((p, i) => `<button class="chip" type="button" data-favorite="${i}">${esc(p.label)}</button>`)
    .join("");
}

function renderPlaceTools() {
  const place = state.place;
  const star = $("favorite");
  // Der eigene Standort wandert mit; merken lässt sich nur ein fester Ort.
  star.hidden = !place || Boolean(place.gps);
  if (place && !place.gps) {
    const saved = favorites().some((p) => samePlace(p, place));
    star.setAttribute("aria-pressed", String(saved));
    star.textContent = saved ? T.saved : T.save;
  }
  $("share").hidden = !place;
  $("map-toggle").hidden = !place;
}

/** Adresse, die genau diese Suche wieder öffnet. Koordinaten auf etwa 100 m gerundet. */
export function shareUrl(base, place, filters) {
  const url = new URL(base);
  url.search = "";
  url.hash = "";
  const q = url.searchParams;
  q.set("lat", place.lat.toFixed(3));
  q.set("lon", place.lon.toFixed(3));
  if (place.label && !place.gps) q.set("ort", place.label);
  if (filters.radius !== 10) q.set("r", String(filters.radius));
  if (filters.power > 0) q.set("kw", String(filters.power));
  if (filters.operator) q.set("netz", filters.operator);
  if (filters.connector !== "any") q.set("stecker", filters.connector);
  if ((filters.tariff || "adhoc") !== "adhoc") q.set("tarif", filters.tariff);
  if (filters.charge > 0) q.set("kwh", String(filters.charge));
  return url.toString();
}

/** Liest eine geteilte Suche aus der Adresse; null, wenn keine gültige darin steht. */
export function parseShared(search) {
  const q = new URLSearchParams(search);
  const lat = Number(q.get("lat"));
  const lon = Number(q.get("lon"));
  if (!q.has("lat") || !q.has("lon") || !(Math.abs(lat) <= 90) || !(Math.abs(lon) <= 180)) return null;
  const pick = (key, allowed, fallback) => (allowed.includes(q.get(key)) ? q.get(key) : fallback);
  return {
    place: { lat, lon, label: (q.get("ort") || T.sharedSearch).slice(0, 80), gps: false },
    filters: {
      radius: Number(pick("r", ["5", "10", "25", "50"], "10")),
      power: Number(pick("kw", ["0", "22", "50", "150"], "0")),
      operator: (q.get("netz") || "").slice(0, 80),
      connector: pick("stecker", ["any", "ccs", "type2", "chademo"], "any"),
      tariff: pick("tarif", ["adhoc", "contract", "subscription"], "adhoc"),
      charge: Number(pick("kwh", ["0", "20", "40", "60", "80"], "0")),
    },
  };
}

async function share() {
  if (!state.place) return;
  const url = shareUrl(location.href, state.place, state.filters);
  const title = T.shareTitle(state.place.label);
  try {
    if (navigator.share) {
      await navigator.share({ title, url });
      return;
    }
    await navigator.clipboard.writeText(url);
    note(T.copied);
  } catch (error) {
    if (error && error.name === "AbortError") return;
    note(T.copyThis(url));
  }
}

function setupPlaceTools() {
  $("share").addEventListener("click", share);
  $("favorite").addEventListener("click", () => {
    const place = state.place;
    if (!place || place.gps) return;
    const list = favorites();
    const index = list.findIndex((p) => samePlace(p, place));
    if (index >= 0) list.splice(index, 1);
    else list.unshift({ lat: place.lat, lon: place.lon, label: place.label, gps: false });
    store.set("favorites", list.slice(0, MAX_FAVORITES));
    renderFavorites();
    renderPlaceTools();
  });
  $("favorites").addEventListener("click", (event) => {
    const button = event.target.closest("[data-favorite]");
    const place = button && favorites()[Number(button.dataset.favorite)];
    if (place) setPlace(place, true);
  });
  renderFavorites();
}

// ---------------------------------------------------------------------------
// Ort wählen
// ---------------------------------------------------------------------------

function setPlace(place, remember) {
  state.place = place;
  if (remember) store.set("place", place);
  render();
}

function locate() {
  if (!("geolocation" in navigator)) {
    note(T.noGeo, "error");
    $("q").focus();
    return;
  }
  note(T.locating);
  navigator.geolocation.getCurrentPosition(
    async ({ coords }) => {
      note("");
      const place = { lat: coords.latitude, lon: coords.longitude, label: T.nearYou, gps: true };
      setPlace(place, false);
      store.set("place", null);
      const index = await loadPlaces();
      const city = index && nearestCity(index, place.lat, place.lon);
      if (city && state.place === place) {
        place.label = T.nearCity(city);
        $("place-title").textContent = place.label;
      }
    },
    (error) => {
      const denied = error.code === error.PERMISSION_DENIED;
      note(
        denied
          ? T.geoDenied
          : T.geoFailed,
        "error",
      );
      $("q").focus();
    },
    { enableHighAccuracy: false, timeout: 15000, maximumAge: 120000 },
  );
}

function setupSearch() {
  const input = $("q");
  const list = $("suggestions");
  let items = [];
  let active = -1;

  const close = () => {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    active = -1;
  };
  const choose = (item) => {
    input.value = "";
    close();
    input.blur();
    setPlace({ lat: item.lat, lon: item.lon, label: item.label, gps: false }, true);
  };
  const highlight = (index) => {
    active = index;
    [...list.children].forEach((li, i) => li.setAttribute("aria-selected", String(i === index)));
    if (index >= 0) input.setAttribute("aria-activedescendant", `s-${index}`);
  };

  input.addEventListener("focus", () => loadPlaces());
  input.addEventListener("input", async () => {
    const query = input.value;
    const index = await loadPlaces();
    if (query !== input.value) return;
    if (!index) {
      note(T.searchDown, "error");
      return;
    }
    items = searchPlaces(index, query);
    if (!items.length) {
      if (query.trim().length >= 3) {
        list.innerHTML = '<li role="option" aria-disabled="true">Kein Ort gefunden</li>';
        list.hidden = false;
        input.setAttribute("aria-expanded", "true");
      } else close();
      return;
    }
    list.innerHTML = items
      .map((item, i) => `<li role="option" id="s-${i}" aria-selected="false">${esc(item.label)}${item.hint ? `<small>${esc(item.hint)}</small>` : ""}</li>`)
      .join("");
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    active = -1;
  });
  input.addEventListener("keydown", (event) => {
    if (list.hidden || !items.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      highlight((active + 1) % items.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      highlight((active - 1 + items.length) % items.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(items[Math.max(active, 0)]);
    } else if (event.key === "Escape") {
      close();
    }
  });
  list.addEventListener("pointerdown", (event) => {
    const li = event.target.closest("li[id]");
    if (!li) return;
    event.preventDefault();
    choose(items[Number(li.id.slice(2))]);
  });
  input.addEventListener("blur", () => setTimeout(close, 150));
}

function setupFilters() {
  const bind = (id, key, parse) =>
    $(id).addEventListener("change", (event) => {
      state.filters[key] = parse(event.target.value);
      store.set("filters", state.filters);
      render();
    });
  bind("f-power", "power", Number);
  bind("f-radius", "radius", Number);
  bind("f-operator", "operator", String);
  bind("f-connector", "connector", String);
  bind("f-tariff", "tariff", String);
  bind("f-charge", "charge", Number);
  $("winner").addEventListener("input", (event) => {
    if (event.target.id !== "monthly-fee" || !state.check) return;
    const fee = Number(event.target.value.replace(",", ".")) || 0;
    store.set("monthlyFee", fee);
    const even = breakEvenKwh(fee, state.check.adhoc, state.check.tariff);
    $("check-result").textContent = even === null ? T.enterFee : T.worthFrom(whole.format(Math.ceil(even)));
  });
  $("winner").addEventListener("click", (event) => {
    if (event.target.closest("[data-reset]")) {
      Object.assign(state.filters, { power: 0, operator: "", connector: "any", tariff: "adhoc", charge: 0 });
    } else {
      const button = event.target.closest("[data-radius]");
      if (!button) return;
      state.filters.radius = Number(button.dataset.radius);
    }
    store.set("filters", state.filters);
    render();
  });
}

// ---------------------------------------------------------------------------
// Installieren, offline, Start
// ---------------------------------------------------------------------------

function setupInstall() {
  let deferred = null;
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferred = event;
    $("install").hidden = false;
  });
  $("install").addEventListener("click", async () => {
    if (!deferred) return;
    deferred.prompt();
    await deferred.userChoice;
    deferred = null;
    $("install").hidden = true;
  });
  const standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent);
  if (ios && !standalone) {
    $("install-hint").textContent = T.iosHint;
    $("install-hint").hidden = false;
  }
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
}

/** Setzt die Texte der Seite in der gewählten Sprache und richtet den Sprachwechsel ein. */
function setupLanguage() {
  document.documentElement.lang = lang;
  const page = T.page;
  if (page) {
    document.title = page.title;
    document.querySelector('meta[name="description"]')?.setAttribute("content", page.description);
    for (const [key, text] of Object.entries(page.text)) {
      const el = document.querySelector(`[data-t="${key}"]`);
      if (el) el.textContent = text;
    }
    for (const [key, html] of Object.entries(page.html)) {
      const el = document.querySelector(`[data-t="${key}"]`);
      if (el) el.innerHTML = html; // feste Texte aus i18n.js, keine fremden Daten
    }
    for (const [key, attrs] of Object.entries(page.attrs)) {
      const el = document.querySelector(`[data-t="${key}"]`) || $(key);
      if (el) for (const [name, value] of Object.entries(attrs)) el.setAttribute(name, value);
    }
    for (const [id, options] of Object.entries(page.options)) {
      for (const option of $(id)?.options || []) {
        if (option.value in options) option.textContent = options[option.value];
      }
    }
  }
  const button = $("lang");
  button.textContent = T.otherLang;
  button.lang = lang === "de" ? "en" : "de";
  button.addEventListener("click", () => {
    store.set("lang", lang === "de" ? "en" : "de");
    location.reload();
  });
}

async function start() {
  setupLanguage();
  setupSearch();
  setupFilters();
  setupInstall();
  setupPlaceTools();
  setupMap();
  $("locate").addEventListener("click", locate);
  loadMeta().catch(() => note(T.loadErrorShort, "error"));

  const saved = store.get("place", null);
  let granted = false;
  try {
    granted = (await navigator.permissions?.query({ name: "geolocation" }))?.state === "granted";
  } catch {
    granted = false;
  }
  const shared = parseShared(location.search);
  if (shared) {
    // Eine geteilte Suche gilt nur für diesen Besuch und überschreibt nichts Gemerktes.
    Object.assign(state.filters, shared.filters);
    state.place = shared.place;
    history.replaceState(null, "", location.pathname);
    render();
  } else if (granted) locate();
  else if (saved && typeof saved.lat === "number") setPlace(saved, false);

  // Preise wechseln zur Viertelstunde (z. B. Nachttarif): dann neu rechnen.
  setInterval(() => {
    if (state.place && Math.floor(Date.now() / 900000) !== state.quarter) render();
  }, 30000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && state.place) render();
  });
}

if (typeof document !== "undefined") start();
