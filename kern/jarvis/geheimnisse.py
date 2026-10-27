"""Geheimnisse (API-Schlüssel): macOS-Schlüsselbund über die `security`-CLI; unter Windows und
Linux über das Paket `keyring` (Windows-Anmeldeinformationsverwaltung bzw. Secret Service von
GNOME-Schlüsselbund/KWallet). Fallback: Fernet-verschlüsselte Datei ~/.jarvis/geheimnisse.enc
(Schlüssel in Datei mit Rechten 0600; unter Windows schützen die Rechte des Benutzerprofils).

Gespeicherte Namen werden in ~/.jarvis/geheimnisse_namen.json geführt (ohne Werte), damit
sie beim Start in os.environ geladen werden können (LiteLLM liest z. B. ANTHROPIC_API_KEY).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .konfig import jarvis_home

DIENST = "jarvis"

# Diese Namen werden immer in die Umgebung geladen, wenn vorhanden.
BEKANNTE_SCHLUESSEL = [
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "MISTRAL_API_KEY",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "DEEPSEEK_API_KEY",
    "TAVILY_API_KEY",
    "BRAVE_API_KEY",
]


# Kontonamen im Schlüsselbund (keine Leerzeichen/Anführungszeichen → sicher für `security -i`)
_KONTO_NAME = re.compile(r"[A-Za-z0-9_.\-]{1,128}")
# Zeilenpuffer von `security -i` (sicherer Abstand zur internen Grenze)
_MAX_INTERAKTIV_ZEILE = 4000


_GEHEIME_WOERTER = {
    "key", "apikey", "token", "secret", "passwort", "password", "pass", "passwd", "pwd", "pat",
    "credential", "credentials", "auth", "authorization", "cookie", "bearer", "geheimnis", "private",
}
GESCHWAERZT = "••••••"


def ist_geheimer_name(name: str) -> bool:
    """True für Namen wie OPENAI_API_KEY, accessToken, client-secret, Authorization (nicht: PATH, AUTHOR)."""
    getrennt = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name))
    woerter = [w for w in re.split(r"[^A-Za-z0-9]+", getrennt.lower()) if w]
    return any(
        w in _GEHEIME_WOERTER or w.endswith(("apikey", "token", "secret", "password", "passwort"))
        for w in woerter
    )


def schwaerzen(wert: object, _tiefe: int = 0) -> object:
    """Ersetzt Werte unter geheimen Schlüsseln (rekursiv) durch ••••••, z. B. für Events und Logs."""
    if _tiefe > 20:
        return wert
    if isinstance(wert, dict):
        return {
            k: (GESCHWAERZT if ist_geheimer_name(str(k)) and v not in (None, "") else schwaerzen(v, _tiefe + 1))
            for k, v in wert.items()
        }
    if isinstance(wert, list):
        return [schwaerzen(v, _tiefe + 1) for v in wert]
    return wert


_O_BINAER = getattr(os, "O_BINARY", 0)  # Windows: keine Zeilenende-Umwandlung


def _unix_rechte() -> bool:
    return os.name != "nt"


class GeheimnisFehler(RuntimeError):
    pass


def _schluesselbund_verfuegbar() -> bool:
    return sys.platform == "darwin" and shutil.which("security") is not None


def _keyring_modul():
    """Das Paket ``keyring`` (in Tests ersetzbar) oder None."""
    try:
        import keyring  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - nicht installiert oder defekte Backends
        return None
    return keyring


def _keyring_verfuegbar() -> bool:
    """True, wenn ``keyring`` ein echtes Backend hat (nicht das „fail“-Backend ohne Secret Service)."""
    kr = _keyring_modul()
    if kr is None:
        return False
    try:
        backend = kr.get_keyring()
        modul = type(backend).__module__
        if "fail" in modul or "null" in modul or getattr(backend, "priority", 1) <= 0:
            return False
        kr.get_password(DIENST, "__jarvis_probe__")  # gesperrter/fehlender Dienst → Ausnahme
        return True
    except Exception:  # noqa: BLE001
        return False


class Geheimnisspeicher:
    def __init__(self, home: Path | None = None, backend: str | None = None):
        self.home = home or jarvis_home()
        gewuenscht = backend or os.environ.get("JARVIS_GEHEIMNIS_BACKEND", "auto")
        if gewuenscht == "auto":
            from .plattform import aktuelle_plattform

            if aktuelle_plattform() == "mac":
                gewuenscht = "schluesselbund" if _schluesselbund_verfuegbar() else "datei"
            else:
                gewuenscht = "keyring" if _keyring_verfuegbar() else "datei"
        if gewuenscht not in ("schluesselbund", "keyring", "datei"):
            raise GeheimnisFehler(f"Unbekanntes Geheimnis-Backend: {gewuenscht}")
        self.backend = gewuenscht
        self._namen_datei = self.home / "geheimnisse_namen.json"
        self._enc_datei = self.home / "geheimnisse.enc"
        self._schluessel_datei = self.home / "geheimnisse.schluessel"

    # ---------- Namensliste ----------
    def namen(self) -> list[str]:
        if not self._namen_datei.exists():
            return []
        try:
            return sorted(set(json.loads(self._namen_datei.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, OSError):
            return []

    def _namen_schreiben(self, namen: list[str]) -> None:
        self._namen_datei.write_text(json.dumps(sorted(set(namen))), encoding="utf-8")

    # ---------- öffentliche API ----------
    def setzen(self, name: str, wert: str) -> None:
        name = name.strip()
        if not name:
            raise GeheimnisFehler("Name des Geheimnisses fehlt.")
        if self.backend == "schluesselbund":
            self._sb_setzen(name, wert)
        elif self.backend == "keyring":
            self._kr_setzen(name, wert)
        else:
            daten = self._datei_lesen()
            daten[name] = wert
            self._datei_schreiben(daten)
        self._namen_schreiben([*self.namen(), name])

    def holen(self, name: str) -> str | None:
        if self.backend == "schluesselbund":
            return self._sb_holen(name)
        if self.backend == "keyring":
            wert = self._kr_holen(name)
            if wert is None and self._enc_datei.exists():
                # Rückfall: vor der keyring-Unterstützung (bzw. bei zeitweise gesperrtem Secret
                # Service) gespeicherte Geheimnisse liegen in der verschlüsselten Datei
                try:
                    wert = self._datei_lesen().get(name)
                except GeheimnisFehler:
                    wert = None
            return wert
        return self._datei_lesen().get(name)

    def loeschen(self, name: str) -> bool:
        vorhanden = name in self.namen()
        if self.backend == "schluesselbund":
            subprocess.run(
                ["security", "delete-generic-password", "-s", DIENST, "-a", name],
                capture_output=True,
                check=False,
            )
        elif self.backend == "keyring":
            self._kr_loeschen(name)
            if self._enc_datei.exists():  # ggf. ältere Kopie in der Datei mit entfernen
                try:
                    daten = self._datei_lesen()
                    if daten.pop(name, None) is not None:
                        self._datei_schreiben(daten)
                except GeheimnisFehler:
                    pass
        else:
            daten = self._datei_lesen()
            vorhanden = daten.pop(name, None) is not None or vorhanden
            self._datei_schreiben(daten)
        self._namen_schreiben([n for n in self.namen() if n != name])
        return vorhanden

    def hat(self, name: str) -> bool:
        return self.holen(name) is not None

    def in_umgebung_laden(self, ueberschreiben: bool = False) -> list[str]:
        """Lädt alle gespeicherten Geheimnisse (und bekannte API-Schlüssel) in os.environ."""
        geladen = []
        for name in sorted(set(self.namen()) | set(BEKANNTE_SCHLUESSEL)):
            if not ueberschreiben and os.environ.get(name):
                continue
            wert = self.holen(name)
            if wert:
                os.environ[name] = wert
                geladen.append(name)
        return geladen

    # ---------- Schlüsselbund ----------
    def _sb_setzen(self, name: str, wert: str) -> None:
        """Speichert im Schlüsselbund, ohne den Wert als Prozessargument sichtbar zu machen.

        `security add-generic-password -w <wert>` würde das Geheimnis für jeden lokalen Prozess
        (`ps`) sichtbar machen. Deshalb wird `security -i` (interaktiver Modus) gestartet und das
        Kommando über stdin übergeben; der Wert steht hexkodiert hinter `-X`, damit weder
        Leerzeichen noch Anführungszeichen geparst werden müssen. Da `security -i` auch bei
        Fehlern mit 0 enden kann, wird das Ergebnis anschließend zurückgelesen und verglichen.

        Nur für sehr lange Werte (> ~1900 Zeichen, Grenze der Eingabezeile von `security -i`)
        wird auf `-w <wert>` als Argument zurückgefallen – dann ist der Wert für die Dauer des
        Aufrufs (Millisekunden) in der Prozessliste sichtbar.
        """
        if not _KONTO_NAME.fullmatch(name):
            raise GeheimnisFehler(f"Ungültiger Name für den Schlüsselbund: {name!r}")
        hexwert = wert.encode("utf-8").hex()
        kommando = f"add-generic-password -U -s {DIENST} -a {name} -X {hexwert}\n"
        if len(kommando) <= _MAX_INTERAKTIV_ZEILE:
            ergebnis = subprocess.run(
                ["security", "-i"], input=kommando, capture_output=True, text=True, check=False, timeout=30
            )
        else:  # pragma: no cover - nur bei sehr langen Werten (dokumentierte Ausnahme)
            ergebnis = subprocess.run(
                ["security", "add-generic-password", "-U", "-s", DIENST, "-a", name, "-w", wert],
                capture_output=True, text=True, check=False, timeout=30,
            )
        if ergebnis.returncode != 0 or self._sb_holen(name) != wert:
            meldung = (ergebnis.stderr or "").replace(hexwert, "…").replace(wert, "…").strip()
            raise GeheimnisFehler(f"Schlüsselbund-Fehler: {meldung or 'Wert konnte nicht gespeichert werden'}")

    def _sb_holen(self, name: str) -> str | None:
        ergebnis = subprocess.run(
            ["security", "find-generic-password", "-s", DIENST, "-a", name, "-w"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if ergebnis.returncode != 0:
            return None
        return ergebnis.stdout.rstrip("\n")

    @property
    def backend_name(self) -> str:
        """Für Meldungen, z. B. „Schlüsselbund“, „Windows-Anmeldeinformationsverwaltung“."""
        if self.backend == "schluesselbund":
            return "Schlüsselbund"
        if self.backend == "keyring":
            return "Windows-Anmeldeinformationsverwaltung" if sys.platform == "win32" else "Schlüsselbund (Secret Service)"
        return "verschlüsselte Datei"

    # ---------- keyring (Windows/Linux) ----------
    def _kr(self):
        kr = _keyring_modul()
        if kr is None:
            raise GeheimnisFehler("Das Paket „keyring“ ist nicht installiert (pip install keyring).")
        return kr

    def _kr_setzen(self, name: str, wert: str) -> None:
        try:
            self._kr().set_password(DIENST, name, wert)
        except GeheimnisFehler:
            raise
        except Exception as e:  # noqa: BLE001 - Backend-Fehler (gesperrt, zu lang …) ohne Wert melden
            meldung = str(e).replace(wert, "…") if wert else str(e)
            raise GeheimnisFehler(f"Schlüsselbund-Fehler: {type(e).__name__}: {meldung}") from None

    def _kr_holen(self, name: str) -> str | None:
        try:
            return self._kr().get_password(DIENST, name)
        except GeheimnisFehler:
            raise
        except Exception:  # noqa: BLE001
            return None

    def _kr_loeschen(self, name: str) -> None:
        try:
            self._kr().delete_password(DIENST, name)
        except Exception:  # noqa: BLE001 - nicht vorhanden
            pass

    # ---------- verschlüsselte Datei ----------
    def _fernet(self) -> Fernet:
        if not self._schluessel_datei.exists():
            schluessel = Fernet.generate_key()
            fd = os.open(self._schluessel_datei, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINAER, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(schluessel)
        if _unix_rechte():  # Windows kennt keine Unix-Rechte; dort schützt das Benutzerprofil
            os.chmod(self._schluessel_datei, 0o600)
        return Fernet(self._schluessel_datei.read_bytes().strip())

    def _datei_lesen(self) -> dict[str, str]:
        if not self._enc_datei.exists():
            return {}
        try:
            roh = self._fernet().decrypt(self._enc_datei.read_bytes())
        except InvalidToken as e:
            raise GeheimnisFehler(
                "Geheimnisdatei kann nicht entschlüsselt werden (Schlüsseldatei passt nicht)."
            ) from e
        return json.loads(roh.decode("utf-8"))

    def _datei_schreiben(self, daten: dict[str, str]) -> None:
        token = self._fernet().encrypt(json.dumps(daten).encode("utf-8"))
        tmp = self._enc_datei.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _O_BINAER, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(token)
        tmp.replace(self._enc_datei)
