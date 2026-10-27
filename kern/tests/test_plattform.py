"""Plattform-Schicht: Erkennung, Werkzeug-Registrierung je Plattform, Systemprompt, PATH,
kritische Pfade (Autostart) je Plattform, Geheimnisse über keyring, Papierkorb."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

from jarvis import plattform
from jarvis.plattform import aktuelle_plattform, systemaktionen
from jarvis.werkzeuge import dateien, desktop, mac, prozess, shell
from tests.helfer import baue_jarvis

NUR_MAC = set(desktop.NUR_MAC)
NEUTRAL = {"app_oeffnen", "app_beenden", "laufende_apps", "lautstaerke_setzen", "mitteilung_anzeigen",
           "musik_steuern", "url_oeffnen", "zwischenablage_lesen", "zwischenablage_schreiben",
           "bildschirmfoto", "systeminfo"}


# ------------------------------------------------------------------------------------ Erkennung
@pytest.mark.parametrize(("sys_platform", "erwartet"), [("darwin", "mac"), ("win32", "windows"), ("linux", "linux"),
                                                       ("cygwin", "windows"), ("freebsd14", "linux")])
def test_erkennung_aus_sys_platform(monkeypatch, sys_platform, erwartet):
    monkeypatch.setattr(sys, "platform", sys_platform)
    assert aktuelle_plattform() == erwartet


@pytest.mark.parametrize(("wert", "erwartet"), [("mac", "mac"), ("macOS", "mac"), ("Windows", "windows"),
                                                ("win32", "windows"), ("linux", "linux")])
def test_ueberschreiben_per_umgebung(monkeypatch, wert, erwartet):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("JARVIS_PLATTFORM", wert)
    assert aktuelle_plattform() == erwartet
    assert prozess.ist_mac() == (erwartet == "mac")


def test_unbekannter_wert_wird_ignoriert(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("JARVIS_PLATTFORM", "amiga")
    assert aktuelle_plattform() == "windows"


@pytest.mark.parametrize(("p", "klasse"), [("mac", "MacAktionen"), ("windows", "WindowsAktionen"), ("linux", "LinuxAktionen")])
def test_systemaktionen_je_plattform(p, klasse):
    a = systemaktionen(p)
    assert type(a).__name__ == klasse and a.plattform == p
    assert isinstance(a, plattform.Systemaktionen)


# ------------------------------------------------------------------------------------ Werkzeuge
@pytest.mark.parametrize("p", ["mac", "windows", "linux"])
def test_registrierung_je_plattform(monkeypatch, p):
    monkeypatch.setenv("JARVIS_PLATTFORM", p)
    j, _ = baue_jarvis()
    namen = {w.name for w in j.register.alle()}
    assert NEUTRAL <= namen
    assert {"datei_suchen", "datei_loeschen", "shell_befehl", "websuche", "timer_stellen"} <= namen
    if p == "mac":
        assert NUR_MAC <= namen
        assert j.register.holen("app_oeffnen") is mac.app_oeffnen  # unverändertes Mac-Werkzeug
        assert j.register.holen("shell_befehl") is shell.shell_befehl
    else:
        assert not (NUR_MAC & namen)
        assert j.register.holen("app_oeffnen") is desktop.app_oeffnen
        assert ("PowerShell" if p == "windows" else "bash") in j.register.holen("shell_befehl").beschreibung


def test_gleiche_risikostufen_wie_mac():
    mac_werkzeuge = {w.name: w for w in mac.werkzeuge()}
    for w in desktop.werkzeuge():
        assert w.name in mac_werkzeuge, w.name
        assert w.risiko == mac_werkzeuge[w.name].risiko, w.name
    assert {w.name for w in desktop.werkzeuge()} == NEUTRAL
    assert set(mac_werkzeuge) - NEUTRAL == NUR_MAC


@pytest.mark.parametrize("p", ["windows", "linux"])
def test_shell_bleibt_kritisch(monkeypatch, p):
    monkeypatch.setenv("JARVIS_PLATTFORM", p)
    (w,) = shell.werkzeuge()
    assert w.name == "shell_befehl" and w.risiko == "kritisch" and w.risiko_fuer({"befehl": "x"}) == "kritisch"
    assert w.freigabe_grund({"befehl": "dir"}) == "Shell-Befehl ausführen: dir"


async def test_shell_nutzt_plattform_shell(monkeypatch):
    aufrufe = []

    async def aufzeichnen(*befehl, **kw):
        aufrufe.append(befehl)
        return prozess.ProzessErgebnis(0, "ok", "")

    monkeypatch.setattr(prozess, "ausfuehren", aufzeichnen)
    monkeypatch.setenv("JARVIS_PLATTFORM", "windows")
    await shell.shell_befehl.ausfuehren(befehl="Get-Date")
    assert aufrufe[-1][0].lower().endswith("powershell.exe") and "-EncodedCommand" in aufrufe[-1]
    monkeypatch.setenv("JARVIS_PLATTFORM", "linux")
    await shell.shell_befehl.ausfuehren(befehl="date")
    assert aufrufe[-1][1:] == ("-c", "date")


async def test_bildschirmfoto_an_geschuetzten_ort_ist_kritisch(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_PLATTFORM", "linux")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert desktop.bildschirmfoto.risiko == "aendern"
    assert desktop.bildschirmfoto.risiko_fuer({}) == "aendern"
    assert desktop.bildschirmfoto.risiko_fuer({"pfad": "~/Bilder/x.png"}) == "aendern"
    assert desktop.bildschirmfoto.risiko_fuer({"pfad": "~/.config/autostart/x.png"}) == "kritisch"


# ------------------------------------------------------------------------------------ Systemprompt
@pytest.mark.parametrize("p", ["mac", "windows", "linux"])
async def test_systemprompt_hinweis_auf_katalog(monkeypatch, p):
    monkeypatch.setenv("JARVIS_PLATTFORM", p)
    j, _ = baue_jarvis()
    text = await j.agent.systemprompt("Hallo", sprechen=False)
    if p == "mac":
        assert "google-kalender" not in text and "auf seinem Mac" in text
    else:
        assert "nur auf dem Mac" in text and "google-kalender" in text and "todoist" in text
        assert "auf seinem Computer" in text and "auf seinem Mac" not in text


# ------------------------------------------------------------------------------------ PATH / Befehle
def test_path_erweiterung_je_plattform(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_PLATTFORM", "mac")
    teile = prozess.erweiterter_path("/a").split(os.pathsep)
    assert teile[:3] == ["/a", "/opt/homebrew/bin", "/opt/homebrew/sbin"]
    monkeypatch.setenv("JARVIS_PLATTFORM", "linux")
    teile = prozess.erweiterter_path("/a").split(os.pathsep)
    assert "/snap/bin" in teile and "/opt/homebrew/bin" not in teile and os.path.expanduser("~/.local/bin") in teile
    monkeypatch.setenv("JARVIS_PLATTFORM", "windows")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "Programme"))
    teile = prozess.erweiterter_path("").split(os.pathsep)
    assert str(tmp_path / "Roaming" / "npm") in teile and str(tmp_path / "Programme" / "nodejs") in teile


def test_npx_unter_windows_als_cmd(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_PLATTFORM", "windows")
    npx = tmp_path / "npx.cmd"
    npx.write_text("@echo off\n")
    npx.chmod(0o755)
    assert prozess.programm_aufloesen("npx", str(tmp_path)) == str(npx)
    assert prozess.programm_aufloesen("gibtsnicht", str(tmp_path)) is None
    monkeypatch.setenv("JARVIS_PLATTFORM", "linux")
    assert prozess.programm_aufloesen("npx", str(tmp_path)) is None  # unter Linux keine .cmd-Dateien


def test_befehl_zerlegen_behaelt_windows_pfade(monkeypatch):
    monkeypatch.setenv("JARVIS_PLATTFORM", "windows")
    assert prozess.befehl_zerlegen('npx -y @mcp/server-filesystem "C:\\Users\\Max Muster\\Dokumente" C:\\x') == [
        "npx", "-y", "@mcp/server-filesystem", "C:\\Users\\Max Muster\\Dokumente", "C:\\x"]
    monkeypatch.setenv("JARVIS_PLATTFORM", "linux")
    assert prozess.befehl_zerlegen("uvx 'mcp server' --a=b") == ["uvx", "mcp server", "--a=b"]


# ------------------------------------------------------------------------------------ Kritische Pfade
@pytest.fixture
def fake_home(monkeypatch, tmp_path):
    home = tmp_path / "nutzer"
    (home / "Documents").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("JARVIS_HOME", str(home / ".jarvis"))
    return home


def test_kritische_pfade_linux(monkeypatch, fake_home):
    monkeypatch.setenv("JARVIS_PLATTFORM", "linux")
    s = dateien.datei_schreiben
    assert s.risiko_fuer({"pfad": "~/Documents/notiz.txt", "inhalt": "x"}) == "aendern"
    erwartet = {
        "~/.config/autostart/boese.desktop": "ausführbare",
        "~/.config/autostart/notiz.txt": "Autostart-Ordner ~/.config/autostart",
        "~/.config/systemd/user/jarvis.service": "ausführbare",
        "~/.config/systemd/user/x.conf": "Autostart-Ordner ~/.config/systemd/user",
        "~/.bashrc": "Shell-",
        "~/.profile": "Shell-",
        "~/.zshrc": "Shell-",
        "~/bin/git": "~/bin",
        "/var/spool/cron/crontabs/nutzer": "crontab",
        "/etc/cron.d/x": "crontab",
        "~/Desktop/start.desktop": "ausführbare",
        "~/.jarvis/integrationen.json": "Konfiguration/Daten des Assistenten",
        "~/Documents/x.AppImage": "ausführbare",
    }
    for pfad, grund in erwartet.items():
        assert s.risiko_fuer({"pfad": pfad, "inhalt": "x"}) == "kritisch", pfad
        assert grund in s.freigabe_grund({"pfad": pfad}), (pfad, s.freigabe_grund({"pfad": pfad}))
    lesen = dateien.datei_lesen
    for pfad in ("~/.local/share/keyrings/login.keyring", "~/.mozilla/firefox/abc/logins.json", "~/.ssh/id_rsa"):
        assert lesen.risiko_fuer({"pfad": pfad}) == "kritisch", pfad
    assert lesen.risiko_fuer({"pfad": "~/Documents/a.txt"}) == "lesen"


def test_kritische_pfade_windows(monkeypatch, fake_home):
    monkeypatch.setenv("JARVIS_PLATTFORM", "windows")
    s = dateien.datei_schreiben
    assert s.risiko_fuer({"pfad": "~/Documents/notiz.txt", "inhalt": "x"}) == "aendern"
    startup = "~/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"
    erwartet = {
        f"{startup}/notiz.txt": "Autostart-Ordner",
        f"{startup.lower()}/x.txt": "Autostart-Ordner",
        "~/AppData/Local/Programs/x/config.json": "AppData",
        "~/Documents/boese.ps1": "(.ps1)",
        "~/Documents/run.BAT": "(.BAT)",
        "~/Documents/autorun.reg": "(.reg)",
        "~/Documents/x.lnk": "(.lnk)",
        "~/Documents/setup.exe": "(.exe)",
        "~/Documents/a.vbs": "(.vbs)",
        "~/Documents/WindowsPowerShell/Microsoft.PowerShell_profile.ps1": "(.ps1)",
        "~/.jarvis/einstellungen.json": "Konfiguration/Daten des Assistenten",
        # Windows entfernt Punkte/Leerzeichen am Namensende → würde boese.ps1 anlegen
        "~/Documents/boese.ps1.": "(.ps1",
        "~/Documents/boese.bat . .": "(.bat",
        # NTFS-Datenströme („datei.ps1::$DATA“ legt datei.ps1 an)
        "~/Documents/boese.ps1::$DATA": "Datenstrom",
        "~/Documents/notiz.txt:versteckt": "Datenstrom",
    }
    for pfad, grund in erwartet.items():
        assert s.risiko_fuer({"pfad": pfad, "inhalt": "x"}) == "kritisch", pfad
        assert grund in s.freigabe_grund({"pfad": pfad}), (pfad, s.freigabe_grund({"pfad": pfad}))
    assert dateien.datei_verschieben.risiko_fuer({"quelle": "~/Documents/a.txt", "ziel": f"{startup}/a.txt"}) == "kritisch"
    for pfad in ("~/AppData/Roaming/Microsoft/Credentials/ABC", "~/AppData/Local/Google/Chrome/User Data/Default/Login Data"):
        assert dateien.datei_lesen.risiko_fuer({"pfad": pfad}) == "kritisch", pfad
    # Shell (z. B. „reg add …\\Run“ oder „schtasks /create“) ist ohnehin immer kritisch
    assert shell.shell_befehl.risiko_fuer({"befehl": "reg add HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run"}) == "kritisch"


def test_mac_regeln_unveraendert(monkeypatch, fake_home):
    monkeypatch.setenv("JARVIS_PLATTFORM", "mac")
    s = dateien.datei_schreiben
    assert "~/Library" in s.freigabe_grund({"pfad": "~/Library/LaunchAgents/x.txt"})
    assert s.risiko_fuer({"pfad": "~/Documents/setup.exe", "inhalt": "x"}) == "aendern"  # .exe ist auf dem Mac egal
    assert s.risiko_fuer({"pfad": "~/AppData/x.txt", "inhalt": "x"}) == "aendern"


# ------------------------------------------------------------------------------------ Papierkorb
async def test_papierkorb_linux_freedesktop(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_PLATTFORM", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    datei = tmp_path / "weg.txt"
    datei.write_text("x")
    await dateien.datei_loeschen.ausfuehren(pfad=str(datei))
    assert not datei.exists()
    assert (tmp_path / "xdg/Trash/files/weg.txt").exists()
    assert (tmp_path / "xdg/Trash/info/weg.txt.trashinfo").exists()  # wiederherstellbar


async def test_papierkorb_windows_nutzt_send2trash(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_PLATTFORM", "windows")
    gesendet = []
    monkeypatch.setitem(sys.modules, "send2trash", types.SimpleNamespace(send2trash=gesendet.append))
    datei = tmp_path / "weg.txt"
    datei.write_text("x")
    text = await dateien.datei_loeschen.ausfuehren(pfad=str(datei))
    assert gesendet == [str(datei)] and "Papierkorb" in text


async def test_papierkorb_windows_ohne_send2trash_powershell(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_PLATTFORM", "windows")
    monkeypatch.setitem(sys.modules, "send2trash", None)  # Import schlägt fehl
    aufrufe = []

    async def aufzeichnen(*befehl, umgebung=None, **kw):
        aufrufe.append(umgebung)
        return prozess.ProzessErgebnis(0, "", "")

    monkeypatch.setattr(prozess, "ausfuehren", aufzeichnen)
    datei = tmp_path / "weg.txt"
    datei.write_text("x")
    await dateien.datei_loeschen.ausfuehren(pfad=str(datei))
    assert aufrufe == [{"JARVIS_ARG_PFAD": str(datei.resolve())}]


# ------------------------------------------------------------------------------------ Geheimnisse
class FakeKeyring(types.SimpleNamespace):
    def __init__(self, modul="keyring.backends.Windows"):
        super().__init__()
        self.daten: dict[tuple[str, str], str] = {}
        backend_klasse = type("WinVaultKeyring", (), {"priority": 5, "__module__": modul})
        self._backend = backend_klasse()

    def get_keyring(self):
        return self._backend

    def set_password(self, dienst, name, wert):
        self.daten[(dienst, name)] = wert

    def get_password(self, dienst, name):
        return self.daten.get((dienst, name))

    def delete_password(self, dienst, name):
        if (dienst, name) not in self.daten:
            raise RuntimeError("nicht vorhanden")
        del self.daten[(dienst, name)]


@pytest.mark.parametrize("p", ["windows", "linux"])
def test_geheimnisse_ueber_keyring(monkeypatch, isoliert, p):
    from jarvis import geheimnisse

    monkeypatch.setenv("JARVIS_PLATTFORM", p)
    monkeypatch.setenv("JARVIS_GEHEIMNIS_BACKEND", "auto")
    kr = FakeKeyring()
    monkeypatch.setattr(geheimnisse, "_keyring_modul", lambda: kr)
    g = geheimnisse.Geheimnisspeicher()
    assert g.backend == "keyring"
    wert = "sk-ant-'\"$(x)` ü"
    g.setzen("ANTHROPIC_API_KEY", wert)
    assert kr.daten[("jarvis", "ANTHROPIC_API_KEY")] == wert
    assert g.holen("ANTHROPIC_API_KEY") == wert and g.namen() == ["ANTHROPIC_API_KEY"]
    assert not (isoliert / "geheimnisse.enc").exists()  # nichts in der Datei
    assert g.loeschen("ANTHROPIC_API_KEY") and g.holen("ANTHROPIC_API_KEY") is None
    g.loeschen("GIBT_ES_NICHT")  # kein Fehler


def test_keyring_ohne_backend_faellt_auf_datei_zurueck(monkeypatch, isoliert):
    from jarvis import geheimnisse

    monkeypatch.setenv("JARVIS_PLATTFORM", "linux")
    monkeypatch.setenv("JARVIS_GEHEIMNIS_BACKEND", "auto")
    monkeypatch.setattr(geheimnisse, "_keyring_modul", lambda: FakeKeyring("keyring.backends.fail"))
    assert geheimnisse.Geheimnisspeicher().backend == "datei"
    monkeypatch.setattr(geheimnisse, "_keyring_modul", lambda: None)
    assert geheimnisse.Geheimnisspeicher().backend == "datei"

    class Gesperrt(FakeKeyring):
        def get_password(self, dienst, name):
            raise RuntimeError("Secret Service gesperrt")

    monkeypatch.setattr(geheimnisse, "_keyring_modul", lambda: Gesperrt("keyring.backends.SecretService"))
    g = geheimnisse.Geheimnisspeicher()
    assert g.backend == "datei"
    g.setzen("X", "y")
    assert g.holen("X") == "y"


def test_keyring_findet_alte_geheimnisse_aus_der_datei(monkeypatch, isoliert):
    """Linux/Windows-Nutzer mit Geheimnissen aus der Zeit vor keyring (Backend „datei“) verlieren nichts."""
    from jarvis import geheimnisse

    alt = geheimnisse.Geheimnisspeicher(backend="datei")
    alt.setzen("OPENAI_API_KEY", "sk-alt")
    kr = FakeKeyring()
    monkeypatch.setattr(geheimnisse, "_keyring_modul", lambda: kr)
    g = geheimnisse.Geheimnisspeicher(backend="keyring")
    assert g.holen("OPENAI_API_KEY") == "sk-alt" and g.hat("OPENAI_API_KEY")
    g.setzen("OPENAI_API_KEY", "sk-neu")  # neuer Wert landet im keyring und hat Vorrang
    assert g.holen("OPENAI_API_KEY") == "sk-neu"
    assert g.loeschen("OPENAI_API_KEY")
    assert g.holen("OPENAI_API_KEY") is None  # auch die alte Kopie in der Datei ist weg
    assert alt.holen("OPENAI_API_KEY") is None


def test_keyring_fehler_ohne_geheimnis_in_meldung(monkeypatch, isoliert):
    from jarvis import geheimnisse

    class Kaputt(FakeKeyring):
        def set_password(self, dienst, name, wert):
            raise RuntimeError(f"Wert {wert} ist zu lang")

    monkeypatch.setattr(geheimnisse, "_keyring_modul", lambda: Kaputt())
    g = geheimnisse.Geheimnisspeicher(backend="keyring")
    with pytest.raises(geheimnisse.GeheimnisFehler) as info:
        g.setzen("TOKEN", "streng-geheim")
    assert "streng-geheim" not in str(info.value) and "zu lang" in str(info.value)


def test_mac_bleibt_beim_schluesselbund(monkeypatch, isoliert):
    from jarvis import geheimnisse

    monkeypatch.setenv("JARVIS_PLATTFORM", "mac")
    monkeypatch.setenv("JARVIS_GEHEIMNIS_BACKEND", "auto")
    monkeypatch.setattr(geheimnisse, "_schluesselbund_verfuegbar", lambda: True)
    monkeypatch.setattr(geheimnisse, "_keyring_modul", lambda: FakeKeyring())
    assert geheimnisse.Geheimnisspeicher().backend == "schluesselbund"


def test_datei_backend_unter_windows_ohne_chmod(monkeypatch, isoliert):
    from jarvis import geheimnisse

    monkeypatch.setattr(geheimnisse, "_unix_rechte", lambda: False)
    aufrufe = []
    monkeypatch.setattr(geheimnisse.os, "chmod", lambda *a: aufrufe.append(a))
    g = geheimnisse.Geheimnisspeicher(backend="datei")
    g.setzen("A", "b")
    assert g.holen("A") == "b" and aufrufe == []
    assert Path(isoliert / "geheimnisse.schluessel").read_bytes().strip()


# ------------------------------------------------------------------------------------ Anwendung/CLI
async def test_melden_und_vorlesen_ohne_mac(monkeypatch):
    monkeypatch.setenv("JARVIS_PLATTFORM", "linux")
    j, _ = baue_jarvis()
    await j.melden("Der Tee ist fertig.")
    # Mitteilung + Sprachausgabe laufen über die (in Tests stummgeschalteten) Plattformwege
    assert j.stille_aufrufe == ["Sir, der Tee ist fertig.", "Sir, der Tee ist fertig."]
    await j.stoppen()


async def test_vorlesen_ohne_stimmdienst_nutzt_tts(monkeypatch):
    from jarvis.anwendung import Jarvis
    from jarvis.stimme import tts as tts_modul

    gesprochen = []

    async def einmal(text, einstellungen):
        gesprochen.append(text)

    monkeypatch.setattr(tts_modul, "einmal_vorlesen", einmal)
    monkeypatch.setenv("JARVIS_PLATTFORM", "windows")
    j, _ = baue_jarvis()
    ereignisse = []

    async def hoerer(e):
        ereignisse.append(e)

    j.hoerer_hinzufuegen(hoerer)
    await j._original_vorlesen("Hallo Welt")
    assert gesprochen == ["Hallo Welt"]
    assert [e["zustand"] for e in ereignisse if e["typ"] == "zustand"][0] == "spricht"
    assert isinstance(j, Jarvis)
    await j.stoppen()


def test_windows_vorbereiten(monkeypatch):
    import asyncio

    from jarvis import cli

    gesetzt = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(asyncio, "WindowsProactorEventLoopPolicy", lambda: "proactor", raising=False)
    monkeypatch.setattr(asyncio, "set_event_loop_policy", gesetzt.append)
    cli.windows_vorbereiten()
    if sys.version_info < (3, 14):
        assert gesetzt == ["proactor"]
    monkeypatch.setattr(sys, "platform", "linux")
    gesetzt.clear()
    cli.windows_vorbereiten()
    assert gesetzt == []
