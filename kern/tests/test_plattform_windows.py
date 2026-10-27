"""Windows-Implementierung mit gemocktem Prozessaufruf: erzeugte PowerShell-Befehle, sichere
Übergabe von Werten (Umgebung/stdin statt Skripttext) und Injektionsversuche."""

from __future__ import annotations

import base64
import json
import re

import pytest

from jarvis.plattform import windows
from jarvis.plattform.windows import WindowsAktionen, kodieren, ps_literal, such_sql
from jarvis.werkzeuge import WerkzeugFehler, desktop, prozess
from jarvis.werkzeuge.prozess import ProzessErgebnis

BOESE = [
    "x'; Remove-Item -Recurse C:\\ ; '",
    'x"; Stop-Computer; "',
    "$(Stop-Computer)",
    "`whoami`",
    "a; rm -rf ~",
    "‘; Stop-Computer; ’",
    "Zeile1\nZeile2 & | > <",
]


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def skript_aus(befehl: tuple) -> str:
    i = befehl.index("-EncodedCommand")
    return base64.b64decode(befehl[i + 1]).decode("utf-16-le")


class PsAufzeichner:
    """Ersetzt prozess.ausfuehren: merkt sich Befehl, Umgebung und stdin; Antwort Base64 (wie Jarvis-Ausgabe)."""

    def __init__(self):
        self.aufrufe: list[dict] = []
        self.antworten: list[tuple[str, str]] = []  # (Teilstring im Skript, Klartext-Antwort)
        self.code = 0

    async def __call__(self, *befehl, eingabe=None, timeout=30, umgebung=None, **kw):
        skript = skript_aus(befehl) if "-EncodedCommand" in befehl else ""
        self.aufrufe.append({"befehl": befehl, "skript": skript, "umgebung": umgebung or {}, "eingabe": eingabe})
        for muster, antwort in self.antworten:
            if muster in skript:
                return ProzessErgebnis(self.code, b64(antwort), "Fehlertext" if self.code else "")
        return ProzessErgebnis(self.code, b64("ok"), "Fehlertext" if self.code else "")

    @property
    def letzter(self) -> dict:
        return self.aufrufe[-1]


@pytest.fixture
def win(monkeypatch):
    monkeypatch.setenv("JARVIS_PLATTFORM", "windows")
    a = PsAufzeichner()
    monkeypatch.setattr(prozess, "ausfuehren", a)
    return a


def test_powershell_aufruf_form(win):
    befehl = windows.powershell_befehl("Jarvis-Ausgabe 'x'")
    assert befehl[0].lower().endswith("powershell.exe")
    assert befehl[1:4] == ["-NoProfile", "-NonInteractive", "-EncodedCommand"]
    skript = base64.b64decode(befehl[4]).decode("utf-16-le")
    assert skript.startswith(windows.VORSPANN) and skript.endswith("Jarvis-Ausgabe 'x'")
    assert kodieren("ä") == base64.b64encode("ä".encode("utf-16-le")).decode()


def test_ps_literal_verdoppelt_alle_einfachen_anfuehrungszeichen():
    assert ps_literal("O'Neil") == "'O''Neil'"
    assert ps_literal("‘x’") == "'‘‘x’’'"
    assert ps_literal("a\x00b") == "'ab'"
    assert ps_literal("$(Stop-Computer)") == "'$(Stop-Computer)'"  # in '…' keine Auswertung


@pytest.mark.parametrize("boese", BOESE)
async def test_werte_nie_im_skript_oder_in_argumenten(win, boese):
    """Gefährliche Werte landen nur in Umgebungsvariablen bzw. Base64 auf stdin – nie im Skript/argv."""
    a = WindowsAktionen()
    await a.mitteilung_anzeigen(boese, boese)
    await a.zwischenablage_schreiben(boese)
    await a.url_oeffnen("https://example.org/?q=" + boese)
    await a.bildschirmfoto("C:\\Users\\x\\" + boese + ".png")
    for aufruf in win.aufrufe:
        argv = " ".join(aufruf["befehl"])
        assert boese not in argv and boese not in aufruf["skript"]
    assert win.aufrufe[0]["umgebung"] == {"JARVIS_ARG_TITEL": boese, "JARVIS_ARG_TEXT": boese}
    assert base64.b64decode(win.aufrufe[1]["eingabe"]).decode("utf-8") == boese
    assert win.aufrufe[2]["umgebung"]["JARVIS_ARG_URL"].endswith(boese)
    assert boese in win.aufrufe[3]["umgebung"]["JARVIS_ARG_PFAD"]


