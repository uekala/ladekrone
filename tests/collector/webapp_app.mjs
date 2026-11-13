// Prüft die reinen Funktionen der Web-App (für test_webapp_app.py).
import { pathToFileURL } from "node:url";

const appUrl = pathToFileURL(process.argv[2]);
const { shareUrl, parseShared, breakEvenKwh, loadTiles } = await import(appUrl.href);
const { tilesForRadius } = await import(new URL("./pricing.js", appUrl).href);
const base = "https://example.org/ladekrone/app/?alt=1#x";
const place = { lat: 51.33456789, lon: 6.56712345, label: "Krefeld & Umgebung", gps: false };
const filters = { radius: 25, power: 150, operator: "Netz A/B", connector: "ccs", tariff: "subscription", charge: 40 };
const url = shareUrl(base, place, filters);
const plain = shareUrl(base, { ...place, gps: true, label: "In deiner Nähe" },
  { radius: 10, power: 0, operator: "", connector: "any", tariff: "adhoc", charge: 0 });

// Datenstand: meta.json nach 15 Minuten neu holen, ein neuer Stand verwirft die Kacheln.
const HOME = [50.11, 8.68, 5];
let clock = Date.parse("2026-11-12T10:00:00Z");
Date.now = () => clock;
const server = { generated: "2026-11-12T09:00:00+00:00", price: 0.49, down: false };
const calls = { meta: 0, tiles: 0 };
globalThis.document = { getElementById: () => ({}) };
globalThis.fetch = async (url) => {
  if (server.down) throw new TypeError("offline");
  const isMeta = String(url).endsWith("meta.json");
  calls[isMeta ? "meta" : "tiles"] += 1;
  const body = isMeta
    ? { v: 1, generated: server.generated, tile_deg: 0.25, tiles: tilesForRadius(...HOME, 0.25) }
    : { stations: [{ id: "s", price: server.price }] };
  return { ok: true, status: 200, headers: { get: () => null }, json: async () => body };
};
const load = async () => {
  const { stations, failed } = await loadTiles(...HOME);
  return { price: stations[0]?.price ?? null, failed, meta: calls.meta, tiles: calls.tiles };
};
const refresh = [await load()];
Object.assign(server, { generated: "2026-11-12T15:00:00+00:00", price: 0.29 });
clock += 5 * 60000; // noch frisch: kein Abruf
refresh.push(await load());
clock += 11 * 60000; // älter als 15 Minuten: neuer Datenstand
refresh.push(await load());
clock += 16 * 60000; // Datenstand unverändert: Kacheln bleiben
refresh.push(await load());
clock += 16 * 60000; // ohne Netz: bisheriger Stand
server.down = true;
refresh.push(await load());

process.stdout.write(JSON.stringify({
  refresh,
  url,
  plain,
  back: parseShared(new URL(url).search),
  defaults: parseShared(new URL(plain).search),
  none: parseShared("?foo=1"),
  bad: [parseShared("?lat=abc&lon=6"), parseShared("?lat=95&lon=6"), parseShared("?lat=51&lon=600")],
  hostile: parseShared("?lat=51&lon=6&r=999&kw=7&stecker=%3Cscript%3E&tarif=x&kwh=-1&ort=" + "A".repeat(500)),
  even: [breakEvenKwh(9.99, 0.59, 0.39), breakEvenKwh(0, 0.59, 0.39), breakEvenKwh(9.99, 0.39, 0.39), breakEvenKwh(5, 0.4, 0.5)],
}));
