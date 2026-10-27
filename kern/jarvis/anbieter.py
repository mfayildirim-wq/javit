"""Anbieter-Register: welche Modellanbieter es gibt, wie sie angesprochen werden und woher ihre
Modelllisten kommen.

* Eingebaute Anbieter (Ollama, Anthropic, OpenAI, Gemini, OpenRouter, DeepSeek, Kimi/Moonshot,
  GLM/Z.AI, OpenCode, Groq, Mistral, xAI) und eigene OpenAI-kompatible Anbieter aus den Einstellungen.
* Modell-IDs bleiben ``<anbieter>/<modell>`` (LiteLLM-Schreibweise). Anbieter ohne LiteLLM-Präfix
  (OpenCode, eigene) werden beim Aufruf nach ``openai/<modell>`` plus ``api_base``/``api_key`` übersetzt.
* Live-Modelllisten werden mit kurzem Zeitlimit abgefragt und zehn Minuten gecacht; schlägt das fehl,
  gelten die festen Vorschläge.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

ANBIETER_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}$")
CACHE_SEKUNDEN = 600.0
ZEITLIMIT = 8.0

# Modelle, die keine Chatmodelle sind (Einbettungen, Sprache, Bilder, Moderation)
_KEIN_CHATMODELL = ("embed", "tts", "whisper", "dall-e", "image", "moderation", "transcribe", "realtime", "audio")


@dataclass(frozen=True)
class Anbieter:
    id: str
    name: str
    #: LiteLLM-Präfix; None = OpenAI-kompatibel über api_base (OpenCode, eigene Anbieter)
    praefix: str | None
    schluessel: str | None
    api_base: str | None = None
    modelle_url: str | None = None
    #: (Modell ohne Präfix, Anzeigename)
    vorschlaege: tuple[tuple[str, str], ...] = ()
    eigen: bool = False
    lokal: bool = False

    def modell_id(self, modell: str) -> str:
        return f"{self.id}/{modell}"

    def verfuegbar(self) -> bool:
        """Schlüssel vorhanden (bzw. keiner nötig). Ollama wird vom Aufrufer live geprüft."""
        return not self.schluessel or bool(os.environ.get(self.schluessel))

    def als_info(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "schluessel": self.schluessel,
            "verfuegbar": self.verfuegbar(),
            "lokal": self.lokal,
            "eigen": self.eigen,
        }


@dataclass
class ModellEintrag:
    id: str
    name: str
    kostenlos: bool | None = None
    werkzeuge: bool | None = None
    live: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


# Modell-IDs: Stand Oktober 2026, geprüft über die Modelllisten bzw. Doku der Anbieter.
EINGEBAUTE: tuple[Anbieter, ...] = (
    Anbieter(
        "ollama", "Ollama (lokal)", "ollama", None, lokal=True,
        vorschlaege=(
            ("qwen2.5:7b", "Qwen 2.5 7B"),
            ("qwen3:8b", "Qwen 3 8B"),
            ("llama3.1:8b", "Llama 3.1 8B"),
            ("llama3.2:3b", "Llama 3.2 3B (klein, schnell)"),
        ),
    ),
    Anbieter(
        "anthropic", "Anthropic", "anthropic", "ANTHROPIC_API_KEY",
        modelle_url="https://api.anthropic.com/v1/models",
        vorschlaege=(
            ("claude-sonnet-5-5", "Claude Sonnet 5.5"),
            ("claude-opus-5-5", "Claude Opus 5.5"),
            ("claude-haiku-5-5", "Claude Haiku 5.5"),
            ("claude-fable-5-1", "Claude Fable 5.1"),
        ),
    ),
    Anbieter(
        "openai", "OpenAI", "openai", "OPENAI_API_KEY",
        modelle_url="https://api.openai.com/v1/models",
        vorschlaege=(
            ("gpt-6.1-sol", "GPT-6.1 Sol"),
            ("gpt-6-luna", "GPT-6 Luna"),
            ("gpt-5.4-mini", "GPT-5.4 mini"),
        ),
    ),
    Anbieter(
        "gemini", "Google Gemini", "gemini", "GEMINI_API_KEY",
        modelle_url="https://generativelanguage.googleapis.com/v1beta/models",
        vorschlaege=(
            ("gemini-4-argon", "Gemini 4 Argon"),
            ("gemini-3.8-flash", "Gemini 3.8 Flash"),
            ("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite"),
        ),
    ),
    Anbieter(
        "openrouter", "OpenRouter", "openrouter", "OPENROUTER_API_KEY",
        modelle_url="https://openrouter.ai/api/v1/models",
        vorschlaege=(
            ("deepseek/deepseek-v4.1-flash", "DeepSeek V4.1 Flash"),
            ("moonshotai/kimi-k3", "Kimi K3"),
            ("z-ai/glm-5.3-flash", "GLM 5.3 Flash"),
            ("anthropic/claude-sonnet-5.5", "Claude Sonnet 5.5"),
            ("openai/gpt-5.6-sol", "GPT-5.6 Sol"),
        ),
    ),
    Anbieter(
        "deepseek", "DeepSeek", "deepseek", "DEEPSEEK_API_KEY",
        modelle_url="https://api.deepseek.com/models",
        vorschlaege=(("deepseek-flash", "DeepSeek V4.1 Flash"), ("deepseek-v4-pro", "DeepSeek V4 Pro")),
    ),
    Anbieter(
        "moonshot", "Kimi (Moonshot)", "moonshot", "MOONSHOT_API_KEY",
        modelle_url="https://api.moonshot.ai/v1/models",
        vorschlaege=(("kimi-k3", "Kimi K3"), ("kimi-k2.6", "Kimi K2.6")),
    ),
    Anbieter(
        "zai", "GLM (Z.AI)", "zai", "ZAI_API_KEY",
        modelle_url="https://api.z.ai/api/paas/v4/models",
        vorschlaege=(("glm-5.3", "GLM 5.3"), ("glm-5.3-flash", "GLM 5.3 Flash")),
    ),
    Anbieter(
        "opencode", "OpenCode (bezahlte Modelle)", None, "OPENCODE_API_KEY",
        api_base="https://opencode.ai/inference/openai/v1",
        modelle_url="https://opencode.ai/inference/v1/models",
        vorschlaege=(
            ("kimi-k2.5", "Kimi K2.5"),
            ("glm-5.3-flash", "GLM 5.3 Flash"),
            ("deepseek-v4.1-flash", "DeepSeek V4.1 Flash"),
            ("qwen3.8-max", "Qwen 3.8 Max"),
        ),
    ),
    Anbieter(
        "groq", "Groq", "groq", "GROQ_API_KEY",
        modelle_url="https://api.groq.com/openai/v1/models",
        vorschlaege=(("llama-3.3-70b-versatile", "Llama 3.3 70B"), ("openai/gpt-oss-120b", "GPT-OSS 120B")),
    ),
    Anbieter(
        "mistral", "Mistral", "mistral", "MISTRAL_API_KEY",
        modelle_url="https://api.mistral.ai/v1/models",
        vorschlaege=(("mistral-large-latest", "Mistral Large"), ("mistral-small-latest", "Mistral Small")),
    ),
    Anbieter(
        "xai", "xAI (Grok)", "xai", "XAI_API_KEY",
        modelle_url="https://api.x.ai/v1/models",
        vorschlaege=(("grok-4.7", "Grok 4.7"), ("grok-4.5", "Grok 4.5")),
    ),
)

EINGEBAUTE_IDS = frozenset(a.id for a in EINGEBAUTE)


def eigener_anbieter(daten: dict[str, Any]) -> Anbieter:
    """Baut einen eigenen OpenAI-kompatiblen Anbieter aus einem Eintrag in ``anbieter_eigene``.

    Wirft ValueError bei ungültiger Kennung, Kollision mit einem eingebauten Anbieter oder
    fehlender http(s)-Basis-URL.
    """
    kennung = str(daten.get("id") or "").strip().lower()
    if not ANBIETER_ID.match(kennung):
        raise ValueError(f"Ungültige Anbieter-Kennung „{kennung}“ (erlaubt: a-z, 0-9, - und _).")
    if kennung in EINGEBAUTE_IDS:
        raise ValueError(f"„{kennung}“ ist ein eingebauter Anbieter.")
    basis = str(daten.get("api_base") or "").strip().rstrip("/")
    if not basis.startswith(("http://", "https://")):
        raise ValueError("Die Basis-URL muss mit http:// oder https:// beginnen.")
    schluessel = str(daten.get("schluessel") or "").strip() or None
    if schluessel and not re.match(r"^[A-Z][A-Z0-9_]{1,63}$", schluessel):
        raise ValueError("Der Schlüsselname darf nur Großbuchstaben, Ziffern und _ enthalten.")
    name = str(daten.get("name") or "").strip() or kennung
    vorschlaege = tuple((str(m), str(m)) for m in (daten.get("modelle") or []) if str(m).strip())
    return Anbieter(
        kennung, name, None, schluessel, api_base=basis, modelle_url=f"{basis}/models",
        vorschlaege=vorschlaege, eigen=True,
    )


def alle_anbieter(eigene: list[dict[str, Any]] | None = None) -> list[Anbieter]:
    ergebnis = list(EINGEBAUTE)
    for eintrag in eigene or []:
        try:
            ergebnis.append(eigener_anbieter(eintrag))
        except ValueError:
            continue
    return ergebnis


def anbieter_finden(kennung: str, eigene: list[dict[str, Any]] | None = None) -> Anbieter | None:
    kennung = (kennung or "").strip().lower()
    for a in alle_anbieter(eigene):
        if a.id == kennung:
            return a
    return None


def anbieter_von_modell(modell: str, eigene: list[dict[str, Any]] | None = None) -> Anbieter | None:
    if modell.startswith("ollama_chat/"):
        return anbieter_finden("ollama")
    return anbieter_finden(modell.split("/", 1)[0] if "/" in modell else "", eigene)


def aufruf_parameter(modell: str, eigene: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """LiteLLM-Parameter für ein Modell: ``model`` und ggf. ``api_base``/``api_key``.

    Anbieter mit LiteLLM-Präfix bleiben unverändert (LiteLLM liest den Schlüssel aus der
    Umgebung). OpenCode und eigene Anbieter werden zu ``openai/<modell>`` mit eigener Basis-URL;
    der Schlüssel wird ausdrücklich mitgegeben, damit nie OPENAI_API_KEY dorthin geht.
    """
    a = anbieter_von_modell(modell, eigene)
    if a is None or a.praefix is not None:
        return {"model": modell}
    rest = modell.split("/", 1)[1] if "/" in modell else modell
    parameter: dict[str, Any] = {"model": f"openai/{rest}", "api_base": a.api_base}
    parameter["api_key"] = os.environ.get(a.schluessel, "") if a.schluessel else "ohne"
    return parameter


# ---------- Live-Modelllisten ----------

def _ist_chatmodell(kennung: str) -> bool:
    k = kennung.lower()
    return not any(m in k for m in _KEIN_CHATMODELL)


def _opencode_filter(kennung: str) -> bool:
    # Gratis-Modelle laufen laut OpenCode-Doku nur in OpenCode selbst, nicht über die API.
    return not (kennung.endswith("-free") or kennung == "big-pickle")


def modelle_parsen(anbieter: Anbieter, daten: Any) -> list[ModellEintrag]:
    """Macht aus der Antwort eines ``/models``-Endpunkts Modelleinträge (ohne Anbieter-Präfix)."""
    eintraege: list[ModellEintrag] = []
    if anbieter.id == "gemini":
        for m in (daten or {}).get("models", []) if isinstance(daten, dict) else []:
            name = str(m.get("name") or "").removeprefix("models/")
            if not name or "generateContent" not in (m.get("supportedGenerationMethods") or []):
                continue
            eintraege.append(ModellEintrag(name, str(m.get("displayName") or name), live=True))
        return [e for e in eintraege if _ist_chatmodell(e.id)]

    roh = daten.get("data", []) if isinstance(daten, dict) else daten
    if not isinstance(roh, list):
        return []
    for m in roh:
        if not isinstance(m, dict):
            continue
        kennung = str(m.get("id") or "").strip()
        if not kennung or not _ist_chatmodell(kennung):
            continue
        if anbieter.id == "opencode" and not _opencode_filter(kennung):
            continue
        name = str(m.get("display_name") or m.get("name") or kennung)
        e = ModellEintrag(kennung, name, live=True)
        if anbieter.id == "openrouter":
            preis = m.get("pricing") or {}
            e.kostenlos = str(preis.get("prompt")) == "0" and str(preis.get("completion")) == "0"
            parameter = m.get("supported_parameters")
            if isinstance(parameter, list):
                e.werkzeuge = "tools" in parameter
        eintraege.append(e)
    return eintraege


def _kopfzeilen(anbieter: Anbieter, schluessel_wert: str | None) -> dict[str, str]:
    if not schluessel_wert:
        return {}
    if anbieter.id == "anthropic":
        return {"x-api-key": schluessel_wert, "anthropic-version": "2023-06-01"}
    if anbieter.id == "gemini":
        return {"x-goog-api-key": schluessel_wert}
    return {"Authorization": f"Bearer {schluessel_wert}"}


class ModellListen:
    """Fragt Modelllisten live ab und cacht sie je Anbieter."""

    def __init__(self, http_client_fabrik: Any = None):
        self._http = http_client_fabrik or (lambda **kw: httpx.AsyncClient(**kw))
        self._cache: dict[str, tuple[float, list[ModellEintrag]]] = {}

    async def laden(self, anbieter: Anbieter, neu: bool = False) -> list[ModellEintrag]:
        """Live-Liste oder leer (Fehler, kein Endpunkt, Schlüssel nötig aber nicht da)."""
        if not anbieter.modelle_url or anbieter.lokal:
            return []
        schluessel_wert = os.environ.get(anbieter.schluessel) if anbieter.schluessel else None
        if anbieter.schluessel and not schluessel_wert and anbieter.id not in ("openrouter", "opencode"):
            return []
        cache = self._cache.get(anbieter.id)
        if cache and not neu and time.monotonic() - cache[0] < CACHE_SEKUNDEN:
            return list(cache[1])
        try:
            async with self._http(timeout=ZEITLIMIT) as client:
                r = await client.get(anbieter.modelle_url, headers=_kopfzeilen(anbieter, schluessel_wert))
                r.raise_for_status()
                eintraege = modelle_parsen(anbieter, r.json())
        except (httpx.HTTPError, ValueError):
            return []
        self._cache[anbieter.id] = (time.monotonic(), eintraege)
        return list(eintraege)

    def vergessen(self, kennung: str | None = None) -> None:
        if kennung is None:
            self._cache.clear()
        else:
            self._cache.pop(kennung, None)


def sortiert(anbieter: Anbieter, live: list[ModellEintrag]) -> list[ModellEintrag]:
    """Vorschläge zuerst (in Vorschlagsreihenfolge, mit Anzeigename), dann übrige alphabetisch."""
    nach_id = {e.id: e for e in live}
    ergebnis: list[ModellEintrag] = []
    for mid, name in anbieter.vorschlaege:
        e = nach_id.pop(mid, None)
        if e is not None:
            e.name = name if name != mid else e.name
            ergebnis.append(e)
    ergebnis.extend(sorted(nach_id.values(), key=lambda e: e.id.lower()))
    return ergebnis


def vorschlaege(anbieter: Anbieter) -> list[ModellEintrag]:
    return [ModellEintrag(mid, name) for mid, name in anbieter.vorschlaege]
