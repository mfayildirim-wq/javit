"""Sprachausgabe je Plattform: Auswahl (auto), SAPI über PowerShell (gemockt), Piper (gemockt,
kein Download), espeak-ng (echt, falls installiert), Abspieler-Wahl, Bestätigungston, Mikrofon-Hinweise."""

from __future__ import annotations

import base64
import json
import shutil
import sys
import wave

import pytest

from jarvis.stimme import tts as tts_modul
from jarvis.stimme.einstellungen import StimmEinstellungen
from jarvis.stimme.fehler import StimmFehler, hinweis_mikrofon_rechte, mikrofon_fehlertext
from jarvis.stimme.tts import (
    Abspieler,
    CloudTTS,
    EspeakTTS,
    KetteTTS,
    PiperTTS,
    SapiTTS,
    SayTTS,
    erzeuge_tts,
    piper_urls,
    sapi_rate,
    ton_datei,
    tts_art,
)

GEFAEHRLICH = "-v Bad \"Zitat\" 'x' $(rm -rf ~); `ls` && echo ok | cat > /tmp/x\nZeile 2 – Ümläüte ß ‘’"


class FakeAusfuehren:
    def __init__(self, code: int = 0, ausgabe: bytes = b""):
        self.aufrufe: list[tuple[list[str], bytes | None]] = []
        self.code = code
        self.ausgabe = ausgabe

    async def __call__(self, befehl, eingabe=None, timeout=60):
        self.aufrufe.append((list(befehl), eingabe))
        return self.code, self.ausgabe, b"kaputt" if self.code else b""


@pytest.mark.parametrize(
    ("plattform", "tts", "klasse"),
    [
        ("mac", "auto", SayTTS), ("windows", "auto", SapiTTS), ("linux", "auto", KetteTTS),
        ("windows", "say", SapiTTS), ("linux", "say", KetteTTS), ("mac", "say", SayTTS),
        ("linux", "espeak-ng", EspeakTTS), ("windows", "piper", KetteTTS), ("linux", "cloud", CloudTTS),
        ("linux", "quatsch", KetteTTS),
    ],
)
def test_auswahl_je_plattform(monkeypatch, plattform, tts, klasse):
    monkeypatch.setenv("JARVIS_PLATTFORM", plattform)
    assert isinstance(erzeuge_tts(StimmEinstellungen.aus({"tts": tts})), klasse)


def test_linux_kette_piper_dann_espeak(monkeypatch):
    monkeypatch.setenv("JARVIS_PLATTFORM", "linux")
    kette = erzeuge_tts(StimmEinstellungen.aus({}))
    assert [type(g) for g in kette.glieder] == [PiperTTS, EspeakTTS]
    assert tts_art(StimmEinstellungen.aus({"tts": "aus"})) == "aus" and erzeuge_tts(StimmEinstellungen.aus({"tts": "aus"})) is None


async def test_sapi_text_nur_ueber_stdin(tmp_path):
    ausf = FakeAusfuehren(ausgabe=base64.b64encode("Microsoft Hedda Desktop".encode()))
    sapi = SapiTTS(stimme="Hedda", tempo=140, ausfuehren=ausf)
    pfad = await sapi.synthetisieren(GEFAEHRLICH, str(tmp_path / "teil0"))
    assert pfad == str(tmp_path / "teil0.wav")
    befehl, eingabe = ausf.aufrufe[-1]
    assert befehl[0].lower().endswith("powershell.exe") and befehl[1:4] == ["-NoProfile", "-NonInteractive", "-EncodedCommand"]
    skript = base64.b64decode(befehl[4]).decode("utf-16-le")
    assert "System.Speech" in skript and "ConvertFrom-Json" in skript
    assert all(GEFAEHRLICH not in t for t in befehl) and GEFAEHRLICH not in skript
    daten = json.loads(base64.b64decode(eingabe))
    assert daten == {"text": GEFAEHRLICH, "ziel": pfad, "stimme": "Hedda", "sprache": "de", "rate": -2}
    assert sapi.gewaehlte_stimme == "Microsoft Hedda Desktop"


