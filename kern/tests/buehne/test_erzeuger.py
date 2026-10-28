"""Bühne: Erzeuger – Vorlagen bauen/ändern mit dem Modell (Reparatur, Fallback) und Stile ableiten."""

from __future__ import annotations

import json

import httpx

from jarvis.buehne.erzeuger import Erzeuger, css_kandidaten
from tests.conftest import mock_fabrik, text_chunks
from tests.helfer import baue_jarvis

ERGEBNIS = {"items": [{"id": "h3", "titel": "Hafenweg 3", "preis": 450000, "bild_url": "https://gg.example/h3.jpg"}], "total": 1}
GUELTIG = {
    "name": "Immobilienliste",
    "zweck": "Objekte aus GG als Kacheln",
    "abbildung": {"/immobilien": "/items", "/anzahl": "/total"},
    "datenschema": {"type": "object"},
    "komponenten": [
        {"id": "root", "component": "Column", "children": ["titel", "kacheln"], "gap": 12},
        {"id": "titel", "component": "Text", "text": "Immobilien", "variant": "h2"},
        {"id": "kacheln", "component": "Grid", "spalten": 3, "children": {"path": "/immobilien", "componentId": "kachel"}},
        {"id": "kachel", "component": "Card", "child": "inhalt"},
        {"id": "inhalt", "component": "Column", "children": ["bild", "name", "notiz"]},
        {"id": "bild", "component": "Image", "url": {"path": "bild_url"}, "alt": {"path": "titel"}},
        {"id": "name", "component": "Text", "text": {"path": "titel"}, "variant": "h4"},
        {"id": "notiz", "component": "Button", "text": "Notiz", "action": {"event": {"name": "notiz_anlegen", "context": {"objekt_id": {"path": "id"}}}}},
    ],
}


def _erzeuger(antworten, handler=None):
    j, skript = baue_jarvis(antworten)
    return Erzeuger(j.llm, http_client_fabrik=mock_fabrik(handler) if handler else None), skript


async def test_vorlage_bauen_gueltig():
    e, skript = _erzeuger([text_chunks("```json\n" + json.dumps(GUELTIG) + "\n```")])
    v = await e.vorlage_bauen("gg__read_collection", ERGEBNIS, wunsch="als Kacheln mit Bild", stil={"vorlieben": {"liste": "kacheln"}}, titel="Immobilien")
    assert v["name"] == "Immobilienliste" and v["komponenten"][2]["component"] == "Grid"
    assert v["abbildung"] == {"/immobilien": "/items", "/anzahl": "/total"} and v["modell"] == "openai/gpt-4o"
    system = skript.aufrufe[0]["messages"][0]["content"]
    assert "Katalog jarvis:buehne/1" in system and "kacheln" in system
    nutzer = skript.aufrufe[0]["messages"][1]["content"]
    assert "gg__read_collection" in nutzer and "Hafenweg 3" in nutzer and "als Kacheln mit Bild" in nutzer


async def test_vorlage_bauen_repariert_nach_fehler():
    kaputt = {**GUELTIG, "komponenten": [{"id": "root", "component": "Hologramm"}]}
    e, skript = _erzeuger([text_chunks(json.dumps(kaputt)), text_chunks(json.dumps(GUELTIG))])
    v = await e.vorlage_bauen("gg__read_collection", ERGEBNIS)
    assert v["komponenten"][0]["component"] == "Column" and len(skript.aufrufe) == 2
    assert "Hologramm" in skript.aufrufe[1]["messages"][-1]["content"]  # Fehlertext im zweiten Versuch


async def test_vorlage_bauen_fallback_standardvorlage():
    e, skript = _erzeuger([text_chunks("kein json"), text_chunks("{\"name\": 1}")])
    v = await e.vorlage_bauen("gg__read_collection", ERGEBNIS, titel="Immobilien")
    assert any(k["component"] == "Tabelle" for k in v["komponenten"]) and v["modell"] is None
    assert v["abbildung"] == {"/eintraege": "/items"} and len(skript.aufrufe) == 2


async def test_vorlage_bauen_entfernt_erfundene_eigenschaften():
    mit_unsinn = json.loads(json.dumps(GUELTIG))
    mit_unsinn["komponenten"][1]["farbe"] = "rot"
    e, _ = _erzeuger([text_chunks(json.dumps(mit_unsinn))])
    v = await e.vorlage_bauen("w", ERGEBNIS)
    assert "farbe" not in v["komponenten"][1]


