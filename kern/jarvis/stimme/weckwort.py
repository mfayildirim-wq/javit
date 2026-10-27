"""Weckwort-Erkennung: openWakeWord (vortrainiertes „hey_jarvis“ oder eigenes .onnx-Modell) und
Vosk (freies Weckwort wie „Javit“, siehe ``weckwort_vosk.py``). ``erzeuge_detektor()`` wählt die
Engine anhand von ``weckwort_engine`` („auto“ | „openwakeword“ | „vosk“).

openWakeWord 0.6:
* ``openwakeword.utils.download_models(model_names=[...], target_directory=...)`` lädt
  Merkmalsmodelle (melspectrogram, embedding), Silero-VAD und die Weckwort-Modelle
  (tflite + onnx) von den GitHub-Releases.
* ``openwakeword.model.Model(wakeword_models=[pfad], inference_framework="onnx",
  melspec_model_path=..., embedding_model_path=...)``
* ``Model.predict(frame)`` mit 1280 int16-Samples (80 ms @ 16 kHz) → ``{modellname: score}``.

Die Modelle landen in ``~/.jarvis/modelle/openwakeword`` (nicht im site-packages-Ordner,
der z. B. bei Homebrew-Python schreibgeschützt sein kann).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Protocol

import numpy as np

from .fehler import HINWEIS_PAKETE, StimmFehler, kurz

log = logging.getLogger("jarvis.stimme.weckwort")


class WeckwortDetektor(Protocol):
    def pruefen(self, rahmen: np.ndarray) -> float:
        """Score 0..1 für einen 1280-Sample-Rahmen."""

    def zuruecksetzen(self) -> None:
        """Interne Puffer leeren (z. B. nach eigener Sprachausgabe)."""


class OpenWakeWordDetektor:
    MERKMALS_MODELLE = ("melspectrogram.onnx", "embedding_model.onnx")

    def __init__(
        self,
        weckwort: str = "hey_jarvis",
        verzeichnis: str | os.PathLike | None = None,
        modell_pfad: str | os.PathLike | None = None,
    ):
        self.weckwort = (weckwort or "hey_jarvis").strip()
        self.verzeichnis = Path(verzeichnis or Path.home() / ".jarvis" / "modelle" / "openwakeword")
        self.modell_pfad = str(modell_pfad or "").strip()
        self._modell = None

    # -- Laden ---------------------------------------------------------------------------
    def _eigenes_modell(self) -> Path:
        """Pfad aus ``weckwort_modell_pfad``: absolut, mit ~ oder nur Dateiname im Modellordner."""
        pfad = Path(os.path.expanduser(self.modell_pfad))
        if not pfad.is_absolute() and not pfad.exists():
            pfad = self.verzeichnis / pfad
        if pfad.suffix.lower() not in (".onnx", ".tflite"):
            raise StimmFehler(f"Eigenes Weckwort-Modell muss eine .onnx-Datei sein: {pfad}")
        if not pfad.is_file():
            raise StimmFehler(
                f"Eigenes Weckwort-Modell nicht gefunden: {pfad}. Trainierte .onnx-Datei nach "
                f"{self.verzeichnis} kopieren (siehe scripts/weckwort-trainieren.md)."
            )
        return pfad

    def _modellpfad(self) -> Path | None:
        if self.modell_pfad:
            return self._eigenes_modell()
        eigener = Path(os.path.expanduser(self.weckwort))
        if eigener.suffix in (".onnx", ".tflite") and eigener.exists():
            return eigener  # eigenes, trainiertes Modell
        name = self.weckwort.replace(" ", "_").lower()
        if not self.verzeichnis.exists():
            return None
        kandidaten = sorted(p for p in self.verzeichnis.glob("*.onnx") if p.name.lower().startswith(name))
        return kandidaten[-1] if kandidaten else None

    def _merkmale_vorhanden(self) -> bool:
        return all((self.verzeichnis / m).exists() for m in self.MERKMALS_MODELLE)

    def laden(self) -> None:
        """Lädt (und lädt bei Bedarf herunter) das Modell. Blockierend – im Thread aufrufen."""
        try:
            import openwakeword  # noqa: PLC0415
            from openwakeword.model import Model  # noqa: PLC0415
            from openwakeword.utils import download_models  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001
            raise StimmFehler(f"openWakeWord ist nicht installiert ({kurz(exc)}). {HINWEIS_PAKETE}") from exc

        pfad = self._modellpfad()
        if self.modell_pfad and not self._merkmale_vorhanden():
            # eigenes Modell: nur die Merkmalsmodelle (melspectrogram/embedding) laden – ein Name,
            # der zu keinem offiziellen Modell passt, lädt keine fremden Weckwort-Modelle mit
            try:
                self.verzeichnis.mkdir(parents=True, exist_ok=True)
                download_models(model_names=["__nur_merkmale__"], target_directory=str(self.verzeichnis))
            except Exception as exc:  # noqa: BLE001
                raise StimmFehler(
                    "Merkmalsmodelle für openWakeWord konnten nicht heruntergeladen werden "
                    f"({kurz(exc)}). Beim ersten Start ist eine Internetverbindung nötig (github.com)."
                ) from exc
        if pfad is None or not self._merkmale_vorhanden():
            name = self.weckwort.replace(" ", "_").lower()
            bekannte = getattr(openwakeword, "MODELS", {}) or {}
            if pfad is None and bekannte and not any(name in k for k in bekannte):
                raise StimmFehler(
                    f"Unbekanntes Weckwort „{self.weckwort}“. Verfügbar: {', '.join(sorted(bekannte))} "
                    "– oder Pfad zu einem eigenen .onnx-Modell angeben."
                )
            try:
                self.verzeichnis.mkdir(parents=True, exist_ok=True)
                log.info("Lade Weckwort-Modell „%s“ herunter nach %s …", name, self.verzeichnis)
                download_models(model_names=[name], target_directory=str(self.verzeichnis))
            except Exception as exc:  # noqa: BLE001
                raise StimmFehler(
                    "Weckwort-Modell konnte nicht heruntergeladen werden "
                    f"({kurz(exc)}). Beim ersten Start ist eine Internetverbindung nötig (github.com)."
                ) from exc
            pfad = self._modellpfad()
            if pfad is None:
                raise StimmFehler(f"Weckwort-Modell „{self.weckwort}“ wurde nach dem Download nicht gefunden.")
        try:
            self._modell = Model(
                wakeword_models=[str(pfad)],
                inference_framework="onnx",
                melspec_model_path=str(self.verzeichnis / "melspectrogram.onnx"),
                embedding_model_path=str(self.verzeichnis / "embedding_model.onnx"),
            )
        except Exception as exc:  # noqa: BLE001
            raise StimmFehler(f"Weckwort-Modell konnte nicht geladen werden ({kurz(exc)}).") from exc
        log.info("Weckwort-Modell geladen: %s", pfad.name)
        if self.modell_pfad:
            self.weckwort = pfad.stem

    # -- Erkennung -----------------------------------------------------------------------
    def pruefen(self, rahmen: np.ndarray) -> float:
        if self._modell is None:
            self.laden()
        ergebnis = self._modell.predict(np.asarray(rahmen, dtype=np.int16))
        return float(max(ergebnis.values())) if ergebnis else 0.0

    def zuruecksetzen(self) -> None:
        if self._modell is not None:
            try:
                self._modell.reset()
            except Exception:  # noqa: BLE001
                log.debug("reset() fehlgeschlagen", exc_info=True)


# ---------------------------------------------------------------------------------------
# Auswahl der Engine
# ---------------------------------------------------------------------------------------
def detektor_schluessel(e) -> tuple:
    """Alles, was einen neuen Detektor erfordert (Vergleich beim Neustart der Stimme)."""
    from ..konfig import weckwort_engine  # noqa: PLC0415

    return (
        weckwort_engine(e),
        e.weckwort,
        tuple(e.weckwort_varianten or ()),
        e.weckwort_modell_pfad,
        e.vosk_modell,
        e.modell_verzeichnis,
    )


def erzeuge_detektor(e):
    """Detektor passend zu den Stimm-Einstellungen ``e`` (``StimmEinstellungen``).

    * openwakeword: „hey_jarvis“ (Download beim ersten Gebrauch) oder ``weckwort_modell_pfad``
    * vosk: freies Weckwort (Standard „javit“), Modell ``vosk_modell`` unter ``modelle/vosk``
    """
    from ..konfig import weckwort_engine  # noqa: PLC0415

    engine = weckwort_engine(e)
    if engine == "openwakeword":
        weckwort = e.weckwort.split(",")[0].strip()
        detektor = OpenWakeWordDetektor(
            weckwort, Path(e.modell_verzeichnis) / "openwakeword", modell_pfad=e.weckwort_modell_pfad or None
        )
    else:
        from .weckwort_vosk import VoskWeckwortDetektor  # noqa: PLC0415

        detektor = VoskWeckwortDetektor(
            e.weckwort,
            varianten=e.weckwort_varianten,
            verzeichnis=Path(e.modell_verzeichnis) / "vosk",
            modell=e.vosk_modell,
            schwelle=e.schwelle,
            sha256=e.vosk_modell_sha256,
        )
    detektor.engine = engine
    detektor.schluessel = detektor_schluessel(e)
    return detektor