async def test_sapi_fehler(tmp_path):
    with pytest.raises(StimmFehler, match="Windows-Sprachausgabe fehlgeschlagen"):
        await SapiTTS(ausfuehren=FakeAusfuehren(code=1)).synthetisieren("x", str(tmp_path / "t"))


def test_sapi_rate():
    assert sapi_rate(0) is None and sapi_rate(180) == 0 and sapi_rate(400) == 10 and sapi_rate(20) == -8


def test_piper_urls():
    modell, konfig = piper_urls("de_DE-thorsten-medium")
    assert modell == ("https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/medium/"
                      "de_DE-thorsten-medium.onnx?download=true")
    assert konfig.endswith("de_DE-thorsten-medium.onnx.json?download=true")
    assert "/de/de_DE/thorsten_emotional/medium/" in piper_urls("de_DE-thorsten_emotional-medium")[0]
    with pytest.raises(StimmFehler):
        piper_urls("../../etc/passwd")


async def test_piper_laedt_modell_einmal_und_nutzt_stdin(monkeypatch, tmp_path):
    monkeypatch.delenv("JARVIS_KEIN_DOWNLOAD", raising=False)
    monkeypatch.setattr(tts_modul, "piper_verfuegbar", lambda: True)
    geladen = []

    async def laden(url, ziel):  # statt Netz: Dateien anlegen
        geladen.append(url)
        ziel.write_bytes(b"modell")

    ausf = FakeAusfuehren()
    piper = PiperTTS(modell_verzeichnis=str(tmp_path), tempo=240, ausfuehren=ausf, laden=laden)
    pfad = await piper.synthetisieren(GEFAEHRLICH, str(tmp_path / "teil0"))
    await piper.synthetisieren("Noch einmal", str(tmp_path / "teil1"))
    assert len(geladen) == 2  # Modell + Konfiguration, nur beim ersten Mal
    befehl, eingabe = ausf.aufrufe[0]
    modell = tmp_path / "piper" / "de_DE-thorsten-medium.onnx"
    assert befehl == [sys.executable, "-m", "piper", "-m", str(modell), "-f", pfad, "--length-scale", "0.75"]
    assert eingabe == GEFAEHRLICH.encode("utf-8")


async def test_piper_ohne_download_und_ohne_paket(monkeypatch, tmp_path):
    monkeypatch.setattr(tts_modul, "piper_verfuegbar", lambda: True)
    monkeypatch.setenv("JARVIS_KEIN_DOWNLOAD", "1")

    async def laden(url, ziel):
        raise AssertionError("darf nicht laden")

    with pytest.raises(StimmFehler, match="JARVIS_KEIN_DOWNLOAD"):
        await PiperTTS(modell_verzeichnis=str(tmp_path), laden=laden, ausfuehren=FakeAusfuehren()).synthetisieren("x", str(tmp_path / "t"))
    monkeypatch.setattr(tts_modul, "piper_verfuegbar", lambda: False)
    with pytest.raises(StimmFehler, match="pip install piper-tts"):
        await PiperTTS(modell_verzeichnis=str(tmp_path)).synthetisieren("x", str(tmp_path / "t"))


async def test_kette_faellt_auf_espeak_zurueck(monkeypatch, tmp_path):
    monkeypatch.setattr(tts_modul, "piper_verfuegbar", lambda: False)
    monkeypatch.setattr(tts_modul.shutil, "which", lambda n: "/usr/bin/espeak-ng" if n == "espeak-ng" else None)
    ausf = FakeAusfuehren()
    kette = KetteTTS([PiperTTS(modell_verzeichnis=str(tmp_path)), EspeakTTS(sprache="de", tempo=170, ausfuehren=ausf)])
    pfad = await kette.synthetisieren(GEFAEHRLICH, str(tmp_path / "t"))
    befehl, eingabe = ausf.aufrufe[-1]
    assert befehl == ["espeak-ng", "-v", "de", "-b", "1", "-w", pfad, "-s", "170", "--stdin"]
    assert eingabe == GEFAEHRLICH.encode()
    assert len(kette.glieder) == 1  # Piper wird nicht erneut probiert