async def test_vorlage_aendern():
    neu = {"komponenten": GUELTIG["komponenten"][:2] + [{"id": "kacheln", "component": "Text", "text": "leer"}], "zweck": "nur Titel"}
    e, skript = _erzeuger([text_chunks(json.dumps(neu))])
    vorlage = {"id": "immobilien", "name": "Immobilien", "zweck": GUELTIG["zweck"], "komponenten": GUELTIG["komponenten"], "datenquelle": {"abbildung": GUELTIG["abbildung"]}, "datenschema": {}}
    v = await e.vorlage_aendern(vorlage, "zeig nur den Titel", beispiel_daten={"immobilien": ERGEBNIS["items"]})
    assert v["komponenten"][2]["component"] == "Text" and v["zweck"] == "nur Titel" and v["abbildung"] == GUELTIG["abbildung"]
    assert "zeig nur den Titel" in skript.aufrufe[0]["messages"][1]["content"]
    assert '"component": "Grid"' in skript.aufrufe[0]["messages"][1]["content"]  # bestehende Vorlage mitgegeben


def test_css_kandidaten():
    css = ":root{--primary-color:#1E88E5;--bg:#fff;} body{font-family: Inter, sans-serif; color:#222222; background:#ffffff} .card{border-radius: 12px; color: rgb(30, 136, 229)} a{color:#1e88e5}"
    k = css_kandidaten(css)
    assert k["variablen"]["--primary-color"] == "#1e88e5" and k["farben"][0] == "#1e88e5"
    assert "Inter" in k["schriften"][0] and k["rundungen"] == [12]


async def test_stil_ableiten_aus_url_und_fallback():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(200, text='<html><head><link rel="stylesheet" href="/app.css"><style>:root{--brand:#0d9488}</style></head><body><div class="x">GG</div></body></html>', headers={"content-type": "text/html"})
        if request.url.path == "/app.css":
            return httpx.Response(200, text="body{font-family: 'Plus Jakarta Sans', sans-serif;background:#0f172a;color:#e2e8f0}.btn{background:#0d9488;border-radius:8px}", headers={"content-type": "text/css"})
        return httpx.Response(404)

    stil_antwort = {"schema": "dunkel", "farben": {"primaer": "#0d9488", "akzent": "#f59e0b", "hintergrund": "#0f172a", "flaeche": "#1e293b", "text": "#e2e8f0", "dezent": "#94a3b8", "ok": "#22c55e", "warn": "#f59e0b", "fehler": "#ef4444"}, "schrift": {"familie": "'Plus Jakarta Sans', sans-serif", "basisgroesse": 14}, "rundung": 8, "abstand": 12, "dichte": "normal", "schatten": "weich", "vorlieben": {"liste": "kacheln", "bildgroesse": "mittel", "kennzahlenOben": True}}
    e, skript = _erzeuger([text_chunks(json.dumps(stil_antwort))], handler)
    stil = await e.stil_ableiten("GG Immo", {"art": "url", "wert": "https://gg.example/"})
    assert stil["id"] == "gg-immo" and stil["werte"]["farben"]["primaer"] == "#0d9488" and stil["quelle"] == {"art": "url", "wert": "https://gg.example/"}
    assert stil["werte"]["schrift"]["familie"].startswith("'Plus Jakarta")
    assert "#0d9488" in skript.aufrufe[0]["messages"][1]["content"] and "Plus Jakarta" in skript.aufrufe[0]["messages"][1]["content"]
    # kaputte Modellantwort → Fallback aus den Kandidaten
    e2, _ = _erzeuger([text_chunks("nix")], handler)
    stil2 = await e2.stil_ableiten("GG Immo", {"art": "url", "wert": "https://gg.example/"})
    assert stil2["werte"]["farben"]["primaer"].startswith("#") and stil2["werte"]["schema"] in ("hell", "dunkel")
    # aus Klassen/Datei ohne Netz
    e3, skript3 = _erzeuger([text_chunks(json.dumps(stil_antwort))])
    stil3 = await e3.stil_ableiten("Firma", {"art": "klassen", "wert": ".btn{background:#123456}"})
    assert stil3["quelle"]["art"] == "klassen" and "#123456" in skript3.aufrufe[0]["messages"][1]["content"]
