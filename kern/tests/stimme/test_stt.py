"""Spracherkennung: Cloud (gemocktes litellm) und lokal (gemocktes faster-whisper)."""

from __future__ import annotations

import io
import sys
import types
import wave

import numpy as np
import pytest

from jarvis.stimme.einstellungen import StimmEinstellungen
from jarvis.stimme.fehler import StimmFehler
from jarvis.stimme.stt import CloudSTT, LokaleSTT, erzeuge_stt, text_bereinigen


def test_text_bereinigen_filtert_whisper_halluzinationen():
    assert text_bereinigen("  Wie   spät ist es? ") == "Wie spät ist es?"
    assert text_bereinigen("Untertitel im Auftrag des ZDF, 2021") == ""
    assert text_bereinigen("Untertitel der Amara.org-Community") == ""
    assert text_bereinigen("Vielen Dank fürs Zuschauen!") == ""
    assert text_bereinigen("...") == ""
    assert text_bereinigen("Vielen Dank fürs Zuschauen, aber erinnere mich morgen") != ""


@pytest.mark.asyncio
async def test_cloud_stt_sendet_wav_an_litellm(monkeypatch):
    aufrufe = []

    async def atranscription(**kwargs):
        aufrufe.append(kwargs)
        return types.SimpleNamespace(text=" Schalte das Licht an. ")

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(atranscription=atranscription))
    stt = CloudSTT(modell="groq/whisper-large-v3", sprache="de")
    audio = (np.sin(np.arange(16000) / 5) * 1000).astype(np.int16)
    assert await stt.transkribieren(audio) == "Schalte das Licht an."
    (aufruf,) = aufrufe
    assert aufruf["model"] == "groq/whisper-large-v3"
    assert aufruf["language"] == "de"
    name, daten, mime = aufruf["file"]
    assert name.endswith(".wav") and mime == "audio/wav"
    with wave.open(io.BytesIO(daten)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()) == (16000, 1, 2, 16000)


@pytest.mark.asyncio
async def test_cloud_stt_fehler_wird_verstaendlich(monkeypatch):
    async def atranscription(**kwargs):
        raise RuntimeError("401 Unauthorized")

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(atranscription=atranscription))
    with pytest.raises(StimmFehler, match="Cloud-Spracherkennung.*API-Schlüssel"):
        await CloudSTT().transkribieren(np.zeros(1600, dtype=np.int16))


@pytest.mark.asyncio
async def test_cloud_stt_akzeptiert_dict_antwort(monkeypatch):
    async def atranscription(**kwargs):
        return {"text": "Hallo"}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(atranscription=atranscription))
    assert await CloudSTT().transkribieren(np.zeros(1600, dtype=np.int16)) == "Hallo"


class FakeWhisper:
    erzeugt: list[tuple] = []

    def __init__(self, name, device="auto", compute_type="default"):
        FakeWhisper.erzeugt.append((name, device, compute_type))

    def transcribe(self, audio, **kwargs):
        assert audio.dtype == np.float32 and np.max(np.abs(audio)) <= 1.0
        assert kwargs["language"] == "de"
        segs = [types.SimpleNamespace(text=" Hallo"), types.SimpleNamespace(text=" Jarvis. ")]
        return iter(segs), types.SimpleNamespace(language="de")


@pytest.mark.asyncio
async def test_lokale_stt_mit_faster_whisper(monkeypatch):
    FakeWhisper.erzeugt = []
    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeWhisper))
    stt = LokaleSTT(modell="small", sprache="de")
    text = await stt.transkribieren(np.full(16000, 1000, dtype=np.int16))
    assert text == "Hallo Jarvis."
    await stt.transkribieren(np.full(16000, 1000, dtype=np.int16))
    assert FakeWhisper.erzeugt == [("small", "auto", "int8")]  # nur einmal geladen


@pytest.mark.asyncio
async def test_lokale_stt_ohne_paket(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    with pytest.raises(StimmFehler, match="faster-whisper ist nicht installiert"):
        await LokaleSTT().transkribieren(np.zeros(1600, dtype=np.int16))


@pytest.mark.asyncio
async def test_lokale_stt_modell_nicht_ladbar(monkeypatch):
    def kaputt(*a, **k):
        raise OSError("Connection refused huggingface.co")

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=kaputt))
    with pytest.raises(StimmFehler, match="konnte nicht geladen werden"):
        await LokaleSTT(modell="tiny").vorbereiten()


def test_erzeuge_stt():
    lokal = erzeuge_stt(StimmEinstellungen.aus({"stt_modell": "base"}))
    assert isinstance(lokal, LokaleSTT) and lokal.modell_name == "base" and lokal.compute_type == "int8"
    cloud = erzeuge_stt(StimmEinstellungen.aus({"stt": "cloud", "stt_cloud_modell": "whisper-1"}))
    assert isinstance(cloud, CloudSTT) and cloud.modell == "whisper-1"
