"""Spracherkennung: lokal mit faster-whisper oder in der Cloud über LiteLLM."""

from __future__ import annotations

import os

import asyncio
import logging
import re
from typing import Protocol

import numpy as np

from .audio import wav_bytes
from .fehler import HINWEIS_PAKETE, StimmFehler, kurz

log = logging.getLogger("jarvis.stimme.stt")

# Typische Whisper-„Halluzinationen“ bei Stille/Rauschen (deutsche Untertitel-Trainingsdaten).
HALLUZINATIONS_MARKER = ("untertitel im auftrag", "untertitel der amara", "untertitelung", "amara.org")
HALLUZINATIONEN_GANZ = {
    "vielen dank fürs zuschauen",
    "vielen dank für's zuschauen",
    "danke fürs zuschauen",
    "bis zum nächsten mal",
    "untertitel",
}


def text_bereinigen(text: str) -> str:
    text = " ".join((text or "").split()).strip()
    klein = text.lower()
    if any(h in klein for h in HALLUZINATIONS_MARKER):
        return ""
    if re.sub(r"[^\w' ]+", "", klein).strip() in HALLUZINATIONEN_GANZ:
        return ""
    if re.fullmatch(r"[\W_]*", text):  # nur Satzzeichen
        return ""
    return text


class Spracherkennung(Protocol):
    async def transkribieren(self, audio: np.ndarray) -> str: ...

    async def vorbereiten(self) -> None: ...


