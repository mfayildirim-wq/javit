import asyncio
import json

import pytest

from jarvis import cli
from jarvis.geheimnisse import Geheimnisspeicher
from jarvis.konfig import KonfigSpeicher
from jarvis.werkzeuge import prozess
from tests.conftest import text_chunks, tool_chunks
from tests.helfer import baue_jarvis


@pytest.fixture(autouse=True)
def kein_server(monkeypatch):
    monkeypatch.setattr(cli, "_server_laeuft", lambda port=None: False)


def test_cli_katalog(capsys):
    assert cli.main(["katalog"]) == 0
    aus = capsys.readouterr().out
    assert "spotify" in aus and "benötigt: SPOTIFY_CLIENT_ID" in aus
    assert cli.main(["katalog", "smart"]) == 0
    aus = capsys.readouterr().out
    assert "home-assistant" in aus and "spotify" not in aus


def test_cli_modell_und_schluessel(capsys):
    assert cli.main(["modell", "anthropic/claude-sonnet-4-5"]) == 0
    assert KonfigSpeicher().einstellungen.modell == "anthropic/claude-sonnet-4-5"
    assert cli.main(["schluessel", "ANTHROPIC_API_KEY", "--wert", "sk-ant"]) == 0
    assert Geheimnisspeicher().holen("ANTHROPIC_API_KEY") == "sk-ant"
    assert "verschlüsselte Datei" in capsys.readouterr().out
    assert cli.main(["schluessel", "ANTHROPIC_API_KEY", "--loeschen"]) == 0
    assert Geheimnisspeicher().holen("ANTHROPIC_API_KEY") is None


def test_cli_add_list_remove(capsys, monkeypatch):
    assert cli.main(["list"]) == 0
    assert "Keine Integrationen" in capsys.readouterr().out
    assert cli.main(["add", "wetter"]) == 0
    aus = capsys.readouterr().out
    assert "wetter" in aus and "verbunden" in aus and "wetter__wetter_abrufen [lesen]" in aus
    # Interaktive Abfrage fehlender Werte
    monkeypatch.setattr("builtins.input", lambda frage: "192.168.1.2")
    monkeypatch.setattr(cli.getpass, "getpass", lambda frage: "hue-benutzer")
    assert cli.main(["add", "philips-hue"]) == 0
    assert "Hinweis:" in capsys.readouterr().out
    assert Geheimnisspeicher().holen("HUE_BENUTZER") == "hue-benutzer"
    assert cli.main(["list"]) == 0
    aus = capsys.readouterr().out
    assert "wetter" in aus and "philips-hue" in aus
    assert cli.main(["remove", "wetter"]) == 0
    assert cli.main(["remove", "wetter"]) == 1
    assert cli.main(["add", "unsinn_xyz"]) == 1


def test_cli_sag(capsys, monkeypatch):
    j, _ = baue_jarvis([tool_chunks("c", "uhrzeit_datum", {}), text_chunks("Es ist Abend, Sir.")])
    monkeypatch.setattr("jarvis.anwendung.Jarvis", lambda: j)
    assert cli.main(["sag", "Wie", "spät?", "--ohne-integrationen"]) == 0
    erfasst = capsys.readouterr()
    assert "Es ist Abend, Sir." in erfasst.out and "→ uhrzeit_datum" in erfasst.err


def test_cli_parser():
    p = cli.parser_erstellen()
    args = p.parse_args(["start", "--kein-browser", "--port", "9000"])
    assert args.kein_browser and args.port == 9000
    with pytest.raises(SystemExit):
        p.parse_args([])


# ---------------------------------------------------------------------------
# System-Werkzeuge
# ---------------------------------------------------------------------------
async def test_system_werkzeuge():
    j, _ = baue_jarvis()
    r = j.register
    ok, text = await r.ausfuehren("uhrzeit_datum", {})
    assert ok and "Uhr" in text and "Kalenderwoche" in text
    ok, text = await r.ausfuehren("katalog_durchsuchen", {"suchbegriff": "musik"})
    assert ok and "spotify" in text
    ok, text = await r.ausfuehren("integration_hinzufuegen", {"quelle": "spotify"})
    assert ok and "SPOTIFY_CLIENT_ID" in text and "developer.spotify.com" in text
    assert r.holen("integration_hinzufuegen").risiko == "kritisch"
    ok, text = await r.ausfuehren("integration_hinzufuegen", {"quelle": "wetter"})
    assert ok and "verbunden" in text
    ok, text = await r.ausfuehren("integrationen_auflisten", {})
    assert "Wetter" in text and "verbunden" in text
    ok, text = await r.ausfuehren("modell_wechseln", {"modell": "gemini/gemini-2.5-flash"})
    assert ok and j.einstellungen.modell == "gemini/gemini-2.5-flash"
    ok, _ = await r.ausfuehren("erinnern", {"text": "Lieblingsfarbe ist Rot"})
    ok, text = await r.ausfuehren("erinnerung_suchen", {"anfrage": "Welche Lieblingsfarbe?"})
    assert "Rot" in text
    ok, text = await r.ausfuehren("timer_stellen", {})
    assert not ok
    await j.stoppen()


async def test_timer_meldet_sich(monkeypatch):
    monkeypatch.setattr(prozess, "ist_mac", lambda: False)
    j, _ = baue_jarvis()
    ereignisse = []

    async def hoerer(e):
        ereignisse.append(e)

    j.hoerer_hinzufuegen(hoerer)
    ok, text = await j.register.ausfuehren("timer_stellen", {"sekunden": 0.05, "text": "Tee"})
    assert ok and "Tee" in text and "Sekunde" in text
    await asyncio.sleep(0.2)
    ende = [e for e in ereignisse if e["typ"] == "antwort_ende"]
    assert ende and "Tee" in ende[0]["text"] and ende[0]["text"].startswith("Sir,")
    await j.stoppen()


async def test_status_und_stimme_schalten(monkeypatch):
    j, _ = baue_jarvis()

    class FalscherDienst:
        def __init__(self, einstellungen, ereignis, anfrage):
            self.einstellungen = einstellungen
            self.anfrage = anfrage
            self.aktiv = False
            self.hoert = False
            self.gesprochen = []

        async def start(self):
            self.aktiv = self.hoert = True

        async def stop(self):
            self.aktiv = self.hoert = False

        async def sprechen(self, text):
            self.gesprochen.append(text)

        async def antwort_abhoeren(self, warte_s=None):
            return "ja bitte"

    import jarvis.stimme

    monkeypatch.setattr(jarvis.stimme, "StimmDienst", FalscherDienst)
    assert await j.stimme_schalten(True)
    await asyncio.sleep(0.01)
    assert j.status()["stimme"]["hoert"] is True and j.einstellungen.stimme.aktiv is True
    assert callable(j.stimme.einstellungen) and j.stimme.einstellungen() is j.einstellungen
    assert await j._sprach_freigabe("Darf ich?") is True
    assert j.stimme.gesprochen == ["Darf ich?"]
    await j.vorlesen("**Hallo**")
    assert j.stimme.gesprochen[-1] == "Hallo"
    assert await j.stimme_schalten(False)
    assert j.status()["stimme"]["hoert"] is False and json.loads(
        (j.konfig.pfad).read_text())["stimme"]["aktiv"] is False
    await j.stoppen()
