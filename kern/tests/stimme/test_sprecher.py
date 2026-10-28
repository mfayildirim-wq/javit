"""Sprecher: Satzstrom, OpenRouter-PCM-Strom, Ausgabeziele, Warteschlange."""

from __future__ import annotations

import asyncio
import json
import struct

import httpx
import numpy as np
import pytest
from stimme_hilfen import FakeAbspieler, FakeTTS

from jarvis.stimme.audio import wav_lesen
from jarvis.stimme.fehler import StimmFehler
from jarvis.stimme.sprecher import BrowserQuelle, BrowserZiel, OpenRouterTTS, Satzstrom, Sprecher

# ---------------------------------------------------------------- Satzstrom
def test_satzstrom_grenzen_und_rest():
    s = Satzstrom()
    assert s.einspeisen("Guten Tag. ") == []  # Satzende steht erst fest, wenn der nächste Satz beginnt
    assert s.einspeisen("Die Reise ist gebucht. Soll ich") == ["Guten Tag."]  # kurzer Satz wartet (< 25 Zeichen)
    assert s.einspeisen(" das Hotel reservieren? Ja") == ["Die Reise ist gebucht. Soll ich das Hotel reservieren?"]
    assert s.abschliessen() == "Ja"
    assert s.abschliessen() is None


def test_satzstrom_abkuerzungen_zahlen_und_kurze_saetze():
    s = Satzstrom()
    saetze = s.einspeisen("Das kostet z. B. 3.5 Euro bei Dr. Müller. Gut. Ok. Dann bis morgen um 9 Uhr. ")
    assert saetze == ["Das kostet z. B. 3.5 Euro bei Dr. Müller."]  # kurze Sätze warten auf den nächsten
    assert s.abschliessen() == "Gut. Ok. Dann bis morgen um 9 Uhr."


def test_satzstrom_deltas_zeichenweise():
    s = Satzstrom()
    text = "Erster Satz ist hier. Zweiter Satz folgt sofort! Dritter"
    saetze = []
    for z in text:
        saetze += s.einspeisen(z)
    assert saetze == ["Erster Satz ist hier.", "Zweiter Satz folgt sofort!"]
    assert s.abschliessen() == "Dritter"


# ---------------------------------------------------------------- OpenRouterTTS
def pcm_sinus(n: int, kanaele: int = 1) -> bytes:
    werte = (np.sin(np.arange(n) / 10) * 10000).astype("<i2")
    if kanaele > 1:
        werte = np.repeat(werte, kanaele)
    return werte.tobytes()


