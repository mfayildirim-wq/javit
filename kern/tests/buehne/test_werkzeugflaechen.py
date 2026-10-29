"""Bühne: Werkzeugflächen – Browser (live mit Bild, Modus Bühne/Fenster), Shell (Terminal), Dateien (Schritte)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from jarvis.buehne.katalog import komponenten_pruefen
from jarvis.buehne.manager import BuehnenFehler, BuehnenManager
from jarvis.buehne.werkzeugflaechen import vorlage_live, vorlage_schritte, vorlage_terminal
from jarvis.integrationen.manager import IntegrationsKonfig
from jarvis.llm import WerkzeugAufruf
from jarvis.werkzeuge import FunktionsWerkzeug, schema
from tests.helfer import baue_jarvis

BILD = "data:image/png;base64,iVBORw0KGgo="


class BildWerkzeug(FunktionsWerkzeug):
    def __init__(self, *a: Any, **kw: Any):
        super().__init__(*a, **kw)
        self.bild: str | None = None

    def letztes_bild(self) -> str | None:
        return self.bild


def _mit_browser():
    j, skript = baue_jarvis([])
    j.konfig.aktualisieren({"freigabe_technisch": False})
    aufrufe: list[tuple[str, dict]] = []
    screenshot = BildWerkzeug(lambda **a: _merken(aufrufe, "browser_take_screenshot", a, "[Bild: image/png]"), "browser__browser_take_screenshot", "Screenshot", schema({}), "lesen", quelle="mcp", integration="browser")

    async def _merken(liste, name, a, antwort):
        liste.append((name, a))
        if name == "browser_take_screenshot":
            screenshot.bild = BILD
        return antwort

    werkzeuge = [
        FunktionsWerkzeug(lambda **a: _merken(aufrufe, "browser_navigate", a, "Seite geladen: Beispiel"), "browser__browser_navigate", "navigiert", schema({"url": {"type": "string"}}, ["url"]), "aendern", quelle="mcp", integration="browser"),
        FunktionsWerkzeug(lambda **a: _merken(aufrufe, "browser_navigate_back", a, "zurück"), "browser__browser_navigate_back", "zurück", schema({}), "aendern", quelle="mcp", integration="browser"),
        FunktionsWerkzeug(lambda **a: _merken(aufrufe, "browser_snapshot", a, "- heading „Deals“"), "browser__browser_snapshot", "snapshot", schema({}), "lesen", quelle="mcp", integration="browser"),
        screenshot,
    ]

    def registrieren() -> None:
        j.register.alle_registrieren(werkzeuge)

    registrieren()
    j.manager.konfigs["browser"] = IntegrationsKonfig(id="browser", name="Browser (Playwright)", art="mcp_stdio", katalog="browser", befehl=["npx", "-y", "@playwright/mcp@latest"])
    j.manager.status["browser"] = "verbunden"
    verbindungen: list[list[str]] = []

    async def neu_verbinden(kennung: str) -> dict:
        verbindungen.append(list(j.manager.konfigs[kennung].befehl or []))
        registrieren()
        j.manager.status[kennung] = "verbunden"
        return {}

    j.manager.neu_verbinden = neu_verbinden  # type: ignore[method-assign]
    ereignisse: list[dict] = []

    async def hoerer(e: dict) -> None:
        ereignisse.append(e)

    j.hoerer_hinzufuegen(hoerer)
    return j, aufrufe, verbindungen, ereignisse


def _buehne(ereignisse):
    return [e["nachricht"] for e in ereignisse if e["typ"] == "buehne"]


async def _modellaufruf(j, name: str, argumente: dict) -> str:
    return await j.agent._werkzeug_ausfuehren(WerkzeugAufruf(id=f"call_{len(name)}", name=name, argumente=argumente), sprechen=False)


async def _ruhe() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


def test_kern_vorlagen_sind_katalogkonform():
    assert komponenten_pruefen(vorlage_live()) == []
    assert komponenten_pruefen(vorlage_terminal("Shell")) == []
    assert komponenten_pruefen(vorlage_schritte("Dateien")) == []
    assert not any(k["id"] == "formular" for k in vorlage_schritte("Dateien"))


async def test_browser_oeffnen_schritte_bild_und_knoepfe():
    j, aufrufe, verbindungen, ereignisse = _mit_browser()
    wf = j.buehne.werkzeugflaechen
    defs = wf.definitionen()
    assert {"shell", "dateien", "browser"} <= set(defs) and defs["browser"]["art"] == "live" and defs["browser"]["bild"] == "browser_take_screenshot"
    # ohne offene Fläche: Werkzeugaufrufe erzeugen nichts auf der Bühne
    await _modellaufruf(j, "browser__browser_snapshot", {})
    assert _buehne(ereignisse) == []
    # öffnen: Standardmodus Bühne → --headless ergänzt, neu verbunden; Fläche mit art werkzeug
    e = await j.buehne.werkzeug_oeffnen("Browser")
    assert e["surfaceId"] == "werkzeug-browser" and e["modus"] == "buehne" and verbindungen == [["npx", "-y", "@playwright/mcp@latest", "--headless"]]
    erzeugt = next(n["createSurface"] for n in _buehne(ereignisse) if "createSurface" in n)
    assert erzeugt["art"] == "werkzeug" and erzeugt["symbol"] == "globe" and erzeugt["vorlage"] is None
    flaeche = j.buehne.zustand()["flaechen"][0]
    assert flaeche["art"] == "werkzeug" and flaeche["werkzeug"] == "browser" and flaeche["daten"]["modus_text"] == "Bühne"
    assert flaeche["daten"]["schritte"][0]["text"].startswith("Modus: Bühne")
    # Modellaufruf navigiert → Schritt läuft/ok, Adresse übernommen, Bild automatisch geholt (Hilfsaufruf ist kein Schritt)
    ereignisse.clear()
    await _modellaufruf(j, "browser__browser_navigate", {"url": "https://gg.example/deals"})
    await _ruhe()
    daten = j.buehne.flaechen["werkzeug-browser"]["daten"]
    assert daten["adresse"] == "https://gg.example/deals" and daten["bild"] == BILD and daten["status"] == "bereit"
    texte = [s["text"] for s in daten["schritte"]]
    assert any(t.startswith("browser_navigate (url=https://gg.example/deals") for t in texte) and not any("screenshot" in t for t in texte)
    assert daten["schritte"][-1]["zustand"] == "ok" and "Seite geladen" in daten["schritte"][-1]["ergebnis"]
    assert [a[0] for a in aufrufe][-2:] == ["browser_navigate", "browser_take_screenshot"]
    assert [n for n in _buehne(ereignisse) if "updateDataModel" in n]
    # Knöpfe: Adresse öffnen, zurück, aktualisieren
    await j.buehne.aktion({"name": "werkzeug_oeffnen_url", "surfaceId": "werkzeug-browser", "context": {"url": "example.org"}})
    await _ruhe()
    assert ("browser_navigate", {"url": "https://example.org"}) in aufrufe
    await j.buehne.aktion({"name": "werkzeug_zurueck", "surfaceId": "werkzeug-browser", "context": {}})
    await _ruhe()
    assert any(a[0] == "browser_navigate_back" for a in aufrufe)
    anzahl = len([a for a in aufrufe if a[0] == "browser_take_screenshot"])
    await j.buehne.aktion({"name": "werkzeug_aktualisieren", "surfaceId": "werkzeug-browser", "context": {}})
    await _ruhe()
    assert len([a for a in aufrufe if a[0] == "browser_take_screenshot"]) == anzahl + 1
    # Modus Fenster: Schalter entfernt, neu verbunden, Adresse neu geladen
    r = await j.buehne.aktion({"name": "werkzeug_modus", "surfaceId": "werkzeug-browser", "context": {}})
    await _ruhe()
    assert r["modus"] == "fenster" and verbindungen[-1] == ["npx", "-y", "@playwright/mcp@latest"]
    assert j.buehne.flaechen["werkzeug-browser"]["daten"]["modus_knopf"] == "Auf der Bühne zeigen"
    assert aufrufe[-1][0] in ("browser_navigate", "browser_take_screenshot")
    with pytest.raises(BuehnenFehler):
        await j.buehne.aktion({"name": "unbekannt", "surfaceId": "werkzeug-browser", "context": {}})
    # schließen über den Knopf
    await j.buehne.aktion({"name": "werkzeug_schliessen", "surfaceId": "werkzeug-browser", "context": {}})
    assert j.buehne.flaechen == {} and wf.offen == {}
    with pytest.raises(BuehnenFehler):
        await j.buehne.werkzeug_oeffnen("gibt-es-nicht")


async def test_browser_direkt_im_fenster_und_nicht_verbunden():
    j, aufrufe, verbindungen, ereignisse = _mit_browser()
    e = await j.buehne.werkzeug_oeffnen("browser", modus="fenster")
    assert e["modus"] == "fenster" and verbindungen == []  # Standardbefehl ist schon sichtbar → nichts zu tun
    await j.buehne.werkzeug_schliessen("browser")
    j.manager.status["browser"] = "fehler"
    j.manager.fehler["browser"] = "npx fehlt"

    async def kaputt(kennung: str) -> dict:
        return {}

    j.manager.neu_verbinden = kaputt  # type: ignore[method-assign]
    with pytest.raises(BuehnenFehler, match="nicht verbunden"):
        await j.buehne.werkzeug_oeffnen("browser")


async def test_shell_terminal_und_dateien_schritte():
    j, aufrufe, verbindungen, ereignisse = _mit_browser()
    befehle: list[dict] = []

    async def shell_befehl(befehl: str, arbeitsverzeichnis: str | None = None, timeout: int = 60) -> str:
        befehle.append({"befehl": befehl})
        return "ok\nzeile 2"

    async def datei_lesen(pfad: str) -> str:
        return "Inhalt"

    j.register.alle_registrieren(
        [
            FunktionsWerkzeug(shell_befehl, "shell_befehl", "shell", schema({"befehl": {"type": "string"}}, ["befehl"]), "kritisch"),
            FunktionsWerkzeug(datei_lesen, "datei_lesen", "liest", schema({"pfad": {"type": "string"}}, ["pfad"]), "lesen"),
        ]
    )
    e = await j.buehne.werkzeug_oeffnen("shell")
    assert e["surfaceId"] == "werkzeug-shell" and e["art"] == "terminal" and e["modus"] is None
    komponenten = j.buehne.flaechen["werkzeug-shell"]["components"]
    assert any(k["component"] == "Formular" for k in komponenten)
    await j.buehne.aktion({"name": "werkzeug_befehl", "surfaceId": "werkzeug-shell", "context": {"werte": {"befehl": "echo hi"}}})
    await _ruhe()
    schritte = j.buehne.flaechen["werkzeug-shell"]["daten"]["schritte"]
    assert befehle == [{"befehl": "echo hi"}] and schritte[-1]["text"].startswith("shell_befehl (befehl=echo hi") and schritte[-1]["ergebnis"] == "ok\nzeile 2"
    with pytest.raises(BuehnenFehler):
        await j.buehne.aktion({"name": "werkzeug_befehl", "surfaceId": "werkzeug-shell", "context": {"werte": {"befehl": ""}}})
    # Dateien: Schrittliste ohne Formular; Reiter schließen (manager.schliessen) räumt die Werkzeugfläche auf
    await j.buehne.werkzeug_oeffnen("dateien")
    assert not any(k["component"] == "Formular" for k in j.buehne.flaechen["werkzeug-dateien"]["components"])
    await _modellaufruf(j, "datei_lesen", {"pfad": "/tmp/x.txt"})
    assert j.buehne.flaechen["werkzeug-dateien"]["daten"]["schritte"][-1]["zustand"] == "ok"
    assert len(j.buehne.flaechen["werkzeug-shell"]["daten"]["schritte"]) == 1  # Dateischritt nicht in der Shell
    await j.buehne.schliessen("werkzeug-dateien")
    assert "dateien" not in j.buehne.werkzeugflaechen.offen
    # Neustart: Werkzeugflächen überleben nicht, Datenflächen schon
    neu = BuehnenManager(j.buehne.speicher, j.buehne.erzeuger, j.senden, j.agent.werkzeug_ausfuehren_extern)
    neu.laden()
    assert neu.flaechen == {}
    # Werkzeuge und Prompt
    namen = {w.name for w in j.register.alle()}
    assert {"buehne_werkzeug_oeffnen", "buehne_werkzeug_schliessen"} <= namen
    ok, text = await j.register.ausfuehren("buehne_werkzeug_oeffnen", {"werkzeug": "shell"})
    assert ok and "werkzeug-shell" in text
    prompt = j._buehne_prompt()
    assert "Werkzeugflächen" in prompt and "shell" in prompt and "Offene Werkzeugflächen: shell" in prompt
    ok, text = await j.register.ausfuehren("buehne_werkzeug_schliessen", {"werkzeug": "shell"})
    assert ok and "geschlossen" in text
    j.konfig.aktualisieren({"buehne": {"aktiv": False}})
    with pytest.raises(BuehnenFehler):
        await j.buehne.werkzeug_oeffnen("shell")
