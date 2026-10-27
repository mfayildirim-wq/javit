import json
from datetime import datetime

import pytest

from jarvis.werkzeuge import WerkzeugFehler, prozess
from jarvis.werkzeuge import mac
from jarvis.werkzeuge.prozess import ProzessErgebnis


class Aufzeichner:
    def __init__(self):
        self.befehle: list[tuple] = []
        self.eingaben: list = []
        self.antworten: dict[str, str] = {}

    async def __call__(self, *befehl, eingabe=None, timeout=30, **kw):
        self.befehle.append(befehl)
        self.eingaben.append(eingabe)
        for muster, ausgabe in self.antworten.items():
            if any(muster in str(t) for t in befehl):
                return ProzessErgebnis(0, ausgabe, "")
        return ProzessErgebnis(0, "", "")

    @property
    def skripte(self) -> list[str]:
        return [b[2] for b in self.befehle if b[0] == "osascript"]


@pytest.fixture
def auf_mac(monkeypatch):
    a = Aufzeichner()
    monkeypatch.setattr(prozess, "ist_mac", lambda: True)
    monkeypatch.setattr(prozess, "ausfuehren", a)
    return a


def test_as_text_escaping():
    assert mac.as_text('Er sagte "Hallo"') == '"Er sagte \\"Hallo\\""'
    assert mac.as_text("C:\\pfad") == '"C:\\\\pfad"'
    assert mac.as_text('\\"') == '"\\\\\\""'


def test_as_datum():
    zeilen = mac.as_datum("d", datetime(2025, 3, 1, 14, 30, 5))
    assert "set year of d to 2025" in zeilen and "set month of d to 3" in zeilen
    assert "set day of d to 1" in zeilen and "set time of d to 52205" in zeilen
    assert zeilen.index("set day of d to 1") < zeilen.index("set month of d to 3")


async def test_nicht_mac_freundliche_meldung(monkeypatch):
    monkeypatch.setattr(prozess, "ist_mac", lambda: False)
    with pytest.raises(WerkzeugFehler, match="nur auf macOS"):
        await mac.app_oeffnen.ausfuehren(name="Safari")


async def test_app_oeffnen_und_beenden(auf_mac):
    await mac.app_oeffnen.ausfuehren(name="Safari")
    assert auf_mac.befehle[0] == ("open", "-a", "Safari")
    await mac.app_beenden.ausfuehren(name='Böse "App"')
    assert auf_mac.befehle[1] == ("osascript", "-e", 'tell application "Böse \\"App\\"" to quit')


async def test_notiz_mit_anfuehrungszeichen(auf_mac):
    await mac.notiz_anlegen.ausfuehren(titel='Zitat "Jarvis"', text='Er sagte: "Ja" & <b>\nZeile 2')
    skript = auf_mac.skripte[0]
    assert 'name:"Zitat \\"Jarvis\\""' in skript
    assert '<h1>Zitat \\"Jarvis\\"</h1>' in skript
    assert "&amp; &lt;b&gt;<br>Zeile 2" in skript
    assert skript.startswith('tell application "Notes"')


async def test_musik_spotify_und_music(auf_mac):
    await mac.musik_steuern.ausfuehren(aktion="weiter", app="spotify")
    assert auf_mac.skripte[-1] == 'tell application "Spotify" to next track'
    await mac.musik_steuern.ausfuehren(aktion="pause", app="music")
    assert auf_mac.skripte[-1] == 'tell application "Music" to pause'
    # auto: Spotify läuft → Spotify
    auf_mac.antworten["is running"] = "true"
    await mac.musik_steuern.ausfuehren(aktion="play")
    assert auf_mac.skripte[-1] == 'tell application "Spotify" to play'
    await mac.musik_steuern.ausfuehren(aktion="aktuell", app="spotify")
    assert "current track" in auf_mac.skripte[-1]


async def test_musik_suchen(auf_mac):
    await mac.musik_steuern.ausfuehren(aktion="suchen", app="spotify", suchbegriff='AC/DC "Thunder"')
    assert ("open", "spotify:search:AC/DC%20%22Thunder%22") in auf_mac.befehle
    await mac.musik_steuern.ausfuehren(aktion="suchen", app="music", suchbegriff='Queen "Bohemian"')
    assert 'search library playlist 1 for "Queen \\"Bohemian\\""' in auf_mac.skripte[-1]
    with pytest.raises(WerkzeugFehler):
        await mac.musik_steuern.ausfuehren(aktion="suchen", app="music")


async def test_lautstaerke(auf_mac):
    auf_mac.antworten["volume"] = "40"
    text = await mac.lautstaerke_setzen.ausfuehren(prozent=140)
    assert "set volume output volume 100" in auf_mac.skripte[-1] and "40 %" in text
    await mac.lautstaerke_setzen.ausfuehren(aenderung=-10)
    assert "aktuell + (-10)" in auf_mac.skripte[-1]
    await mac.lautstaerke_setzen.ausfuehren(stumm=True)
    assert "set volume output muted true" in auf_mac.skripte[-1]
    with pytest.raises(WerkzeugFehler):
        await mac.lautstaerke_setzen.ausfuehren()


