"""Linux-Implementierung der Systemaktionen (GNOME/KDE/…, X11 und Wayland).

Genutzt wird, was vorhanden ist: ``gtk-launch``/``gio``/Desktop-Dateien zum Starten, ``pkill``,
``wmctrl``/``ps``, ``wpctl``/``pactl``/``amixer``, ``notify-send``, ``playerctl`` (inkl. Spotify),
``wl-copy``/``wl-paste`` bzw. ``xclip``/``xsel``, ``gnome-screenshot``/``spectacle``/``grim``/
``scrot``/``import``, ``xdg-open``, ``locate``/``plocate``. Fehlt ein Hilfsprogramm, gibt es eine
deutsche Meldung mit dem passenden Installationsbefehl (apt/dnf/pacman/zypper).

Alle Aufrufe sind Argumentlisten ohne Shell; Werte stehen hinter ``--``, wo das Programm Optionen
auswertet.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
from pathlib import Path
from urllib.parse import quote

from . import Systemaktionen, desktop_umgebung, ist_wayland
from .gemeinsam import fehlt_meldung, installationsbefehl, python_dateisuche


def _fehler(text: str) -> Exception:
    from ..werkzeuge import WerkzeugFehler

    return WerkzeugFehler(text)


def _prozess():
    from ..werkzeuge import prozess

    return prozess


def programm_vorhanden(name: str) -> bool:
    """In Tests ersetzbar."""
    return shutil.which(name, path=_prozess().erweiterter_path()) is not None


def _erstes(*namen: str) -> str | None:
    return next((n for n in namen if programm_vorhanden(n)), None)


async def _lauf(*befehl: str, eingabe: str | None = None, timeout: float = 30.0, ohne_ausgabe: bool = False,
                zweck: str = "") -> str:
    erg = await _prozess().ausfuehren(*befehl, eingabe=eingabe, timeout=timeout, ohne_ausgabe=ohne_ausgabe)
    if not erg.ok:
        meldung = (erg.fehler or erg.ausgabe).strip() or f"Exit-Code {erg.code}"
        raise _fehler(f"{zweck or befehl[0]} fehlgeschlagen: {meldung}")
    return erg.ausgabe.strip()


# ---------------------------------------------------------------------------
# Desktop-Dateien (*.desktop) – Apps finden
# ---------------------------------------------------------------------------
def anwendungs_ordner() -> list[Path]:
    daten_home = Path(os.environ.get("XDG_DATA_HOME") or "~/.local/share").expanduser()
    daten = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    ordner = [daten_home / "applications"]
    ordner += [Path(d) / "applications" for d in daten.split(":") if d]
    ordner += [
        Path("/var/lib/flatpak/exports/share/applications"),
        daten_home / "flatpak" / "exports" / "share" / "applications",
        Path("/var/lib/snapd/desktop/applications"),
    ]
    gesehen: list[Path] = []
    for o in ordner:
        if o not in gesehen:
            gesehen.append(o)
    return gesehen


class DesktopEintrag:
    def __init__(self, pfad: Path, werte: dict[str, str]):
        self.pfad = pfad
        self.werte = werte

    @property
    def kennung(self) -> str:
        return self.pfad.name[: -len(".desktop")]

    @property
    def namen(self) -> list[str]:
        return [v for k, v in self.werte.items() if k == "Name" or k.startswith("Name[") or k == "GenericName"
                or k.startswith("GenericName[")]

    @property
    def programm(self) -> str | None:
        """Ausführbare Datei aus ``Exec`` (ohne Feldcodes), z. B. ``firefox``."""
        teile = self.befehl()
        if not teile:
            return None
        if Path(teile[0]).name in ("env", "flatpak") and len(teile) > 1:
            return None
        return Path(teile[0]).name

    def befehl(self) -> list[str]:
        exec_ = self.werte.get("Exec", "")
        exec_ = re.sub(r"%[fFuUdDnNickvm]", "", exec_).replace("%%", "%")
        try:
            return shlex.split(exec_)
        except ValueError:
            return []


def desktop_eintrag_lesen(pfad: Path) -> DesktopEintrag | None:
    try:
        text = pfad.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    werte: dict[str, str] = {}
    abschnitt = ""
    for zeile in text.splitlines():
        zeile = zeile.strip()
        if zeile.startswith("["):
            abschnitt = zeile
            continue
        if abschnitt == "[Desktop Entry]" and "=" in zeile and not zeile.startswith("#"):
            k, v = zeile.split("=", 1)
            werte[k.strip()] = v.strip()
    if werte.get("Type", "Application") != "Application":
        return None
    if werte.get("NoDisplay", "").lower() == "true" or werte.get("Hidden", "").lower() == "true":
        return None
    return DesktopEintrag(pfad, werte)


def desktop_eintraege() -> list[DesktopEintrag]:
    eintraege: dict[str, DesktopEintrag] = {}
    for ordner in anwendungs_ordner():
        if not ordner.is_dir():
            continue
        for datei in sorted(ordner.glob("*.desktop")):
            if datei.name in eintraege:  # frühere Ordner (Nutzer) haben Vorrang
                continue
            e = desktop_eintrag_lesen(datei)
            if e:
                eintraege[datei.name] = e
    return list(eintraege.values())


def desktop_eintrag_finden(name: str) -> DesktopEintrag | None:
    """Exakter Name/ID vor Präfix vor Teilstring (Groß/Klein egal)."""
    gesucht = name.strip().lower()
    if not gesucht:
        return None
    eintraege = desktop_eintraege()

    def stufen(e: DesktopEintrag) -> int | None:
        namen = [n.lower() for n in e.namen]
        kennung = e.kennung.lower()
        if gesucht in namen or gesucht == kennung or kennung.endswith("." + gesucht) or gesucht == (e.programm or "").lower():
            return 0
        if any(n.startswith(gesucht) for n in namen):
            return 1
        if any(gesucht in n for n in namen) or gesucht in kennung:
            return 2
        return None

    bewertet = [(s, len(e.kennung), e.kennung, e) for e in eintraege if (s := stufen(e)) is not None]
    return min(bewertet, key=lambda t: t[:3])[3] if bewertet else None


# Programme, die schon ohne Argumente Schaden anrichten bzw. die Sitzung beenden (Neustart,
# Abmelden …) oder Rechte erhöhen. „App öffnen/beenden“ ist nur „aendern“ (ohne Freigabe) –
# solche Programme dürfen darüber nicht gestartet werden (Windows: Get-Command/Start-Process,
# Linux: Rückfall auf ein Programm im PATH).
GESPERRTE_PROGRAMME = frozenset({
    "reboot", "poweroff", "shutdown", "halt", "init", "telinit", "systemctl", "loginctl", "logout",
    "logoff", "tsdiscon", "rundll32", "gnome-session-quit", "cinnamon-session-quit", "mate-session-save",
    "xfce4-session-logout", "lxqt-leave", "lxsession-logout", "qdbus", "qdbus6", "dbus-send", "busctl",
    "sudo", "su", "pkexec", "doas", "runas", "rm", "dd", "mkfs", "shred", "wipefs", "kill", "killall",
    "pkill", "xkill", "taskkill", "format", "diskpart", "cipher", "bcdedit", "vssadmin", "wmic",
    "reg", "regedit", "schtasks", "sc", "net", "netsh", "takeown", "icacls", "crontab", "at",
})


def app_name_pruefen(name: str) -> str:
    """Nur App-Namen, keine Pfade/URLs/Optionen (sonst könnte „App öffnen“ beliebige Dateien ausführen)
    und keine Systemprogramme wie ``reboot``/``logoff`` (siehe ``GESPERRTE_PROGRAMME``)."""
    name = (name or "").strip()
    if not name or any(z in name for z in ("/", "\\", "\x00")) or name.startswith("-") or ":" in name:
        raise _fehler("Bitte nur den Namen der App angeben (kein Pfad, keine URL).")
    basis = name.lower()
    for endung in (".exe", ".com", ".bat", ".cmd"):
        if basis.endswith(endung):
            basis = basis[: -len(endung)]
    if basis.strip(" .") in GESPERRTE_PROGRAMME or basis.split(".")[0] in ("mkfs",):
        raise _fehler(f"„{name}“ ist ein Systemprogramm und lässt sich nicht als App öffnen/beenden – "
                      "dafür ggf. shell_befehl (mit Freigabe) verwenden.")
    return name


def _send2trash_ordner_angleichen(modul) -> None:
    """send2trash liest XDG_DATA_HOME nur beim Import – an die aktuelle Umgebung anpassen."""
    xdg = os.path.expanduser(os.environb.get(b"XDG_DATA_HOME", b"~/.local/share"))
    if getattr(modul, "XDG_DATA_HOME", xdg) != xdg:
        modul.XDG_DATA_HOME = xdg
        modul.HOMETRASH_B = os.path.join(xdg, b"Trash")
        modul.HOMETRASH = os.fsdecode(modul.HOMETRASH_B)


# ---------------------------------------------------------------------------
class LinuxAktionen(Systemaktionen):
    plattform = "linux"

    # ---------------- Apps ----------------
    async def app_oeffnen(self, name: str) -> str:
        name = app_name_pruefen(name)
        eintrag = desktop_eintrag_finden(name)
        if eintrag is not None:
            if programm_vorhanden("gtk-launch"):
                await _lauf("gtk-launch", eintrag.kennung, timeout=20, ohne_ausgabe=True, zweck="gtk-launch")
            elif programm_vorhanden("gio"):
                await _lauf("gio", "launch", str(eintrag.pfad), timeout=20, ohne_ausgabe=True, zweck="gio launch")
            elif programm_vorhanden("kioclient5") or programm_vorhanden("kioclient"):
                kio = "kioclient5" if programm_vorhanden("kioclient5") else "kioclient"
                await _lauf(kio, "exec", str(eintrag.pfad), timeout=20, ohne_ausgabe=True, zweck=kio)
            else:
                befehl = eintrag.befehl()
                if not befehl:
                    raise _fehler(f"„{eintrag.werte.get('Name', name)}“ hat keinen startbaren Befehl.")
                _prozess().losgeloest_starten(*befehl)
            return f"{eintrag.werte.get('Name', name)} wurde geöffnet."
        programm = name.lower().replace(" ", "-")
        if programm_vorhanden(programm):
            _prozess().losgeloest_starten(programm)
            return f"{name} wurde geöffnet."
        raise _fehler(f"Keine App „{name}“ gefunden. Mit laufende_apps oder dem genauen Namen erneut versuchen.")

    async def app_beenden(self, name: str) -> str:
        name = app_name_pruefen(name)
        eintrag = desktop_eintrag_finden(name)
        kandidaten = []
        if eintrag is not None and eintrag.programm:
            kandidaten.append(eintrag.programm)
        kandidaten.append(name)
        if not programm_vorhanden("pkill"):
            raise _fehler(fehlt_meldung("das Beenden von Apps", "pkill"))
        for prozessname in dict.fromkeys(k[:15] for k in kandidaten):  # comm ist auf 15 Zeichen gekürzt
            erg = await _prozess().ausfuehren("pkill", "-i", "-x", "--", prozessname, timeout=10)
            if erg.code == 0:
                return f"{name} wurde beendet."
        raise _fehler(f"„{name}“ läuft nicht (kein passender Prozess gefunden).")

    async def laufende_apps(self) -> str:
        if programm_vorhanden("wmctrl") and not ist_wayland():
            erg = await _prozess().ausfuehren("wmctrl", "-l", timeout=10)
            if erg.ok:
                titel = []
                for zeile in erg.ausgabe.splitlines():
                    teile = zeile.split(None, 3)
                    if len(teile) == 4 and teile[1] != "-1":
                        titel.append(teile[3])
                if titel:
                    return "Offene Fenster:\n" + "\n".join(dict.fromkeys(titel))
        # Ohne Fensterliste (Wayland): laufende Prozesse mit installierten Apps abgleichen
        erg = await _prozess().ausfuehren("ps", "-u", str(os.getuid()), "-o", "comm=", timeout=10)
        if not erg.ok:
            raise _fehler("Laufende Programme konnten nicht ermittelt werden.")
        laufend = {z.strip().lower() for z in erg.ausgabe.splitlines() if z.strip()}
        apps = []
        for e in desktop_eintraege():
            prog = (e.programm or "").lower()
            if prog and prog[:15] in laufend:
                apps.append(e.werte.get("Name", e.kennung))
        return "\n".join(sorted(dict.fromkeys(apps))) or "Keine laufenden Apps erkannt."

    # ---------------- Ton ----------------
    async def _lautstaerke_lesen(self, werkzeug: str) -> tuple[int, bool]:
        if werkzeug == "wpctl":
            text = await _lauf("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@", zweck="wpctl")
            m = re.search(r"([0-9]*\.?[0-9]+)", text)
            return (round(float(m.group(1)) * 100) if m else 0), "MUTED" in text.upper()
        if werkzeug == "pactl":
            text = await _lauf("pactl", "get-sink-volume", "@DEFAULT_SINK@", zweck="pactl")
            m = re.search(r"(\d+)%", text)
            stumm = await _prozess().ausfuehren("pactl", "get-sink-mute", "@DEFAULT_SINK@", timeout=10)
            return (int(m.group(1)) if m else 0), "yes" in stumm.ausgabe.lower() or "ja" in stumm.ausgabe.lower()
        text = await _lauf("amixer", "get", "Master", zweck="amixer")
        m = re.search(r"\[(\d+)%\]", text)
        return (int(m.group(1)) if m else 0), "[off]" in text

    async def lautstaerke_setzen(self, prozent: int | None, aenderung: int | None, stumm: bool | None) -> str:
        werkzeug = _erstes("wpctl", "pactl", "amixer")
        if werkzeug is None:
            raise _fehler(fehlt_meldung("die Lautstärke", "pactl", "wpctl", "amixer"))
        if prozent is None and aenderung is not None:
            aktuell, _ = await self._lautstaerke_lesen(werkzeug)
            prozent = aktuell + int(aenderung)
        if prozent is not None:
            p = max(0, min(100, int(prozent)))
            if werkzeug == "wpctl":
                await _lauf("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{p / 100:.2f}", zweck="wpctl")
            elif werkzeug == "pactl":
                await _lauf("pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{p}%", zweck="pactl")
            else:
                await _lauf("amixer", "-q", "sset", "Master", f"{p}%", zweck="amixer")
        if stumm is not None:
            if werkzeug == "wpctl":
                await _lauf("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if stumm else "0", zweck="wpctl")
            elif werkzeug == "pactl":
                await _lauf("pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if stumm else "0", zweck="pactl")
            else:
                await _lauf("amixer", "-q", "sset", "Master", "mute" if stumm else "unmute", zweck="amixer")
        stand, _ = await self._lautstaerke_lesen(werkzeug)
        return f"Lautstärke jetzt {stand} %." + (" (stumm)" if stumm else "")

    async def mitteilung_anzeigen(self, text: str, titel: str) -> str:
        if not programm_vorhanden("notify-send"):
            raise _fehler(fehlt_meldung("Mitteilungen", "notify-send"))
        from ..konfig import aktueller_name

        name = aktueller_name()
        await _lauf("notify-send", f"--app-name={name}", "--", titel or name, text, timeout=10, zweck="notify-send")
        return "Mitteilung angezeigt."

    async def musik_steuern(self, aktion: str, app: str, suchbegriff: str | None) -> str:
        if aktion == "suchen":
            if not suchbegriff:
                raise _fehler("Für aktion=suchen wird ein suchbegriff benötigt.")
            await self.url_oeffnen("spotify:search:" + quote(suchbegriff))
            return (
                f"Spotify-Suche nach „{suchbegriff}“ geöffnet. Für gezieltes Abspielen bestimmter "
                "Titel kann die Spotify-Integration aus dem Katalog hinzugefügt werden."
            )
        if not programm_vorhanden("playerctl"):
            raise _fehler(fehlt_meldung("die Musiksteuerung", "playerctl"))
        basis = ["playerctl"] + (["--player=spotify"] if app == "spotify" else [])
        befehle = {"play": "play", "pause": "pause", "playpause": "play-pause", "weiter": "next",
                   "zurueck": "previous"}
        if aktion in befehle:
            await _lauf(*basis, befehle[aktion], timeout=10, zweck="playerctl")
            return f"{'Spotify' if app == 'spotify' else 'Player'}: {aktion} ausgeführt."
        if aktion == "aktuell":
            erg = await _prozess().ausfuehren(
                *basis, "metadata", "--format", "{{title}} – {{artist}} ({{status}})", timeout=10
            )
            if not erg.ok or not erg.ausgabe.strip():
                return "Es läuft gerade nichts."
            return erg.ausgabe.strip()
        raise _fehler(f"Unbekannte Aktion: {aktion}")

    # ---------------- URLs, Zwischenablage, Bildschirmfoto ----------------
    async def url_oeffnen(self, url: str) -> str:
        programm = _erstes("xdg-open", "gio")
        if programm is None:
            raise _fehler(fehlt_meldung("das Öffnen von Links", "xdg-open"))
        befehl = ["xdg-open", url] if programm == "xdg-open" else ["gio", "open", url]
        await _lauf(*befehl, timeout=20, ohne_ausgabe=True, zweck=programm)
        return f"{url} geöffnet."

    def _zwischenablage(self, schreiben: bool) -> list[str]:
        if ist_wayland() and programm_vorhanden("wl-copy" if schreiben else "wl-paste"):
            return ["wl-copy"] if schreiben else ["wl-paste", "--no-newline"]
        if programm_vorhanden("xclip"):
            return ["xclip", "-selection", "clipboard", "-in" if schreiben else "-out"]
        if programm_vorhanden("xsel"):
            return ["xsel", "--clipboard", "--input" if schreiben else "--output"]
        if programm_vorhanden("wl-copy" if schreiben else "wl-paste"):
            return ["wl-copy"] if schreiben else ["wl-paste", "--no-newline"]
        raise _fehler(fehlt_meldung("die Zwischenablage", "wl-copy" if ist_wayland() else "xclip",
                                    "xsel" if not ist_wayland() else "xclip"))

    async def zwischenablage_lesen(self) -> str:
        befehl = self._zwischenablage(False)
        erg = await _prozess().ausfuehren(*befehl, timeout=10)
        if not erg.ok and erg.ausgabe == "":
            fehler = erg.fehler.lower()
            if "nothing is copied" in fehler or "no selection" in fehler or "target" in fehler or "no suitable" in fehler:
                return ""
            raise _fehler(f"{befehl[0]} fehlgeschlagen: {erg.fehler.strip()}")
        return erg.ausgabe

    async def zwischenablage_schreiben(self, text: str) -> str:
        befehl = self._zwischenablage(True)
        # xclip/wl-copy bleiben im Hintergrund, um die Auswahl bereitzustellen → Ausgabe verwerfen
        await _lauf(*befehl, eingabe=text, timeout=10, ohne_ausgabe=True, zweck=befehl[0])
        return "Text in die Zwischenablage kopiert."

    def _bildschirmfoto_befehle(self, pfad: str) -> list[list[str]]:
        de = desktop_umgebung().upper()
        kandidaten: list[list[str]] = []
        if "GNOME" in de or "UNITY" in de or "CINNAMON" in de:
            kandidaten.append(["gnome-screenshot", "-f", pfad])
        if "KDE" in de:
            kandidaten.append(["spectacle", "-b", "-n", "-f", "-o", pfad])
        if ist_wayland():
            kandidaten += [["grim", pfad], ["gnome-screenshot", "-f", pfad], ["spectacle", "-b", "-n", "-f", "-o", pfad]]
        kandidaten += [
            ["scrot", "--overwrite", pfad], ["maim", pfad], ["import", "-window", "root", pfad],
            ["gnome-screenshot", "-f", pfad], ["spectacle", "-b", "-n", "-f", "-o", pfad], ["grim", pfad],
        ]
        eindeutig: list[list[str]] = []
        for b in kandidaten:
            if b not in eindeutig and programm_vorhanden(b[0]):
                eindeutig.append(b)
        return eindeutig

    async def bildschirmfoto(self, pfad: str) -> str:
        befehle = self._bildschirmfoto_befehle(pfad)
        if not befehle:
            programm = "grim" if ist_wayland() else "scrot"
            raise _fehler(fehlt_meldung("Bildschirmfotos", "gnome-screenshot", programm, "spectacle"))
        letzter = ""
        for befehl in befehle:
            erg = await _prozess().ausfuehren(*befehl, timeout=30)
            if erg.ok and Path(pfad).exists():
                return f"Bildschirmfoto gespeichert: {pfad}"
            letzter = f"{befehl[0]}: {(erg.fehler or erg.ausgabe).strip() or erg.code}"
        raise _fehler(f"Bildschirmfoto fehlgeschlagen ({letzter}).")

    # ---------------- Systeminfo ----------------
    async def systeminfo(self) -> str:
        teile: list[str] = []
        try:
            werte = dict(
                z.split("=", 1) for z in Path("/etc/os-release").read_text(encoding="utf-8").splitlines() if "=" in z
            )
            teile.append(f"System: {werte.get('PRETTY_NAME', 'Linux').strip(chr(34))} (Kernel {os.uname().release})")
        except OSError:
            teile.append(f"System: Linux (Kernel {os.uname().release})")
        sitzung = "Wayland" if ist_wayland() else ("X11" if os.environ.get("DISPLAY") else "ohne grafische Sitzung")
        teile.append(f"Desktop: {desktop_umgebung() or 'unbekannt'} ({sitzung})")
        akkus = sorted(Path("/sys/class/power_supply").glob("BAT*"))
        for akku in akkus:
            try:
                stand = (akku / "capacity").read_text().strip()
                status = (akku / "status").read_text().strip()
                teile.append(f"Akku {akku.name}: {stand} % ({status})")
            except OSError:
                pass
        if programm_vorhanden("nmcli"):
            erg = await _prozess().ausfuehren("nmcli", "-t", "-f", "active,ssid", "dev", "wifi", timeout=10)
            ssid = [z.split(":", 1)[1] for z in erg.ausgabe.splitlines() if z.startswith(("yes:", "ja:"))]
            if ssid:
                teile.append(f"WLAN: {ssid[0]}")
        elif programm_vorhanden("iwgetid"):
            erg = await _prozess().ausfuehren("iwgetid", "-r", timeout=10)
            if erg.ok and erg.ausgabe.strip():
                teile.append(f"WLAN: {erg.ausgabe.strip()}")
        try:
            belegt = shutil.disk_usage(Path.home())
            teile.append(f"Speicherplatz (Home): {belegt.free / 1024**3:.0f} GB frei von {belegt.total / 1024**3:.0f} GB")
        except OSError:
            pass
        try:
            mem = dict(
                (z.split(":", 1)[0], z.split(":", 1)[1].strip())
                for z in Path("/proc/meminfo").read_text().splitlines() if ":" in z
            )
            gesamt = int(mem["MemTotal"].split()[0]) / 1024**2
            frei = int(mem.get("MemAvailable", "0 kB").split()[0]) / 1024**2
            teile.append(f"Arbeitsspeicher: {gesamt:.0f} GB ({frei:.1f} GB verfügbar)")
        except (OSError, KeyError, ValueError):
            pass
        try:
            sekunden = float(Path("/proc/uptime").read_text().split()[0])
            teile.append(f"Laufzeit: {int(sekunden // 86400)} Tage, {int(sekunden % 86400 // 3600)} Stunden")
        except (OSError, ValueError, IndexError):
            pass
        return "\n".join(teile)

    # ---------------- Dateien ----------------
    async def in_papierkorb(self, pfad: Path) -> str:
        try:
            from send2trash import plat_other  # Freedesktop-Papierkorb (inkl. .trashinfo)

            _send2trash_ordner_angleichen(plat_other)
            send2trash = plat_other.send2trash
        except ImportError:
            send2trash = None
        if send2trash is not None:
            try:
                send2trash(str(pfad))
                return f"{pfad} liegt jetzt im Papierkorb."
            except OSError:
                pass  # z. B. kein Papierkorb auf dem Laufwerk → einfacher Fallback
        from datetime import datetime

        papierkorb = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser() / "Trash" / "files"
        papierkorb.mkdir(parents=True, exist_ok=True)
        ziel = papierkorb / pfad.name
        if ziel.exists():
            ziel = ziel.with_name(f"{pfad.name}.{datetime.now():%Y%m%d%H%M%S}")
        shutil.move(str(pfad), str(ziel))
        return f"{pfad} liegt jetzt im Papierkorb ({ziel})."

    async def dateien_suchen(self, anfrage: str, ordner: str, nur_namen: bool, max_treffer: int) -> list[str]:
        """``plocate``/``locate`` (Dateinamen-Index), sonst Python-Suche. Inhalte durchsucht Linux nicht."""
        programm = _erstes("plocate", "locate")
        treffer: list[str] = []
        if programm:
            erg = await _prozess().ausfuehren(programm, "-i", "-l", str(max_treffer * 20), "--", anfrage, timeout=20)
            if erg.ok:
                basis = str(Path(ordner)).rstrip("/") + "/"
                for zeile in erg.ausgabe.splitlines():
                    if not zeile.startswith(basis):
                        continue
                    rest = zeile[len(basis):]
                    if any(teil.startswith(".") for teil in rest.split("/")):
                        continue
                    if anfrage.lower() not in Path(zeile).name.lower():
                        continue
                    treffer.append(zeile)
                    if len(treffer) >= max_treffer:
                        break
        if not treffer:
            import asyncio

            treffer = await asyncio.to_thread(python_dateisuche, anfrage, ordner, max_treffer)
        return treffer

    def shell_befehl(self, befehl: str) -> list[str]:
        shell = shutil.which("bash") or "/bin/sh"
        return [shell, "-c", befehl]


__all__ = ["LinuxAktionen", "desktop_eintrag_finden", "installationsbefehl", "programm_vorhanden"]
