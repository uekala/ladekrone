"""Tests für den Build-Schritt des Datensammlers."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from ladekrone_collector.build import run

FIXTURE = Path(__file__).parent.parent / "fixtures" / "afir_static_sample.json"


def _sources(tmp_path: Path) -> Path:
    path = tmp_path / "sources.json"
    path.write_text(
        json.dumps(
            {
                "sources": [
                    {"key": "tesla", "name": "Tesla", "license": "CC0-1.0", "offer": "1"},
                    {"key": "broken", "name": "Kaputt", "license": "CC0-1.0", "offer": "2"},
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_run_writes_diagnostics(tmp_path: Path) -> None:
    broken = tmp_path / "broken.xml"
    broken.write_text("<?xml version='1.0'?><x/>", encoding="utf-8")
    out = tmp_path / "public"
    args = Namespace(
        sources=str(_sources(tmp_path)),
        out=str(out),
        cache=str(tmp_path / "cache"),
        cert=None,
        key=None,
        subscriptions_env=None,
        input=[f"tesla={FIXTURE}", f"broken={broken}"],
        generated="2026-10-30T00:00:00+00:00",
    )
    assert run(args) == 0
    diag = json.loads((out / "v1" / "diag.json").read_text(encoding="utf-8"))
    assert diag["sources"]["tesla"]["stations"] > 0
    assert "XML" in diag["sources"]["broken"]["error"]
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "Noch ohne Preise" in page
    assert "Kaputt" in page
    assert '<svg class="map"' in page
    assert (out / "assets" / "fonts" / "atkinson-400.woff2").exists()
    assert (out / "assets" / "icon.svg").exists()
    assert "app/" in page
    app = out / "app"
    for name in ("index.html", "app.js", "pricing.js", "manifest.webmanifest", "datenschutz.html"):
        assert (app / name).exists(), name
    worker = (app / "sw.js").read_text(encoding="utf-8")
    assert "__VERSION__" not in worker
    manifest = json.loads((app / "manifest.webmanifest").read_text(encoding="utf-8"))
    for icon in manifest["icons"]:
        assert (app / icon["src"]).exists()
    places = json.loads((out / "v1" / "places.json").read_text(encoding="utf-8"))["places"]
    assert places and all(len(row) == 5 and len(row[0]) == 5 for row in places)


def test_dot_map_ignores_tiles_outside_germany() -> None:
    from ladekrone_collector.site import dot_map

    inside = dot_map({"205_26": (10, 5)}, 0.25)
    with_outlier = dot_map({"205_26": (10, 5), "0_0": (1, 0)}, 0.25)
    assert inside == with_outlier
    assert inside.count("<circle") == 1


def test_places_from_addresses() -> None:
    from ladekrone_collector.places import build_places, clean_city

    stations = [
        {"a": "Hauptstr. 1, 47441 Moers", "la": 51.45, "lo": 6.62},
        {"a": "Bahnhofstr. 2, 47441 MOERS", "la": 51.46, "lo": 6.64},
        {"a": "Kirchweg 3, 47441 Moers", "la": 51.44, "lo": 6.63},
        {"a": "Am Markt 1, 60311 FRANKFURT AM MAIN", "la": 50.11, "lo": 8.68},
        {"a": "Irgendwo 5, 12345 Fern", "la": 0.0, "lo": 0.0},  # falsche Koordinaten
        {"a": "Ohne Postleitzahl", "la": 50.0, "lo": 8.0},
        {"la": 50.0, "lo": 8.0},
    ]
    places = build_places(stations)
    assert places == [
        ["47441", "Moers", 51.45, 6.63, 3],
        ["60311", "Frankfurt am Main", 50.11, 8.68, 1],
    ]
    assert clean_city("BAD HOMBURG VOR DER HÖHE") == "Bad Homburg vor der Höhe"
    assert clean_city("Castrop-Rauxel") == "Castrop-Rauxel"
    assert clean_city("  ") is None


def _args(tmp_path: Path, sources: list[dict], inputs: list[str]) -> Namespace:
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({"sources": sources}), encoding="utf-8")
    return Namespace(
        sources=str(path),
        out=str(tmp_path / "public"),
        cache=str(tmp_path / "cache"),
        cert=None,
        key=None,
        subscriptions_env=None,
        input=inputs,
        generated="2026-10-30T00:00:00+00:00",
    )


def _status_without_prices(tmp_path: Path, points: int) -> Path:
    statuses = [
        {
            "aegiElectricChargingPointStatus": {
                "reference": {"idG": f"P{i}"},
                "status": {"value": "available"},
            }
        }
        for i in range(points)
    ]
    doc = {
        "messageContainer": {
            "payload": [
                {
                    "aegiEnergyInfrastructureStatusPublication": {
                        "energyInfrastructureSiteStatus": [
                            {"energyInfrastructureStationStatus": [{"refillPointStatus": statuses}]}
                        ]
                    }
                }
            ]
        }
    }
    path = tmp_path / "status.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_missing_subscriptions_are_reported(tmp_path: Path, caplog) -> None:
    caplog.set_level("INFO", logger="ladekrone")
    sources = [
        {"key": "tesla", "name": "Tesla", "license": "CC0-1.0", "offer": "1"},
        {"key": "ladenetz", "name": "ladenetz.de", "license": "CC0-1.0", "offer": "902"},
        {"key": "closed", "name": "Geschlossen", "license": "unbekannt", "offer": "3"},
    ]
    assert run(_args(tmp_path, sources, [f"tesla={FIXTURE}"])) == 0

    diag = json.loads((tmp_path / "public" / "v1" / "diag.json").read_text(encoding="utf-8"))
    assert diag["sources"]["tesla"]["status"] == "ok"
    assert diag["sources"]["ladenetz"] == {
        "name": "ladenetz.de",
        "status": "no_subscription",
        "offer": "902",
    }
    assert diag["sources"]["closed"]["status"] == "license_not_open"
    summary = diag["summary"]
    assert summary["sources_total"] == 3
    assert summary["sources_loaded"] == 1
    assert summary["sources_without_subscription"] == ["ladenetz"]
    assert summary["sources_not_open_license"] == ["closed"]

    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("ladenetz: kein Mobilithek-Abo hinterlegt (Angebot 902)" in w for w in warnings)
    assert any("1 von 3 Quellen geladen, 2 übersprungen" in r.getMessage() for r in caplog.records)


def test_dynamic_feed_without_prices_is_flagged(tmp_path: Path, caplog) -> None:
    caplog.set_level("INFO", logger="ladekrone")
    sources = [
        {
            "key": "tesla",
            "name": "Tesla",
            "license": "CC0-1.0",
            "offer": "1",
            "dynamic": {"offer": "9"},
        }
    ]
    status = _status_without_prices(tmp_path, 3)
    assert run(_args(tmp_path, sources, [f"tesla={FIXTURE}", f"tesla_dyn={status}"])) == 0

    diag = json.loads((tmp_path / "public" / "v1" / "diag.json").read_text(encoding="utf-8"))
    dynamic = diag["sources"]["tesla"]["dynamic"]
    assert dynamic["status"] == "no_prices"
    assert dynamic["point_status"] == 3
    assert dynamic["points_with_price"] == 0
    assert diag["summary"]["dynamic"] == {"no_prices": ["tesla"]}
    assert any(
        "tesla: dynamischer Feed liefert 3 Status, aber keine Preise" in r.getMessage()
        for r in caplog.records
    )


def test_dynamic_offer_without_subscription_is_flagged(tmp_path: Path, caplog) -> None:
    caplog.set_level("INFO", logger="ladekrone")
    sources = [
        {
            "key": "vw",
            "name": "VW",
            "license": "CC0-1.0",
            "offer": "1",
            "dynamic": {"offer": "983006934617260032"},
        }
    ]
    assert run(_args(tmp_path, sources, [f"vw={FIXTURE}"])) == 0

    diag = json.loads((tmp_path / "public" / "v1" / "diag.json").read_text(encoding="utf-8"))
    assert diag["sources"]["vw"]["dynamic"] == {
        "status": "no_subscription",
        "offer": "983006934617260032",
    }
    assert diag["summary"]["dynamic"] == {"no_subscription": ["vw"]}
    assert any(
        "vw: dynamisches Angebot 983006934617260032 ohne Abo" in r.getMessage()
        for r in caplog.records
    )


def test_github_actions_report(tmp_path: Path, monkeypatch, capsys) -> None:
    summary_file = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    sources = [
        {"key": "tesla", "name": "Tesla", "license": "CC0-1.0", "offer": "1"},
        {"key": "ladebusiness", "name": "ladebusiness", "license": "CC0-1.0", "offer": "903"},
    ]
    assert run(_args(tmp_path, sources, [f"tesla={FIXTURE}"])) == 0

    out = capsys.readouterr().out
    assert "::warning title=Mobilithek-Abo fehlt::ladebusiness" in out
    text = summary_file.read_text(encoding="utf-8")
    assert "1 von 2 Quellen geladen." in text
    assert "| ladebusiness | kein Abo |" in text
    assert "| Tesla | geladen |" in text


def test_no_data_at_all_fails(tmp_path: Path) -> None:
    sources = [{"key": "ladenetz", "name": "ladenetz.de", "license": "CC0-1.0", "offer": "902"}]
    assert run(_args(tmp_path, sources, [])) == 1


def test_annotations_cannot_inject_workflow_commands(monkeypatch, capsys) -> None:
    from ladekrone_collector.build import _github_report

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    summary = {"sources_without_subscription": [], "dynamic": {}, "sources_failed": ["x"]}
    _github_report(summary, {"x": {"error": "HTTP 500\n::warning::injiziert 100%"}})
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "::error title=Quelle fehlgeschlagen::x: HTTP 500%0A::warning::injiziert 100%25"
    ]