async def test_mitteilung(auf_mac):
    await mac.mitteilung_anzeigen.ausfuehren(text='Timer "Tee" fertig')
    from jarvis.konfig import aktueller_name

    assert auf_mac.skripte[-1] == f'display notification "Timer \\"Tee\\" fertig" with title "{aktueller_name()}"'
    await mac.mitteilung_anzeigen.ausfuehren(text="Hallo", titel="Eigener Titel")
    assert auf_mac.skripte[-1].endswith('with title "Eigener Titel"')
    assert "Jarvis" not in json.dumps(mac.mitteilung_anzeigen.als_openai(), ensure_ascii=False)


async def test_erinnerung_und_termin(auf_mac):
    await mac.erinnerung_anlegen.ausfuehren(titel='Milch "bio"', faellig="2025-03-01T09:15", liste="Einkauf")
    s = auf_mac.skripte[-1]
    assert 'tell list "Einkauf"' in s and 'name:"Milch \\"bio\\""' in s and "due date:faelligDatum" in s
    assert "set time of faelligDatum to 33300" in s
    await mac.erinnerung_anlegen.ausfuehren(titel="x")
    assert "tell default list" in auf_mac.skripte[-1]
    await mac.termin_anlegen.ausfuehren(titel="Zahnarzt", start="2025-03-02T10:00", dauer_minuten=30, ort="Praxis")
    s = auf_mac.skripte[-1]
    assert "set time of startD to 36000" in s and "set time of endeD to 37800" in s
    assert 'summary:"Zahnarzt"' in s and 'location:"Praxis"' in s and "first calendar whose writable is true" in s
    with pytest.raises(WerkzeugFehler, match="Ungültiges Datum"):
        await mac.termin_anlegen.ausfuehren(titel="x", start="morgen")


async def test_kalender_lesen(auf_mac):
    auf_mac.antworten["Calendar"] = "Meeting | Montag | Arbeit"
    text = await mac.kalender_termine.ausfuehren(ab="2025-03-03", tage=2)
    assert text == "Meeting | Montag | Arbeit"
    s = auf_mac.skripte[-1]
    assert "set day of startD to 3" in s and "set day of endeD to 5" in s and "start date ≥ startD" in s


async def test_url_zwischenablage_bildschirmfoto(auf_mac):
    await mac.url_oeffnen.ausfuehren(url="apple.com")
    assert auf_mac.befehle[-1] == ("open", "https://apple.com")
    with pytest.raises(WerkzeugFehler, match="nicht erlaubt"):
        await mac.url_oeffnen.ausfuehren(url="file:///etc/passwd")
    await mac.zwischenablage_schreiben.ausfuehren(text="Hallo")
    assert auf_mac.befehle[-1] == ("pbcopy",) and auf_mac.eingaben[-1] == "Hallo"
    auf_mac.antworten["pbpaste"] = "Inhalt"
    assert await mac.zwischenablage_lesen.ausfuehren() == "Inhalt"
    text = await mac.bildschirmfoto.ausfuehren(pfad="/tmp/x.png")
    assert auf_mac.befehle[-1] == ("screencapture", "-x", "/tmp/x.png") and "/tmp/x.png" in text


async def test_shortcuts(auf_mac):
    auf_mac.antworten["list"] = "Licht an\nGuten Morgen"
    assert "Guten Morgen" in await mac.kurzbefehle_auflisten.ausfuehren()
    await mac.shortcuts_ausfuehren.ausfuehren(name="Licht an", eingabe="Wohnzimmer")
    befehl = auf_mac.befehle[-1]
    assert befehl[:3] == ("shortcuts", "run", "Licht an") and "--input-path" in befehl


async def test_applescript_fehler_mit_hinweis(monkeypatch):
    async def fehler(*befehl, **kw):
        return ProzessErgebnis(1, "", "execution error: Not authorized to send Apple events (-1743)")

    monkeypatch.setattr(prozess, "ist_mac", lambda: True)
    monkeypatch.setattr(prozess, "ausfuehren", fehler)
    with pytest.raises(WerkzeugFehler, match="Automation"):
        await mac.laufende_apps.ausfuehren()


async def test_systeminfo(auf_mac):
    auf_mac.antworten["pmset"] = "Now drawing from 'Battery Power' 87%"
    auf_mac.antworten["getsummary"] = "  SSID : MeinWLAN"
    auf_mac.antworten["hw.memsize"] = str(16 * 1024**3)
    text = await mac.systeminfo.ausfuehren()
    assert "87%" in text and "MeinWLAN" in text and "16 GB" in text


def test_shortcuts_ausfuehren_ist_kritisch():
    # Kurzbefehle können beliebige Aktionen enthalten → immer Freigabe
    assert mac.shortcuts_ausfuehren.risiko == "kritisch"
    assert mac.shortcuts_ausfuehren.risiko_fuer({"name": "x"}) == "kritisch"
    assert "Licht an" in mac.shortcuts_ausfuehren.freigabe_grund({"name": "Licht an"})
    assert mac.kurzbefehle_auflisten.risiko == "lesen"
