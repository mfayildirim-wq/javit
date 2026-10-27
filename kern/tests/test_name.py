"""Einstellbarer Name („Javit“): Persona, Systemprompt, Status, Einstellungen, CLI, Meldungen."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jarvis import cli, konfig
from jarvis.konfig import (
    ALTE_STANDARD_PERSONAS,
    STANDARD_PERSONA,
    Einstellungen,
    KonfigSpeicher,
    name_bereinigen,
    standard_persona,
)
from jarvis.server import create_app
from tests.conftest import text_chunks
from tests.helfer import baue_jarvis

KERN = Path(__file__).resolve().parents[1]


def _datei_schreiben(daten: dict) -> KonfigSpeicher:
    pfad = konfig.jarvis_home() / "einstellungen.json"
    pfad.write_text(json.dumps(daten, ensure_ascii=False), encoding="utf-8")
    return KonfigSpeicher()


# ---------------------------------------------------------------------------------------
# Einstellungen und Migration
# ---------------------------------------------------------------------------------------
def test_standardname_und_persona_mit_platzhalter():
    e = Einstellungen()
    assert e.name == "Javit"
    assert "{name}" in e.persona and "Jarvis" not in e.persona
    assert e.persona_text().startswith("Du bist Javit, der persönliche KI-Assistent")
    assert e.stimme.weckwort == "javit" and e.stimme.weckwort_engine == "auto"


@pytest.mark.parametrize("roh", ["", "   ", None, "\n"])
def test_leerer_name_wird_standard(roh):
    assert Einstellungen(name=roh).name == "Javit"
    assert name_bereinigen("  Frau   Friday \x07 ") == "Frau Friday"
    assert len(name_bereinigen("x" * 200)) == 40


@pytest.mark.parametrize("alte", ALTE_STANDARD_PERSONAS)
def test_alte_standard_persona_wird_ersetzt(alte):
    assert "Du bist Jarvis" in alte
    k = _datei_schreiben({"modell": "ollama/x", "persona": alte, "stimme": {"aktiv": True, "weckwort": "hey_jarvis"}})
    e = k.einstellungen
    assert e.name == "Javit" and e.persona == standard_persona() and "{name}" in e.persona
    assert e.persona_text().startswith("Du bist Javit")
    # altes Standard-Weckwort aus einer Datei ohne „name“ → neues Standard-Weckwort
    assert e.stimme.weckwort == "javit" and e.stimme.aktiv is True
    # nach dem Speichern steht „name“ in der Datei
    k.speichern()
    gespeichert = json.loads(k.pfad.read_text(encoding="utf-8"))
    assert gespeichert["name"] == "Javit" and gespeichert["persona"] == standard_persona()


def test_eigene_persona_bleibt_und_nur_platzhalter_wird_ersetzt():
    eigene = "Du bist Jarvis, mein Butler. Sprich wie ein Pirat."
    k = _datei_schreiben({"persona": eigene})
    assert k.einstellungen.persona == eigene
    assert k.einstellungen.persona_text() == eigene  # nichts wird umbenannt
    k.aktualisieren({"persona": "Ich heiße {name} und helfe {name}s Nutzer.", "name": "Friday"})
    assert k.einstellungen.persona_text() == "Ich heiße Friday und helfe Fridays Nutzer."


def test_bewusst_gewaehltes_hey_jarvis_bleibt():
    k = _datei_schreiben({"name": "Javit", "stimme": {"weckwort": "hey_jarvis"}})
    assert k.einstellungen.stimme.weckwort == "hey_jarvis"
    k = _datei_schreiben({"stimme": {"weckwort": "alexa"}})
    assert k.einstellungen.stimme.weckwort == "alexa"


def test_hey_jarvis_bleibt_bei_ausdruecklicher_engine_oder_eigenem_modell():
    """Weckwort-Migration nur für den alten Standard (Engine „auto“, kein eigenes Modell)."""
    k = _datei_schreiben({"stimme": {"weckwort": "hey_jarvis", "weckwort_engine": "openwakeword"}})
    assert k.einstellungen.stimme.weckwort == "hey_jarvis"
    k = _datei_schreiben({"stimme": {"weckwort": "hey_jarvis", "weckwort_modell_pfad": "~/x.onnx"}})
    assert k.einstellungen.stimme.weckwort == "hey_jarvis"
    k = _datei_schreiben({"stimme": {"weckwort": "Hey_Jarvis ", "weckwort_engine": "auto"}})
    assert k.einstellungen.stimme.weckwort == "javit"


def test_alte_persona_mit_anderen_zeilenumbruechen_wird_ersetzt():
    alte = ALTE_STANDARD_PERSONAS[0].replace(". ", ".\n", 1) + "\n"
    assert _datei_schreiben({"persona": alte}).einstellungen.persona == standard_persona()


def test_alte_datei_ohne_neue_felder_laedt():
    k = _datei_schreiben({"modell": "ollama/x", "anrede": "Chef", "stimme": {"aktiv": False, "schwelle": 0.6}})
    e = k.einstellungen
    assert (e.name, e.anrede, e.stimme.weckwort, e.stimme.weckwort_varianten) == ("Javit", "Chef", "javit", [])
    assert e.stimme.model_dump()["schwelle"] == 0.6  # unbekannte Stimmfelder bleiben erhalten


def test_varianten_als_text_und_engine_normalisiert():
    k = KonfigSpeicher()
    k.aktualisieren({"stimme": {"weckwort_varianten": "javit; ja witt, dschawit", "weckwort_engine": "Vosk"}})
    assert k.einstellungen.stimme.weckwort_varianten == ["javit", "ja witt", "dschawit"]
    assert k.einstellungen.stimme.weckwort_engine == "vosk"
    with pytest.raises(ValueError):
        k.aktualisieren({"stimme": {"weckwort_engine": "porcupine"}})


def test_persona_mac_und_computer():
    assert standard_persona() in (STANDARD_PERSONA, STANDARD_PERSONA.replace("auf seinem Mac", "auf seinem Computer"))


# ---------------------------------------------------------------------------------------
# Systemprompt, Status, REST
# ---------------------------------------------------------------------------------------
async def test_systemprompt_nutzt_namen():
    j, skript = baue_jarvis([text_chunks("Hallo."), text_chunks("Hallo.")])
    j.konfig.aktualisieren({"name": "Friday"})
    await j.agent.verarbeiten("Wer bist du?")
    system = skript.aufrufe[0]["messages"][0]["content"]
    assert system.startswith("Du bist Friday, der persönliche KI-Assistent") and "Jarvis" not in system
    # eigene Persona ohne Namen → Name wird ergänzt
    j.konfig.aktualisieren({"persona": "Antworte immer gereimt."})
    await j.agent.verarbeiten("Und jetzt?")
    system = skript.aufrufe[1]["messages"][0]["content"]
    assert system.startswith("Antworte immer gereimt.\n\nDein Name ist Friday.")


def test_status_und_einstellungen_liefern_namen():
    j, _ = baue_jarvis()
    with TestClient(create_app(j, integrationen_starten=False, stimme_starten=False), base_url="http://127.0.0.1:8765") as c:
        s = c.get("/api/status").json()
        assert s["name"] == "Javit" and s["stimme"]["weckwort"] == "javit" and s["stimme"]["engine"] == "vosk"
        assert c.get("/api/einstellungen").json()["name"] == "Javit"
        r = c.put("/api/einstellungen", json={"name": "  Friday ", "stimme": {"weckwort": "friday, hey friday"}})
        assert r.status_code == 200 and r.json()["name"] == "Friday"
        s = c.get("/api/status").json()
        assert s["name"] == "Friday" and s["stimme"]["weckwort"] == "friday, hey friday"
        assert konfig.aktueller_name() == "Friday"
        assert c.put("/api/einstellungen", json={"name": ""}).json()["name"] == "Javit"
        assert c.put("/api/einstellungen", json={"stimme": {"weckwort_engine": "unsinn"}}).status_code == 422


class FakeStimme:
    def __init__(self):
        self.aufrufe: list[str] = []
        self.hoert = False

    async def start(self):
        self.aufrufe.append("start")

    async def stop(self):
        self.aufrufe.append("stop")


def test_weckwort_aenderung_startet_stimme_neu():
    j, _ = baue_jarvis()
    j.konfig.aktualisieren({"stimme": {"aktiv": True}})
    j.stimme = FakeStimme()
    with TestClient(create_app(j, integrationen_starten=False, stimme_starten=False), base_url="http://127.0.0.1:8765") as c:
        c.put("/api/einstellungen", json={"anrede": "Chef"})
        assert j.stimme.aufrufe == []  # nichts Weckwort-Relevantes geändert
        c.put("/api/einstellungen", json={"stimme": {"weckwort": "hey_jarvis"}})
        assert j.stimme.aufrufe == ["stop", "start"]
        c.put("/api/einstellungen", json={"stimme": {"weckwort_engine": "vosk"}})
        assert j.stimme.aufrufe == ["stop", "start", "stop", "start"]


async def test_mitteilungen_mit_namen(monkeypatch):
    j, _ = baue_jarvis()
    j.konfig.aktualisieren({"name": "Friday", "anrede_verwenden": False})
    titel = []

    class Aktionen:
        async def mitteilung_anzeigen(self, text, t):
            titel.append(t)
            return "ok"

    from jarvis.werkzeuge import desktop

    monkeypatch.setattr(desktop, "_aktionen", lambda: Aktionen())
    await desktop.mitteilung_anzeigen.ausfuehren(text="Hallo")
    assert titel == ["Friday"]
    assert "Jarvis" not in json.dumps(desktop.mitteilung_anzeigen.als_openai(), ensure_ascii=False)


@pytest.mark.parametrize("plattform", ["windows", "linux"])
def test_werkzeugbeschreibungen_neutral(monkeypatch, plattform):
    monkeypatch.setenv("JARVIS_PLATTFORM", plattform)
    j, _ = baue_jarvis()
    for w in j.register.alle():
        assert "Jarvis" not in json.dumps(w.als_openai(), ensure_ascii=False), w.name


def test_fehlertexte_mit_namen(monkeypatch):
    from jarvis.stimme import fehler

    KonfigSpeicher().aktualisieren({"name": "Friday"})
    monkeypatch.setenv("JARVIS_PLATTFORM", "mac")
    assert "Friday neu starten" in fehler.hinweis_mikrofon_rechte() and "Jarvis" not in fehler.hinweis_mikrofon_rechte()
    assert "Friday neu starten" in fehler.portaudio_hinweis()
    monkeypatch.setenv("JARVIS_PLATTFORM", "windows")
    assert "Friday neu starten" in fehler.hinweis_mikrofon_rechte()


# ---------------------------------------------------------------------------------------
# Kommandozeile `jarvis` / `javit`
# ---------------------------------------------------------------------------------------
def test_pyproject_hat_beide_befehle():
    daten = tomllib.loads((KERN / "pyproject.toml").read_text(encoding="utf-8"))
    skripte = daten["project"]["scripts"]
    assert skripte["javit"] == skripte["jarvis"] == "jarvis.cli:main"
    assert any(a.startswith("vosk") for a in daten["project"]["optional-dependencies"]["stimme"])


@pytest.mark.parametrize(("argv0", "prog"), [("/x/bin/javit", "javit"), ("C:\\venv\\Scripts\\javit.exe", "javit"),
                                             ("/x/bin/jarvis", "jarvis"), ("-c", "jarvis")])
def test_cli_programmname(monkeypatch, argv0, prog):
    monkeypatch.setattr(sys, "argv", [argv0.replace("\\", "/")])
    assert cli.parser_erstellen().prog == prog


def test_cli_hilfe_nutzt_namen(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["/usr/local/bin/javit"])
    assert "Javit – Ihr persönlicher KI-Assistent" in cli.parser_erstellen().format_help()
    KonfigSpeicher().aktualisieren({"name": "Friday"})
    hilfe = cli.parser_erstellen().format_help()
    assert hilfe.startswith("usage: javit") and "Friday – Ihr persönlicher KI-Assistent" in hilfe
    assert "Friday starten" in hilfe and "Jarvis" not in hilfe
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert "(Friday)" in capsys.readouterr().out
