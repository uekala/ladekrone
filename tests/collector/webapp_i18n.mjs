// Vergleicht die Texte beider Sprachen (für test_webapp_i18n.py).
import { pathToFileURL } from "node:url";

const { TEXT, LANGS, pickLang } = await import(pathToFileURL(process.argv[2]).href);
const shape = (value) => (typeof value === "function" ? `fn${value.length}` : typeof value);
const keys = (lang) => Object.fromEntries(Object.entries(TEXT[lang]).filter(([k]) => k !== "page").map(([k, v]) => [k, shape(v)]));
const page = TEXT.en.page;
process.stdout.write(JSON.stringify({
  langs: LANGS,
  de: keys("de"),
  en: keys("en"),
  page: { text: Object.keys(page.text), html: Object.keys(page.html), attrs: Object.keys(page.attrs), options: page.options },
  pick: [
    pickLang(null, ["de-AT", "en"]), pickLang(null, ["fr-FR", "de"]), pickLang(null, ["fr-FR"]),
    pickLang("en", ["de-DE"]), pickLang("xx", ["de-DE"]), pickLang(null, []), pickLang(null, undefined),
  ],
}));