async def test_app_oeffnen_und_beenden(win):
    win.antworten.append(("Get-StartApps", "Spotify"))
    assert await WindowsAktionen().app_oeffnen("spotify") == "Spotify wurde geöffnet."
    assert win.letzter["umgebung"] == {"JARVIS_ARG_NAME": "spotify"}
    assert "Start Menu" in win.letzter["skript"] and "shell:AppsFolder" in win.letzter["skript"]
    win.antworten.insert(0, ("CloseMainWindow", "1"))
    assert await WindowsAktionen().app_beenden("Notepad.exe") == "Notepad.exe wurde beendet."
    assert "CloseMainWindow" in win.letzter["skript"]
    for unzulaessig in ("C:\\Windows\\evil.exe", "..\\x", "https://x", "-Verb RunAs", "/bin/sh"):
        with pytest.raises(WerkzeugFehler, match="nur den Namen"):
            await WindowsAktionen().app_oeffnen(unzulaessig)


async def test_lautstaerke_werte_und_com_snippet(win):
    win.antworten.append(("IAudioEndpointVolume", "35"))
    text = await WindowsAktionen().lautstaerke_setzen(140, None, None)
    assert text == "Lautstärke jetzt 35 %."
    assert win.letzter["umgebung"] == {"JARVIS_ARG_PROZENT": "100", "JARVIS_ARG_AENDERUNG": "", "JARVIS_ARG_STUMM": ""}
    assert "Add-Type -TypeDefinition" in win.letzter["skript"] and "SendKeys" in win.letzter["skript"]
    await WindowsAktionen().lautstaerke_setzen(None, -20, True)
    assert win.letzter["umgebung"] == {"JARVIS_ARG_PROZENT": "", "JARVIS_ARG_AENDERUNG": "-20", "JARVIS_ARG_STUMM": "1"}
    win.antworten.insert(0, ("IAudioEndpointVolume", "?"))
    assert "Medientasten" in await WindowsAktionen().lautstaerke_setzen(None, 10, None)
    skript = win.letzter["skript"]
    # Ergebnis der relativen Änderung bleibt Zeichenkette ('0' ist wahr, die Zahl 0 wäre falsch →
    # „von 10 % um -10“ würde sonst nicht gesetzt); Fallback ohne 1..0 (= zwei Tastendrücke)
    assert "$prozent = [string]([Math]::Round(" in skript
    assert "if ($schritte -gt 0) { 1..$schritte" in skript


@pytest.mark.parametrize("name", ["logoff", "LOGOFF.EXE", "shutdown", "tsdiscon", "rundll32", "taskkill", "runas"])
async def test_systemprogramme_nicht_als_app(win, name):
    for aktion in (WindowsAktionen().app_oeffnen, WindowsAktionen().app_beenden):
        with pytest.raises(WerkzeugFehler, match="Systemprogramm"):
            await aktion(name)
    assert win.aufrufe == []


async def test_musik_medientasten_und_suche(win):
    a = WindowsAktionen()
    await a.musik_steuern("weiter", "auto", None)
    assert win.letzter["umgebung"] == {"JARVIS_ARG_TASTE": str(0xB0)} and "keybd_event" in win.letzter["skript"]
    await a.musik_steuern("playpause", "spotify", None)
    assert win.letzter["umgebung"]["JARVIS_ARG_TASTE"] == str(0xB3)
    await a.musik_steuern("suchen", "spotify", 'AC/DC "Thunder"')
    assert win.letzter["umgebung"]["JARVIS_ARG_URL"] == "spotify:search:AC/DC%20%22Thunder%22"
    win.antworten.append(("Spotify", "Daft Punk - One More Time"))
    assert await a.musik_steuern("aktuell", "auto", None) == "Daft Punk - One More Time"
    win.antworten[-1] = ("Spotify", "Spotify Premium")
    assert "läuft gerade nichts" in await a.musik_steuern("aktuell", "auto", None)


async def test_zwischenablage_lesen_unicode(win):
    win.antworten.append(("Get-Clipboard", "Grüße „Jarvis“ ✓"))
    assert await WindowsAktionen().zwischenablage_lesen() == "Grüße „Jarvis“ ✓"


async def test_systeminfo_und_bildschirmfoto(win):
    win.antworten.append(("Win32_OperatingSystem", "System: Microsoft Windows 11 Pro"))
    assert "Windows 11" in await WindowsAktionen().systeminfo()
    await WindowsAktionen().bildschirmfoto("C:\\Users\\x\\Desktop\\a.png")
    assert "CopyFromScreen" in win.letzter["skript"]


async def test_fehler_wird_verstaendlich(win):
    win.code = 1
    with pytest.raises(WerkzeugFehler, match="Mitteilung fehlgeschlagen: Fehlertext"):
        await WindowsAktionen().mitteilung_anzeigen("x", "y")


