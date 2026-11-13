// Prüft die reinen Funktionen der Web-App (für test_webapp_app.py).
import { pathToFileURL } from "node:url";

const { shareUrl, parseShared, breakEvenKwh } = await import(pathToFileURL(process.argv[2]).href);
const base = "https://example.org/ladekrone/app/?alt=1#x";
const place = { lat: 51.33456789, lon: 6.56712345, label: "Krefeld & Umgebung", gps: false };
const filters = { radius: 25, power: 150, operator: "Netz A/B", connector: "ccs", tariff: "subscription", charge: 40 };
const url = shareUrl(base, place, filters);
const plain = shareUrl(base, { ...place, gps: true, label: "In deiner Nähe" },
  { radius: 10, power: 0, operator: "", connector: "any", tariff: "adhoc", charge: 0 });
process.stdout.write(JSON.stringify({
  url,
  plain,
  back: parseShared(new URL(url).search),
  defaults: parseShared(new URL(plain).search),
  none: parseShared("?foo=1"),
  bad: [parseShared("?lat=abc&lon=6"), parseShared("?lat=95&lon=6"), parseShared("?lat=51&lon=600")],
  hostile: parseShared("?lat=51&lon=6&r=999&kw=7&stecker=%3Cscript%3E&tarif=x&kwh=-1&ort=" + "A".repeat(500)),
  even: [breakEvenKwh(9.99, 0.59, 0.39), breakEvenKwh(0, 0.59, 0.39), breakEvenKwh(9.99, 0.39, 0.39), breakEvenKwh(5, 0.4, 0.5)],
}));
