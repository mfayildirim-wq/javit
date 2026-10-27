"""Smoke-Tests mit echten Modellen (werden übersprungen, wenn Paket/Netz fehlen)."""

from __future__ import annotations

import os

import numpy as np
import pytest
from stimme_hilfen import FakeQuelle, FakeSTT, FakeTTS, rahmen_sprache, rahmen_stille

from jarvis.stimme.fehler import StimmFehler


@pytest.fixture(scope="session")
def oww_verzeichnis(request, tmp_path_factory):
    try:
        return request.config.cache.mkdir("jarvis_openwakeword")
    except Exception:  # noqa: BLE001 – Cache-Plugin deaktiviert
        return tmp_path_factory.mktemp("openwakeword")


@pytest.fixture(scope="session")
def oww_detektor(oww_verzeichnis):
    pytest.importorskip("openwakeword")
    pytest.importorskip("onnxruntime")
    from jarvis.stimme.weckwort import OpenWakeWordDetektor

    detektor = OpenWakeWordDetektor("hey_jarvis", oww_verzeichnis)
    try:
        detektor.laden()
    except StimmFehler as f:
        if "herunterg" in f.text or "nicht installiert" in f.text:
            pytest.skip(f"openWakeWord-Modell nicht verfügbar: {f.text}")
        raise
    return detektor


def test_openwakeword_hey_jarvis_laedt_und_bleibt_bei_stille_still(oww_detektor):
    assert list(oww_detektor._modell.models) == ["hey_jarvis_v0.1"]
    scores = [oww_detektor.pruefen(np.zeros(1280, dtype=np.int16)) for _ in range(40)]
    scores += [oww_detektor.pruefen(r) for r in rahmen_stille(40, amplitude=300)]
    scores += [oww_detektor.pruefen(r) for r in rahmen_sprache(20)]
    assert max(scores) < 0.5
    oww_detektor.zuruecksetzen()


def test_unbekanntes_weckwort_gibt_verstaendlichen_fehler(oww_verzeichnis):
    pytest.importorskip("openwakeword")
    from jarvis.stimme.weckwort import OpenWakeWordDetektor

    with pytest.raises(StimmFehler, match="Unbekanntes Weckwort"):
        OpenWakeWordDetektor("hey_computer_xyz", oww_verzeichnis).laden()


@pytest.mark.asyncio
async def test_dienst_mit_echtem_weckwort_modell(oww_detektor, protokoll):
    from stimme_hilfen import warte_bis

    from jarvis.stimme import StimmDienst

    quelle = FakeQuelle()

    async def anfrage(text):
        raise AssertionError("darf nicht aufgerufen werden")

    dienst = StimmDienst({"stimme": {"vad": "energie"}}, protokoll, anfrage, audioquelle=quelle,
                         detektor=oww_detektor, stt=FakeSTT(), tts=FakeTTS())
    await dienst.start()
    await quelle.senden(rahmen_stille(30) + rahmen_sprache(20) + rahmen_stille(10))
    await warte_bis(lambda: oww_detektor._modell is not None)
    await dienst.stop()
    assert protokoll.zustaende() == ["bereit"]
    assert protokoll.fehlertexte() == []


def test_faster_whisper_tiny_laedt():
    pytest.importorskip("faster_whisper")
    from faster_whisper import WhisperModel

    try:
        modell = WhisperModel("tiny", device="cpu", compute_type="int8")
    except Exception as exc:  # noqa: BLE001 – meist kein Zugang zu huggingface.co
        pytest.skip(f"faster-whisper-Modell nicht ladbar (Netz?): {str(exc)[:120]}")
    segmente, info = modell.transcribe(np.zeros(16000, dtype=np.float32), language="de", vad_filter=True)
    assert " ".join(s.text for s in segmente).strip() == ""  # Stille → kein Text
    assert info.language == "de"


@pytest.mark.skipif(not os.environ.get("JARVIS_TEST_AUDIO"), reason="JARVIS_TEST_AUDIO=<datei.wav> nicht gesetzt")
@pytest.mark.asyncio
async def test_lokale_stt_mit_echter_datei():
    """Optional (z. B. am Mac): JARVIS_TEST_AUDIO=/pfad/frage.wav JARVIS_TEST_TEXT='wie spät'."""
    from jarvis.stimme.audio import Rahmenbildner, wav_lesen
    from jarvis.stimme.stt import LokaleSTT

    daten, rate = wav_lesen(os.environ["JARVIS_TEST_AUDIO"])
    rahmen = []
    Rahmenbildner(rahmen.append, eingangsrate=rate).hinzufuegen(daten)
    text = await LokaleSTT(os.environ.get("JARVIS_TEST_STT_MODELL", "tiny")).transkribieren(np.concatenate(rahmen))
    erwartet = os.environ.get("JARVIS_TEST_TEXT", "").lower()
    assert text and erwartet in text.lower()
