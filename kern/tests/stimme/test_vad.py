"""VAD und Sprachpausen-Erkennung mit synthetischen Signalen."""

from __future__ import annotations

import sys

import numpy as np
import pytest
from stimme_hilfen import RAHMEN, rahmen_sprache, rahmen_stille

from jarvis.stimme.vad import (
    EnergieVAD,
    Sprachpausenerkenner,
    Status,
    erzeuge_vad,
    pegel_anzeige,
    pegel_dbfs,
)


def test_pegel_dbfs_und_anzeige():
    assert pegel_dbfs(np.zeros(RAHMEN, dtype=np.int16)) == -96.0
    voll = np.full(RAHMEN, 32767, dtype=np.int16)
    assert pegel_dbfs(voll) == pytest.approx(0.0, abs=0.01)
    assert pegel_anzeige(np.zeros(RAHMEN, dtype=np.int16)) == 0.0
    assert pegel_anzeige(voll) == 1.0
    leise, laut = rahmen_stille(1)[0], rahmen_sprache(1)[0]
    assert 0.0 <= pegel_anzeige(leise) < pegel_anzeige(laut) <= 1.0


def test_energie_vad_unterscheidet_sprache_und_rauschen():
    vad = EnergieVAD()
    for r in rahmen_stille(20):
        assert not vad.ist_sprache(r)
    assert all(vad.ist_sprache(r) for r in rahmen_sprache(10))
    assert not vad.ist_sprache(rahmen_stille(1, seed=5)[0])


def test_energie_vad_passt_sich_lautem_raum_an():
    """Gleichmäßiges lautes Rauschen (Lüfter) wird nach kurzer Zeit nicht mehr als Sprache gewertet."""
    vad = EnergieVAD()
    laut = rahmen_stille(80, amplitude=800.0, seed=3)  # ≈ -32 dBFS
    ergebnisse = [vad.ist_sprache(r) for r in laut]
    assert not any(ergebnisse[-40:])
    # Sprache deutlich über dem Rauschen wird weiterhin erkannt
    assert sum(vad.ist_sprache(r) for r in rahmen_sprache(5, amplitude=20000)) >= 4


def test_energie_vad_lernt_keine_digitale_stille():
    vad = EnergieVAD()
    for _ in range(10):
        vad.ist_sprache(np.zeros(RAHMEN, dtype=np.int16))
    assert vad.rauschen_db == -60.0


def test_sprachpause_beendet_aufnahme():
    sp = Sprachpausenerkenner(vad=EnergieVAD(), stille_ms=800, max_aufnahme_s=20, warte_auf_sprache_s=5)
    for r in rahmen_stille(5):
        assert sp.zufuehren(r) is Status.WARTET
    for r in rahmen_sprache(15):  # 1,2 s Sprache
        sp.zufuehren(r)
    assert sp.status is Status.SPRICHT
    # 800 ms Stille = 10 Rahmen à 80 ms
    stati = [sp.zufuehren(r) for r in rahmen_stille(12, seed=1)]
    assert stati.index(Status.FERTIG) == 9
    audio = sp.audio()
    assert audio is not None
    # Vorlauf (≤ 400 ms) + Sprache + max. 250 ms Nachlauf
    sekunden = len(audio) / 16000
    assert 1.2 <= sekunden <= 1.2 + 0.4 + 0.25 + 0.08


def test_kurze_pausen_innerhalb_der_aeusserung_beenden_nicht():
    sp = Sprachpausenerkenner(vad=EnergieVAD(), stille_ms=900)
    for r in rahmen_stille(5) + rahmen_sprache(10) + rahmen_stille(6) + rahmen_sprache(10):
        sp.zufuehren(r)
    assert sp.status is Status.SPRICHT


def test_keine_sprache_innerhalb_der_wartezeit():
    sp = Sprachpausenerkenner(vad=EnergieVAD(), warte_auf_sprache_s=1.0)
    stati = [sp.zufuehren(r) for r in rahmen_stille(20)]
    assert Status.KEINE_SPRACHE in stati
    assert stati.index(Status.KEINE_SPRACHE) == 12  # 13 Rahmen ≥ 1 s
    assert sp.audio() is None
    assert sp.fertig


def test_einzelnes_klicken_startet_keine_aufnahme():
    sp = Sprachpausenerkenner(vad=EnergieVAD(), min_sprache_ms=240, warte_auf_sprache_s=2.0)
    folge = rahmen_stille(5) + rahmen_sprache(1) + rahmen_stille(30, seed=2)
    for r in folge:
        sp.zufuehren(r)
    assert sp.status is Status.KEINE_SPRACHE


def test_max_aufnahme_begrenzt_dauer():
    sp = Sprachpausenerkenner(vad=EnergieVAD(), max_aufnahme_s=2.0)
    for r in rahmen_stille(3) + rahmen_sprache(60):
        if sp.zufuehren(r) is Status.FERTIG:
            break
    assert sp.status is Status.FERTIG
    assert sp.dauer_s == pytest.approx(2.0, abs=0.1)


def test_ignorierte_anfangszeit_zaehlt_nicht_als_sprache():
    """Der Bestätigungston am Anfang darf keinen Sprachbeginn auslösen."""
    sp = Sprachpausenerkenner(vad=EnergieVAD(), ignoriere_ms=240, min_sprache_ms=240, warte_auf_sprache_s=1.0)
    for r in rahmen_stille(3):
        sp.vad.ist_sprache(r)
    for r in rahmen_sprache(3) + rahmen_stille(20):
        sp.zufuehren(r)
    assert sp.status is Status.KEINE_SPRACHE


def test_erzeuge_vad_faellt_ohne_webrtcvad_auf_energie_zurueck(monkeypatch):
    monkeypatch.setitem(sys.modules, "webrtcvad", None)
    assert type(erzeuge_vad("auto")) is EnergieVAD
    assert type(erzeuge_vad("energie")) is EnergieVAD


def test_webrtc_vad_falls_installiert():
    pytest.importorskip("webrtcvad")
    from jarvis.stimme.vad import WebrtcVAD

    vad = erzeuge_vad("webrtc")
    assert isinstance(vad, WebrtcVAD)
    for r in rahmen_stille(20):
        assert not vad.ist_sprache(r)
    # Mit webrtcvad muss ein sprachähnliches Signal weiterhin zum Ende der Äußerung führen
    sp = Sprachpausenerkenner(vad=vad, stille_ms=500)
    for r in rahmen_sprache(15, amplitude=8000) + rahmen_stille(10, seed=4):
        sp.zufuehren(r)
    assert sp.status is Status.FERTIG
    assert sp.audio() is not None
