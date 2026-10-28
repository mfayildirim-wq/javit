"""Mikrofon mit Echounterdrückung unter macOS.

Apples Sprachverarbeitung (Voice Processing, AVAudioEngine) rechnet das Echo der eigenen Sprachausgabe
aus dem Mikrofonsignal heraus. Ohne sie bildet die kleine Vosk-Grammatik die eigene Stimme ständig auf
„stopp“/„halt“ ab und das Stoppwort löst sich selbst aus. Der Helfer ``javit-mikrofon`` (Quelle
``mac_mikrofon.swift``) läuft als Unterprozess und liefert PCM (int16, mono, 16 kHz) über stdout.

``helfer_sicherstellen()`` baut ihn bei Bedarf mit ``xcrun swiftc`` (Xcode Command Line Tools); ohne
Compiler oder bei Fehlern bleibt es beim normalen Mikrofon (``MikrofonQuelle``).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

import numpy as np

from ..konfig import jarvis_home
from .audio import Rahmenbildner
from .fehler import StimmFehler, kurz

log = logging.getLogger("jarvis.stimme.aec")

QUELLE = Path(__file__).with_name("mac_mikrofon.swift")
HELFER_NAME = "javit-mikrofon"


def helfer_pfad() -> Path:
    return jarvis_home() / "bin" / HELFER_NAME


def swiftc_vorhanden() -> bool:
    if shutil.which("swiftc"):
        return True
    if shutil.which("xcrun"):
        try:
            return subprocess.run(["xcrun", "--find", "swiftc"], capture_output=True, timeout=20).returncode == 0
        except Exception:  # noqa: BLE001
            return False
    return False


def helfer_sicherstellen(bauen: bool = True) -> Path | None:
    """Pfad des Helfers; baut ihn, wenn er fehlt oder älter als die Quelle ist. None = nicht verfügbar."""
    pfad = helfer_pfad()
    try:
        aktuell = pfad.exists() and pfad.stat().st_mtime >= QUELLE.stat().st_mtime
    except OSError:
        aktuell = False
    if aktuell:
        return pfad
    if not bauen or os.environ.get("JARVIS_KEIN_DOWNLOAD") or not QUELLE.exists() or not swiftc_vorhanden():
        return pfad if pfad.exists() else None
    pfad.parent.mkdir(parents=True, exist_ok=True)
    befehl = ["swiftc"] if shutil.which("swiftc") else ["xcrun", "swiftc"]
    try:
        ergebnis = subprocess.run(
            [*befehl, "-O", "-o", str(pfad), str(QUELLE)], capture_output=True, text=True, timeout=300
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Mikrofon-Helfer konnte nicht gebaut werden: %s", kurz(exc))
        return pfad if pfad.exists() else None
    if ergebnis.returncode != 0:
        log.warning("Mikrofon-Helfer: swiftc meldet %s", (ergebnis.stderr or ergebnis.stdout)[-400:])
        return pfad if pfad.exists() else None
    log.info("Mikrofon-Helfer gebaut: %s", pfad)
    return pfad


_bau_gestartet = False


def helfer_im_hintergrund_bauen() -> None:
    """Baut den Helfer einmalig in einem Thread (erster Start ohne Installer); nicht in Tests/Containern."""
    global _bau_gestartet
    if _bau_gestartet or os.environ.get("JARVIS_KEIN_DOWNLOAD") or not swiftc_vorhanden():
        return
    _bau_gestartet = True
    threading.Thread(target=helfer_sicherstellen, name="jarvis-mikrofon-bauen", daemon=True).start()


class MikrofonAEC:
    """Audioquelle über den Helfer (Echounterdrückung). Schnittstelle wie ``MikrofonQuelle``."""

    #: für den Dienst: Weckwort/Stoppwort dürfen auch mitten in der eigenen Ausgabe geprüft werden
    echo_unterdrueckung = True

    def __init__(self, pfad: str | os.PathLike | None = None, starter: Callable[..., Any] | None = None):
        self._pfad = Path(pfad) if pfad else None
        self._starter = starter or subprocess.Popen
        self._proc: Any = None
        self._thread: threading.Thread | None = None
        self.rate = 16000

    def starten(self, rueckruf: Callable[[np.ndarray], None]) -> None:
        pfad = self._pfad or helfer_sicherstellen()
        if pfad is None or not Path(pfad).exists():
            raise StimmFehler("Mikrofon-Helfer (Echounterdrückung) nicht verfügbar.")
        try:
            self._proc = self._starter(
                [str(pfad)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0
            )
        except Exception as exc:  # noqa: BLE001
            raise StimmFehler(f"Mikrofon-Helfer ließ sich nicht starten: {kurz(exc)}") from exc
        bildner = Rahmenbildner(rueckruf, eingangsrate=16000)
        proc = self._proc

        def lesen() -> None:
            rest = b""
            try:
                while True:
                    block = proc.stdout.read(2560)
                    if not block:
                        break
                    daten = rest + block
                    n = len(daten) - len(daten) % 2
                    daten, rest = daten[:n], daten[n:]
                    if daten:
                        bildner.hinzufuegen(np.frombuffer(daten, dtype="<i2"))
            except Exception:  # noqa: BLE001 – Lesethread darf nie sterben
                log.debug("Mikrofon-Helfer: Lesefehler", exc_info=True)
            if proc.poll() not in (None, 0):
                try:
                    fehler = proc.stderr.read().decode("utf-8", "replace").strip()
                except Exception:  # noqa: BLE001
                    fehler = ""
                log.warning("Mikrofon-Helfer beendet (Code %s): %s", proc.returncode, fehler[-300:])

        self._thread = threading.Thread(target=lesen, name="jarvis-mikrofon-aec", daemon=True)
        self._thread.start()
        log.info("Mikrofon mit Echounterdrückung geöffnet (%s)", pfad)

    def stoppen(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.write(b"ende\n")
                proc.stdin.flush()
                proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:  # noqa: BLE001
                proc.kill()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
