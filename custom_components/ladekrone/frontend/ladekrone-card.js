// Ladekrone-Karte: der günstigste Ad-hoc-Preis im Look der Ladekrone-Web-App.
// Kommt mit der Integration und braucht keine weiteren Karten.

const FONTS = {
  atkinson400: new URL("fonts/atkinson-400.woff2", import.meta.url).href,
  atkinson700: new URL("fonts/atkinson-700.woff2", import.meta.url).href,
  bricolage: new URL("fonts/bricolage.woff2", import.meta.url).href,
};

// Schriften gelten für das ganze Dokument, auch im Shadow DOM der Karte.
if (!document.getElementById("ladekrone-fonts")) {
  const style = document.createElement("style");
  style.id = "ladekrone-fonts";
  style.textContent = `
@font-face{font-family:"Ladekrone Atkinson";src:url(${FONTS.atkinson400}) format("woff2");font-weight:400;font-display:swap}
@font-face{font-family:"Ladekrone Atkinson";src:url(${FONTS.atkinson700}) format("woff2");font-weight:700;font-display:swap}
@font-face{font-family:"Ladekrone Bricolage";src:url(${FONTS.bricolage}) format("woff2");font-weight:200 800;font-display:swap}`;
  document.head.appendChild(style);
}

const TEXT = {
  de: {
    best: "Gerade am günstigsten",
    unknown: "Unbekanntes Ladenetz",
    away: (km) => `${km} km entfernt`,
    points: (n) => `${n} Ladepunkte`,
    connectors: { ccs: "CCS", type2: "Typ 2", chademo: "CHAdeMO" },
    until: (t, p) => `Gilt bis ${t}, danach ${p} €`,
    untilNone: (t) => `Gilt bis ${t}, danach ohne Ad-hoc-Preis`,
    sessionFee: (p) => `Startgebühr ${p} €`,
    blockFee: (p, m) => `Blockiergebühr ${p} € pro Minute ab Minute ${m}`,
    timeFee: (p) => `Zeitgebühr ${p} € pro Minute`,
    route: "Route starten",
    details: "Verlauf",
    later: (p) => `Später günstiger: ${p} €/kWh`,
    laterAt: (from, to, who, km) => `ab ${from}${to ? ` bis ${to}` : ""} bei ${who}, ${km} km`,
    more: "Weitere Stationen",
    summary: (n, m) => `${n} von ${m} passenden Stationen melden gerade einen Preis.`,
    stand: (d) => `Stand ${d}`,
    empty: (m) => (m ? `In der Nähe gibt es ${m} passende Stationen, aber keine meldet gerade einen Preis.`
      : "In der Nähe gibt es gerade keine passende Station."),
    unavailable: "Ladekrone hat gerade keine Daten.",
    missing: (e) => `Entität nicht gefunden: ${e}`,
    tomorrow: "morgen ",
    dayAfter: "übermorgen ",
    clock: (t) => `${t} Uhr`,
    adhoc: "Ad-hoc-Preise ohne Vertrag, gemeldet von den Ladenetzen.",
    tesla: "Supercharger-Preise laut AFIR, in der Tesla-App kann der Preis abweichen.",
    supercharger: (city) => `Supercharger ${city}`.trim(),
    editor: { entity: "Günstigster Preis (Ladekrone-Sensor)", title: "Überschrift", show_list: "Weitere Stationen zeigen" },
  },
  en: {
    best: "Cheapest right now",
    unknown: "Unknown network",
    away: (km) => `${km} km away`,
    points: (n) => `${n} charge points`,
    connectors: { ccs: "CCS", type2: "Type 2", chademo: "CHAdeMO" },
    until: (t, p) => `Valid until ${t}, then ${p} €`,
    untilNone: (t) => `Valid until ${t}, then no ad-hoc price`,
    sessionFee: (p) => `Session fee ${p} €`,
    blockFee: (p, m) => `Idle fee ${p} € per minute from minute ${m}`,
    timeFee: (p) => `Time fee ${p} € per minute`,
    route: "Start route",
    details: "History",
    later: (p) => `Cheaper later: ${p} €/kWh`,
    laterAt: (from, to, who, km) => `from ${from}${to ? ` to ${to}` : ""} at ${who}, ${km} km`,
    more: "More stations",
    summary: (n, m) => `${n} of ${m} matching stations report a price right now.`,
    stand: (d) => `As of ${d}`,
    empty: (m) => (m ? `There are ${m} matching stations nearby, but none reports a price right now.`
      : "There is no matching station nearby right now."),
    unavailable: "Ladekrone has no data right now.",
    missing: (e) => `Entity not found: ${e}`,
    tomorrow: "tomorrow ",
    dayAfter: "the day after tomorrow ",
    clock: (t) => t,
    adhoc: "Ad-hoc prices without a contract, as reported by the networks.",
    tesla: "Supercharger prices as reported under AFIR; the Tesla app may show a different price.",
    supercharger: (city) => `Supercharger ${city}`.trim(),
    editor: { entity: "Cheapest price (Ladekrone sensor)", title: "Title", show_list: "Show more stations" },
  },
};