class LokaleSTT:
    """faster-whisper (CTranslate2). Auf Apple Silicon: CPU mit int8 (Metal wird nicht unterstützt)."""

    def __init__(self, modell: str = "small", sprache: str = "de", device: str = "auto", compute_type: str = "int8"):
        self.modell_name = modell or "small"
        self.sprache = sprache
        self.device = device
        self.compute_type = compute_type
        self._modell = None
        self._lock = asyncio.Lock()

    def _laden_sync(self):
        try:
            from faster_whisper import WhisperModel  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001
            raise StimmFehler(f"faster-whisper ist nicht installiert ({kurz(exc)}). {HINWEIS_PAKETE}") from exc
        try:
            return WhisperModel(self.modell_name, device=self.device, compute_type=self.compute_type)
        except Exception as exc:  # noqa: BLE001
            raise StimmFehler(
                f"Spracherkennungs-Modell „{self.modell_name}“ konnte nicht geladen werden ({kurz(exc)}). "
                "Beim ersten Start wird es von huggingface.co heruntergeladen – Internetverbindung prüfen."
            ) from exc

    async def vorbereiten(self) -> None:
        async with self._lock:
            if self._modell is None:
                self._modell = await asyncio.to_thread(self._laden_sync)

    def _transkribieren_sync(self, audio: np.ndarray) -> str:
        daten = np.asarray(audio, dtype=np.int16).astype(np.float32) / 32768.0
        segmente, _info = self._modell.transcribe(
            daten,
            language=self.sprache or None,
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        return " ".join(s.text.strip() for s in segmente)

    async def transkribieren(self, audio: np.ndarray) -> str:
        await self.vorbereiten()
        try:
            roh = await asyncio.to_thread(self._transkribieren_sync, audio)
        except Exception as exc:  # noqa: BLE001
            raise StimmFehler(f"Spracherkennung fehlgeschlagen ({kurz(exc)}).") from exc
        return text_bereinigen(roh)


class CloudSTT:
    """Spracherkennung über ``litellm.atranscription`` (z. B. ``whisper-1``, ``groq/whisper-large-v3``).

    API-Schlüssel kommen wie bei allen LiteLLM-Aufrufen aus den Umgebungsvariablen
    (OPENAI_API_KEY, GROQ_API_KEY, …), die der Kern aus dem Schlüsselbund setzt.
    """

    def __init__(self, modell: str = "whisper-1", sprache: str = "de", **parameter):
        self.modell = modell or "whisper-1"
        self.sprache = sprache
        self.parameter = parameter

    async def vorbereiten(self) -> None:
        return None

    async def transkribieren(self, audio: np.ndarray) -> str:
        try:
            import litellm  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001
            raise StimmFehler(f"LiteLLM ist nicht installiert ({kurz(exc)}).") from exc
        datei = ("aufnahme.wav", wav_bytes(audio), "audio/wav")
        try:
            antwort = await litellm.atranscription(
                model=self.modell, file=datei, language=self.sprache or None, **self.parameter
            )
        except Exception as exc:  # noqa: BLE001
            raise StimmFehler(
                f"Cloud-Spracherkennung ({self.modell}) fehlgeschlagen: {kurz(exc)}. API-Schlüssel hinterlegt?"
            ) from exc
        text = getattr(antwort, "text", None)
        if text is None and isinstance(antwort, dict):
            text = antwort.get("text", "")
        return text_bereinigen(text or "")


OPENROUTER_TRANSCRIPTION_URL = "https://openrouter.ai/api/v1/audio/transcriptions"


class OpenRouterSTT:
    """Spracherkennung über OpenRouter ``/audio/transcriptions`` (z. B. ``openai/whisper-large-v3``)."""

    def __init__(
        self,
        modell: str = "openai/whisper-large-v3",
        sprache: str = "de",
        schluessel=None,
        http_client_fabrik=None,
    ):
        self.modell = modell or "openai/whisper-large-v3"
        self.sprache = sprache
        self._schluessel = schluessel if schluessel is not None else (lambda: os.environ.get("OPENROUTER_API_KEY"))
        self._fabrik = http_client_fabrik

    async def vorbereiten(self) -> None:
        return None

    async def transkribieren(self, audio: np.ndarray) -> str:
        import base64  # noqa: PLC0415

        import httpx  # noqa: PLC0415

        key = self._schluessel() if callable(self._schluessel) else self._schluessel
        if not key:
            raise StimmFehler("OpenRouter-Schlüssel fehlt (OPENROUTER_API_KEY) – in den Einstellungen hinterlegen.")
        daten = {
            "model": self.modell,
            "input_audio": {"data": base64.b64encode(wav_bytes(audio)).decode("ascii"), "format": "wav"},
        }
        if self.sprache:
            daten["language"] = self.sprache
        kopf = {"Authorization": f"Bearer {key}", "HTTP-Referer": "https://github.com/mfayildirim-wq/javit", "X-Title": "Javit"}
        timeout = httpx.Timeout(60.0, connect=15.0)
        client = self._fabrik(timeout=timeout) if self._fabrik is not None else httpx.AsyncClient(timeout=timeout)
        try:
            async with client:
                antwort = await client.post(OPENROUTER_TRANSCRIPTION_URL, headers=kopf, json=daten)
        except Exception as exc:  # noqa: BLE001
            raise StimmFehler(f"OpenRouter-Spracherkennung ({self.modell}) fehlgeschlagen: {kurz(exc)}") from exc
        if antwort.status_code != 200:
            raise StimmFehler(
                f"OpenRouter-Spracherkennung ({self.modell}): HTTP {antwort.status_code} {antwort.text[:200]}"
            )
        try:
            text = antwort.json().get("text", "")
        except ValueError:
            text = ""
        return text_bereinigen(str(text or ""))


def stt_art(e) -> str:
    """Wirksame STT-Art: ``auto`` → ``openrouter`` mit OPENROUTER_API_KEY, sonst ``lokal``."""
    art = str(getattr(e, "stt", "auto") or "auto").lower()
    if art not in ("lokal", "cloud", "openrouter"):
        art = "openrouter" if os.environ.get("OPENROUTER_API_KEY") else "lokal"
    return art


def erzeuge_stt(e) -> Spracherkennung:
    art = stt_art(e)
    if art == "cloud":
        return CloudSTT(modell=e.stt_cloud_modell, sprache=e.sprache)
    if art == "openrouter":
        return OpenRouterSTT(modell=getattr(e, "stt_openrouter_modell", "") or "openai/whisper-large-v3", sprache=e.sprache)
    return LokaleSTT(modell=e.stt_modell, sprache=e.sprache)
