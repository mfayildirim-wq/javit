"""Einstellungen des Sprachmoduls (Schlüssel ``stimme`` in ~/.jarvis/einstellungen.json).

Die Einstellungen werden bei jedem Zugriff frisch aus der Quelle gelesen, damit Änderungen
über ``PUT /api/einstellungen`` ohne Neustart greifen (soweit technisch möglich – ein neues
Weckwort oder ein anderes Mikrofon wird erst nach ``stop()``/``start()`` wirksam).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

STANDARD_MODELL_VERZEICHNIS = str(Path.home() / ".jarvis" / "modelle")
STANDARD_VOSK_MODELL = "vosk-model-small-de-0.15"


@dataclass
class StimmEinstellungen:
    aktiv: bool = False
    weckwort: str = "javit"  # mehrere durch Komma, z. B. "javit, hey javit"
    # "auto" (hey_jarvis/eigenes .onnx → openwakeword, sonst vosk) | "openwakeword" | "vosk"
    weckwort_engine: str = "auto"
    weckwort_varianten: list = field(default_factory=list)  # Schreibvarianten für Vosk (leer = Standards)
    weckwort_modell_pfad: str = ""  # eigenes openWakeWord-Modell (.onnx)
    vosk_modell: str = STANDARD_VOSK_MODELL  # Name (Download von alphacephei.com) oder Pfad zu einem Modellordner
    vosk_modell_sha256: str = ""  # optional: erwartete SHA-256-Prüfsumme des Modell-ZIPs
    schwelle: float = 0.5  # openWakeWord: Score; Vosk: Ähnlichkeit (siehe weckwort_vosk.py)
    # Spracherkennung
    # "auto" (openrouter mit OPENROUTER_API_KEY, sonst lokal) | "lokal" (faster-whisper) | "openrouter" | "cloud" (LiteLLM)
    stt: str = "auto"
    stt_modell: str = "small"  # faster-whisper-Modell (tiny/base/small/medium/large-v3 …)
    stt_cloud_modell: str = "whisper-1"  # z. B. "whisper-1", "groq/whisper-large-v3"
    stt_openrouter_modell: str = "openai/whisper-large-v3"  # OpenRouter /audio/transcriptions
    sprache: str = "de"
    # Sprachausgabe
    # "auto" (openrouter mit OPENROUTER_API_KEY; sonst Mac: say, Windows: sapi, Linux: piper → espeak-ng)
    # | "openrouter" (PCM-Strom) | "say" | "sapi" | "piper" | "espeak" | "cloud" (LiteLLM) | "aus"
    tts: str = "auto"
    tts_stimme: str = ""  # leer = automatisch (say/sapi: beste deutsche Stimme, piper: de_DE-thorsten-medium, cloud: "onyx", openrouter: je Modell)
    tts_cloud_modell: str = "openai/tts-1"
    tts_openrouter_modell: str = "elevenlabs/eleven-flash-v2.5"  # OpenRouter /audio/speech (ElevenLabs, Microsoft MAI, Google …)
    tts_tempo: int = 0  # Wörter/Minute (say, espeak; SAPI/Piper umgerechnet; 0 = Standard)
    # Ablauf
    bestaetigungston: bool = True
    ton_datei: str = "/System/Library/Sounds/Tink.aiff"  # fehlt die Datei (Windows/Linux): erzeugter Ton
    stille_ms: int = 900
    max_aufnahme_s: float = 20.0
    warte_auf_sprache_s: float = 5.0  # nach dem Weckwort: so lange auf Sprachbeginn warten
    folgemodus_s: float = 5.0  # nach einer Antwort ohne Weckwort weiter zuhören (0 = aus)
    unterbrechen: bool = False  # „Barge-in“: Weckwort während des Sprechens stoppt die Ausgabe
    stoppwort: str = "stopp"  # Stoppwörter (Komma-getrennt) beenden die Ausgabe sofort; leer = aus
    geraet: Any = None  # sounddevice-Eingabegerät (Name oder Index), None = Standard
    vad: str = "auto"  # "auto" (webrtcvad falls installiert) | "webrtc" | "energie"
    modell_verzeichnis: str = STANDARD_MODELL_VERZEICHNIS
    extra: dict = field(default_factory=dict)

    @classmethod
    def aus(cls, quelle: Any) -> "StimmEinstellungen":
        """Erzeugt Einstellungen aus dict / Objekt mit Attribut ``stimme`` / bereits fertigen Einstellungen."""
        roh = _stimm_teil(quelle)
        bekannt = {f.name for f in fields(cls)}
        werte: dict[str, Any] = {}
        extra: dict[str, Any] = {}
        for k, v in roh.items():
            if k in bekannt and k != "extra":
                if v is None and k != "geraet":
                    continue  # None = Standard verwenden
                werte[k] = v
            else:
                extra[k] = v
        e = cls(**werte)
        e.extra = extra
        e._normalisieren()
        return e

    def _normalisieren(self) -> None:
        self.weckwort = str(self.weckwort or "").strip() or "javit"
        self.weckwort_engine = str(self.weckwort_engine or "auto").strip().lower()
        if self.weckwort_engine not in ("auto", "openwakeword", "vosk"):
            self.weckwort_engine = "auto"
        varianten = self.weckwort_varianten
        if isinstance(varianten, str):
            varianten = varianten.replace(";", ",").split(",")
        self.weckwort_varianten = [" ".join(str(v).split()) for v in (varianten or []) if str(v).strip()]
        self.weckwort_modell_pfad = str(self.weckwort_modell_pfad or "").strip()
        self.vosk_modell = str(self.vosk_modell or STANDARD_VOSK_MODELL).strip()
        self.vosk_modell_sha256 = str(self.vosk_modell_sha256 or "").strip().lower()
        self.stt = str(self.stt or "auto").lower()
        stoppwort = self.stoppwort
        if isinstance(stoppwort, (list, tuple)):
            stoppwort = ", ".join(str(w) for w in stoppwort)
        self.stoppwort = ", ".join(w.strip() for w in str(stoppwort or "").replace(";", ",").split(",") if w.strip())
        self.tts = "aus" if self.tts is False else str(self.tts or "auto").lower()
        if self.tts in ("false", "none", "keine", "off"):
            self.tts = "aus"
        try:
            self.schwelle = min(max(float(self.schwelle), 0.05), 0.99)
        except (TypeError, ValueError):
            self.schwelle = 0.5
        for name, standard, minimum in (
            ("stille_ms", 900, 200),
            ("max_aufnahme_s", 20.0, 2.0),
            ("warte_auf_sprache_s", 5.0, 1.0),
            ("folgemodus_s", 5.0, 0.0),
        ):
            try:
                wert = float(getattr(self, name))
            except (TypeError, ValueError):
                wert = standard
            setattr(self, name, max(wert, minimum))
        self.stille_ms = int(self.stille_ms)
        self.sprache = (self.sprache or "de").split("-")[0].split("_")[0].lower()
        self.modell_verzeichnis = str(Path(self.modell_verzeichnis or STANDARD_MODELL_VERZEICHNIS).expanduser())


def _als_dict(obj: Any) -> dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return dict(obj)
    if hasattr(obj, "model_dump"):  # pydantic v2
        return dict(obj.model_dump())
    if hasattr(obj, "dict") and callable(obj.dict):  # pydantic v1
        try:
            return dict(obj.dict())
        except TypeError:
            pass
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    return {}


def _stimm_teil(quelle: Any) -> dict:
    if isinstance(quelle, StimmEinstellungen):
        d = dataclasses.asdict(quelle)
        d.update(d.pop("extra", {}) or {})
        return d
    if isinstance(quelle, dict):
        if "stimme" in quelle and not isinstance(quelle["stimme"], (str, bool)):
            return _als_dict(quelle["stimme"])
        return dict(quelle)
    if quelle is not None and hasattr(quelle, "stimme"):
        return _als_dict(quelle.stimme)
    return _als_dict(quelle)