async def test_kette_alle_fehlen(monkeypatch, tmp_path):
    monkeypatch.setattr(tts_modul, "piper_verfuegbar", lambda: False)
    monkeypatch.setattr(tts_modul.shutil, "which", lambda n: None)
    with pytest.raises(StimmFehler, match="espeak-ng ist nicht installiert"):
        await KetteTTS([PiperTTS(modell_verzeichnis=str(tmp_path)), EspeakTTS()]).synthetisieren("x", str(tmp_path / "t"))


@pytest.mark.skipif(not (shutil.which("espeak-ng") or shutil.which("espeak")), reason="espeak-ng nicht installiert")
async def test_espeak_echt(tmp_path):
    pfad = await EspeakTTS().synthetisieren("Guten Tag, Sir. $(rm -rf ~) „Test“", str(tmp_path / "t"))
    with wave.open(pfad, "rb") as w:
        assert w.getnframes() > 1000 and w.getsampwidth() == 2


def test_abspieler_wahl_je_plattform(monkeypatch):
    vorhanden = {"paplay", "aplay", "mpv"}
    monkeypatch.setattr(tts_modul.shutil, "which", lambda n: f"/usr/bin/{n}" if n in vorhanden else None)
    monkeypatch.setenv("JARVIS_PLATTFORM", "linux")
    assert Abspieler().befehl("/t/a.wav") == ["paplay", "/t/a.wav"]
    assert Abspieler().befehl("/t/a.mp3") == ["mpv", "--no-video", "--really-quiet", "/t/a.mp3"]
    vorhanden.discard("paplay")
    assert Abspieler().befehl("/t/a.wav") == ["aplay", "-q", "/t/a.wav"]
    vorhanden.clear()
    with pytest.raises(StimmFehler, match="Kein Wiedergabeprogramm"):
        Abspieler().befehl("/t/a.wav")
    monkeypatch.setenv("JARVIS_PLATTFORM", "windows")
    assert Abspieler().befehl("C:\\t\\a.wav") is None  # winsound
    monkeypatch.setenv("JARVIS_PLATTFORM", "mac")
    with pytest.raises(StimmFehler, match="afplay"):
        Abspieler().befehl("/t/a.wav")
    vorhanden.add("afplay")
    assert Abspieler().befehl("/t/a.wav") == ["afplay", "/t/a.wav"]


def test_winsound_nur_wav():
    with pytest.raises(StimmFehler, match="nur WAV"):
        Abspieler._winsound_starten("x.mp3", None)


def test_bestaetigungston_wird_erzeugt(tmp_path):
    vorhanden = tmp_path / "eigener.wav"
    vorhanden.write_bytes(b"RIFF")
    assert ton_datei(str(vorhanden)) == str(vorhanden)
    pfad = ton_datei(str(tmp_path / "fehlt.aiff"))
    with wave.open(pfad, "rb") as w:
        assert 0.1 < w.getnframes() / w.getframerate() < 0.2


@pytest.mark.parametrize(
    ("plattform", "teil"),
    [("mac", "Datenschutz & Sicherheit → Mikrofon"), ("windows", "Datenschutz und Sicherheit → Mikrofon"),
     ("linux", "PipeWire bzw. PulseAudio")],
)
def test_mikrofon_hinweise_je_plattform(monkeypatch, plattform, teil):
    monkeypatch.setenv("JARVIS_PLATTFORM", plattform)
    assert teil in hinweis_mikrofon_rechte()
    assert teil in mikrofon_fehlertext(PermissionError("permission denied"))


def test_portaudio_hinweis_linux_distribution(monkeypatch, tmp_path):
    from jarvis.plattform import gemeinsam

    monkeypatch.setenv("JARVIS_PLATTFORM", "linux")
    datei = tmp_path / "os-release"
    datei.write_text("ID=fedora\n")
    monkeypatch.setattr(gemeinsam, "OS_RELEASE", datei)
    assert "sudo dnf install portaudio" in mikrofon_fehlertext(OSError("PortAudio library not found"))
    monkeypatch.setenv("JARVIS_PLATTFORM", "windows")
    assert "pip install --force-reinstall sounddevice" in mikrofon_fehlertext(OSError("PortAudio library not found"))
