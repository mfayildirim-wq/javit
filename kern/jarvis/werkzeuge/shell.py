"""Shell-Werkzeug (immer kritisch → Freigabe nötig).

macOS: zsh (unverändert), Linux: bash (sonst sh), Windows: Windows PowerShell
(``powershell -NoProfile -EncodedCommand …``, damit Anführungszeichen nicht verloren gehen).
"""

from __future__ import annotations

import os

from ..plattform import aktuelle_plattform, systemaktionen
from . import FunktionsWerkzeug, Werkzeug, schema, werkzeug
from . import prozess

MAX_AUSGABE = 8000


def _kuerzen(text: str) -> str:
    if len(text) <= MAX_AUSGABE:
        return text
    haelfte = MAX_AUSGABE // 2
    return text[:haelfte] + f"\n… ({len(text) - MAX_AUSGABE} Zeichen ausgelassen) …\n" + text[-haelfte:]


@werkzeug(
    "shell_befehl",
    "Führt einen Shell-Befehl auf dem Mac aus (zsh). Nur verwenden, wenn kein spezielleres Werkzeug passt.",
    schema(
        {
            "befehl": {"type": "string"},
            "arbeitsverzeichnis": {"type": "string", "description": "Standard: Home-Ordner"},
            "timeout": {"type": "integer", "default": 60, "maximum": 600},
        },
        ["befehl"],
    ),
    risiko="kritisch",
    grund=lambda a: f"Shell-Befehl ausführen: {a.get('befehl')}",
)
async def shell_befehl(befehl: str, arbeitsverzeichnis: str | None = None, timeout: int = 60) -> str:
    if prozess.ist_mac():
        shell = "/bin/zsh" if os.path.exists("/bin/zsh") else "/bin/sh"
        argv = [shell, "-c", befehl]
    else:
        argv = systemaktionen("windows" if aktuelle_plattform() == "windows" else "linux").shell_befehl(befehl)
    cwd = os.path.expanduser(arbeitsverzeichnis or "~")
    erg = await prozess.ausfuehren(*argv, cwd=cwd, timeout=max(1, min(int(timeout), 600)))
    teile = [f"Exit-Code: {erg.code}"]
    if erg.ausgabe.strip():
        teile.append("Ausgabe:\n" + _kuerzen(erg.ausgabe.rstrip()))
    if erg.fehler.strip():
        teile.append("Fehlerausgabe:\n" + _kuerzen(erg.fehler.rstrip()))
    return "\n".join(teile)


_BESCHREIBUNG = {
    "windows": "Führt einen Befehl in Windows PowerShell aus. Nur verwenden, wenn kein spezielleres Werkzeug passt.",
    "linux": "Führt einen Shell-Befehl unter Linux aus (bash). Nur verwenden, wenn kein spezielleres Werkzeug passt.",
}


def werkzeuge() -> list[Werkzeug]:
    if not isinstance(shell_befehl, FunktionsWerkzeug):
        return []
    plattform = aktuelle_plattform()
    if plattform == "mac":
        return [shell_befehl]
    # gleicher Name, gleiche Risikostufe (kritisch) – nur die Beschreibung nennt die passende Shell
    return [
        FunktionsWerkzeug(
            shell_befehl._funktion, shell_befehl.name, _BESCHREIBUNG[plattform], shell_befehl.json_schema,
            shell_befehl.risiko, grund=shell_befehl._grund,
        )
    ]
