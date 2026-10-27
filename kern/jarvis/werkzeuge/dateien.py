"""Datei-Werkzeuge: suchen (Mac: Spotlight/mdfind; Windows: Suchindex; Linux: plocate/locate;
Fallback Namenssuche), lesen, schreiben, verschieben, löschen (in den Papierkorb), Ordner auflisten.

Die Sicherheitsregeln (kritische Ziele wie Autostart-Orte, Schlüsseldateien) gelten je Plattform:
macOS unverändert (~/Library, Dotfiles …), Windows zusätzlich AppData (Startup-Ordner), ausführbare
Endungen (.exe, .bat, .ps1, .reg …), Linux zusätzlich ~/.config/autostart, ~/.config/systemd/user,
Shell-Startdateien, ~/bin und .desktop-Dateien.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from ..plattform import aktuelle_plattform, systemaktionen
from . import FunktionsWerkzeug, Risiko, Werkzeug, WerkzeugFehler, schema, werkzeug
from . import prozess

MAX_LESE_BYTES = 200_000


def _pfad(p: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(p.strip()))).resolve()


# Dateiendungen, deren Inhalt ausgeführt/geladen werden kann (Autostart, Skripte, Programme)
_AUSFUEHRBAR = {
    ".sh", ".zsh", ".bash", ".command", ".tool", ".py", ".rb", ".pl", ".js", ".plist", ".app",
    ".scpt", ".applescript", ".workflow", ".terminal", ".dylib", ".so", ".pkg",
}
# Lesen nur mit Freigabe: Schlüssel, Zugangsdaten, Jarvis' eigene Geheimnisse
_GEHEIME_ORDNER = (".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", ".config/gcloud", ".password-store",
                   "Library/Keychains", "Library/Cookies")
_GEHEIME_DATEIEN = {".netrc", ".npmrc", ".pypirc", ".git-credentials", ".pgpass", "credentials", "id_rsa",
                    "id_ed25519", "id_ecdsa", "geheimnisse.schluessel", "geheimnisse.enc"}


# Zusätzliche ausführbare/automatisch geladene Endungen je Plattform
_AUSFUEHRBAR_WINDOWS = {
    ".exe", ".bat", ".cmd", ".com", ".ps1", ".psm1", ".psd1", ".vbs", ".vbe", ".jse", ".wsf", ".wsh",
    ".msi", ".msp", ".lnk", ".scr", ".reg", ".dll", ".hta", ".cpl", ".msc", ".url", ".appref-ms", ".inf",
    ".pif", ".jar", ".chm", ".application", ".gadget", ".ps1xml", ".settingcontent-ms", ".library-ms", ".xbap",
}
_AUSFUEHRBAR_LINUX = {".desktop", ".service", ".timer", ".appimage", ".run", ".bin", ".fish"}
# Linux: Orte, an denen Programme automatisch starten (relativ zu ~)
_AUTOSTART_LINUX = (
    ".config/autostart", ".config/systemd/user", ".config/environment.d", ".local/share/systemd/user",
    ".config/plasma-workspace/env", ".config/plasma-workspace/shutdown", ".kde/Autostart",
    ".config/autostart-scripts",
)
_SHELL_START_LINUX = {".bashrc", ".bash_profile", ".bash_login", ".profile", ".zshrc", ".zprofile", ".zshenv",
                      ".zlogin", ".xprofile", ".xinitrc", ".xsession", ".xsessionrc", ".pam_environment"}
# Windows: Ordner mit Zugangsdaten (relativ zu ~, Vergleich ohne Groß/Klein)
_GEHEIME_ORDNER_WINDOWS = (
    "AppData/Roaming/Microsoft/Credentials", "AppData/Local/Microsoft/Credentials",
    "AppData/Roaming/Microsoft/Protect", "AppData/Local/Microsoft/Vault",
    "AppData/Local/Google/Chrome/User Data", "AppData/Local/Microsoft/Edge/User Data",
    "AppData/Roaming/Mozilla/Firefox/Profiles",
)
_GEHEIME_ORDNER_LINUX = (".local/share/keyrings", ".config/google-chrome", ".config/chromium",
                         ".mozilla/firefox", ".config/BraveSoftware")


def _unter(p: Path, basis: Path) -> bool:
    try:
        p.relative_to(basis)
        return True
    except ValueError:
        return False


def _temp_ordner() -> list[Path]:
    import tempfile

    return [Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve()]


def schreib_grund(p: Path) -> str | None:
    """Grund, warum Schreiben nach `p` eine Freigabe braucht (None = unkritisch).

    Schützt vor Persistenz/Codeausführung durch manipulierte Anweisungen (z. B. aus einer Webseite):
    versteckte Dateien (~/.zshrc, ~/.ssh), ~/Library (LaunchAgents), Jarvis' eigene Konfiguration
    (integrationen.json kann Programme starten), ausführbare Dateien und alles außerhalb des Home-Ordners.
    """
    from ..konfig import jarvis_home

    plattform = aktuelle_plattform()
    if plattform == "windows":
        return _schreib_grund_windows(p)
    if plattform == "linux":
        return _schreib_grund_linux(p)
    home = Path.home().resolve()
    if _unter(p, jarvis_home().resolve()):
        return "die eigene Konfiguration/Daten des Assistenten würden verändert"
    if p.suffix.lower() in _AUSFUEHRBAR:
        return f"ausführbare bzw. automatisch geladene Datei ({p.suffix})"
    if not _unter(p, home):
        if any(_unter(p, t) for t in _temp_ordner()):
            return None
        return "Ziel liegt außerhalb des Benutzerordners"
    teile = p.relative_to(home).parts
    if any(teil.startswith(".") for teil in teile):
        return "versteckte Datei bzw. Konfigurationsordner"
    if teile and teile[0] == "Library":
        return "Systemordner ~/Library (z. B. Autostart)"
    return None


def _gemeinsamer_grund(p: Path, home: Path) -> str | None:
    """Regeln für Windows und Linux, die vor den plattformeigenen greifen."""
    from ..konfig import jarvis_home

    if _unter(p, jarvis_home().resolve()):
        return "die eigene Konfiguration/Daten des Assistenten würden verändert"
    return None


def _schreib_grund_linux(p: Path) -> str | None:
    home = Path.home().resolve()
    grund = _gemeinsamer_grund(p, home)
    if grund:
        return grund
    endung = p.suffix.lower()
    if endung in _AUSFUEHRBAR or endung in _AUSFUEHRBAR_LINUX:
        return f"ausführbare bzw. automatisch geladene Datei ({p.suffix})"
    if not _unter(p, home):
        if any(_unter(p, t) for t in _temp_ordner()):
            return None
        if _unter(p, Path("/var/spool/cron")) or _unter(p, Path("/etc")):
            return "Systemkonfiguration bzw. crontab (Autostart)"
        return "Ziel liegt außerhalb des Benutzerordners"
    teile = p.relative_to(home).parts
    relativ = "/".join(teile)
    for ort in _AUTOSTART_LINUX:
        if relativ == ort or relativ.startswith(ort + "/"):
            return f"Autostart-Ordner ~/{ort}"
    if len(teile) == 1 and teile[0] in _SHELL_START_LINUX:
        return "Shell-/Sitzungs-Startdatei (wird bei jeder Anmeldung ausgeführt)"
    if teile and teile[0] == "bin":
        return "~/bin liegt im Suchpfad für Programme"
    if any(teil.startswith(".") for teil in teile):
        return "versteckte Datei bzw. Konfigurationsordner"
    return None


def _windows_endung(name: str) -> str:
    """Endung, wie Windows sie beim Anlegen sieht: Windows entfernt Punkte/Leerzeichen am Ende
    („boese.ps1.“ → boese.ps1)."""
    return Path(name.rstrip(" .")).suffix.lower()


def _schreib_grund_windows(p: Path) -> str | None:
    home = Path.home().resolve()
    grund = _gemeinsamer_grund(p, home)
    if grund:
        return grund
    if ":" in p.name:
        return "alternativer Datenstrom (NTFS) bzw. ungültiger Dateiname"
    endung = _windows_endung(p.name)
    if endung in _AUSFUEHRBAR or endung in _AUSFUEHRBAR_WINDOWS:
        return f"ausführbare bzw. automatisch geladene Datei ({Path(p.name.rstrip(' .')).suffix})"
    if not _unter(p, home):
        if any(_unter(p, t) for t in _temp_ordner()):
            return None
        text = str(p).replace("\\", "/").lower()
        if "/start menu/programs/startup" in text or "/system32/tasks" in text:
            return "Autostart-Ordner bzw. Aufgabenplanung"
        return "Ziel liegt außerhalb des Benutzerordners"
    teile = [t.lower() for t in p.relative_to(home).parts]
    relativ = "/".join(teile)
    if "start menu/programs/startup" in relativ:
        return "Autostart-Ordner (Start Menu\\Programs\\Startup)"
    if relativ.startswith("appdata/local/temp/") or any(
        _unter(p, t) and not _unter(home, t) for t in _temp_ordner()
    ):
        return None  # %TEMP% liegt unter AppData
    if teile and teile[0] == "appdata":
        return "Systemordner AppData (z. B. Autostart, Programmeinstellungen)"
    if any(teil.startswith(".") for teil in teile):
        return "versteckte Datei bzw. Konfigurationsordner"
    return None


def lese_grund(p: Path) -> str | None:
    """Grund, warum Lesen von `p` eine Freigabe braucht (Schlüssel, Zugangsdaten)."""
    from ..konfig import jarvis_home

    home = Path.home().resolve()
    if p.name in _GEHEIME_DATEIEN or p.name.startswith(".env") or p.suffix.lower() in (".pem", ".key", ".p12"):
        return "Datei enthält vermutlich Zugangsdaten oder Schlüssel"
    if _unter(p, jarvis_home().resolve()) and p.name.startswith("geheimnisse"):
        return "Geheimnisspeicher des Assistenten"
    if any(_unter(p, home / o) for o in _GEHEIME_ORDNER):
        return "Ordner mit Schlüsseln/Zugangsdaten"
    plattform = aktuelle_plattform()
    if plattform == "windows" and _unter(p, home):
        relativ = "/".join(p.relative_to(home).parts).lower()
        if any(relativ == o.lower() or relativ.startswith(o.lower() + "/") for o in _GEHEIME_ORDNER_WINDOWS):
            return "Ordner mit Zugangsdaten (Anmeldeinformationen/Browserprofil)"
    if plattform == "linux" and any(_unter(p, home / o) for o in _GEHEIME_ORDNER_LINUX):
        return "Ordner mit Zugangsdaten (Schlüsselbund/Browserprofil)"
    return None


@werkzeug(
    "datei_suchen",
    "Sucht Dateien nach Name oder Inhalt (Spotlight auf dem Mac, sonst Dateinamensuche).",
    schema(
        {
            "anfrage": {"type": "string", "description": "Suchbegriff (Dateiname oder Inhalt)"},
            "ordner": {"type": "string", "description": "Optional: nur in diesem Ordner suchen"},
            "nur_namen": {"type": "boolean", "default": False, "description": "Nur Dateinamen durchsuchen"},
            "max_treffer": {"type": "integer", "default": 20},
        },
        ["anfrage"],
    ),
    risiko="lesen",
)
async def datei_suchen(
    anfrage: str, ordner: str | None = None, nur_namen: bool = False, max_treffer: int = 20
) -> str:
    ordner_pfad = str(_pfad(ordner)) if ordner else str(Path.home())
    treffer: list[str] = []
    max_treffer = max(1, int(max_treffer))
    if prozess.ist_mac() and shutil.which("mdfind"):
        befehl = ["mdfind", "-onlyin", ordner_pfad]
        befehl += ["-name", anfrage] if nur_namen else [anfrage]
        erg = await prozess.ausfuehren(*befehl, timeout=30)
        if erg.ok:
            treffer = [z for z in erg.ausgabe.splitlines() if z.strip()]
    elif not prozess.ist_mac():
        # Windows: Suchindex, Linux: plocate/locate – jeweils mit Python-Namenssuche als Rückfall
        aktionen = systemaktionen("windows" if aktuelle_plattform() == "windows" else "linux")
        treffer = await aktionen.dateien_suchen(anfrage, ordner_pfad, nur_namen, max_treffer)
    if not treffer and prozess.ist_mac():
        erg = await prozess.ausfuehren(
            "find", ordner_pfad, "-maxdepth", "6", "-not", "-path", "*/.*",
            "-iname", f"*{anfrage}*", timeout=30,
        )
        treffer = [z for z in erg.ausgabe.splitlines() if z.strip()]
    if not treffer:
        return f"Keine Dateien zu „{anfrage}“ gefunden."
    rest = len(treffer) - max_treffer
    text = "\n".join(treffer[:max_treffer])
    return text + (f"\n… und {rest} weitere" if rest > 0 else "")


@werkzeug(
    "datei_lesen",
    "Liest eine Textdatei (maximal 200 KB).",
    schema({"pfad": {"type": "string"}}, ["pfad"]),
    risiko="lesen",
    risiko_fuer=lambda a: "kritisch" if lese_grund(_pfad(str(a.get("pfad") or "~"))) else "lesen",
    grund=lambda a: f"Datei lesen: {a.get('pfad')} – {lese_grund(_pfad(str(a.get('pfad') or '~')))}",
)
async def datei_lesen(pfad: str) -> str:
    p = _pfad(pfad)
    if not p.exists():
        raise WerkzeugFehler(f"Datei nicht gefunden: {p}")
    if p.is_dir():
        raise WerkzeugFehler(f"{p} ist ein Ordner – bitte ordner_auflisten verwenden.")
    groesse = p.stat().st_size
    with p.open("rb") as f:
        roh = f.read(MAX_LESE_BYTES)
    if b"\x00" in roh[:8000]:
        raise WerkzeugFehler(f"{p.name} ist keine Textdatei ({groesse} Bytes).")
    text = roh.decode("utf-8", errors="replace")
    if groesse > MAX_LESE_BYTES:
        text += f"\n… (gekürzt, Datei ist {groesse} Bytes groß)"
    return text


def _ziel_grund(argumente: dict[str, Any], schluessel: str) -> str | None:
    ziel = argumente.get(schluessel)
    if not ziel:
        return None
    p = _pfad(str(ziel))
    grund = schreib_grund(p)
    if grund:
        return grund
    if schluessel == "ziel" and argumente.get("quelle"):
        q = _pfad(str(argumente["quelle"]))
        grund = schreib_grund(q) or lese_grund(q)
        if grund:
            return f"Quelle: {grund}"
    if p.exists() and not argumente.get("anhaengen"):
        return "existiert bereits und würde überschrieben/ersetzt"
    return None


def _existiert_risiko(schluessel: str) -> Any:
    def bewerten(argumente: dict[str, Any]) -> Risiko:
        return "kritisch" if _ziel_grund(argumente, schluessel) else "aendern"

    return bewerten


@werkzeug(
    "datei_schreiben",
    "Schreibt Text in eine Datei (legt sie an; Überschreiben bestehender Dateien erfordert Freigabe).",
    schema(
        {
            "pfad": {"type": "string"},
            "inhalt": {"type": "string"},
            "anhaengen": {"type": "boolean", "default": False},
        },
        ["pfad", "inhalt"],
    ),
    risiko="aendern",
    risiko_fuer=_existiert_risiko("pfad"),
    grund=lambda a: f"Datei schreiben: {a.get('pfad')} – {_ziel_grund(a, 'pfad')}",
)
async def datei_schreiben(pfad: str, inhalt: str, anhaengen: bool = False) -> str:
    p = _pfad(pfad)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a" if anhaengen else "w", encoding="utf-8") as f:
        f.write(inhalt)
    return f"{len(inhalt)} Zeichen {'angehängt an' if anhaengen else 'geschrieben in'} {p}."


@werkzeug(
    "datei_verschieben",
    "Verschiebt oder benennt eine Datei/einen Ordner um.",
    schema({"quelle": {"type": "string"}, "ziel": {"type": "string"}}, ["quelle", "ziel"]),
    risiko="aendern",
    risiko_fuer=_existiert_risiko("ziel"),
    grund=lambda a: f"Verschieben {a.get('quelle')} → {a.get('ziel')} – {_ziel_grund(a, 'ziel')}",
)
async def datei_verschieben(quelle: str, ziel: str) -> str:
    q, z = _pfad(quelle), _pfad(ziel)
    if not q.exists():
        raise WerkzeugFehler(f"Quelle nicht gefunden: {q}")
    if z.is_dir():
        z = z / q.name
    z.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(q), str(z))
    return f"{q} → {z}"


@werkzeug(
    "datei_loeschen",
    "Legt eine Datei oder einen Ordner in den Papierkorb (wiederherstellbar).",
    schema({"pfad": {"type": "string"}}, ["pfad"]),
    risiko="kritisch",
    grund=lambda a: f"Datei/Ordner in den Papierkorb legen: {a.get('pfad')}",
)
async def datei_loeschen(pfad: str) -> str:
    p = _pfad(pfad)
    if not p.exists():
        raise WerkzeugFehler(f"Nicht gefunden: {p}")
    if p == Path.home() or p == Path("/"):
        raise WerkzeugFehler("Dieser Ordner darf nicht gelöscht werden.")
    if prozess.ist_mac():
        from .mac import as_text, osascript

        await osascript(f'tell application "Finder" to delete (POSIX file {as_text(str(p))})')
        return f"{p} liegt jetzt im Papierkorb."
    # Windows: Papierkorb über send2trash (Fallback PowerShell/VisualBasic); Linux: Freedesktop-Papierkorb
    plattform = aktuelle_plattform()
    return await systemaktionen("windows" if plattform == "windows" else "linux").in_papierkorb(p)


@werkzeug(
    "ordner_auflisten",
    "Listet den Inhalt eines Ordners auf (Name, Typ, Größe).",
    schema({"pfad": {"type": "string", "default": "~"}}),
    risiko="lesen",
)
async def ordner_auflisten(pfad: str = "~") -> str:
    p = _pfad(pfad)
    if not p.is_dir():
        raise WerkzeugFehler(f"Kein Ordner: {p}")
    zeilen = []
    for eintrag in sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))[:300]:
        if eintrag.name.startswith("."):
            continue
        if eintrag.is_dir():
            zeilen.append(f"[Ordner] {eintrag.name}/")
        else:
            try:
                zeilen.append(f"{eintrag.name} ({eintrag.stat().st_size} B)")
            except OSError:
                zeilen.append(eintrag.name)
    return f"{p}:\n" + ("\n".join(zeilen) or "(leer)")


def werkzeuge() -> list[Werkzeug]:
    return [w for w in globals().values() if isinstance(w, FunktionsWerkzeug)]

