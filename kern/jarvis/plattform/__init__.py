"""Plattform-Schicht: Erkennung des Betriebssystems und einheitliche Schnittstelle für Systemaktionen.

    from jarvis.plattform import aktuelle_plattform, systemaktionen
    aktuelle_plattform()                 # "mac" | "windows" | "linux"
    await systemaktionen().app_oeffnen("Firefox")

Die Plattform lässt sich für Tests mit der Umgebungsvariable ``JARVIS_PLATTFORM`` (mac, windows,
linux) überschreiben. Die Implementierungen liegen in ``mac.py`` (AppleScript, delegiert an die
unveränderten Mac-Werkzeuge), ``windows.py`` (PowerShell) und ``linux.py`` (xdg-open, playerctl,
pactl/wpctl, notify-send …). Alle Programmaufrufe laufen über ``werkzeuge.prozess.ausfuehren``
(in Tests gemockt) – nie über eine Shell.

Dieses Modul importiert absichtlich nichts aus ``jarvis.werkzeuge`` (sonst Import-Zyklus mit
``werkzeuge.prozess``); die Implementierungen werden erst in ``systemaktionen()`` geladen.
"""

from __future__ import annotations

import logging
import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

log = logging.getLogger("jarvis.plattform")

Plattform = Literal["mac", "windows", "linux"]
PLATTFORMEN: tuple[Plattform, ...] = ("mac", "windows", "linux")

_ALIASE: dict[str, Plattform] = {
    "mac": "mac", "macos": "mac", "darwin": "mac", "osx": "mac",
    "windows": "windows", "win": "windows", "win32": "windows",
    "linux": "linux",
}

PLATTFORM_NAMEN: dict[str, str] = {"mac": "macOS", "windows": "Windows", "linux": "Linux"}


def aktuelle_plattform() -> Plattform:
    """Aktuelles System als ``mac`` | ``windows`` | ``linux`` (überschreibbar per ``JARVIS_PLATTFORM``)."""
    wunsch = os.environ.get("JARVIS_PLATTFORM", "").strip().lower()
    if wunsch:
        if wunsch in _ALIASE:
            return _ALIASE[wunsch]
        log.warning("Unbekannte JARVIS_PLATTFORM=%r – wird ignoriert.", wunsch)
    if sys.platform == "darwin":
        return "mac"
    if sys.platform.startswith(("win", "cygwin", "msys")):
        return "windows"
    return "linux"


def ist_mac() -> bool:
    return aktuelle_plattform() == "mac"


def ist_windows() -> bool:
    return aktuelle_plattform() == "windows"


def ist_linux() -> bool:
    return aktuelle_plattform() == "linux"


def ist_wayland() -> bool:
    """Linux-Sitzung unter Wayland (sonst X11 bzw. keine grafische Sitzung)."""
    return bool(os.environ.get("WAYLAND_DISPLAY")) or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"


def desktop_umgebung() -> str:
    """z. B. ``GNOME``, ``KDE``, ``XFCE`` (leer, wenn unbekannt)."""
    return os.environ.get("XDG_CURRENT_DESKTOP", "") or os.environ.get("DESKTOP_SESSION", "")


class Systemaktionen(ABC):
    """Einheitliche Schnittstelle der Systemaktionen hinter den plattformneutralen Werkzeugen.

    Alle Methoden liefern einen deutschen Ergebnistext oder werfen ``WerkzeugFehler`` mit einer
    verständlichen Meldung (inkl. Installationsbefehl, wenn ein Hilfsprogramm fehlt).
    """

    plattform: Plattform

    @abstractmethod
    async def app_oeffnen(self, name: str) -> str: ...

    @abstractmethod
    async def app_beenden(self, name: str) -> str: ...

    @abstractmethod
    async def laufende_apps(self) -> str: ...

    @abstractmethod
    async def lautstaerke_setzen(self, prozent: int | None, aenderung: int | None, stumm: bool | None) -> str: ...

    @abstractmethod
    async def mitteilung_anzeigen(self, text: str, titel: str) -> str: ...

    @abstractmethod
    async def musik_steuern(self, aktion: str, app: str, suchbegriff: str | None) -> str: ...

    @abstractmethod
    async def url_oeffnen(self, url: str) -> str:
        """``url`` ist bereits geprüft (erlaubtes Schema)."""

    @abstractmethod
    async def zwischenablage_lesen(self) -> str: ...

    @abstractmethod
    async def zwischenablage_schreiben(self, text: str) -> str: ...

    @abstractmethod
    async def bildschirmfoto(self, pfad: str) -> str: ...

    @abstractmethod
    async def systeminfo(self) -> str: ...

    @abstractmethod
    async def in_papierkorb(self, pfad: Path) -> str: ...

    @abstractmethod
    async def dateien_suchen(self, anfrage: str, ordner: str, nur_namen: bool, max_treffer: int) -> list[str]:
        """Trefferliste (leer = nichts gefunden; der Aufrufer fällt dann auf die Namenssuche zurück)."""

    @abstractmethod
    def shell_befehl(self, befehl: str) -> list[str]:
        """Argumentliste, die ``befehl`` in der Standard-Shell der Plattform ausführt."""


def systemaktionen(plattform: Plattform | None = None) -> Systemaktionen:
    """Implementierung für ``plattform`` (Standard: aktuelle Plattform)."""
    plattform = plattform or aktuelle_plattform()
    if plattform == "mac":
        from .mac import MacAktionen

        return MacAktionen()
    if plattform == "windows":
        from .windows import WindowsAktionen

        return WindowsAktionen()
    from .linux import LinuxAktionen

    return LinuxAktionen()


__all__ = [
    "PLATTFORMEN",
    "PLATTFORM_NAMEN",
    "Plattform",
    "Systemaktionen",
    "aktuelle_plattform",
    "desktop_umgebung",
    "ist_linux",
    "ist_mac",
    "ist_wayland",
    "ist_windows",
    "systemaktionen",
]
