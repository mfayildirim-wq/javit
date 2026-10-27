"""Gemeinsame Hilfen zum Ausführen externer Programme (osascript, open, shell …)."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from dataclasses import dataclass

from ..plattform import aktuelle_plattform

ZUSATZ_PFADE = ["/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin", "/usr/bin", "/bin"]
# Linux: Standardpfade, Linuxbrew, Snap und Flatpak-Exporte
ZUSATZ_PFADE_LINUX = [
    "/usr/local/bin", "/usr/bin", "/bin", "/usr/local/sbin", "/usr/sbin",
    "/home/linuxbrew/.linuxbrew/bin", "/snap/bin", "/var/lib/flatpak/exports/bin",
]


def _zusatz_pfade_windows() -> list[str]:
    """npm-Global (npx.cmd), Node.js, uv/pipx (~/.local/bin), Cargo, WinGet-Links."""
    env = os.environ
    pfade = []
    if env.get("APPDATA"):
        pfade.append(os.path.join(env["APPDATA"], "npm"))
    for programme in (env.get("ProgramFiles"), env.get("ProgramFiles(x86)")):
        if programme:
            pfade.append(os.path.join(programme, "nodejs"))
    if env.get("LOCALAPPDATA"):
        pfade.append(os.path.join(env["LOCALAPPDATA"], "Microsoft", "WinGet", "Links"))
        pfade.append(os.path.join(env["LOCALAPPDATA"], "Programs", "Ollama"))
    pfade += [os.path.expanduser("~/.local/bin"), os.path.expanduser("~/.cargo/bin")]
    return pfade


def erweiterter_path(path: str | None = None) -> str:
    """PATH um plattformübliche Pfade erweitern (damit npx, uvx, node … gefunden werden).

    macOS: Homebrew + ~/.local/bin + ~/.cargo/bin (unverändert); Linux: zusätzlich Linuxbrew/Snap/
    Flatpak; Windows: %APPDATA%\\npm, Programme\\nodejs, WinGet-Links, ~/.local/bin (uv).
    """
    teile = (path if path is not None else os.environ.get("PATH", "")).split(os.pathsep)
    plattform = aktuelle_plattform()
    if plattform == "windows":
        zusaetze = _zusatz_pfade_windows()
    elif plattform == "linux":
        zusaetze = [*ZUSATZ_PFADE_LINUX, os.path.expanduser("~/.local/bin"), os.path.expanduser("~/.cargo/bin")]
    else:
        zusaetze = [*ZUSATZ_PFADE, os.path.expanduser("~/.local/bin"), os.path.expanduser("~/.cargo/bin")]
    for zusatz in zusaetze:
        if zusatz not in teile:
            teile.append(zusatz)
    return os.pathsep.join(t for t in teile if t)


def programm_aufloesen(name: str, path: str | None = None) -> str | None:
    """Vollständiger Pfad eines Programms im (erweiterten) PATH.

    Unter Windows werden ``.cmd``/``.exe``/``.bat`` ausdrücklich probiert: ``npx`` und ``uvx``
    sind dort ``npx.cmd`` bzw. ``uvx.exe`` und lassen sich ohne Endung nicht starten.
    """
    pfad = path if path is not None else erweiterter_path()
    gefunden = shutil.which(name, path=pfad)
    if gefunden or aktuelle_plattform() != "windows" or os.path.splitext(name)[1]:
        return gefunden
    for endung in (".cmd", ".exe", ".bat"):
        gefunden = shutil.which(name + endung, path=pfad)
        if gefunden:
            return gefunden
    return None


def befehl_zerlegen(befehl: str) -> list[str]:
    """Befehlszeile in Argumente zerlegen (wie eine Shell, ohne sie auszuführen).

    Unter Windows bleiben Backslashes in Pfaden erhalten (``C:\\Users\\…``); umschließende
    Anführungszeichen werden entfernt.
    """
    import shlex

    if aktuelle_plattform() != "windows":
        return shlex.split(befehl)
    teile = []
    for teil in shlex.split(befehl, posix=False):
        if len(teil) >= 2 and teil[0] == teil[-1] and teil[0] in "\"'":
            teil = teil[1:-1]
        teile.append(teil)
    return teile


def ist_mac() -> bool:
    return aktuelle_plattform() == "mac"


def ist_windows() -> bool:
    return aktuelle_plattform() == "windows"


def _fenster_flags() -> dict:
    """Unter Windows kein Konsolenfenster für Hilfsprozesse (PowerShell) aufblitzen lassen."""
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def losgeloest_starten(*befehl: str) -> None:
    """Startet ein (GUI-)Programm unabhängig von Jarvis (eigene Sitzung, keine Pipes)."""
    env = dict(os.environ)
    env["PATH"] = erweiterter_path(env.get("PATH"))
    extra: dict = {"start_new_session": True} if os.name != "nt" else _fenster_flags()
    subprocess.Popen(  # noqa: S603 - Argumentliste, keine Shell
        list(befehl), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=env, close_fds=True, **extra,
    )


@dataclass
class ProzessErgebnis:
    code: int
    ausgabe: str
    fehler: str

    @property
    def ok(self) -> bool:
        return self.code == 0


async def ausfuehren(
    *befehl: str,
    eingabe: str | None = None,
    timeout: float = 30.0,
    cwd: str | None = None,
    umgebung: dict[str, str] | None = None,
    ohne_ausgabe: bool = False,
) -> ProzessErgebnis:
    """Startet ein Programm ohne Shell und sammelt Ausgabe. Wird in Tests gemockt.

    ``ohne_ausgabe=True`` verwirft stdout/stderr – nötig für Programme, die einen Hintergrundprozess
    hinterlassen, der die Pipe offen hält (z. B. ``xclip``/``wl-copy`` beim Kopieren).
    """
    env = dict(os.environ)
    env["PATH"] = erweiterter_path(env.get("PATH"))
    if umgebung:
        env.update(umgebung)
    try:
        proc = await asyncio.create_subprocess_exec(
            *befehl,
            stdin=asyncio.subprocess.PIPE if eingabe is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL if ohne_ausgabe else asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL if ohne_ausgabe else asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
            **_fenster_flags(),
        )
    except FileNotFoundError:
        return ProzessErgebnis(127, "", f"Programm nicht gefunden: {befehl[0]}")
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(eingabe.encode("utf-8") if eingabe is not None else None), timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return ProzessErgebnis(124, "", f"Zeitüberschreitung nach {timeout:.0f} s")
    return ProzessErgebnis(
        proc.returncode if proc.returncode is not None else -1,
        (out or b"").decode("utf-8", errors="replace"),
        (err or b"").decode("utf-8", errors="replace"),
    )
