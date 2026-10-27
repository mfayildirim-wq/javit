"""Sprachausgabe: Stimmenwahl, say-Befehl (gemockt), Cloud-TTS (gemocktes litellm), Abspieler."""

from __future__ import annotations

import asyncio
import os
import stat
import sys
import types

import numpy as np
import pytest

from jarvis.stimme import tts as tts_modul
from jarvis.stimme.audio import wav_bytes
from jarvis.stimme.einstellungen import StimmEinstellungen
from jarvis.stimme.fehler import StimmFehler
from jarvis.stimme.tts import (
    Abspieler,
    CloudTTS,
    SayTTS,
    beste_say_stimme,
    erzeuge_tts,
    say_stimmen_parsen,
)

SAY_LISTE = """\
Albert              en_US    # Hello! My name is Albert.
Anna                de_DE    # Hallo! Ich heiße Anna.
Eddy (Deutsch (Deutschland)) de_DE    # Hallo! Ich heiße Eddy.
Grandma (Deutsch (Deutschland)) de_DE    # Hallo! Ich heiße Grandma.
Helena (Enhanced)   de_DE    # Hallo! Ich heiße Helena.
Markus              de_DE    # Hallo! Ich heiße Markus.
Petra (Premium)     de_DE    # Hallo! Ich heiße Petra.
Anna (Erweitert)    de_DE    # Hallo! Ich heiße Anna.
Samantha            en_US    # Hello! My name is Samantha.
Thomas              fr_FR    # Bonjour, je m’appelle Thomas.
"""


def test_say_liste_parsen():
    stimmen = say_stimmen_parsen(SAY_LISTE)
    namen = [s.name for s in stimmen]
    assert "Eddy (Deutsch (Deutschland))" in namen
    assert "Petra (Premium)" in namen
    assert all(s.sprache in ("en_US", "de_DE", "fr_FR") for s in stimmen)
    assert len(stimmen) == 10


def test_beste_deutsche_stimme_premium_vor_enhanced_vor_normal():
    stimmen = say_stimmen_parsen(SAY_LISTE)
    assert beste_say_stimme(stimmen, "de") == "Petra (Premium)"
    ohne_premium = [s for s in stimmen if "Premium" not in s.name]
    # Enhanced/Erweitert gleichwertig → Anna wird bevorzugt
    assert beste_say_stimme(ohne_premium, "de") == "Anna (Erweitert)"
    nur_normal = [s for s in stimmen if s.qualitaet == 1]
    assert beste_say_stimme(nur_normal, "de") == "Anna"


def test_spassstimmen_werden_gemieden_und_wunsch_hat_vorrang():
    stimmen = say_stimmen_parsen(SAY_LISTE)
    nur_spass = [s for s in stimmen if s.basisname in ("Eddy", "Grandma")]
    assert beste_say_stimme(nur_spass, "de") in ("Eddy (Deutsch (Deutschland))", "Grandma (Deutsch (Deutschland))")
    assert beste_say_stimme(stimmen, "de", wunsch="markus") == "Markus"
    assert beste_say_stimme(stimmen, "de", wunsch="Helena") == "Helena (Enhanced)"
    assert beste_say_stimme(stimmen, "fr") == "Thomas"
    assert beste_say_stimme(stimmen, "ja") is None


class FakeAusfuehren:
    def __init__(self, liste: str = SAY_LISTE, code: int = 0):
        self.aufrufe: list[tuple[list[str], bytes | None]] = []
        self.liste = liste
        self.code = code

    async def __call__(self, befehl, eingabe=None, timeout=60):
        self.aufrufe.append((list(befehl), eingabe))
        if befehl[:3] == ["say", "-v", "?"]:
            return 0, self.liste.encode(), b""
        return self.code, b"", b"Fehler XY" if self.code else b""


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setattr(tts_modul.sys, "platform", "darwin")


@pytest.mark.asyncio
async def test_say_befehl_wird_korrekt_gebaut(mac, tmp_path):
    ausf = FakeAusfuehren()
    say = SayTTS(sprache="de", ausfuehren=ausf)
    pfad = await say.synthetisieren("Hallo Welt", str(tmp_path / "teil0"))
    assert pfad == str(tmp_path / "teil0.wav")
    befehl, eingabe = ausf.aufrufe[-1]
    assert befehl == [
        "say", "-v", "Petra (Premium)", "-o", pfad,
        "--file-format=WAVE", "--data-format=LEI16@22050", "-f", "-",
    ]
    assert eingabe == "Hallo Welt".encode()
    # Stimmenliste wird nur einmal abgefragt
    await say.synthetisieren("Noch einmal", str(tmp_path / "teil1"))
    assert sum(1 for b, _ in ausf.aufrufe if b[:3] == ["say", "-v", "?"]) == 1


@pytest.mark.asyncio
async def test_say_escaping_text_geht_unveraendert_ueber_stdin(mac, tmp_path):
    """Kein Shell-Aufruf: Anführungszeichen, $(), ;, führende Bindestriche landen nur in stdin."""
    ausf = FakeAusfuehren()
    say = SayTTS(stimme="Anna", tempo=190, ausfuehren=ausf)
    gefaehrlich = "-v Bad \"Zitat\" 'x' $(rm -rf ~); `ls` && echo ok | cat > /tmp/x\nZeile 2 – Ümläüte ß"
    await say.synthetisieren(gefaehrlich, str(tmp_path / "t"))
    befehl, eingabe = ausf.aufrufe[-1]
    assert eingabe.decode("utf-8") == gefaehrlich
    assert all(gefaehrlich not in teil for teil in befehl)
    assert befehl[:5] == ["say", "-v", "Anna", "-r", "190"]
    assert befehl[-2:] == ["-f", "-"]
    assert isinstance(befehl, list)  # Argumentliste, nie ein Shell-String