def test_such_sql_maskiert_eingaben():
    sql = such_sql("Bericht 'Q1' 50%_[x] \"zitat\"", "C:\\Users\\x", nur_namen=False, max_treffer=20)
    assert sql.startswith("SELECT TOP 20 System.ItemPathDisplay FROM SYSTEMINDEX WHERE SCOPE='file:C:/Users/x'")
    assert "LIKE '%Bericht ''Q1'' 50[%][_][[]x] \"zitat\"%'" in sql
    assert "CONTAINS(*, '\"Bericht ''Q1'' 50%_[x]  zitat\"')" in sql
    # Ohne verdoppelte Anführungszeichen gibt es keine Möglichkeit, aus dem String auszubrechen
    ohne_escapes = sql.replace("''", "")
    assert ohne_escapes.count("'") % 2 == 0
    nur_namen = such_sql("x' OR 1=1 --", "C:\\Users\\o'brien", nur_namen=True, max_treffer=10_000)
    assert "CONTAINS" not in nur_namen and "SELECT TOP 500" in nur_namen
    assert "SCOPE='file:C:/Users/o''brien'" in nur_namen and "LIKE '%x'' OR 1=1 --%'" in nur_namen


async def test_dateien_suchen_mit_index_und_rueckfall(win, tmp_path):
    win.antworten.append(("ADODB", "C:\\Users\\x\\Steuer.pdf\nC:\\Users\\x\\Steuer2.pdf"))
    treffer = await WindowsAktionen().dateien_suchen("Steuer", "C:\\Users\\x", False, 20)
    assert treffer == ["C:\\Users\\x\\Steuer.pdf", "C:\\Users\\x\\Steuer2.pdf"]
    assert win.letzter["umgebung"]["JARVIS_ARG_SQL"].startswith("SELECT TOP 20")
    # Indexdienst liefert nichts → Python-Namenssuche
    win.antworten.clear()
    win.antworten.append(("ADODB", ""))
    (tmp_path / "Urlaub.txt").write_text("x")
    assert await WindowsAktionen().dateien_suchen("urlaub", str(tmp_path), True, 5) == [str(tmp_path / "Urlaub.txt")]


def test_shell_befehl_als_encoded_command(monkeypatch):
    befehl = 'Get-ChildItem "C:\\Program Files" | Where-Object { $_.Name -like \'*x*\' }'
    argv = WindowsAktionen().shell_befehl(befehl)
    assert argv[0].lower().endswith("powershell.exe") and argv[1:4] == ["-NoProfile", "-NonInteractive", "-EncodedCommand"]
    assert base64.b64decode(argv[4]).decode("utf-16-le").endswith("\n" + befehl)
    assert befehl not in " ".join(argv)


async def test_desktop_werkzeuge_nutzen_windows(win):
    """Die neutralen Werkzeuge rufen auf JARVIS_PLATTFORM=windows die PowerShell-Implementierung."""
    win.antworten.append(("Get-Clipboard", ""))
    assert await desktop.zwischenablage_lesen.ausfuehren() == "(Die Zwischenablage ist leer.)"
    await desktop.url_oeffnen.ausfuehren(url="example.org")
    assert win.letzter["umgebung"] == {"JARVIS_ARG_URL": "https://example.org"}
    with pytest.raises(WerkzeugFehler, match="nicht erlaubt"):
        await desktop.url_oeffnen.ausfuehren(url="file:///C:/Windows/System32/calc.exe")
    with pytest.raises(WerkzeugFehler, match="nicht erlaubt"):
        await desktop.url_oeffnen.ausfuehren(url="ms-msdt:/id PCWDiagnostic")


def test_skripte_sind_ausgeglichen():
    """Einfache statische Prüfung der PowerShell-Skripte: Klammern ausgeglichen, keine Python-Platzhalter."""
    from jarvis.stimme.tts import SKRIPT_SAPI

    skripte = {n: v for n, v in vars(windows).items() if n.startswith("SKRIPT_")} | {"SAPI": SKRIPT_SAPI}
    for name, skript in skripte.items():
        ohne_strings = re.sub(r"'[^'\n]*'", "''", skript)
        for auf, zu in ("()", "{}", "[]"):
            assert ohne_strings.count(auf) == ohne_strings.count(zu), (name, auf)
        assert "{name}" not in skript and "%s" not in skript, name
        assert "Invoke-Expression" not in skript and "iex " not in skript, name


async def test_sapi_daten_als_json(win):
    from jarvis.stimme.tts import SapiTTS

    tts = SapiTTS(stimme="Hedda", tempo=220)
    roh = json.loads(base64.b64decode(tts.eingabe("Hallo", "C:\\t\\a.wav")))
    assert roh == {"text": "Hallo", "ziel": "C:\\t\\a.wav", "stimme": "Hedda", "sprache": "de", "rate": 2}


def test_fehlertext_clixml():
    roh = ('#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">'
           '<S S="Error">Start-Process : Das System kann die Datei &quot;x&quot; nicht finden._x000D__x000A_</S>'
           '<S S="Error">In Zeile:1 Zeichen:1_x000D__x000A_</S></Objs>')
    assert windows.fehlertext(roh) == 'Start-Process : Das System kann die Datei "x" nicht finden.'
    assert windows.fehlertext("\n  Zugriff verweigert\nmehr") == "Zugriff verweigert"
