"""Baut aus den Mobilithek-Angeboten die Kacheldateien für GitHub Pages."""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .datex import (
    RateUpdates,
    UnsupportedFormatError,
    diagnose,
    diagnose_status,
    load_document,
    parse_document,
    parse_status,
    rate_ids,
    uses_special_days,
)
from .mobilithek import FetchError, build_ssl_context, fetch_subscription
from .operators import build_operator_names, resolve_operator_ids
from .places import build_places
from .site import copy_assets, copy_webapp, render_index

TILE_DEG = 0.25
FORMAT_VERSION = 1
OPEN_LICENSES = {"CC0-1.0", "CC-BY-4.0", "DL-DE-ZERO-2.0", "DL-DE-BY-2.0"}
DYNAMIC_ROUNDS = 300

_LOGGER = logging.getLogger("ladekrone")


def tile_key(lat: float, lon: float) -> str:
    return f"{math.floor(lat / TILE_DEG)}_{math.floor(lon / TILE_DEG)}"


def load_sources(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [s for s in data["sources"] if s.get("enabled", True)]


def merge_sources(
    parsed: list[tuple[dict, list[tuple[dict, set[str]]]]],
) -> tuple[list[dict], dict[str, dict[str, int]]]:
    """Führt Quellen zusammen. Frühere Quellen haben Vorrang; eine Station wird
    übersprungen, wenn einer ihrer Ladepunkte (EVSE-ID) schon vorkam."""
    seen_evse: set[str] = set()
    seen_ids: set[str] = set()
    stations: list[dict] = []
    stats: dict[str, dict[str, int]] = {}
    for source, records in parsed:
        count = {"stations": 0, "points": 0, "duplicates": 0, "with_price": 0}
        for record, evse_ids in records:
            if record["id"] in seen_ids or (evse_ids and evse_ids & seen_evse):
                count["duplicates"] += 1
                continue
            seen_ids.add(record["id"])
            seen_evse |= evse_ids
            stations.append(record)
            count["stations"] += 1
            count["points"] += sum(g["n"] for g in record["g"])
            if record.get("r"):
                count["with_price"] += 1
        stats[source["key"]] = count
    return stations, stats


def write_output(
    out_dir: Path,
    stations: list[dict],
    sources: list[dict],
    stats: dict[str, dict[str, Any]],
    generated: str,
    diagnostics: dict[str, dict[str, Any]] | None = None,
    extra_diagnostics: dict[str, Any] | None = None,
) -> dict:
    tiles: dict[str, list[dict]] = {}
    for record in stations:
        tiles.setdefault(tile_key(record["la"], record["lo"]), []).append(record)

    base = out_dir / f"v{FORMAT_VERSION}"
    tile_dir = base / "tiles"
    tile_dir.mkdir(parents=True, exist_ok=True)
    for key, records in tiles.items():
        payload = {"v": FORMAT_VERSION, "tile": key, "generated": generated, "stations": records}
        (tile_dir / f"{key}.json").write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )

    meta = {
        "v": FORMAT_VERSION,
        "generated": generated,
        "tile_deg": TILE_DEG,
        "tiles": sorted(tiles),
        "stations": len(stations),
        "points": sum(g["n"] for s in stations for g in s["g"]),
        "sources": [
            {
                "key": s["key"],
                "name": s["name"],
                "license": s["license"],
                "attribution": s.get("attribution", s["name"]),
                "offer": s.get("offer"),
                **stats.get(s["key"], {}),
            }
            for s in sources
            if s["key"] in stats
        ],
    }
    (base / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    diagnostics = diagnostics or {}
    (base / "diag.json").write_text(
        json.dumps(
            {"generated": generated, "sources": diagnostics, **(extra_diagnostics or {})},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    (base / "places.json").write_text(
        json.dumps(
            {"v": FORMAT_VERSION, "generated": generated, "places": build_places(stations)},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    (out_dir / ".nojekyll").write_text("")
    tile_counts = {
        key: (len(records), sum(1 for record in records if record.get("r")))
        for key, records in tiles.items()
    }
    copy_assets(out_dir)
    copy_webapp(out_dir)
    (out_dir / "index.html").write_text(
        render_index(meta, diagnostics, tile_counts), encoding="utf-8"
    )
    return meta


def subscription_id(
    source: dict, subscriptions: dict[str, str], dynamic: bool = False
) -> str | None:
    """Abo-ID aus dem Secret (Vorrang) oder aus sources.json.

    Abo-IDs funktionieren nur mit dem Zertifikat der Organisation und dürfen
    daher öffentlich in sources.json stehen; Forks überschreiben sie per Secret.
    """
    key = f"{source['key']}_dyn" if dynamic else source["key"]
    if subscriptions.get(key):
        return str(subscriptions[key])
    holder = source.get("dynamic") if dynamic else source
    value = holder.get("subscription") if isinstance(holder, dict) else None
    return str(value) if value else None


def _fetch_updates(
    source: dict,
    subscriptions: dict[str, str],
    context: Any,
    cache: Path,
    local_inputs: dict[str, str],
) -> tuple[RateUpdates | None, Any]:
    """Holt die dynamischen Preise eines Betreibers, falls abonniert."""
    key = f"{source['key']}_dyn"
    if key in local_inputs:
        raw = Path(local_inputs[key]).read_bytes()
    else:
        sub = subscription_id(source, subscriptions, dynamic=True)
        if not sub or context is None:
            return None, None
        raw = fetch_subscription(key, sub, context, cache, max_rounds=DYNAMIC_ROUNDS).body
    document = load_document(raw)
    return parse_status(document), document


def _has_dynamic_offer(source: dict) -> bool:
    """True, wenn für die Quelle ein dynamisches Angebot eingetragen ist."""
    dynamic = source.get("dynamic")
    return isinstance(dynamic, dict) and bool(dynamic.get("offer") or dynamic.get("subscription"))


def _dynamic_status(dynamic: dict[str, Any]) -> str:
    """Ordnet die Kennzahlen eines dynamischen Feeds einem Status zu."""
    if dynamic.get("error"):
        return "error"
    if not dynamic.get("points_with_price"):
        return "no_prices"
    return "ok"


def summarize(total: int, diagnostics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Fasst den Lauf zusammen: geladene, übersprungene und fehlerhafte Quellen."""
    by_status: dict[str, list[str]] = {}
    dynamic: dict[str, list[str]] = {}
    for key, diag in diagnostics.items():
        by_status.setdefault(diag.get("status", "ok"), []).append(key)
        if isinstance(diag.get("dynamic"), dict):
            dynamic.setdefault(diag["dynamic"].get("status", "ok"), []).append(key)
    return {
        "sources_total": total,
        "sources_loaded": len(by_status.get("ok", [])),
        "sources_without_subscription": sorted(by_status.get("no_subscription", [])),
        "sources_without_certificate": sorted(by_status.get("no_certificate", [])),
        "sources_not_open_license": sorted(by_status.get("license_not_open", [])),
        "sources_failed": sorted(by_status.get("error", [])),
        "dynamic": {status: sorted(keys) for status, keys in sorted(dynamic.items())},
    }


def _escape_annotation(value: object) -> str:
    """Escapes text for a GitHub Actions workflow command.

    Error texts can come from the Mobilithek server. Without escaping, a line
    break in them would start a second workflow command.
    """
    return str(value).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _github_report(summary: dict[str, Any], diagnostics: dict[str, dict[str, Any]]) -> None:
    """Macht Lücken in GitHub Actions sichtbar (Annotationen und Zusammenfassung)."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        esc = _escape_annotation
        for key in summary["sources_without_subscription"]:
            print(f"::warning title=Mobilithek-Abo fehlt::{esc(key)}: Quelle ohne Abo übersprungen")
        for key in summary["dynamic"].get("no_prices", []):
            print(f"::warning title=Dynamischer Feed ohne Preise::{esc(key)}")
        for key in summary["dynamic"].get("no_subscription", []):
            print(f"::warning title=Dynamisches Abo fehlt::{esc(key)}")
        for key in summary["sources_failed"]:
            error = diagnostics[key].get("error")
            print(f"::error title=Quelle fehlgeschlagen::{esc(key)}: {esc(error)}")
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    labels = {
        "ok": "geladen",
        "no_subscription": "kein Abo",
        "no_certificate": "kein Zertifikat",
        "license_not_open": "Lizenz nicht offen",
        "error": "Fehler",
    }
    dyn_labels = {
        "ok": "mit Preisen",
        "no_prices": "ohne Preise",
        "no_subscription": "kein Abo",
        "error": "Fehler",
    }
    lines = [
        "## Ladekrone-Datenlauf",
        "",
        f"{summary['sources_loaded']} von {summary['sources_total']} Quellen geladen.",
        "",
        "| Quelle | Status | Stationen | Dynamische Preise |",
        "| --- | --- | ---: | --- |",
    ]
    for key, diag in diagnostics.items():
        dyn = diag.get("dynamic")
        dyn_text = dyn_labels.get(dyn.get("status", ""), "") if isinstance(dyn, dict) else ""
        lines.append(
            f"| {diag.get('name', key)} | {labels.get(diag.get('status', 'ok'), '')} "
            f"| {diag.get('stations', '')} | {dyn_text} |"
        )
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def run(args: argparse.Namespace) -> int:
    sources = load_sources(Path(args.sources))
    subscriptions: dict[str, str] = {}
    if args.subscriptions_env and os.environ.get(args.subscriptions_env):
        subscriptions = json.loads(os.environ[args.subscriptions_env])
    local_inputs = dict(item.split("=", 1) for item in args.input or [])

    context = None
    if args.cert and args.key:
        context = build_ssl_context(args.cert, args.key)

    parsed: list[tuple[dict, list[tuple[dict, set[str]]]]] = []
    used_sources: list[dict] = []
    diagnostics: dict[str, dict[str, Any]] = {}
    failures = 0
    for source in sources:
        key = source["key"]
        if source.get("license") not in OPEN_LICENSES:
            _LOGGER.warning("%s: Lizenz %s nicht offen, übersprungen", key, source.get("license"))
            diagnostics[key] = {
                "name": source["name"],
                "status": "license_not_open",
                "license": source.get("license"),
            }
            continue
        sub = subscription_id(source, subscriptions)
        try:
            if key in local_inputs:
                raw = Path(local_inputs[key]).read_bytes()
            elif not sub:
                _LOGGER.warning(
                    "%s: kein Mobilithek-Abo hinterlegt (Angebot %s) – Quelle übersprungen",
                    key,
                    source.get("offer"),
                )
                diagnostics[key] = {
                    "name": source["name"],
                    "status": "no_subscription",
                    "offer": source.get("offer"),
                }
                continue
            elif context is None:
                _LOGGER.warning("%s: kein Client-Zertifikat – Quelle übersprungen", key)
                diagnostics[key] = {"name": source["name"], "status": "no_certificate"}
                continue
            else:
                raw = fetch_subscription(key, sub, context, Path(args.cache)).body
            document = load_document(raw)
        except (FetchError, UnsupportedFormatError, OSError) as err:
            failures += 1
            diagnostics[key] = {"name": source["name"], "status": "error", "error": str(err)}
            _LOGGER.error("%s: %s", key, err)
            continue

        dynamic: dict[str, Any] | None = None
        updates: RateUpdates | None = None
        try:
            updates, status_doc = _fetch_updates(
                source, subscriptions, context, Path(args.cache), local_inputs
            )
            if updates is not None:
                dynamic = diagnose_status(status_doc, updates, rate_ids(document))
                dynamic["status"] = _dynamic_status(dynamic)
                if dynamic["status"] == "no_prices":
                    _LOGGER.warning(
                        "%s: dynamischer Feed liefert %d Status, aber keine Preise",
                        key,
                        dynamic.get("point_status", 0),
                    )
            elif _has_dynamic_offer(source) and f"{key}_dyn" not in local_inputs:
                dynamic = {"status": "no_subscription", "offer": source["dynamic"].get("offer")}
                _LOGGER.warning(
                    "%s: dynamisches Angebot %s ohne Abo – nur statische Preise",
                    key,
                    source["dynamic"].get("offer"),
                )
        except (FetchError, UnsupportedFormatError, OSError) as err:
            dynamic = {"status": "error", "error": str(err)}
            _LOGGER.warning("%s: dynamische Preise nicht verfügbar: %s", key, err)

        records = parse_document(document, key, updates)
        diagnostics[key] = {
            "name": source["name"],
            "status": "ok",
            "stations": len(records),
            **diagnose(document),
        }
        if dynamic is not None:
            diagnostics[key]["dynamic"] = dynamic
        holidays = sum(1 for record, _evse in records if uses_special_days(record.get("r", [])))
        _LOGGER.info("%s: %d Stationen gelesen, %d mit Feiertagsregel", key, len(records), holidays)
        parsed.append((source, records))
        used_sources.append(source)

    summary = summarize(len(sources), diagnostics)
    _github_report(summary, diagnostics)

    if not parsed:
        _LOGGER.error(
            "Keine Quelle lieferte Daten (0 von %d) – Ausgabe wird nicht geschrieben",
            len(sources),
        )
        return 1

    all_records = [item for _source, records in parsed for item in records]
    operator_ids = resolve_operator_ids(all_records, build_operator_names(all_records))
    stations, stats = merge_sources(parsed)
    generated = args.generated or datetime.now(UTC).replace(microsecond=0).isoformat()
    meta = write_output(
        Path(args.out),
        stations,
        used_sources,
        stats,
        generated,
        diagnostics,
        {"summary": summary, "operator_ids": operator_ids},
    )
    skipped = (
        len(summary["sources_without_subscription"])
        + len(summary["sources_without_certificate"])
        + len(summary["sources_not_open_license"])
    )
    dynamic = summary["dynamic"]
    _LOGGER.info(
        "Fertig: %d von %d Quellen geladen, %d übersprungen, %d mit Fehler; "
        "dynamische Feeds: %d mit Preisen, %d ohne Preise, %d ohne Abo, %d mit Fehler; "
        "%d Stationen, %d Ladepunkte, %d Kacheln",
        summary["sources_loaded"],
        summary["sources_total"],
        skipped,
        failures,
        len(dynamic.get("ok", [])),
        len(dynamic.get("no_prices", [])),
        len(dynamic.get("no_subscription", [])),
        len(dynamic.get("error", [])),
        meta["stations"],
        meta["points"],
        len(meta["tiles"]),
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ladekrone-Datensammler")
    parser.add_argument("--sources", required=True, help="Pfad zu sources.json")
    parser.add_argument("--out", required=True, help="Ausgabeverzeichnis (GitHub Pages)")
    parser.add_argument("--cache", default=".cache/mobilithek", help="Cache für Rohdaten")
    parser.add_argument("--cert", help="Client-Zertifikat (PEM)")
    parser.add_argument("--key", help="Privater Schlüssel (PEM)")
    parser.add_argument(
        "--subscriptions-env",
        default="MOBILITHEK_SUBSCRIPTIONS",
        help="Umgebungsvariable mit JSON {quelle: abo-id}",
    )
    parser.add_argument(
        "--input", action="append", help="Lokale Datei statt Abruf: quelle=pfad (mehrfach)"
    )
    parser.add_argument("--generated", help="Zeitstempel überschreiben (Tests)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