const CROWN = `<svg class="crown" viewBox="0 0 256 256" aria-hidden="true">
<path d="M14 206 L34 78 L88 132 L128 44 L168 132 L222 78 L242 206 Z" fill="#F7B500" stroke="#B87A00" stroke-width="10" stroke-linejoin="round"/>
<rect class="dark" x="14" y="200" width="228" height="36" rx="12"/><circle class="dark" cx="34" cy="74" r="16"/>
<circle class="dark" cx="128" cy="36" r="18"/><circle class="dark" cx="222" cy="74" r="16"/>
<path d="M141 96 L100 160 H127 L115 206 L160 138 H133 Z" fill="#2B1B3D" stroke="#2B1B3D" stroke-width="6" stroke-linejoin="round"/>
</svg>`;

const CLOCK = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2a10 10 0 1 1 0 20 10 10 0 0 1 0-20Zm0 2a8 8 0 1 0 0 16 8 8 0 0 0 0-16Zm0 2.2a1 1 0 0 1 1 1v4.4l3 1.8a1 1 0 1 1-1 1.7l-3.5-2.1a1 1 0 0 1-.5-.9V7.2a1 1 0 0 1 1-1Z"/></svg>`;

const STYLE = `
:host{
  --ink:#2B1B3D;--muted:#64547A;--paper:#FFFFFF;--wash:#F5F0FF;--line:#E4DAF7;
  --gold:#F7B500;--gold-deep:#B87A00;--link:#5B3FD0;--later:#EDE7FF;--later-ink:#4A2FB8;
  display:block;
}
:host([dark]){
  --ink:#F4EEFF;--muted:#BFB2D6;--paper:#1F1630;--wash:#2A2040;--line:#3D3158;
  --gold-deep:#FFD54A;--link:#C3B3FF;--later:#33285A;--later-ink:#D8CCFF;
}
*{box-sizing:border-box}
ha-card{display:block;background:var(--paper);color:var(--ink);border-radius:1.75rem;border:1px solid var(--line);
  padding:1.1rem 1.1rem 1rem;container-type:inline-size;overflow:hidden;
  font:1rem/1.5 "Ladekrone Atkinson","Atkinson Hyperlegible",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
a{color:var(--link);text-underline-offset:.18em}
p{margin:0}
.bar{display:flex;align-items:center;justify-content:space-between;gap:.8rem;margin:0 .15rem .8rem}
.brand{display:flex;align-items:center;gap:.5rem;font:700 1.2rem/1.2 "Ladekrone Bricolage",sans-serif;letter-spacing:-.01em}
.crown{width:1.7rem;height:1.7rem;flex:none}
.crown .dark{fill:var(--ink)}
.stand{color:var(--muted);font-size:.85rem;text-align:right}
.winner{background:var(--wash);border-radius:1.5rem;padding:1.15rem 1.2rem 1.1rem}
.label{display:flex;align-items:center;gap:.4rem;color:var(--muted);font-weight:700}
.price{display:flex;align-items:baseline;gap:.45rem;margin:.05rem 0 .5rem;flex-wrap:wrap}
.num{font:780 clamp(3rem,17cqi,5rem)/.95 "Ladekrone Bricolage",sans-serif;letter-spacing:-.045em;
  font-variant-numeric:tabular-nums;font-variation-settings:"wdth" 88}
.unit{font:600 1.15rem/1.2 "Ladekrone Bricolage",sans-serif;color:var(--muted)}
.who{font-weight:700;font-size:1.12rem}
.addr{color:var(--muted)}
.facts{display:flex;flex-wrap:wrap;gap:.35rem;margin:.7rem 0 0;padding:0;list-style:none}
.facts li{padding:.15rem .6rem;border-radius:999px;background:var(--paper);font-size:.9rem}
.until{margin-top:.8rem;font-weight:700}
.fees{margin-top:.3rem;color:var(--muted);font-size:.92rem}
.actions{display:flex;flex-wrap:wrap;gap:.55rem;margin-top:1rem}
.btn{display:inline-flex;align-items:center;justify-content:center;min-height:2.75rem;padding:.55rem 1.15rem;
  border-radius:999px;border:2px solid var(--ink);background:none;color:var(--ink);cursor:pointer;
  font:700 .98rem/1.2 "Ladekrone Atkinson",sans-serif;text-decoration:none}
.btn.primary{background:var(--gold);border-color:var(--gold);color:#2B1B3D}
.btn.ghost{border-color:var(--line)}
.btn:focus-visible,summary:focus-visible{outline:3px solid var(--gold);outline-offset:3px}
.later{margin-top:.7rem;border-radius:1.3rem;padding:.9rem 1.1rem;background:var(--later);color:var(--later-ink);
  display:grid;grid-template-columns:auto 1fr;gap:.15rem .85rem;align-items:center}
.later svg{grid-row:span 2;width:1.6rem;height:1.6rem;fill:currentColor}
.later strong{font:700 1.08rem/1.3 "Ladekrone Bricolage",sans-serif}
h3{font:700 1.08rem/1.25 "Ladekrone Bricolage",sans-serif;margin:1.3rem .15rem .2rem}
.list{list-style:none;margin:0;padding:0}
.list>li{border-bottom:1px solid var(--line)}
.list>li:last-child{border-bottom:0}
summary{list-style:none;display:grid;grid-template-columns:1fr auto;gap:.1rem 1rem;padding:.75rem .15rem;cursor:pointer;border-radius:.6rem}
summary::-webkit-details-marker{display:none}
.op{font-weight:700;min-width:0;overflow-wrap:anywhere}
.sub{grid-column:1;color:var(--muted);font-size:.92rem}
.p{grid-row:1 / span 2;grid-column:2;text-align:right;font:700 1.4rem/1.1 "Ladekrone Bricolage",sans-serif;
  font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.p small{display:block;font:400 .8rem/1.3 "Ladekrone Atkinson",sans-serif;color:var(--muted);letter-spacing:0}
.change{grid-column:1 / -1;font-size:.9rem;color:var(--later-ink)}
details[open]>summary{padding-bottom:.35rem}
.detail{padding:0 .15rem .9rem;color:var(--muted);font-size:.94rem}
.detail p{margin:.15rem 0}
.detail .btn{margin-top:.5rem;min-height:2.4rem;padding:.35rem .95rem;font-size:.92rem}
.empty{background:var(--wash);border-radius:1.4rem;padding:1.1rem 1.2rem}
.foot{margin:.9rem .15rem 0;color:var(--muted);font-size:.85rem}
.foot p+p{margin-top:.15rem}
`;

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function splitAddress(address) {
  if (!address) return { street: "", city: "" };
  const parts = String(address).split(", ");
  const last = parts.length > 1 ? parts.pop() : "";
  return { street: parts.join(", "), city: last.replace(/^\d{4,5}\s+/, "") };
}

