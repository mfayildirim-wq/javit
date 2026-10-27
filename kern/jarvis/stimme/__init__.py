"""Sprachmodul des Assistenten: Weckwort („Javit“ über Vosk, „Hey Jarvis“ über openWakeWord), Aufnahme mit Sprachpausen-Erkennung,
Spracherkennung (faster-whisper / Cloud) und Sprachausgabe (macOS ``say`` / Cloud).

Öffentliche Schnittstelle::

    from jarvis.stimme import StimmDienst

    dienst = StimmDienst(einstellungen, ereignis, anfrage)
    await dienst.start()            # Mikrofon + Weckwort (Fehler → Event „fehler“)
    await dienst.sprechen("Hallo")  # Text vorlesen
    await dienst.einmal_zuhoeren()  # Push-to-talk ohne Weckwort
    dienst.aktiv, dienst.hoert
    await dienst.stop()

Schwere Abhängigkeiten (sounddevice, openwakeword, faster-whisper, litellm) werden erst bei
Bedarf importiert – der Import dieses Pakets gelingt auch ohne sie.
"""

from .dienst import StimmDienst
from .einstellungen import StimmEinstellungen
from .fehler import StimmFehler
from .text import fuer_sprache

__all__ = ["StimmDienst", "StimmEinstellungen", "StimmFehler", "fuer_sprache"]
