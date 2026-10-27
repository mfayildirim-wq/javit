"""Einstellungen, Rahmenbildung, Mikrofon-Fehlerübersetzung (sounddevice gemockt)."""

from __future__ import annotations

import dataclasses
import sys
import types

import numpy as np
import pytest

from jarvis.stimme.audio import MikrofonQuelle, Rahmenbildner, wav_bytes, wav_lesen
from jarvis.stimme.einstellungen import StimmEinstellungen
from jarvis.stimme.fehler import StimmFehler, mikrofon_fehlertext

# ---------------------------------------------------------------------------------------- Einstellungen


def test_standardwerte():
    e = StimmEinstellungen.aus({})
    assert (e.aktiv, e.weckwort, e.schwelle, e.stt, e.stt_modell, e.sprache) == (False, "javit", 0.5, "lokal", "small", "de")
    assert (e.tts, e.bestaetigungston, e.stille_ms, e.max_aufnahme_s, e.folgemodus_s) == ("auto", True, 900, 20.0, 5.0)


def test_einstellungen_aus_gesamt_dict_objekt_und_pydantic_artig():
    gesamt = {"modell": "ollama/x", "stimme": {"weckwort": "alexa", "schwelle": 0.7, "unbekannt": 1}}
    e = StimmEinstellungen.aus(gesamt)
    assert e.weckwort == "alexa" and e.schwelle == 0.7 and e.extra == {"unbekannt": 1}

    obj = types.SimpleNamespace(stimme={"tts": "aus", "sprache": "de-DE"})
    e2 = StimmEinstellungen.aus(obj)
    assert e2.tts == "aus" and e2.sprache == "de"

    class PydanticArtig:
        def model_dump(self):
            return {"stt": "cloud", "stille_ms": 50, "schwelle": None}

    e3 = StimmEinstellungen.aus(types.SimpleNamespace(stimme=PydanticArtig()))
    assert e3.stt == "cloud" and e3.stille_ms == 200 and e3.schwelle == 0.5  # Minimum / Standard

    @dataclasses.dataclass
    class DC:
        folgemodus_s: float = 0

    assert StimmEinstellungen.aus(types.SimpleNamespace(stimme=DC())).folgemodus_s == 0
    assert StimmEinstellungen.aus({"stimme": {"tts": False}}).tts == "aus"


# ---------------------------------------------------------------------------------------- Rahmenbildung


def test_rahmenbildner_liefert_exakte_rahmen():
    rahmen = []
    rb = Rahmenbildner(rahmen.append)
    for groesse in (500, 1000, 3000, 620):
        rb.hinzufuegen(np.ones(groesse, dtype=np.int16))
    assert len(rahmen) == 5120 // 1280 and all(len(r) == 1280 and r.dtype == np.int16 for r in rahmen)


def test_rahmenbildner_rechnet_48khz_um_und_float_eingabe():
    rahmen = []
    rb = Rahmenbildner(rahmen.append, eingangsrate=48000)
    t = np.arange(48000) / 48000
    rb.hinzufuegen((np.sin(2 * np.pi * 440 * t) * 0.5).astype(np.float32).reshape(-1, 1))
    assert len(rahmen) == 12  # 1 s @16 kHz = 16000 Samples = 12,5 Rahmen
    x = np.concatenate(rahmen).astype(np.float32)
    spektrum = np.abs(np.fft.rfft(x))
    frequenz = np.argmax(spektrum) * 16000 / len(x)
    assert frequenz == pytest.approx(440, abs=3)  # 440 Hz bleiben 440 Hz


def test_wav_hin_und_zurueck():
    x = (np.arange(1000) - 500).astype(np.int16)
    y, rate = wav_lesen(wav_bytes(x))
    assert rate == 16000 and np.array_equal(x, y)


# ---------------------------------------------------------------------------------------- Mikrofonfehler


class PortAudioError(Exception):
    pass


def _fake_sd(*, check=None, query=None, stream=None):
    def check_input_settings(**kwargs):
        if check:
            raise check

    def query_devices(device=None, kind=None):
        if query:
            raise query
        return {"default_samplerate": 48000.0, "name": "Fake"}

    class InputStream:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            if stream:
                raise stream

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass

    return types.SimpleNamespace(
        PortAudioError=PortAudioError,
        check_input_settings=check_input_settings,
        query_devices=query_devices,
        InputStream=InputStream,
    )


def test_kein_mikrofon(monkeypatch):
    fehler = PortAudioError("Error querying device -1")
    monkeypatch.setitem(sys.modules, "sounddevice", _fake_sd(check=fehler, query=fehler))
    with pytest.raises(StimmFehler, match="Kein Mikrofon gefunden"):
        MikrofonQuelle().starten(lambda r: None)


def test_stream_fehler_auf_mac_nennt_berechtigung(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setitem(
        sys.modules, "sounddevice", _fake_sd(stream=PortAudioError("Error opening InputStream: Internal PortAudio error"))
    )
    with pytest.raises(StimmFehler) as info:
        MikrofonQuelle().starten(lambda r: None)
    assert "Datenschutz & Sicherheit → Mikrofon → Terminal" in info.value.text


def test_mikrofon_mit_anderer_abtastrate(monkeypatch):
    sd = _fake_sd(check=PortAudioError("Invalid sample rate"))
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    q = MikrofonQuelle()
    q.starten(lambda r: None)
    assert q.rate == 48000 and q._stream.kwargs["blocksize"] == 3840 and q._stream.kwargs["dtype"] == "int16"
    q.stoppen()
    q.stoppen()  # mehrfach erlaubt


def test_portaudio_bibliothek_fehlt(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert "brew install portaudio" in mikrofon_fehlertext(OSError("PortAudio library not found"))
    assert "pip install" in mikrofon_fehlertext(ImportError("No module named 'sounddevice'"))
    assert "Berechtigung" not in mikrofon_fehlertext(PortAudioError("Error querying device -1"))


def test_einstellungen_aus_kern_konfig_und_fabrik():
    pydantic = pytest.importorskip("pydantic")

    class KernStimme(pydantic.BaseModel):
        model_config = pydantic.ConfigDict(extra="allow")
        aktiv: bool = False
        weckwort: str = "hey_jarvis"

    class Kern(pydantic.BaseModel):
        modell: str = "ollama/x"
        stimme: KernStimme = pydantic.Field(default_factory=KernStimme)

    kern = Kern(stimme={"aktiv": True, "stt": "cloud", "folgemodus_s": 3})
    e = StimmEinstellungen.aus(kern)
    assert e.aktiv and e.stt == "cloud" and e.folgemodus_s == 3.0 and e.weckwort == "hey_jarvis"

    from jarvis.stimme import StimmDienst

    async def egal(*a):
        return ""

    zustand = {"k": kern}
    dienst = StimmDienst(lambda: zustand["k"], egal, egal)
    assert dienst.einstellungen.stt == "cloud"
    zustand["k"] = Kern(stimme={"stt": "lokal"})
    assert dienst.einstellungen.stt == "lokal"