// Superchargern gibt Tesla keinen eigenen Namen, „Tesla, Inc.“ sagt nichts: Ort statt Firma.
const isTesla = (offer) => /^tesla\b/i.test(offer?.operator || "");

const has = (state) => state && !["unknown", "unavailable", ""].includes(state.state);

class LadekroneCard extends HTMLElement {
  static getConfigForm() {
    return {
      schema: [
        { name: "entity", required: true, selector: { entity: { filter: { integration: "ladekrone", domain: "sensor" } } } },
        { name: "title", selector: { text: {} } },
        { name: "show_list", selector: { boolean: {} } },
      ],
      computeLabel: (schema, data, hass) => LadekroneCard.text(hass).editor[schema.name],
    };
  }

  static getStubConfig(hass) {
    const entry = Object.values(hass.entities || {}).find(
      (e) => e.platform === "ladekrone" && e.translation_key === "cheapest_price",
    );
    return { entity: entry ? entry.entity_id : "" };
  }

  static text(hass) {
    const lang = (hass?.locale?.language || hass?.language || "de").split("-")[0];
    return TEXT[lang] || TEXT.en;
  }

  setConfig(config) {
    if (!config || !config.entity) throw new Error("entity is required");
    this._config = { show_list: true, ...config };
    this._key = null;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 7;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  _sibling(key) {
    const hass = this._hass;
    const own = hass.entities?.[this._config.entity];
    if (!own || !own.device_id) return undefined;
    const match = Object.values(hass.entities).find(
      (e) => e.device_id === own.device_id && e.platform === "ladekrone" && e.translation_key === key,
    );
    return match ? hass.states[match.entity_id] : undefined;
  }

  _fmt() {
    const hass = this._hass;
    const lang = hass.locale?.language || hass.language || "de";
    const timeZone = hass.locale?.time_zone === "local" ? undefined : hass.config?.time_zone;
    const number = (min, max) => new Intl.NumberFormat(lang, { minimumFractionDigits: min, maximumFractionDigits: max });
    const day = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" });
    const clock = new Intl.DateTimeFormat(lang, { timeZone, hour: "2-digit", minute: "2-digit" });
    const stamp = new Intl.DateTimeFormat(lang, { timeZone, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
    const t = LadekroneCard.text(hass);
    const dayIndex = (date) => {
      const [y, m, d] = day.format(date).split("-").map(Number);
      return Date.UTC(y, m - 1, d) / 86400000;
    };
    return {
      euro: (v) => number(2, 2).format(v),
      one: (v) => number(1, 1).format(v),
      whole: (v) => number(0, 0).format(v),
      stamp: (v) => t.clock(stamp.format(new Date(v))),
      when: (iso, base) => {
        const date = new Date(iso);
        const diff = dayIndex(date) - dayIndex(base ? new Date(base) : new Date());
        const prefix = diff <= 0 ? "" : diff === 1 ? t.tomorrow : t.dayAfter;
        return `${prefix}${t.clock(clock.format(date))}`;
      },
    };
  }

  _facts(offer, f, t) {
    const items = [t.away(f.one(offer.distance_km ?? 0))];
    if (offer.power_kw) items.push(`${f.whole(Math.round(offer.power_kw))} kW`);
    const plugs = (offer.connectors || []).map((k) => t.connectors[k] || k).join(", ");
    const kind = [offer.current_type ? String(offer.current_type).toUpperCase() : "", plugs].filter(Boolean).join(" ");
    if (kind) items.push(kind);
    if (offer.points > 1) items.push(t.points(offer.points));
    return items;
  }

  _fees(offer, f, t) {
    const parts = [];
    if (offer.session_fee) parts.push(t.sessionFee(f.euro(offer.session_fee)));
    if (offer.minute_fee) {
      parts.push(offer.minute_fee_from ? t.blockFee(f.euro(offer.minute_fee), offer.minute_fee_from) : t.timeFee(f.euro(offer.minute_fee)));
    }
    return parts.join(". ");
  }

  _until(offer, f, t) {
    if (!offer.until) return "";
    return offer.next_price == null ? t.untilNone(f.when(offer.until)) : t.until(f.when(offer.until), f.euro(offer.next_price));
  }

  _name(offer, t) {
    return isTesla(offer) ? t.supercharger(splitAddress(offer.address).city) : offer.operator || t.unknown;
  }

  _route(offer) {
    const apple = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    return apple
      ? `https://maps.apple.com/?daddr=${offer.latitude},${offer.longitude}`
      : `https://www.google.com/maps/dir/?api=1&destination=${offer.latitude},${offer.longitude}`;
  }

  _render() {
    if (!this._config || !this._hass) return;
    const hass = this._hass;
    const main = hass.states[this._config.entity];
    const ahead = this._sibling("cheapest_ahead");
    const count = this._sibling("station_count");
    const updated = this._sibling("data_updated");
    const dark = !!hass.themes?.darkMode;
    const key = [main, ahead, count, updated, dark, hass.locale?.language, this._config].map((x) => (x && x.last_updated) || JSON.stringify(x)).join("|");
    if (key === this._key) return;
    this._key = key;
    this.toggleAttribute("dark", dark);

    const t = LadekroneCard.text(hass);
    const f = this._fmt();
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const open = new Set([...this.shadowRoot.querySelectorAll("details[open]")].map((d) => d.dataset.key));

    const device = hass.entities?.[this._config.entity]?.device_id;
    const title = this._config.title || (device && (hass.devices?.[device]?.name_by_user || hass.devices?.[device]?.name)) || "Ladekrone";
    const stand = has(updated) ? `<p class="stand">${esc(t.stand(f.stamp(updated.state)))}</p>` : "";
    let body;

    if (!main) {
      body = `<div class="empty"><p>${esc(t.missing(this._config.entity))}</p></div>`;
    } else if (main.state === "unavailable") {
      body = `<div class="empty"><p>${esc(t.unavailable)}</p></div>`;
    } else if (!has(main)) {
      body = `<div class="empty"><p>${esc(t.empty(has(count) ? Number(count.state) : 0))}</p></div>`;
    } else {
      const a = main.attributes;
      const offers = a.offers || [];
      const best = { ...(offers[0] || {}), ...a, price: Number(main.state) };
      const { street, city } = splitAddress(best.address);
      const fees = this._fees(best, f, t);
      const until = this._until(best, f, t);
      body = `<article class="winner">
        <p class="label">${esc(t.best)}</p>
        <p class="price"><span class="num">${f.euro(best.price)}</span><span class="unit">€/kWh</span></p>
        <p class="who">${esc(this._name(best, t))}</p>
        <p class="addr">${esc((isTesla(best) ? [street] : [street, city]).filter(Boolean).join(", "))}</p>
        <ul class="facts">${this._facts(best, f, t).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
        ${until ? `<p class="until">${esc(until)}</p>` : ""}
        ${fees ? `<p class="fees">${esc(fees)}</p>` : ""}
        <div class="actions">
          <a class="btn primary" href="${esc(this._route(best))}" target="_blank" rel="noopener">${esc(t.route)}</a>
          <button class="btn ghost" type="button" data-more="${esc(main.entity_id)}">${esc(t.details)}</button>
        </div>
      </article>`;

      if (has(ahead) && ahead.attributes.now === false && Number(ahead.state) < best.price - 1e-9) {
        const o = ahead.attributes;
        const where = isTesla(o) ? this._name(o, t) : [o.operator || t.unknown, splitAddress(o.address).city].filter(Boolean).join(", ");
        body += `<aside class="later">${CLOCK}
          <strong>${esc(t.later(f.euro(Number(ahead.state))))}</strong>
          <p>${esc(t.laterAt(f.when(o.from), o.until ? f.when(o.until, o.from) : "", where, f.one(o.distance_km ?? 0)))}</p>
        </aside>`;
      }

      const rest = this._config.show_list ? offers.slice(1) : [];
      if (rest.length) {
        const rows = rest.map((o) => {
          const addr = splitAddress(o.address);
          const head = [isTesla(o) ? addr.street : addr.city || addr.street, `${f.one(o.distance_km ?? 0)} km`, o.power_kw ? `${f.whole(Math.round(o.power_kw))} kW` : ""]
            .filter(Boolean).join(", ");
          const rowUntil = this._until(o, f, t);
          const rowFees = this._fees(o, f, t);
          const id = `${o.latitude},${o.longitude}`;
          return `<li><details data-key="${esc(id)}"${open.has(id) ? " open" : ""}>
            <summary>
              <span class="op">${esc(this._name(o, t))}</span>
              <span class="p">${f.euro(o.price)}<small>€/kWh</small></span>
              <span class="sub">${esc(head)}</span>
              ${rowUntil ? `<span class="change">${esc(rowUntil)}</span>` : ""}
            </summary>
            <div class="detail">
              <p>${esc([addr.street, addr.city].filter(Boolean).join(", "))}</p>
              <p>${esc(this._facts(o, f, t).slice(1).join(", "))}</p>
              ${rowFees ? `<p>${esc(rowFees)}</p>` : ""}
              <a class="btn" href="${esc(this._route(o))}" target="_blank" rel="noopener">${esc(t.route)}</a>
            </div>
          </details></li>`;
        });
        body += `<h3>${esc(t.more)}</h3><ul class="list">${rows.join("")}</ul>`;
      }
    }

    const tesla = has(main) && [main.attributes, ...(main.attributes.offers || [])].some(isTesla);
    const summary = has(count) && has(main)
      ? `<p>${esc(t.summary(f.whole(count.attributes.with_price ?? 0), f.whole(Number(count.state))))}</p>` : "";

    this.shadowRoot.innerHTML = `<style>${STYLE}</style>
      <ha-card>
        <div class="bar"><span class="brand">${CROWN}${esc(title)}</span>${stand}</div>
        ${body}
        <div class="foot">${summary}<p>${esc(t.adhoc)}</p>${tesla ? `<p>${esc(t.tesla)}</p>` : ""}</div>
      </ha-card>`;

    this.shadowRoot.querySelectorAll("[data-more]").forEach((button) =>
      button.addEventListener("click", () =>
        this.dispatchEvent(new CustomEvent("hass-more-info", {
          detail: { entityId: button.dataset.more }, bubbles: true, composed: true,
        })),
      ),
    );
  }
}

if (!customElements.get("ladekrone-card")) {
  customElements.define("ladekrone-card", LadekroneCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "ladekrone-card",
    name: "Ladekrone",
    description: "Günstigster Ad-hoc-Ladepreis in der Nähe, im Look der Ladekrone-App.",
    preview: true,
    documentationURL: "https://github.com/uekala/ladekrone",
  });
}
