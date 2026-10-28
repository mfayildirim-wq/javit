"""Sprecher: streamende Sprachausgabe.

* ``Satzstrom`` – zerlegt ankommende Text-Deltas in vorlesbare Sätze, sobald sie vollständig sind.
* ``OpenRouterTTS`` – ``POST /api/v1/audio/speech`` als PCM-Strom (int16, mono, meist 24 kHz).
* Ausgabeziele: ``LautsprecherZiel`` (sounddevice), ``BrowserZiel`` (Binärframes über den WebSocket).
* ``Sprecher`` – Warteschlange: Sätze → bis zu zwei Synthesen voraus → Wiedergabe in Reihenfolge.
  Synthesen ohne ``strom`` (say, SAPI, Piper, espeak, cloud) laufen weiter dateiweise über ``Abspieler``.
* ``BrowserQuelle`` – Audioquelle aus Binärframes des Browsers (beliebige Rate → 16-kHz-Rahmen).
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from .audio import Rahmenbildner, wav_bytes
from .fehler import StimmFehler, kurz
from .text import fuer_sprache
from .tts import Abspieler, aufraeumen, temp_verzeichnis

log = logging.getLogger("jarvis.stimme.sprecher")

OPENROUTER_SPEECH_URL = "https://openrouter.ai/api/v1/audio/speech"
STANDARD_RATE = 24000
#: Binärframe-Größe für den Browser: 200 ms bei 24 kHz int16
BROWSER_FRAME_BYTES = 9600


def pcm_pegel(pcm: bytes, unten_db: float = -60.0, oben_db: float = -12.0) -> float:
    """Pegel 0..1 (wie ``vad.pegel_anzeige``) für rohe int16-Bytes."""
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    werte = np.frombuffer(pcm[: n * 2], dtype="<i2").astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(werte * werte))) if werte.size else 0.0
    db = 20 * math.log10(rms) if rms > 1e-9 else -120.0
    return round(float(min(max((db - unten_db) / (oben_db - unten_db), 0.0), 1.0)), 3)


# ---------------------------------------------------------------- Satzstrom
_ABKUERZUNGEN = {
    "z", "b", "bzw", "dr", "nr", "ca", "evtl", "usw", "vgl", "prof", "st", "u", "a", "o", "ä", "etc", "inkl",
    "zzgl", "ggf", "bspw", "sog", "max", "min", "tel", "str", "hr", "fr", "mio", "mrd", "jh", "n", "chr",
}
_GRENZE = re.compile(r"[.!?…]+[\"“»)\]]?\s+(?=[A-ZÄÖÜ0-9\"„(«])")


class Satzstrom:
    """Sammelt Text-Deltas und gibt fertige Sätze frei.

    Der erste Satz kommt sofort (schneller Start), danach werden sehr kurze Sätze (< ``min_laenge``)
    mit dem nächsten verschmolzen, damit die Synthese nicht mit Schnipseln hantiert.
    """

    def __init__(self, min_erster: int = 1, min_laenge: int = 25):
        self.min_erster = min_erster
        self.min_laenge = min_laenge
        self._puffer = ""
        self._erster = True

    @staticmethod
    def _ist_grenze(vor: str) -> bool:
        """Endet ``vor`` mit einem echten Satzende? Abkürzungen („z. B.“, „Dr.“) und Ordnungszahlen nicht."""
        vor = vor.rstrip().rstrip("\"“»)]")
        if not vor or vor[-1] not in ".!?…":
            return True
        davor = vor.rstrip(".!?…").strip()
        wort = re.split(r"\s+", davor)[-1].lower() if davor else ""
        if vor[-1] == "." and (wort in _ABKUERZUNGEN or (wort.isdigit() and len(wort) <= 2)):
            return False
        return True

    def einspeisen(self, delta: str) -> list[str]:
        self._puffer += delta
        fertig: list[str] = []
        while True:
            start = 0
            treffer = None
            for m in _GRENZE.finditer(self._puffer):
                satz = self._puffer[start : m.end()].strip()
                if not self._ist_grenze(self._puffer[: m.end()]):
                    continue
                minimum = self.min_erster if self._erster else self.min_laenge
                if len(satz) < minimum:
                    continue  # mit dem nächsten Satz zusammenfassen
                treffer = m
                break
            if treffer is None:
                break
            fertig.append(self._puffer[: treffer.end()].strip())
            self._puffer = self._puffer[treffer.end() :]
            self._erster = False
        return fertig

    def abschliessen(self) -> str | None:
        rest, self._puffer = self._puffer.strip(), ""
        self._erster = True
        return rest or None


# ---------------------------------------------------------------- Synthese
class StreamSynthese(Protocol):
    rate: int

    def strom(self, text: str) -> AsyncIterator[bytes]: ...
    async def synthetisieren(self, text: str, ziel: str) -> str: ...


def _content_type_werte(ct: str) -> tuple[int, int]:
    rate, kanaele = STANDARD_RATE, 1
    for teil in ct.split(";")[1:]:
        k, _, v = teil.strip().partition("=")
        if k == "rate" and v.isdigit():
            rate = int(v)
        elif k == "channels" and v.isdigit():
            kanaele = int(v)
    return rate, kanaele


class OpenRouterTTS:
    """Sprachausgabe über OpenRouter (ElevenLabs, Microsoft MAI, Google TTS …) als PCM-Strom."""

    def __init__(
        self,
        modell: str,
        stimme: str = "",
        schluessel: str | Callable[[], str | None] | None = None,
        http_client_fabrik: Callable[..., Any] | None = None,
        geschwindigkeit: float = 1.0,
        anweisung: str = "",
    ):
        self.modell = modell
        self.stimme = stimme
        self._schluessel = schluessel if schluessel is not None else (lambda: os.environ.get("OPENROUTER_API_KEY"))
        self._fabrik = http_client_fabrik
        self.geschwindigkeit = geschwindigkeit
        self.anweisung = anweisung
        self.rate = STANDARD_RATE

    def _client(self) -> Any:
        import httpx  # noqa: PLC0415

        if self._fabrik is not None:
            return self._fabrik(timeout=httpx.Timeout(60.0, connect=15.0))
        return httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0))

    def _anfrage(self, text: str) -> dict[str, Any]:
        daten: dict[str, Any] = {"model": self.modell, "input": text, "voice": self.stimme, "response_format": "pcm"}
        if self.geschwindigkeit and abs(self.geschwindigkeit - 1.0) > 1e-6:
            daten["speed"] = self.geschwindigkeit
        if self.anweisung:
            daten["instructions"] = self.anweisung
        return daten

    async def strom(self, text: str) -> AsyncIterator[bytes]:
        key = self._schluessel() if callable(self._schluessel) else self._schluessel
        if not key:
            raise StimmFehler("OpenRouter-Schlüssel fehlt (OPENROUTER_API_KEY) – in den Einstellungen hinterlegen.")
        kopf = {
            "Authorization": f"Bearer {key}",
            "HTTP-Referer": "https://github.com/mfayildirim-wq/javit",
            "X-Title": "Javit",
        }
        try:
            async with self._client() as client, client.stream(
                "POST", OPENROUTER_SPEECH_URL, headers=kopf, json=self._anfrage(text)
            ) as antwort:
                if antwort.status_code != 200:
                    body = (await antwort.aread())[:300].decode("utf-8", "replace")
                    raise StimmFehler(f"OpenRouter-Sprachausgabe ({self.modell}): HTTP {antwort.status_code} {body}")
                self.rate, kanaele = _content_type_werte(antwort.headers.get("content-type", ""))
                rest = b""
                schritt = 2 * kanaele
                async for chunk in antwort.aiter_bytes(8192):
                    daten = rest + chunk
                    n = len(daten) - len(daten) % schritt
                    daten, rest = daten[:n], daten[n:]
                    if not daten:
                        continue
                    if kanaele > 1:
                        daten = np.frombuffer(daten, dtype="<i2").reshape(-1, kanaele)[:, 0].astype("<i2").tobytes()
                    yield daten
        except StimmFehler:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StimmFehler(f"OpenRouter-Sprachausgabe ({self.modell}) fehlgeschlagen: {kurz(exc)}") from exc

    async def synthetisieren(self, text: str, ziel: str) -> str:
        teile = [t async for t in self.strom(text)]
        pfad = str(Path(ziel).with_suffix(".wav"))
        audio = np.frombuffer(b"".join(teile), dtype="<i2")
        Path(pfad).write_bytes(wav_bytes(audio, self.rate))
        return pfad


# ---------------------------------------------------------------- Ausgabeziele
Pegel = Callable[[float], Awaitable[None]]


class Ausgabeziel(Protocol):
    async def start(self, rate: int) -> None: ...
    async def schreiben(self, pcm: bytes) -> None: ...
    async def ende(self) -> None: ...
    def stoppen(self) -> None: ...


class LautsprecherZiel:
    """PCM-Wiedergabe über ``sounddevice.OutputStream``; meldet den Pegel 15/s."""

    def __init__(self, pegel: Pegel | None = None, geraet: Any = None):
        self._pegel = pegel
        self._geraet = geraet
        self._strom: Any = None
        self._puffer = deque()
        self._rest = b""
        self._rate = STANDARD_RATE
        self._offen = 0  # Bytes, die noch nicht abgespielt wurden
        self._gestoppt = False
        self._pegel_task: asyncio.Task | None = None
        self._letzter_pegel = 0.0
        self._lock = __import__("threading").Lock()

    def _callback(self, outdata: Any, frames: int, _zeit: Any, _status: Any) -> None:
        noetig = frames * 2
        with self._lock:
            daten = bytearray(self._rest)
            self._rest = b""
            while len(daten) < noetig and self._puffer:
                daten += self._puffer.popleft()
            block, self._rest = bytes(daten[:noetig]), bytes(daten[noetig:])
            self._offen -= len(block)
        self._letzter_pegel = pcm_pegel(block)
        out = np.frombuffer(block.ljust(noetig, b"\x00"), dtype="<i2")
        outdata[:, 0] = out

    async def start(self, rate: int) -> None:
        try:
            import sounddevice as sd  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001
            raise StimmFehler(f"sounddevice fehlt ({kurz(exc)}).") from exc
        self._rate = rate
        self._gestoppt = False
        self._offen = 0
        self._puffer.clear()
        self._rest = b""
        try:
            self._strom = sd.OutputStream(samplerate=rate, channels=1, dtype="int16", device=self._geraet, callback=self._callback)
            self._strom.start()
        except Exception as exc:  # noqa: BLE001
            self._strom = None
            raise StimmFehler(f"Lautsprecher konnte nicht geöffnet werden: {kurz(exc)}") from exc
        if self._pegel is not None:
            self._pegel_task = asyncio.create_task(self._pegel_melden())

    async def _pegel_melden(self) -> None:
        try:
            while True:
                await asyncio.sleep(1 / 15)
                if self._pegel is not None:
                    await self._pegel(self._letzter_pegel if self._offen > 0 else 0.0)
        except asyncio.CancelledError:
            pass

    async def schreiben(self, pcm: bytes) -> None:
        if self._gestoppt or self._strom is None:
            return
        with self._lock:
            self._puffer.append(pcm)
            self._offen += len(pcm)
        # Rückstau: nicht mehr als ~2 s vorpuffern, damit „stoppen“ sofort wirkt
        while self._offen > self._rate * 2 * 2 and not self._gestoppt:
            await asyncio.sleep(0.05)

    async def leer(self) -> None:
        """Wartet, bis der Puffer abgespielt ist (Strom bleibt offen)."""
        while self._offen > 0 and not self._gestoppt:
            await asyncio.sleep(0.02)

    async def ende(self) -> None:
        await self.leer()
        await asyncio.sleep(0.1)  # Latenz des Geräts
        await self._schliessen()

    def stoppen(self) -> None:
        self._gestoppt = True
        with self._lock:
            self._puffer.clear()
            self._rest = b""
            self._offen = 0
        strom, self._strom = self._strom, None
        if strom is not None:
            try:
                strom.abort()
                strom.close()
            except Exception:  # noqa: BLE001
                pass
        if self._pegel_task is not None:
            self._pegel_task.cancel()
            self._pegel_task = None

    async def _schliessen(self) -> None:
        strom, self._strom = self._strom, None
        if strom is not None:
            try:
                await asyncio.to_thread(strom.stop)
                strom.close()
            except Exception:  # noqa: BLE001
                pass
        if self._pegel_task is not None:
            self._pegel_task.cancel()
            self._pegel_task = None
            if self._pegel is not None:
                await self._pegel(0.0)


class BrowserZiel:
    """Sendet PCM als Binärframes an eine WebSocket-Verbindung; ``ende`` wartet die Spieldauer ab."""

    def __init__(
        self,
        sender: Callable[[dict[str, Any] | bytes], Awaitable[Any]],
        pegel: Pegel | None = None,
        uhr: Callable[[], float] = time.monotonic,
        schlaf: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._sender = sender
        self._pegel = pegel
        self._uhr = uhr
        self._schlaf = schlaf
        self._rate = STANDARD_RATE
        self._gespielt_bis = 0.0
        self._gestoppt = False

    async def start(self, rate: int) -> None:
        self._rate = rate
        self._gestoppt = False
        self._gespielt_bis = self._uhr()
        await self._sender({"typ": "sprachausgabe", "zustand": "start", "rate": rate})

    async def schreiben(self, pcm: bytes) -> None:
        if self._gestoppt:
            return
        jetzt = self._uhr()
        if self._gespielt_bis < jetzt:
            self._gespielt_bis = jetzt
        for i in range(0, len(pcm), BROWSER_FRAME_BYTES):
            if self._gestoppt:
                return
            frame = pcm[i : i + BROWSER_FRAME_BYTES]
            await self._sender(frame)
            if self._pegel is not None:
                await self._pegel(pcm_pegel(frame))
        self._gespielt_bis += len(pcm) / (self._rate * 2)
        # Nicht weiter als ~2 s vorauslaufen, damit „stoppen“ sofort wirkt
        vorsprung = self._gespielt_bis - self._uhr() - 2.0
        if vorsprung > 0:
            await self._schlaf(vorsprung)

    async def leer(self) -> None:
        rest = self._gespielt_bis - self._uhr()
        if rest > 0 and not self._gestoppt:
            await self._schlaf(rest)

    async def ende(self) -> None:
        if self._gestoppt:
            return
        await self.leer()
        if self._pegel is not None:
            await self._pegel(0.0)
        await self._sender({"typ": "sprachausgabe", "zustand": "ende"})

    def stoppen(self) -> None:
        if self._gestoppt:
            return
        self._gestoppt = True
        self._gespielt_bis = self._uhr()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._sender({"typ": "sprachausgabe", "zustand": "gestoppt"}))


# ---------------------------------------------------------------- Browser-Quelle
class BrowserQuelle:
    """Audioquelle aus Binärframes des Browsers (int16 mono, ``rate``); liefert 16-kHz-Rahmen à 1280."""

    def __init__(self, rate: int = 48000):
        self.rate = int(rate)
        self._bildner: Rahmenbildner | None = None

    def starten(self, rueckruf: Callable[[np.ndarray], None]) -> None:
        self._bildner = Rahmenbildner(rueckruf, eingangsrate=self.rate)

    def stoppen(self) -> None:
        self._bildner = None

    @property
    def aktiv(self) -> bool:
        return self._bildner is not None

    def einspeisen(self, daten: bytes) -> None:
        bildner = self._bildner
        if bildner is None or len(daten) < 2:
            return
        n = len(daten) - len(daten) % 2
        bildner.hinzufuegen(np.frombuffer(daten[:n], dtype="<i2"))


# ---------------------------------------------------------------- Sprecher
class Sprecher:
    """Nimmt Text-Deltas an und spricht satzweise, sobald Sätze fertig sind.

    ``tts`` mit ``strom`` → PCM an ``ziel``; sonst ``synthetisieren`` in Datei und ``abspieler.abspielen``.
    """

    def __init__(
        self,
        tts: Any,
        ziel: Ausgabeziel | None,
        abspieler: Any | None = None,
        pegel: Pegel | None = None,
        stopp: asyncio.Event | None = None,
        fehler: Callable[[str], Any] | None = None,
        voraus: int = 2,
        bei_start: Callable[[], Awaitable[None]] | None = None,
    ):
        self.tts = tts
        self.ziel = ziel
        self.abspieler = abspieler
        self._pegel = pegel
        self.stopp = stopp or asyncio.Event()
        self._fehler = fehler
        self.voraus = max(1, voraus)
        self._strom = Satzstrom()
        self._saetze: asyncio.Queue[str | None] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._laufende: list[asyncio.Task] = []
        self._verzeichnis: str | None = None
        self.gesprochen = False
        self.gestoppt = False
        self.streamt = False
        self._bei_start = bei_start
        self._leer = asyncio.Event()
        self._leer.set()

    async def beginnen(self) -> None:
        self.stopp.clear()
        self.gestoppt = False
        self._task = asyncio.create_task(self._lauf(), name="jarvis-sprecher")

    def einspeisen(self, delta: str) -> None:
        if self.gestoppt or not delta:
            return
        for satz in self._strom.einspeisen(delta):
            self._reihen(satz)

    def _reihen(self, satz: str) -> None:
        sauber = fuer_sprache(satz)
        if sauber:
            self._leer.clear()
            self._saetze.put_nowait(sauber)

    async def warten_bis_leer(self) -> None:
        """Wartet, bis alle eingereihten Sätze synthetisiert, geschrieben und abgespielt sind."""
        rest = self._strom.abschliessen()
        if rest and not self.gestoppt:
            self._reihen(rest)
        await self._leer.wait()
        if self.streamt and self.ziel is not None and not self.gestoppt:
            leer = getattr(self.ziel, "leer", None)
            if leer is not None:
                await leer()

    async def abschliessen(self) -> None:
        rest = self._strom.abschliessen()
        if rest and not self.gestoppt:
            self._reihen(rest)
        self._saetze.put_nowait(None)
        if self._task is not None:
            await self._task

    def stoppen(self) -> None:
        self.gestoppt = True
        self.stopp.set()
        while not self._saetze.empty():
            try:
                self._saetze.get_nowait()
            except asyncio.QueueEmpty:
                break
        for t in self._laufende:
            t.cancel()
        if self.ziel is not None and self.streamt:
            self.ziel.stoppen()
        if self.abspieler is not None:
            try:
                self.abspieler.abbrechen()
            except Exception:  # noqa: BLE001
                pass

    def _melden(self, text: str) -> None:
        if self._fehler is not None:
            try:
                self._fehler(text)
            except Exception:  # noqa: BLE001
                log.debug("Fehlerrückruf", exc_info=True)

    async def _sammeln(self, satz: str) -> bytes:
        teile = [t async for t in self.tts.strom(satz)]
        return b"".join(teile)

    async def _datei(self, satz: str, nr: int) -> str:
        if self._verzeichnis is None:
            self._verzeichnis = temp_verzeichnis()
        return await self.tts.synthetisieren(satz, str(Path(self._verzeichnis) / f"teil{nr}"))

    async def _lauf(self) -> None:
        self.streamt = hasattr(self.tts, "strom") and self.ziel is not None
        if self.streamt:
            try:
                await self.ziel.start(int(getattr(self.tts, "rate", STANDARD_RATE)))  # type: ignore[union-attr]
            except StimmFehler as f:
                log.info("Stromausgabe nicht möglich (%s) – Dateiweg", f.text)
                self.streamt = False
        if not self.streamt and self.abspieler is None:
            self.abspieler = Abspieler()
        warte: deque[tuple[str, asyncio.Task]] = deque()
        zu_ende = False
        nr = 0
        try:
            while not self.gestoppt:
                # Warteschlange bis ``voraus`` Synthesen füllen
                while not zu_ende and len(warte) < self.voraus:
                    if warte:
                        try:
                            satz = self._saetze.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    else:
                        if self._saetze.empty():
                            self._leer.set()  # nichts in Arbeit, nichts eingereiht: alles gesprochen
                        satz = await self._saetze.get()
                    if satz is None:
                        zu_ende = True
                        break
                    aufgabe = asyncio.create_task(self._sammeln(satz) if self.streamt else self._datei(satz, nr))
                    nr += 1
                    self._laufende.append(aufgabe)
                    warte.append((satz, aufgabe))
                if not warte:
                    self._leer.set()
                    if zu_ende:
                        break
                    continue
                satz, aufgabe = warte.popleft()
                try:
                    ergebnis = await aufgabe
                except asyncio.CancelledError:
                    if self.gestoppt:
                        break
                    continue
                except StimmFehler as f:
                    self._melden(f.text)
                    continue
                except Exception as exc:  # noqa: BLE001
                    log.exception("Sprachsynthese")
                    self._melden(f"Sprachausgabe fehlgeschlagen: {kurz(exc)}")
                    continue
                finally:
                    if aufgabe in self._laufende:
                        self._laufende.remove(aufgabe)
                if self.gestoppt:
                    break
                if not self.gesprochen and self._bei_start is not None:
                    await self._bei_start()
                self.gesprochen = True
                if self.streamt:
                    await self.ziel.schreiben(ergebnis)  # type: ignore[union-attr]
                else:
                    await self.abspieler.abspielen(ergebnis, pegel=self._pegel, stopp=self.stopp)
            if self.streamt and not self.gestoppt:
                await self.ziel.ende()  # type: ignore[union-attr]
        except asyncio.CancelledError:
            self.stoppen()
            raise
        finally:
            self._leer.set()
            for t in self._laufende:
                t.cancel()
            self._laufende.clear()
            if self._verzeichnis is not None:
                aufraeumen(self._verzeichnis)
                self._verzeichnis = None


# ---------------------------------------------------------------- Modellkatalog (OpenRouter)
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_TTS_ANBIETER = ("elevenlabs/", "microsoft/mai-voice", "google/gemini", "mistralai/voxtral")
STT_MODELLE = [
    {"id": "openai/whisper-large-v3", "name": "Whisper large v3 (OpenAI)"},
    {"id": "openai/gpt-4o-mini-transcribe", "name": "GPT-4o mini Transcribe (OpenAI)"},
    {"id": "openai/gpt-4o-transcribe", "name": "GPT-4o Transcribe (OpenAI)"},
]
_modell_cache: dict[str, Any] = {"zeit": 0.0, "daten": None}


def _anbieter_rang(kennung: str) -> int:
    for i, praefix in enumerate(_TTS_ANBIETER):
        if kennung.startswith(praefix):
            return i
    return len(_TTS_ANBIETER)


async def openrouter_sprachmodelle(http_client_fabrik: Callable[..., Any] | None = None, cache_s: float = 600.0) -> dict[str, Any]:
    """Sprachausgabe-Modelle von OpenRouter (``output_modalities=speech``), gefiltert auf bewährte Anbieter,
    mit Stimmen und Preis je 1 Mio. Zeichen; dazu die festen Transkriptionsmodelle."""
    import httpx  # noqa: PLC0415

    jetzt = time.monotonic()
    if _modell_cache["daten"] is not None and jetzt - _modell_cache["zeit"] < cache_s:
        return _modell_cache["daten"]
    tts: list[dict[str, Any]] = []
    fehler = None
    try:
        client = http_client_fabrik(timeout=15.0) if http_client_fabrik is not None else httpx.AsyncClient(timeout=15.0)
        async with client:
            antwort = await client.get(OPENROUTER_MODELS_URL, params={"output_modalities": "speech"})
        antwort.raise_for_status()
        for m in antwort.json().get("data", []):
            kennung = str(m.get("id") or "")
            if _anbieter_rang(kennung) >= len(_TTS_ANBIETER) or kennung.endswith(":free"):
                continue
            preis = m.get("pricing") or {}
            try:
                je_1m = round(float(preis.get("prompt") or 0) * 1_000_000, 2)
            except (TypeError, ValueError):
                je_1m = None
            tts.append({
                "id": kennung,
                "name": str(m.get("name") or kennung),
                "stimmen": [str(v) for v in (m.get("supported_voices") or [])],
                "preis_je_1m_zeichen": je_1m,
                "standard_stimme": _standard_stimme(kennung),
            })
        tts.sort(key=lambda e: (_anbieter_rang(e["id"]), e["id"]))
    except Exception as exc:  # noqa: BLE001
        fehler = kurz(exc)
    daten = {"tts": tts, "stt": list(STT_MODELLE), "fehler": fehler}
    if fehler is None:
        _modell_cache.update(zeit=jetzt, daten=daten)
    return daten


def _standard_stimme(kennung: str) -> str:
    from .tts import openrouter_standard_stimme  # noqa: PLC0415

    return openrouter_standard_stimme(kennung)
