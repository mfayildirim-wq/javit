"""Audioquellen: Mikrofon über sounddevice (eigener PortAudio-Thread) und Hilfen.

Eine Audioquelle liefert int16-Rahmen à 1280 Samples (80 ms, 16 kHz, mono) an einen Rückruf.
Der Rückruf wird im Audio-Thread aufgerufen – der :class:`~jarvis.stimme.dienst.StimmDienst`
reicht die Rahmen per ``loop.call_soon_threadsafe`` an asyncio weiter.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Protocol

import numpy as np

from .fehler import StimmFehler, mikrofon_fehlertext
from .vad import ABTASTRATE, RAHMEN

log = logging.getLogger("jarvis.stimme.audio")

RahmenRueckruf = Callable[[np.ndarray], None]


class AudioQuelle(Protocol):
    """Schnittstelle einer Audioquelle (für Tests austauschbar)."""

    def starten(self, rueckruf: RahmenRueckruf) -> None:
        """Öffnet die Quelle; wirft :class:`StimmFehler` mit deutschem Hinweis bei Problemen."""

    def stoppen(self) -> None:
        """Schließt die Quelle (mehrfacher Aufruf erlaubt)."""


class Rahmenbildner:
    """Sammelt beliebig große Blöcke und gibt exakte 1280er-Rahmen aus; rechnet ggf. auf 16 kHz um."""

    def __init__(self, rueckruf: RahmenRueckruf, eingangsrate: int = ABTASTRATE, rahmen: int = RAHMEN):
        self.rueckruf = rueckruf
        self.eingangsrate = int(eingangsrate)
        self.rahmen = rahmen
        self._puffer = np.zeros(0, dtype=np.int16)
        self._lock = threading.Lock()

    def _umrechnen(self, block: np.ndarray) -> np.ndarray:
        if self.eingangsrate == ABTASTRATE or block.size == 0:
            return block
        try:
            from math import gcd

            from scipy.signal import resample_poly  # noqa: PLC0415

            g = gcd(ABTASTRATE, self.eingangsrate)
            y = resample_poly(block.astype(np.float32), ABTASTRATE // g, self.eingangsrate // g)
        except Exception:  # noqa: BLE001 – Fallback: lineare Interpolation
            n_neu = int(round(block.size * ABTASTRATE / self.eingangsrate))
            x_alt = np.linspace(0.0, 1.0, block.size, endpoint=False)
            x_neu = np.linspace(0.0, 1.0, n_neu, endpoint=False)
            y = np.interp(x_neu, x_alt, block.astype(np.float32))
        return np.clip(np.round(y), -32768, 32767).astype(np.int16)

    def hinzufuegen(self, block: np.ndarray) -> None:
        block = np.asarray(block)
        if block.ndim > 1:
            block = block[:, 0]
        if block.dtype != np.int16:
            if np.issubdtype(block.dtype, np.floating):
                block = np.clip(block * 32767.0, -32768, 32767).astype(np.int16)
            else:
                block = block.astype(np.int16)
        block = self._umrechnen(block)
        with self._lock:
            self._puffer = np.concatenate([self._puffer, block]) if self._puffer.size else block.copy()
            fertige = []
            while self._puffer.size >= self.rahmen:
                fertige.append(self._puffer[: self.rahmen].copy())
                self._puffer = self._puffer[self.rahmen :]
        for r in fertige:
            self.rueckruf(r)


class MikrofonQuelle:
    """Mikrofon über ``sounddevice.InputStream`` (16 kHz, mono, int16, Blöcke à 80 ms)."""

    def __init__(self, geraet=None):
        self.geraet = geraet if geraet not in ("", "standard") else None
        self._stream = None
        self.rate = ABTASTRATE

    def starten(self, rueckruf: RahmenRueckruf) -> None:
        try:
            import sounddevice as sd  # noqa: PLC0415
        except (ImportError, OSError) as exc:
            raise StimmFehler(mikrofon_fehlertext(exc, self.geraet)) from exc

        def _callback(indata, frames, zeit, status):  # läuft im PortAudio-Thread
            if status:
                log.debug("Audio-Status: %s", status)
            try:
                bildner.hinzufuegen(indata[:, 0] if indata.ndim > 1 else indata)
            except Exception:  # noqa: BLE001 – Audio-Thread darf nie sterben
                log.exception("Fehler im Audio-Rückruf")

        try:
            sd.check_input_settings(device=self.geraet, channels=1, dtype="int16", samplerate=ABTASTRATE)
            rate = ABTASTRATE
            blockgroesse = RAHMEN
        except Exception as exc:  # noqa: BLE001
            # 16 kHz nicht unterstützt → mit Geräte-Standardrate öffnen und selbst umrechnen.
            try:
                info = sd.query_devices(self.geraet, "input")
                rate = int(info["default_samplerate"])
                blockgroesse = int(rate * RAHMEN / ABTASTRATE)
            except Exception as exc2:  # noqa: BLE001
                raise StimmFehler(mikrofon_fehlertext(exc2 if str(exc2) else exc, self.geraet)) from exc2
        self.rate = rate
        bildner = Rahmenbildner(rueckruf, eingangsrate=rate)
        try:
            self._stream = sd.InputStream(
                samplerate=rate,
                channels=1,
                dtype="int16",
                blocksize=blockgroesse,
                device=self.geraet,
                callback=_callback,
            )
            self._stream.start()
        except Exception as exc:  # noqa: BLE001 – u. a. sd.PortAudioError
            self._stream = None
            raise StimmFehler(mikrofon_fehlertext(exc, self.geraet)) from exc
        log.info("Mikrofon geöffnet (%s Hz, Gerät %s)", rate, self.geraet or "Standard")

    def stoppen(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception:  # noqa: BLE001
            log.debug("Fehler beim Schließen des Mikrofons", exc_info=True)


def wav_bytes(audio: np.ndarray, abtastrate: int = ABTASTRATE) -> bytes:
    """int16-Mono-Audio als WAV-Datei (Bytes)."""
    import io
    import wave

    puffer = io.BytesIO()
    with wave.open(puffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(abtastrate)
        w.writeframes(np.asarray(audio, dtype="<i2").tobytes())
    return puffer.getvalue()


def wav_lesen(pfad_oder_bytes) -> tuple[np.ndarray, int]:
    """Liest eine PCM-WAV-Datei → (Mono-int16, Abtastrate)."""
    import io
    import wave

    quelle = io.BytesIO(pfad_oder_bytes) if isinstance(pfad_oder_bytes, (bytes, bytearray)) else str(pfad_oder_bytes)
    with wave.open(quelle, "rb") as w:
        kanaele, breite, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        roh = w.readframes(n)
    if breite == 2:
        daten = np.frombuffer(roh, dtype="<i2")
    elif breite == 1:
        daten = ((np.frombuffer(roh, dtype=np.uint8).astype(np.int16) - 128) * 256).astype(np.int16)
    elif breite == 4:
        daten = (np.frombuffer(roh, dtype="<i4") >> 16).astype(np.int16)
    else:
        raise ValueError(f"Nicht unterstützte Sample-Breite: {breite}")
    if kanaele > 1:
        daten = daten.reshape(-1, kanaele)[:, 0]
    return daten.copy(), rate
