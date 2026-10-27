"""Linux-Implementierung: gemockte Befehle (inkl. Injektionsversuche) und – wo die Programme im
Container vorhanden sind – echte Ausführung (xclip unter Xvfb, pkill, import, espeak-ng, Dateisuche)."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from jarvis.plattform import gemeinsam, linux
from jarvis.plattform.linux import LinuxAktionen, desktop_eintrag_finden
from jarvis.werkzeuge import WerkzeugFehler, desktop, prozess
from jarvis.werkzeuge.prozess import ProzessErgebnis

BOESE = ["x'; rm -rf ~; '", 'x"; reboot; "', "$(reboot)", "`reboot`", "a; rm -rf ~", "-rf --help", "a\nb && c | d > e"]


class Aufzeichner:
    def __init__(self):
        self.befehle: list[tuple] = []
        self.eingaben: list = []
        self.optionen: list[dict] = []
        self.antworten: dict[str, ProzessErgebnis] = {}

    async def __call__(self, *befehl, eingabe=None, timeout=30, **kw):
        self.befehle.append(befehl)
        self.eingaben.append(eingabe)
        self.optionen.append(kw)
        for muster, erg in self.antworten.items():
            if any(muster == t for t in befehl):
                return erg
        return ProzessErgebnis(0, "", "")


@pytest.fixture
def lx(monkeypatch, tmp_path):
    """Linux mit gemocktem Prozessaufruf; vorhandene Programme über `vorhanden` steuerbar."""
    monkeypatch.setenv("JARVIS_PLATTFORM", "linux")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "sys"))
    a = Aufzeichner()
    a.vorhanden = set()
    monkeypatch.setattr(prozess, "ausfuehren", a)
    monkeypatch.setattr(linux, "programm_vorhanden", lambda n: n in a.vorhanden)
    gestartet = []
    monkeypatch.setattr(prozess, "losgeloest_starten", lambda *b: gestartet.append(b))
    a.gestartet = gestartet
    return a


def desktop_datei(ordner: Path, kennung: str, inhalt: str) -> Path:
    ordner.mkdir(parents=True, exist_ok=True)
    pfad = ordner / f"{kennung}.desktop"
    pfad.write_text("[Desktop Entry]\nType=Application\n" + inhalt)
    return pfad


def test_desktop_eintraege_finden(lx, tmp_path):
    desktop_datei(tmp_path / "sys/applications", "org.mozilla.firefox", "Name=Firefox\nName[de]=Firefox-Webbrowser\nExec=firefox %u\n")
    desktop_datei(tmp_path / "sys/applications", "org.gnome.Calculator", "Name=Calculator\nName[de]=Rechner\nExec=gnome-calculator\n")
    desktop_datei(tmp_path / "sys/applications", "versteckt", "Name=Firefox Hilfe\nNoDisplay=true\nExec=x\n")
    desktop_datei(tmp_path / "share/applications", "spotify", "Name=Spotify\nExec=/usr/bin/spotify --uri=%U\n")
    assert desktop_eintrag_finden("firefox").kennung == "org.mozilla.firefox"
    assert desktop_eintrag_finden("Rechner").kennung == "org.gnome.Calculator"
    assert desktop_eintrag_finden("calc").kennung == "org.gnome.Calculator"
    sp = desktop_eintrag_finden("SPOTIFY")
    assert sp.programm == "spotify" and sp.befehl() == ["/usr/bin/spotify", "--uri="]
    assert desktop_eintrag_finden("gibt es nicht") is None


async def test_app_oeffnen_gtk_launch_und_fallbacks(lx, tmp_path):
    desktop_datei(tmp_path / "sys/applications", "org.mozilla.firefox", "Name=Firefox\nExec=firefox %u\n")
    lx.vorhanden = {"gtk-launch"}
    assert await LinuxAktionen().app_oeffnen("firefox") == "Firefox wurde geöffnet."
    assert lx.befehle[-1] == ("gtk-launch", "org.mozilla.firefox") and lx.optionen[-1]["ohne_ausgabe"]
    lx.vorhanden = set()  # weder gtk-launch noch gio → Exec direkt (ohne Shell)
    await LinuxAktionen().app_oeffnen("Firefox")
    assert lx.gestartet[-1] == ("firefox",)
    lx.vorhanden = {"htop"}
    await LinuxAktionen().app_oeffnen("htop")
    assert lx.gestartet[-1] == ("htop",)
    with pytest.raises(WerkzeugFehler, match="Keine App"):
        await LinuxAktionen().app_oeffnen("gibtsnicht")
    for unzulaessig in ("/tmp/boese.sh", "../x", "-e", "https://x"):
        with pytest.raises(WerkzeugFehler, match="nur den Namen"):
            await LinuxAktionen().app_oeffnen(unzulaessig)


async def test_app_beenden_mit_pkill(lx, tmp_path):
    desktop_datei(tmp_path / "sys/applications", "org.gnome.Calculator", "Name=Rechner\nExec=gnome-calculator\n")
    lx.vorhanden = {"pkill"}

    assert await LinuxAktionen().app_beenden("Rechner") == "Rechner wurde beendet."
    assert lx.befehle[0] == ("pkill", "-i", "-x", "--", "gnome-calculato")
    lx.antworten.clear()
    lx.antworten["pkill"] = ProzessErgebnis(1, "", "")
    with pytest.raises(WerkzeugFehler, match="läuft nicht"):
        await LinuxAktionen().app_beenden("Rechner")
    lx.vorhanden = set()
    with pytest.raises(WerkzeugFehler, match="sudo apt install pkill|Installieren mit"):
        await LinuxAktionen().app_beenden("Rechner")


async def test_lautstaerke_wpctl_pactl_amixer(lx):
    lx.vorhanden = {"wpctl", "pactl", "amixer"}
    lx.antworten["get-volume"] = ProzessErgebnis(0, "Volume: 0.40", "")
    assert await LinuxAktionen().lautstaerke_setzen(140, None, None) == "Lautstärke jetzt 40 %."
    assert ("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "1.00") in lx.befehle
    lx.befehle.clear()
    await LinuxAktionen().lautstaerke_setzen(None, -15, True)
    assert ("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "0.25") in lx.befehle
    assert ("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1") in lx.befehle
    lx.vorhanden = {"pactl"}
    lx.antworten["get-sink-volume"] = ProzessErgebnis(0, "Volume: front-left: 32768 /  50% / -18 dB", "")
    lx.befehle.clear()
    await LinuxAktionen().lautstaerke_setzen(None, 10, False)
    assert ("pactl", "set-sink-volume", "@DEFAULT_SINK@", "60%") in lx.befehle
    assert ("pactl", "set-sink-mute", "@DEFAULT_SINK@", "0") in lx.befehle
    lx.vorhanden = {"amixer"}
    lx.antworten["get"] = ProzessErgebnis(0, "Mono: Playback 30 [47%] [on]", "")
    lx.befehle.clear()
    assert "47 %" in await LinuxAktionen().lautstaerke_setzen(47, None, None)
    assert ("amixer", "-q", "sset", "Master", "47%") in lx.befehle
    lx.vorhanden = set()
    with pytest.raises(WerkzeugFehler, match="Installieren mit: sudo"):
        await LinuxAktionen().lautstaerke_setzen(10, None, None)


@pytest.mark.parametrize("boese", BOESE)
async def test_injektion_bleibt_argument(lx, boese):
    """Werte gehen als einzelnes Argument (hinter --) bzw. über stdin, nie durch eine Shell."""
    lx.vorhanden = {"notify-send", "xclip", "xdg-open", "playerctl"}
    a = LinuxAktionen()
    await a.mitteilung_anzeigen(boese, boese)
    from jarvis.konfig import aktueller_name

    assert lx.befehle[-1] == ("notify-send", f"--app-name={aktueller_name()}", "--", boese, boese)
    await a.mitteilung_anzeigen("Text", "")
    assert lx.befehle[-1][-2] == aktueller_name() and "Jarvis" not in " ".join(lx.befehle[-1])
    await a.zwischenablage_schreiben(boese)
    assert lx.befehle[-1] == ("xclip", "-selection", "clipboard", "-in") and lx.eingaben[-1] == boese
    assert lx.optionen[-1]["ohne_ausgabe"]  # xclip bleibt im Hintergrund → Pipes nicht offen halten
    await a.musik_steuern("suchen", "spotify", boese)
    befehl = lx.befehle[-1]
    assert befehl[0] == "xdg-open" and len(befehl) == 2 and befehl[1].startswith("spotify:search:")
    assert all(z not in befehl[1] for z in " ;$`\n'\"")


async def test_musik_mit_playerctl(lx):
    lx.vorhanden = {"playerctl"}
    a = LinuxAktionen()
    await a.musik_steuern("playpause", "spotify", None)
    assert lx.befehle[-1] == ("playerctl", "--player=spotify", "play-pause")
    await a.musik_steuern("zurueck", "auto", None)
    assert lx.befehle[-1] == ("playerctl", "previous")
    lx.antworten["metadata"] = ProzessErgebnis(0, "One More Time – Daft Punk (Playing)\n", "")
    assert await a.musik_steuern("aktuell", "auto", None) == "One More Time – Daft Punk (Playing)"
    lx.vorhanden = set()
    with pytest.raises(WerkzeugFehler, match="playerctl"):
        await a.musik_steuern("play", "auto", None)


async def test_zwischenablage_wayland_und_x11(lx, monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    lx.vorhanden = {"wl-copy", "wl-paste", "xclip"}
    lx.antworten["wl-paste"] = ProzessErgebnis(0, "Grüße", "")
    assert await LinuxAktionen().zwischenablage_lesen() == "Grüße"
    assert lx.befehle[-1] == ("wl-paste", "--no-newline")
    await LinuxAktionen().zwischenablage_schreiben("x")
    assert lx.befehle[-1] == ("wl-copy",)
    monkeypatch.delenv("WAYLAND_DISPLAY")
    lx.vorhanden = {"xsel"}
    await LinuxAktionen().zwischenablage_lesen()
    assert lx.befehle[-1] == ("xsel", "--clipboard", "--output")
    lx.vorhanden = set()
    with pytest.raises(WerkzeugFehler, match="xclip"):
        await LinuxAktionen().zwischenablage_lesen()


async def test_bildschirmfoto_reihenfolge_je_desktop(lx, monkeypatch, tmp_path):
    ziel = tmp_path / "foto.png"
    lx.vorhanden = {"gnome-screenshot", "spectacle", "grim", "scrot", "import"}
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "ubuntu:GNOME")
    befehle = LinuxAktionen()._bildschirmfoto_befehle(str(ziel))
    assert befehle[0] == ["gnome-screenshot", "-f", str(ziel)]
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    assert LinuxAktionen()._bildschirmfoto_befehle(str(ziel))[0][0] == "spectacle"
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "sway")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    assert LinuxAktionen()._bildschirmfoto_befehle(str(ziel))[0] == ["grim", str(ziel)]
    monkeypatch.delenv("WAYLAND_DISPLAY")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "XFCE")
    assert LinuxAktionen()._bildschirmfoto_befehle(str(ziel))[0][0] == "scrot"
    with pytest.raises(WerkzeugFehler, match="fehlgeschlagen"):  # Programm „läuft“, legt aber keine Datei an
        await LinuxAktionen().bildschirmfoto(str(ziel))
    lx.vorhanden = set()
    with pytest.raises(WerkzeugFehler, match="Installieren mit"):
        await LinuxAktionen().bildschirmfoto(str(ziel))


def test_installationsbefehl_je_distribution(monkeypatch, tmp_path):
    datei = tmp_path / "os-release"
    monkeypatch.setattr(gemeinsam, "OS_RELEASE", datei)
    for inhalt, erwartet in (
        ('ID=ubuntu\nID_LIKE=debian', "sudo apt install libnotify-bin"),
        ('ID=fedora', "sudo dnf install libnotify"),
        ('ID="endeavouros"\nID_LIKE="arch"', "sudo pacman -S libnotify"),
        ('ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"', "sudo zypper install libnotify-tools"),
    ):
        datei.write_text(inhalt)
        assert gemeinsam.installationsbefehl("notify-send") == erwartet
    datei.write_text("ID=arch")
    assert gemeinsam.installationsbefehl("pactl", "wl-copy") == "sudo pacman -S libpulse wl-clipboard"


async def test_dateisuche_locate_gefiltert(lx, tmp_path):
    home = tmp_path / "home"
    lx.vorhanden = {"plocate"}
    lx.antworten["plocate"] = ProzessErgebnis(0, "\n".join([
        f"{home}/Dokumente/Steuer 2025.pdf", f"{home}/.cache/steuer.tmp", "/etc/steuer.conf",
        f"{home}/Steuerordner/notiz.txt", f"{home}/Archiv/steuer-alt.pdf",
    ]), "")
    treffer = await LinuxAktionen().dateien_suchen("steuer", str(home), True, 10)
    assert treffer == [f"{home}/Dokumente/Steuer 2025.pdf", f"{home}/Archiv/steuer-alt.pdf"]
    assert lx.befehle[-1] == ("plocate", "-i", "-l", "200", "--", "steuer")


def test_shell_ist_bash():
    argv = LinuxAktionen().shell_befehl("echo $HOME")
    assert argv[1:] == ["-c", "echo $HOME"] and argv[0].endswith(("bash", "sh"))


# ---------------------------------------------------------------------------------------------
# Echte Ausführung (nur wenn die Programme im Container/auf dem Rechner vorhanden sind)
# ---------------------------------------------------------------------------------------------
nur_linux = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="nur unter Linux")


@pytest.fixture
def xvfb(monkeypatch):
    if not (shutil.which("Xvfb") and sys.platform.startswith("linux")):
        pytest.skip("Xvfb nicht installiert")
    anzeige = f":{90 + os.getpid() % 9}"
    proc = subprocess.Popen(["Xvfb", anzeige, "-screen", "0", "320x200x24", "-nolisten", "tcp"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sock = Path(f"/tmp/.X11-unix/X{anzeige[1:]}")
    for _ in range(50):
        if sock.exists():
            break
        time.sleep(0.1)
    monkeypatch.setenv("DISPLAY", anzeige)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("JARVIS_PLATTFORM", "linux")
    yield anzeige
    proc.terminate()
    proc.wait(5)


@nur_linux
async def test_echt_zwischenablage_mit_xclip(xvfb):
    if not (shutil.which("xclip") or shutil.which("xsel")):
        pytest.skip("xclip/xsel fehlen")
    text = "Grüße „Jarvis“ $(rm -rf ~) `x` ; ' \" ✓"
    assert await desktop.zwischenablage_schreiben.ausfuehren(text=text) == "Text in die Zwischenablage kopiert."
    assert await asyncio.wait_for(desktop.zwischenablage_lesen.ausfuehren(), 10) == text


@nur_linux
async def test_echt_bildschirmfoto_unter_xvfb(xvfb, tmp_path):
    if not any(shutil.which(p) for p in ("scrot", "import", "maim")):
        pytest.skip("kein Bildschirmfoto-Programm")
    ziel = tmp_path / "foto.png"
    text = await desktop.bildschirmfoto.ausfuehren(pfad=str(ziel))
    assert str(ziel) in text and ziel.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


@nur_linux
async def test_echt_app_beenden_mit_pkill(monkeypatch, tmp_path):
    if not shutil.which("pkill") or not shutil.which("sleep"):
        pytest.skip("pkill fehlt")
    monkeypatch.setenv("JARVIS_PLATTFORM", "linux")
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "leer"))
    programm = tmp_path / "jarvistestapp"
    shutil.copy(shutil.which("sleep"), programm)
    proc = subprocess.Popen([str(programm), "30"])
    try:
        await asyncio.sleep(0.2)
        assert await desktop.app_beenden.ausfuehren(name="JarvisTestApp") == "JarvisTestApp wurde beendet."
        assert proc.wait(5) != 0
        with pytest.raises(WerkzeugFehler, match="läuft nicht"):
            await LinuxAktionen().app_beenden("jarvistestapp")
    finally:
        proc.kill()


@nur_linux
async def test_echt_systeminfo_und_dateisuche(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_PLATTFORM", "linux")
    text = await desktop.systeminfo.ausfuehren()
    assert "System:" in text and "Arbeitsspeicher" in text
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "Urlaubsplanung.txt").write_text("x")
    (tmp_path / ".versteckt").mkdir()
    (tmp_path / ".versteckt" / "urlaub.txt").write_text("x")
    from jarvis.werkzeuge import dateien

    text = await dateien.datei_suchen.ausfuehren(anfrage="urlaub", ordner=str(tmp_path))
    assert "Urlaubsplanung.txt" in text and ".versteckt" not in text


@nur_linux
async def test_echt_mitteilung_ohne_dbus_gibt_fehler(monkeypatch):
    if not shutil.which("notify-send"):
        pytest.skip("notify-send fehlt")
    monkeypatch.setenv("JARVIS_PLATTFORM", "linux")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/nicht/vorhanden")
    with pytest.raises(WerkzeugFehler, match="notify-send fehlgeschlagen"):
        await desktop.mitteilung_anzeigen.ausfuehren(text="Test")


@pytest.mark.parametrize("name", ["reboot", "poweroff", "Shutdown", "systemctl", "loginctl", "gnome-session-quit",
                                  "sudo", "pkexec", "rm", "mkfs.ext4", "killall", "xfce4-session-logout"])
async def test_systemprogramme_nicht_als_app(lx, name, tmp_path):
    """„App öffnen“ (ohne Freigabe) darf keine Programme starten, die schon ohne Argumente neu starten,
    abmelden oder Rechte erhöhen – auch nicht über den Rückfall auf ein Programm im PATH."""
    lx.vorhanden = {name.lower(), "gtk-launch", "pkill"}
    for aktion in (LinuxAktionen().app_oeffnen, LinuxAktionen().app_beenden):
        with pytest.raises(WerkzeugFehler, match="Systemprogramm"):
            await aktion(name)
    assert lx.gestartet == [] and lx.befehle == []