@pytest.mark.asyncio
async def test_say_ohne_deutsche_stimme_nutzt_systemstandard(mac, tmp_path):
    ausf = FakeAusfuehren(liste="Samantha            en_US    # Hello!\n")
    say = SayTTS(ausfuehren=ausf)
    await say.synthetisieren("Hallo", str(tmp_path / "t"))
    befehl, _ = ausf.aufrufe[-1]
    assert "-v" not in befehl


@pytest.mark.asyncio
async def test_say_fehler_wird_zu_stimmfehler(mac, tmp_path):
    say = SayTTS(ausfuehren=FakeAusfuehren(code=1))
    with pytest.raises(StimmFehler, match="say ist fehlgeschlagen"):
        await say.synthetisieren("Hallo", str(tmp_path / "t"))


@pytest.mark.asyncio
async def test_say_auf_linux_meldet_verstaendlichen_fehler(monkeypatch, tmp_path):
    monkeypatch.setattr(tts_modul.sys, "platform", "linux")
    monkeypatch.setattr(tts_modul.shutil, "which", lambda name: None)
    with pytest.raises(StimmFehler, match="nur unter macOS"):
        await SayTTS(ausfuehren=FakeAusfuehren()).synthetisieren("Hallo", str(tmp_path / "t"))


class FakeLitellm(types.SimpleNamespace):
    pass


@pytest.mark.asyncio
async def test_cloud_tts_ruft_litellm_aspeech(monkeypatch, tmp_path):
    aufrufe = []
    wav = wav_bytes(np.zeros(1600, dtype=np.int16))

    async def aspeech(**kwargs):
        aufrufe.append(kwargs)
        return types.SimpleNamespace(content=wav)

    monkeypatch.setitem(sys.modules, "litellm", FakeLitellm(aspeech=aspeech))
    tts = CloudTTS(modell="openai/tts-1", stimme="nova")
    pfad = await tts.synthetisieren("Guten Tag", str(tmp_path / "teil0"))
    assert aufrufe == [{"model": "openai/tts-1", "input": "Guten Tag", "voice": "nova", "response_format": "wav"}]
    assert pfad.endswith(".wav")
    with open(pfad, "rb") as f:
        assert f.read() == wav


@pytest.mark.asyncio
async def test_cloud_tts_standardstimme_und_mp3(monkeypatch, tmp_path):
    async def aspeech(**kwargs):
        assert kwargs["voice"] == "onyx"
        return types.SimpleNamespace(content=b"ID3\x00mp3daten")

    monkeypatch.setitem(sys.modules, "litellm", FakeLitellm(aspeech=aspeech))
    pfad = await CloudTTS().synthetisieren("Hallo", str(tmp_path / "x"))
    assert pfad.endswith(".mp3")


@pytest.mark.asyncio
async def test_cloud_tts_fehler(monkeypatch, tmp_path):
    async def aspeech(**kwargs):
        raise RuntimeError("AuthenticationError: invalid api key")

    monkeypatch.setitem(sys.modules, "litellm", FakeLitellm(aspeech=aspeech))
    with pytest.raises(StimmFehler, match="API-Schlüssel"):
        await CloudTTS().synthetisieren("Hallo", str(tmp_path / "x"))


def test_erzeuge_tts_nach_einstellung(monkeypatch):
    monkeypatch.setenv("JARVIS_PLATTFORM", "mac")  # Standard „auto“ = say auf dem Mac
    assert erzeuge_tts(StimmEinstellungen.aus({"tts": "aus"})) is None
    assert isinstance(erzeuge_tts(StimmEinstellungen.aus({})), SayTTS)
    cloud = erzeuge_tts(StimmEinstellungen.aus({"tts": "cloud", "tts_cloud_modell": "openai/gpt-4o-mini-tts"}))
    assert isinstance(cloud, CloudTTS) and cloud.modell == "openai/gpt-4o-mini-tts"


def _fake_player(tmp_path, sekunden: float) -> str:
    skript = tmp_path / "fakeplay"
    skript.write_text(f"#!/bin/sh\nsleep {sekunden}\n")
    skript.chmod(skript.stat().st_mode | stat.S_IEXEC)
    return str(skript)


def _testwav(tmp_path) -> str:
    t = np.arange(16000) / 16000
    x = (np.sin(2 * np.pi * 220 * t) * 10000).astype(np.int16)
    pfad = tmp_path / "ton.wav"
    pfad.write_bytes(wav_bytes(x))
    return str(pfad)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="Shell-Skript als Abspieler")
async def test_abspieler_meldet_pegel_und_laesst_sich_stoppen(tmp_path):
    abspieler = Abspieler(programm=_fake_player(tmp_path, 5))
    pegel: list[float] = []

    async def pegel_cb(w):
        pegel.append(w)

    stopp = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.call_later(0.4, stopp.set)
    start = loop.time()
    await asyncio.wait_for(abspieler.abspielen(_testwav(tmp_path), pegel=pegel_cb, stopp=stopp), 3)
    assert loop.time() - start < 2.0  # abgebrochen, nicht 5 s gelaufen
    assert len(pegel) >= 4 and max(pegel) > 0.5
    assert pegel[-1] == 0.0


@pytest.mark.asyncio
async def test_abspieler_ohne_programm():
    with pytest.raises(StimmFehler, match="nicht gefunden"):
        await Abspieler(programm="gibt-es-nicht-afplay").abspielen("/tmp/x.wav")
