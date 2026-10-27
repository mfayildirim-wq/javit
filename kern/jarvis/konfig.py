"""Einstellungen des Assistenten (~/.jarvis/einstellungen.json, per Env JARVIS_HOME überschreibbar)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

STANDARD_MODELL = "ollama/qwen2.5:7b"

STANDARD_NAME = "Javit"
NAME_MAX_LAENGE = 40
#: Platzhalter in der Persona, der beim Systemprompt durch den eingestellten Namen ersetzt wird
NAME_PLATZHALTER = "{name}"

STANDARD_PERSONA = (
    "Du bist {name}, der persönliche KI-Assistent deines Nutzers auf seinem Mac. "
    "Du bist höflich, souverän, knapp und präzise, mit einem Hauch trockenem britischem Humor. "
    "Du antwortest auf Deutsch, außer der Nutzer spricht dich in einer anderen Sprache an. "
    "Du erledigst Aufgaben aktiv mit deinen Werkzeugen, statt nur zu erklären, wie es ginge."
)

#: Frühere Standard-Personas (bis 0.1.0 fest „Jarvis“) – werden beim Laden durch den neuen
#: Standard ersetzt; vom Nutzer selbst geschriebene Personas bleiben unverändert.
ALTE_STANDARD_PERSONAS = tuple(
    STANDARD_PERSONA.replace(NAME_PLATZHALTER, "Jarvis").replace("auf seinem Mac", ort)
    for ort in ("auf seinem Mac", "auf seinem Computer")
)

_ALTE_PERSONAS_NORMALISIERT = frozenset(" ".join(p.split()) for p in ALTE_STANDARD_PERSONAS)

#: Früheres Standard-Weckwort (openWakeWord „Hey Jarvis“)
ALTES_STANDARD_WECKWORT = "hey_jarvis"
STANDARD_WECKWORT = "javit"


#: Weckwörter, für die openWakeWord ein fertiges Modell mitbringt (Engine „auto“ → openwakeword)
OPENWAKEWORD_EINGEBAUT = ("hey_jarvis", "alexa", "hey_mycroft", "hey_rhasspy")


def weckwoerter(text: Any) -> list[str]:
    """„javit, hey javit“ → ["javit", "hey javit"] (Komma/Semikolon trennen)."""
    teile = str(text or "").replace(";", ",").split(",")
    return [" ".join(t.split()) for t in teile if t.strip()]


def weckwort_engine(stimme: Any) -> str:
    """Löst ``weckwort_engine`` auf: "openwakeword" oder "vosk".

    "auto": eigenes .onnx-Modell oder ein eingebautes openWakeWord-Wort („hey_jarvis“/„hey jarvis“,
    bisheriges Verhalten) → openwakeword, jedes andere (freie) Wort → vosk.
    """
    def wert(name: str, standard: Any = "") -> Any:
        if isinstance(stimme, dict):
            return stimme.get(name, standard)
        return getattr(stimme, name, standard)

    engine = str(wert("weckwort_engine", "auto") or "auto").strip().lower()
    if engine in ("openwakeword", "vosk"):
        return engine
    if str(wert("weckwort_modell_pfad", "") or "").strip():
        return "openwakeword"
    woerter = weckwoerter(wert("weckwort", STANDARD_WECKWORT)) or [STANDARD_WECKWORT]
    erstes = woerter[0].lower()
    if erstes.endswith((".onnx", ".tflite")):
        return "openwakeword"
    if erstes.replace(" ", "_") in OPENWAKEWORD_EINGEBAUT:
        return "openwakeword"
    return "vosk"


def standard_persona() -> str:
    """Standard-Persona (mit Platzhalter ``{name}``); auf Windows/Linux ohne Bezug auf den Mac."""
    from .plattform import aktuelle_plattform

    if aktuelle_plattform() == "mac":
        return STANDARD_PERSONA
    return STANDARD_PERSONA.replace("auf seinem Mac", "auf seinem Computer")


def name_bereinigen(name: Any) -> str:
    """Leerzeichen/Steuerzeichen entfernen, Länge begrenzen; leer → Standardname."""
    text = " ".join(str(name or "").split())
    text = "".join(z for z in text if z.isprintable())[:NAME_MAX_LAENGE].strip()
    return text or STANDARD_NAME


def persona_mit_name(persona: str, name: str) -> str:
    """Setzt den Namen in die Persona ein (nur der Platzhalter ``{name}`` wird ersetzt)."""
    return (persona or "").replace(NAME_PLATZHALTER, name_bereinigen(name))


_aktueller_name = STANDARD_NAME


def aktueller_name() -> str:
    """Name des Assistenten aus den zuletzt geladenen/gespeicherten Einstellungen (für Stellen
    ohne Zugriff auf die Anwendung, z. B. Fehlertexte des Sprachmoduls oder Mitteilungstitel)."""
    return _aktueller_name


def _name_merken(name: str) -> None:
    global _aktueller_name
    _aktueller_name = name_bereinigen(name)


def jarvis_home() -> Path:
    """Datenverzeichnis (Standard ~/.jarvis – unter Windows %USERPROFILE%\\.jarvis –, per JARVIS_HOME überschreibbar)."""
    pfad = Path(os.environ.get("JARVIS_HOME") or "~/.jarvis").expanduser()
    pfad.mkdir(parents=True, exist_ok=True)
    return pfad


class StimmEinstellungen(BaseModel):
    """Einstellungen des Sprachmoduls (das Sprachmodul darf eigene Felder ergänzen)."""

    model_config = ConfigDict(extra="allow")

    aktiv: bool = False
    #: Weckwort(e), mehrere durch Komma getrennt, z. B. "javit, hey javit"
    weckwort: str = STANDARD_WECKWORT
    #: "auto" (hey_jarvis → openwakeword, sonst vosk) | "openwakeword" | "vosk"
    weckwort_engine: Literal["auto", "openwakeword", "vosk"] = "auto"
    #: zusätzliche Schreibweisen für Vosk (leer = sinnvolle Standards je Weckwort)
    weckwort_varianten: list[str] = Field(default_factory=list)
    #: eigenes openWakeWord-Modell (.onnx), z. B. ~/.jarvis/modelle/openwakeword/javit.onnx
    weckwort_modell_pfad: str = ""

    @field_validator("weckwort", mode="before")
    @classmethod
    def _weckwort_text(cls, wert: Any) -> str:
        text = str(wert or "").strip()
        return text or STANDARD_WECKWORT

    @field_validator("weckwort_engine", mode="before")
    @classmethod
    def _engine_klein(cls, wert: Any) -> str:
        text = str(wert or "auto").strip().lower().replace("-", "").replace(" ", "")
        return {"oww": "openwakeword", "": "auto"}.get(text, text)

    @field_validator("weckwort_varianten", mode="before")
    @classmethod
    def _varianten_liste(cls, wert: Any) -> list[str]:
        if wert is None:
            return []
        if isinstance(wert, str):
            wert = wert.replace(";", ",").split(",")
        return [" ".join(str(v).split()) for v in wert if str(v).strip()]

    @field_validator("weckwort_modell_pfad", mode="before")
    @classmethod
    def _pfad_text(cls, wert: Any) -> str:
        return str(wert or "").strip()


class Einstellungen(BaseModel):
    model_config = ConfigDict(extra="ignore")

    #: Name des Assistenten (Persona, Oberfläche, Ansagen) – interne Bezeichner bleiben „jarvis“
    name: str = STANDARD_NAME
    modell: str = STANDARD_MODELL
    einbettungs_modell: str | None = "ollama/nomic-embed-text"
    sprache: str = "de"
    ort: str | None = None
    zeitzone: str | None = None
    persona: str = Field(default_factory=standard_persona)
    anrede: str = "Sir"
    anrede_verwenden: bool = True
    temperatur: float = 0.4
    werkzeug_modus: Literal["auto", "nativ", "prompt"] = "auto"
    max_werkzeugrunden: int = 12
    freigabe_timeout: float = 120.0
    werkzeug_timeout: float = 300.0
    llm_timeout: float = 180.0
    ollama_url: str = "http://localhost:11434"
    # Eigene Endpunkte für OpenAI-kompatible Server (LM Studio, vLLM, Proxy …):
    # Schlüssel = vollständige Modell-ID (z. B. "openai/mein-modell"), Wert = api_base.
    # Bewusst je Modell und nicht global, damit API-Schlüssel anderer Anbieter nie dorthin gehen.
    api_basen: dict[str, str] = Field(default_factory=dict)
    port: int = 8765
    verlauf_kontext: int = 10
    stimme: StimmEinstellungen = Field(default_factory=StimmEinstellungen)

    @model_validator(mode="before")
    @classmethod
    def _alte_daten_uebernehmen(cls, daten: Any) -> Any:
        """Rückwärtskompatibilität mit einstellungen.json aus Versionen ohne ``name``.

        * Alte Standard-Persona („Du bist Jarvis …“) → neuer Standard mit ``{name}``; eine eigene
          Persona des Nutzers bleibt unverändert.
        * Fehlt ``name`` (Datei vor der Umbenennung) und steht noch das alte Standard-Weckwort
          „hey_jarvis“ darin, gilt das neue Standard-Weckwort „javit“. Wer danach bewusst
          „hey_jarvis“ wählt, behält es (die Datei enthält dann ``name``).
        """
        if not isinstance(daten, dict):
            return daten
        daten = dict(daten)
        persona = daten.get("persona")
        if isinstance(persona, str) and " ".join(persona.split()) in _ALTE_PERSONAS_NORMALISIERT:
            daten["persona"] = standard_persona()
        if "name" not in daten:
            stimme = daten.get("stimme")
            if (
                isinstance(stimme, dict)
                and str(stimme.get("weckwort", "")).strip().lower() == ALTES_STANDARD_WECKWORT
                # nur den alten Standard ersetzen – nicht, wenn openWakeWord bzw. ein eigenes
                # Modell ausdrücklich gewählt ist (dann bliebe „javit“ ohne passendes Modell)
                and str(stimme.get("weckwort_engine") or "auto").strip().lower() == "auto"
                and not str(stimme.get("weckwort_modell_pfad") or "").strip()
            ):
                daten["stimme"] = {**stimme, "weckwort": STANDARD_WECKWORT}
        return daten

    @field_validator("name", mode="before")
    @classmethod
    def _name_pruefen(cls, wert: Any) -> str:
        return name_bereinigen(wert)

    @field_validator("persona", mode="before")
    @classmethod
    def _persona_leer(cls, wert: Any) -> str:
        return str(wert).strip() if wert and str(wert).strip() else standard_persona()

    def persona_text(self) -> str:
        """Persona mit eingesetztem Namen (für den Systemprompt)."""
        return persona_mit_name(self.persona, self.name)


def _pfad() -> Path:
    return jarvis_home() / "einstellungen.json"


def _tief_mischen(basis: dict[str, Any], teil: dict[str, Any]) -> dict[str, Any]:
    ergebnis = dict(basis)
    for schluessel, wert in teil.items():
        if isinstance(wert, dict) and isinstance(ergebnis.get(schluessel), dict):
            ergebnis[schluessel] = _tief_mischen(ergebnis[schluessel], wert)
        else:
            ergebnis[schluessel] = wert
    return ergebnis


class KonfigSpeicher:
    """Lädt und speichert Einstellungen; hält die aktuelle Instanz."""

    def __init__(self, pfad: Path | None = None):
        self.pfad = pfad or _pfad()
        self._sperre = threading.Lock()
        self.einstellungen = self.laden()

    def laden(self) -> Einstellungen:
        if self.pfad.exists():
            try:
                daten = json.loads(self.pfad.read_text(encoding="utf-8"))
                einstellungen = Einstellungen.model_validate(daten)
                _name_merken(einstellungen.name)
                return einstellungen
            except (json.JSONDecodeError, ValueError):
                sicherung = self.pfad.with_suffix(".defekt.json")
                self.pfad.replace(sicherung)
        einstellungen = Einstellungen()
        _name_merken(einstellungen.name)
        return einstellungen

    def speichern(self) -> None:
        with self._sperre:
            self.pfad.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.pfad.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self.einstellungen.model_dump(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(self.pfad)

    def aktualisieren(self, teil: dict[str, Any]) -> Einstellungen:
        """Teilupdate (tief gemischt, validiert, gespeichert)."""
        neu = _tief_mischen(self.einstellungen.model_dump(), teil)
        validiert = Einstellungen.model_validate(neu)
        # Instanz in-place aktualisieren, damit alle Referenzen den neuen Stand sehen
        for feld in Einstellungen.model_fields:
            setattr(self.einstellungen, feld, getattr(validiert, feld))
        _name_merken(self.einstellungen.name)
        self.speichern()
        return self.einstellungen