def openrouter_attrappe(anfragen: list, kanaele: int = 1, status: int = 200, rate: int = 24000):
    def handler(request: httpx.Request) -> httpx.Response:
        anfragen.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer or-test"
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "Model unknown"}})
        daten = pcm_sinus(2400, kanaele)
        return httpx.Response(
            200, content=daten, headers={"content-type": f"audio/pcm;rate={rate};channels={kanaele}"}
        )

    def fabrik(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    return fabrik


async def test_openrouter_tts_strom_und_datei(tmp_path):
    anfragen: list = []
    tts = OpenRouterTTS("elevenlabs/eleven-flash-v2.5", "daniel", schluessel=lambda: "or-test", http_client_fabrik=openrouter_attrappe(anfragen))
    teile = [t async for t in tts.strom("Hallo Welt.")]
    assert b"".join(teile) == pcm_sinus(2400) and tts.rate == 24000
    assert anfragen[0] == {"model": "elevenlabs/eleven-flash-v2.5", "input": "Hallo Welt.", "voice": "daniel", "response_format": "pcm"}
    pfad = await tts.synthetisieren("Hallo Welt.", str(tmp_path / "teil0"))
    daten, rate = wav_lesen(pfad)
    assert pfad.endswith(".wav") and rate == 24000 and len(daten) == 2400


async def test_openrouter_tts_stereo_wird_mono_und_rate_aus_kopfzeile():
    tts = OpenRouterTTS("google/gemini-3.8-flash-lite-tts", "Kore", schluessel=lambda: "or-test", http_client_fabrik=openrouter_attrappe([], kanaele=2, rate=22050))
    daten = b"".join([t async for t in tts.strom("Hi.")])
    assert daten == pcm_sinus(2400) and tts.rate == 22050


async def test_openrouter_tts_fehler():
    ohne = OpenRouterTTS("x/y", "v", schluessel=lambda: None, http_client_fabrik=openrouter_attrappe([]))
    with pytest.raises(StimmFehler, match="OPENROUTER_API_KEY"):
        _ = [t async for t in ohne.strom("Hi.")]
    kaputt = OpenRouterTTS("x/y", "v", schluessel=lambda: "or-test", http_client_fabrik=openrouter_attrappe([], status=400))
    with pytest.raises(StimmFehler, match="400"):
        _ = [t async for t in kaputt.strom("Hi.")]


# ---------------------------------------------------------------- Ziele und Quelle
class FakeZiel:
    def __init__(self, fehler_beim_start: bool = False):
        self.fehler_beim_start = fehler_beim_start
        self.gestartet: list[int] = []
        self.daten: list[bytes] = []
        self.beendet = 0
        self.gestoppt = 0

    async def start(self, rate: int) -> None:
        if self.fehler_beim_start:
            raise StimmFehler("kein Gerät")
        self.gestartet.append(rate)

    async def schreiben(self, pcm: bytes) -> None:
        self.daten.append(pcm)

    async def ende(self) -> None:
        self.beendet += 1

    def stoppen(self) -> None:
        self.gestoppt += 1


class StromTTS:
    rate = 24000

    def __init__(self, verzoegerung: float = 0.0, fehler_bei: str | None = None):
        self.texte: list[str] = []
        self.laufend = 0
        self.max_laufend = 0
        self.verzoegerung = verzoegerung
        self.fehler_bei = fehler_bei

    async def strom(self, text: str):
        self.texte.append(text)
        self.laufend += 1
        self.max_laufend = max(self.max_laufend, self.laufend)
        try:
            await asyncio.sleep(self.verzoegerung)
            if text == self.fehler_bei:
                raise StimmFehler("Synthese kaputt")
            for teil in (text[: len(text) // 2], text[len(text) // 2 :]):
                yield teil.encode()
        finally:
            self.laufend -= 1

    async def synthetisieren(self, text: str, ziel: str) -> str:
        raise AssertionError("Stream-Weg erwartet")


async def test_sprecher_streamt_saetze_in_reihenfolge():
    tts, ziel, fehler = StromTTS(verzoegerung=0.02), FakeZiel(), []
    sp = Sprecher(tts, ziel, fehler=lambda t: fehler.append(t))
    await sp.beginnen()
    for delta in ["Erster Satz ist hier. Zweiter Satz folgt sofort! ", "Dritter Satz kommt auch noch. Vierter und ", "letzter Satz."]:
        sp.einspeisen(delta)
    await sp.abschliessen()
    assert tts.texte == ["Erster Satz ist hier.", "Zweiter Satz folgt sofort!", "Dritter Satz kommt auch noch.", "Vierter und letzter Satz."]
    assert b"".join(ziel.daten).decode() == "".join(tts.texte)
    assert ziel.gestartet == [24000] and ziel.beendet == 1 and ziel.gestoppt == 0
    assert tts.max_laufend <= 2 and fehler == [] and sp.gesprochen


async def test_sprecher_fehler_eines_satzes_und_markdown():
    tts, ziel, fehler = StromTTS(fehler_bei="Zweiter Satz folgt sofort!"), FakeZiel(), []
    sp = Sprecher(tts, ziel, fehler=lambda t: fehler.append(t))
    await sp.beginnen()
    sp.einspeisen("**Erster** Satz ist hier. Zweiter Satz folgt sofort! Dritter Satz kommt auch noch.")
    await sp.abschliessen()
    assert tts.texte[0] == "Erster Satz ist hier."  # Markdown entfernt
    assert b"".join(ziel.daten).decode() == "Erster Satz ist hier.Dritter Satz kommt auch noch."
    assert fehler == ["Synthese kaputt"]


async def test_sprecher_stoppen_leert_warteschlange():
    tts, ziel = StromTTS(verzoegerung=0.05), FakeZiel()
    sp = Sprecher(tts, ziel)
    await sp.beginnen()
    sp.einspeisen("Erster Satz ist hier. Zweiter Satz folgt sofort! Dritter Satz kommt auch noch. ")
    await asyncio.sleep(0.07)
    sp.stoppen()
    await sp.abschliessen()
    assert ziel.gestoppt == 1 and len(tts.texte) <= 2 and ziel.beendet == 0


async def test_sprecher_dateiweg_ohne_stromziel():
    tts, abspieler = FakeTTS(), FakeAbspieler(dauer_schritte=1)
    sp = Sprecher(tts, FakeZiel(fehler_beim_start=True), abspieler=abspieler)
    await sp.beginnen()
    sp.einspeisen("Erster Satz ist hier. Zweiter Satz folgt sofort!")
    await sp.abschliessen()
    assert tts.texte == ["Erster Satz ist hier.", "Zweiter Satz folgt sofort!"]
    assert len(abspieler.gespielt) == 2 and abspieler.gespielt[0].endswith("teil0.wav")


async def test_browserziel_frames_und_ereignisse():
    gesendet: list = []
    zeit = [100.0]
    geschlafen: list[float] = []

    async def sender(daten):
        gesendet.append(daten)

    async def schlaf(s: float):
        geschlafen.append(s)
        zeit[0] += s

    ziel = BrowserZiel(sender, uhr=lambda: zeit[0], schlaf=schlaf)
    await ziel.start(24000)
    await ziel.schreiben(b"\x00\x01" * 12000)  # 0,5 s Audio = 24000 Bytes → 3 Frames à 9600/9600/4800
    await ziel.ende()
    assert gesendet[0] == {"typ": "sprachausgabe", "zustand": "start", "rate": 24000}
    assert [len(d) for d in gesendet[1:4]] == [9600, 9600, 4800]
    assert gesendet[4] == {"typ": "sprachausgabe", "zustand": "ende"}
    assert pytest.approx(sum(geschlafen), abs=0.05) == 0.5
    ziel.stoppen()
    await asyncio.sleep(0)
    assert gesendet[-1] == {"typ": "sprachausgabe", "zustand": "gestoppt"}


async def test_browserquelle_bildet_rahmen():
    rahmen: list[np.ndarray] = []
    quelle = BrowserQuelle(rate=48000)
    quelle.starten(rahmen.append)
    block = (np.sin(np.arange(48000) / 20) * 8000).astype("<i2").tobytes()  # 1 s bei 48 kHz
    quelle.einspeisen(block[: len(block) // 2])
    quelle.einspeisen(block[len(block) // 2 :])
    assert len(rahmen) == 12 and all(r.shape == (1280,) and r.dtype == np.int16 for r in rahmen)  # 16000/1280 = 12,5
    quelle.stoppen()
    quelle.einspeisen(block)
    assert len(rahmen) == 12


def test_pcm_pegel():
    from jarvis.stimme.sprecher import pcm_pegel

    assert pcm_pegel(b"") == 0.0
    leise = struct.pack("<4h", 10, -10, 10, -10)
    laut = struct.pack("<4h", 20000, -20000, 20000, -20000)
    assert 0.0 <= pcm_pegel(leise) < pcm_pegel(laut) <= 1.0


# ---------------------------------------------------------------- Einstellungen und Fabriken
from jarvis.stimme.einstellungen import StimmEinstellungen
from jarvis.stimme.stt import LokaleSTT, OpenRouterSTT, erzeuge_stt, stt_art
from jarvis.stimme.tts import SayTTS, erzeuge_tts, openrouter_standard_stimme, tts_art


def test_tts_art_auto_mit_und_ohne_schluessel(monkeypatch):
    monkeypatch.setenv("JARVIS_PLATTFORM", "mac")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert tts_art(StimmEinstellungen.aus({})) == "say"
    assert isinstance(erzeuge_tts(StimmEinstellungen.aus({})), SayTTS)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    assert tts_art(StimmEinstellungen.aus({})) == "openrouter"
    tts = erzeuge_tts(StimmEinstellungen.aus({}))
    assert isinstance(tts, OpenRouterTTS) and tts.modell == "elevenlabs/eleven-flash-v2.5" and tts.stimme == "daniel"
    ms = erzeuge_tts(StimmEinstellungen.aus({"tts": "openrouter", "tts_openrouter_modell": "microsoft/mai-voice-2.1-flash"}))
    assert ms.stimme == "de-DE-Klaus:MAI-Voice-2.1-Flash"
    eigen = erzeuge_tts(StimmEinstellungen.aus({"tts": "openrouter", "tts_stimme": "sarah"}))
    assert eigen.stimme == "sarah"
    assert tts_art(StimmEinstellungen.aus({"tts": "say"})) == "say"  # ausdrücklich gewählt bleibt
    assert openrouter_standard_stimme("google/gemini-3.8-flash-tts") == "Kore"
    assert openrouter_standard_stimme("unbekannt/x") == ""


def test_stt_art_und_stoppwort(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    e = StimmEinstellungen.aus({"stoppwort": [" Stopp", "halt "]})
    assert e.stt == "auto" and stt_art(e) == "lokal" and isinstance(erzeuge_stt(e), LokaleSTT)
    assert e.stoppwort == "Stopp, halt"
    assert StimmEinstellungen.aus({"stoppwort": ""}).stoppwort == ""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    stt = erzeuge_stt(StimmEinstellungen.aus({}))
    assert isinstance(stt, OpenRouterSTT) and stt.modell == "openai/whisper-large-v3"
    assert isinstance(erzeuge_stt(StimmEinstellungen.aus({"stt": "lokal"})), LokaleSTT)


async def test_openrouter_stt():
    anfragen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        anfragen.append((request.headers["authorization"], json.loads(request.content)))
        return httpx.Response(200, json={"text": " Hallo  Welt. ", "usage": {"seconds": 1}})

    def fabrik(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    stt = OpenRouterSTT("openai/whisper-large-v3", "de", schluessel=lambda: "or-test", http_client_fabrik=fabrik)
    audio = np.zeros(1600, dtype=np.int16)
    assert await stt.transkribieren(audio) == "Hallo Welt."
    auth, daten = anfragen[0]
    assert auth == "Bearer or-test" and daten["model"] == "openai/whisper-large-v3" and daten["language"] == "de"
    assert daten["input_audio"]["format"] == "wav" and len(daten["input_audio"]["data"]) > 100

    def kaputt(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": {"message": "Guthaben"}})

    stt2 = OpenRouterSTT(schluessel=lambda: "or-test", http_client_fabrik=lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(kaputt), **kw))
    with pytest.raises(StimmFehler, match="402"):
        await stt2.transkribieren(audio)
    with pytest.raises(StimmFehler, match="OPENROUTER_API_KEY"):
        await OpenRouterSTT(schluessel=lambda: None).transkribieren(audio)
