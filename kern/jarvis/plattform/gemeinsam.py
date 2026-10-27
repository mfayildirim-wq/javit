"""Gemeinsame Hilfen der Plattform-Implementierungen: Installationshinweise, Python-Dateisuche,
Standardordner."""

from __future__ import annotations

import os
import time
from pathlib import Path

OS_RELEASE = Path("/etc/os-release")

# Paketnamen je Paketverwaltung (Programm → Paket); fehlt ein Eintrag, heißt das Paket wie das Programm
_PAKETE: dict[str, dict[str, str]] = {
    "notify-send": {"apt": "libnotify-bin", "dnf": "libnotify", "pacman": "libnotify", "zypper": "libnotify-tools"},
    "pactl": {"apt": "pulseaudio-utils", "dnf": "pulseaudio-utils", "pacman": "libpulse", "zypper": "pulseaudio-utils"},
    "wpctl": {"apt": "wireplumber", "dnf": "wireplumber", "pacman": "wireplumber", "zypper": "wireplumber"},
    "amixer": {"apt": "alsa-utils", "dnf": "alsa-utils", "pacman": "alsa-utils", "zypper": "alsa-utils"},
    "wl-copy": {"apt": "wl-clipboard", "dnf": "wl-clipboard", "pacman": "wl-clipboard", "zypper": "wl-clipboard"},
    "wl-paste": {"apt": "wl-clipboard", "dnf": "wl-clipboard", "pacman": "wl-clipboard", "zypper": "wl-clipboard"},
    "paplay": {"apt": "pulseaudio-utils", "dnf": "pulseaudio-utils", "pacman": "libpulse", "zypper": "pulseaudio-utils"},
    "pw-play": {"apt": "pipewire-bin", "dnf": "pipewire-utils", "pacman": "pipewire", "zypper": "pipewire-tools"},
    "aplay": {"apt": "alsa-utils", "dnf": "alsa-utils", "pacman": "alsa-utils", "zypper": "alsa-utils"},
    "spd-say": {"apt": "speech-dispatcher", "dnf": "speech-dispatcher-utils", "pacman": "speech-dispatcher",
                "zypper": "speech-dispatcher"},
    "import": {"apt": "imagemagick", "dnf": "ImageMagick", "pacman": "imagemagick", "zypper": "ImageMagick"},
    "gtk-launch": {"apt": "libgtk-3-bin", "dnf": "gtk3", "pacman": "gtk3", "zypper": "gtk3-tools"},
}


def paketverwaltung() -> str:
    """``apt`` | ``dnf`` | ``pacman`` | ``zypper`` (aus /etc/os-release, Standard ``apt``)."""
    try:
        text = OS_RELEASE.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return "apt"
    werte: dict[str, str] = {}
    for zeile in text.splitlines():
        if "=" in zeile:
            k, v = zeile.split("=", 1)
            werte[k.strip()] = v.strip().strip('"')
    kennungen = {werte.get("id", ""), *werte.get("id_like", "").split()}
    if kennungen & {"arch", "manjaro", "endeavouros", "cachyos"}:
        return "pacman"
    if kennungen & {"fedora", "rhel", "centos", "rocky", "almalinux", "nobara"}:
        return "dnf"
    if kennungen & {"opensuse", "suse", "opensuse-leap", "opensuse-tumbleweed", "sles"}:
        return "zypper"
    return "apt"


def installationsbefehl(*programme: str) -> str:
    """z. B. ``sudo apt install playerctl`` für die erkannte Distribution."""
    pv = paketverwaltung()
    pakete: list[str] = []
    for programm in programme:
        paket = _PAKETE.get(programm, {}).get(pv, programm)
        if paket not in pakete:
            pakete.append(paket)
    befehl = {"apt": "sudo apt install", "dnf": "sudo dnf install", "pacman": "sudo pacman -S",
              "zypper": "sudo zypper install"}[pv]
    return f"{befehl} {' '.join(pakete)}"


def fehlt_meldung(zweck: str, *programme: str) -> str:
    """Verständliche Meldung, wenn kein passendes Hilfsprogramm installiert ist."""
    liste = " oder ".join(f"„{p}“" for p in programme)
    return f"Für {zweck} fehlt ein Hilfsprogramm ({liste}). Installieren mit: {installationsbefehl(programme[0])}"


def python_dateisuche(anfrage: str, ordner: str, max_treffer: int, max_tiefe: int = 6,
                      zeitlimit_s: float = 20.0) -> list[str]:
    """Dateinamensuche ohne externe Programme (versteckte Ordner werden übersprungen)."""
    nadel = anfrage.strip().lower()
    if not nadel:
        return []
    basis = Path(ordner)
    basis_tiefe = len(basis.parts)
    ende = time.monotonic() + zeitlimit_s
    treffer: list[str] = []
    for wurzel, ordnernamen, dateinamen in os.walk(basis, onerror=lambda e: None):
        tiefe = len(Path(wurzel).parts) - basis_tiefe
        ordnernamen[:] = sorted(o for o in ordnernamen if not o.startswith(".") and o not in ("node_modules", "__pycache__"))
        if tiefe >= max_tiefe:
            ordnernamen[:] = []
        for name in sorted([*ordnernamen, *dateinamen]):
            if not name.startswith(".") and nadel in name.lower():
                treffer.append(str(Path(wurzel) / name))
                if len(treffer) >= max_treffer:
                    return treffer
        if time.monotonic() > ende:
            break
    return treffer


def bilder_ordner() -> Path:
    """Standardziel für Bildschirmfotos: Schreibtisch, sonst Bilder, sonst Benutzerordner."""
    home = Path.home()
    kandidaten = [home / "Desktop"]
    if os.environ.get("OneDrive"):  # Windows: Schreibtisch oft nach OneDrive umgeleitet
        kandidaten.append(Path(os.environ["OneDrive"]) / "Desktop")
    kandidaten += [home / "Schreibtisch", home / "Pictures", home / "Bilder"]
    for ordner in kandidaten:
        if ordner.is_dir():
            return ordner
    return home
