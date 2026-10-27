"""Zustandsmaschine des StimmDienstes mit gefälschter Audioquelle, Detektor, STT und TTS."""

from __future__ import annotations

import asyncio
import sys
import threading
import types

import numpy as np
import pytest
from stimme_hilfen import (
    FakeAbspieler,
    FakeDetektor,
    FakeQuelle,
    FakeSTT,
    FakeTTS,
    rahmen_sprache,
    rahmen_stille,
    rahmen_weckwort,
    warte_bis,
)

from jarvis.stimme import StimmDienst
from jarvis.stimme.fehler import StimmFehler

pytestmark = pytest.mark.asyncio

ANTWORT = "Es ist **zwölf** Uhr 🕛."


def baue(protokoll, einstellungen=None, anfrage=None, stt_texte=("Wie spät ist es?",), abspieler=None, **kw):
    stimme = {"vad": "energie", "folgemodus_s": 0, "bestaetigungston": True}
    stimme.update(einstellungen or {})
    t = types.SimpleNamespace(
        quelle=kw.pop("quelle", FakeQuelle()),
        detektor=kw.pop("detektor", FakeDetektor()),
        stt=FakeSTT(stt_texte),
        tts=kw.pop("tts", FakeTTS()),
        abspieler=abspieler or FakeAbspieler(),
        toene=[],
        anfragen=[],
        protokoll=protokoll,
    )

    async def standard_anfrage(text):
        t.anfragen.append(text)
        return ANTWORT

    t.dienst = StimmDienst(
        {"modell": "egal", "stimme": stimme},
        protokoll,
        anfrage or standard_anfrage,
        audioquelle=t.quelle,
        detektor=t.detektor,
        stt=t.stt,
        tts=t.tts,
        abspieler=t.abspieler,
        ton=lambda: t.toene.append(1),
        **kw,
    )
    t.dienst.nachlauf_s = 0.0
    return t


def aeusserung(sprache=10, stille=13):
    return rahmen_stille(2, seed=11) + rahmen_sprache(sprache) + rahmen_stille(stille, seed=12)


async def weckwort_sagen(t):
    await t.quelle.senden(rahmen_stille(5) + [rahmen_weckwort()])
    await warte_bis(lambda: t.dienst.hoert)


async def test_vollstaendiger_ablauf_events_in_richtiger_reihenfolge(protokoll):
    t = baue(protokoll)
    await t.dienst.start()
    assert t.dienst.aktiv and not t.dienst.hoert
    await weckwort_sagen(t)
    assert t.toene == [1]
    await t.quelle.senden(aeusserung())
    await warte_bis(lambda: protokoll.zustaende()[-1:] == ["bereit"] and "spricht" in protokoll.zustaende())

    assert t.anfragen == ["Wie spät ist es?"]
    assert protokoll.zustaende() == ["bereit", "hoert", "denkt", "spricht", "bereit"]
    assert protokoll.ohne_pegel() == [
        "zustand:bereit", "zustand:hoert", "transkript", "zustand:denkt", "zustand:spricht", "zustand:bereit",
    ]
    assert protokoll.typen("transkript") == [{"typ": "transkript", "text": "Wie spät ist es?", "final": True}]
    # Pegel während des Zuhörens (je Rahmen ≈ 12,5/s) und während des Sprechens
    marken = [e["typ"] if e["typ"] != "zustand" else e["zustand"] for e in protokoll.ereignisse]
    zwischen_hoert = marken[marken.index("hoert") : marken.index("transkript")]
    assert zwischen_hoert.count("pegel") >= 20
    pegel = [e["wert"] for e in protokoll.typen("pegel")]
    assert all(0.0 <= w <= 1.0 for w in pegel) and max(pegel) > 0.5
    # Aufgenommen wurde die Äußerung inkl. Vorlauf, ohne die lange Stille am Ende
    assert 10 * 1280 <= t.stt.aufrufe[0] <= 16 * 1280
    # TTS bekommt gesäuberten Text
    assert t.tts.texte == ["Es ist zwölf Uhr."]
    assert t.detektor.zurueckgesetzt >= 1
    assert not t.dienst.hoert
    await t.dienst.stop()
    assert t.quelle.gestoppt == 1 and not t.dienst.aktiv


async def test_ablauf_mit_webrtc_vad(protokoll):
    pytest.importorskip("webrtcvad")
    t = baue(protokoll, {"vad": "webrtc"})
    await t.dienst.start()
    await weckwort_sagen(t)
    await t.quelle.senden(aeusserung())
    await warte_bis(lambda: protokoll.zustaende()[-1:] == ["bereit"] and len(t.anfragen) == 1)
    assert protokoll.zustaende() == ["bereit", "hoert", "denkt", "spricht", "bereit"]
    await t.dienst.stop()


async def test_folgefrage_ohne_weckwort(protokoll):
    t = baue(protokoll, {"folgemodus_s": 1.0}, stt_texte=("Wie wird das Wetter?", "Und morgen?"))
    await t.dienst.start()
    await weckwort_sagen(t)
    await t.quelle.senden(aeusserung())
    await warte_bis(lambda: protokoll.zustaende()[-2:] == ["spricht", "hoert"])
    assert t.dienst.hoert
    await t.quelle.senden(aeusserung())  # ohne Weckwort
    await warte_bis(lambda: len(t.anfragen) == 2)
    await warte_bis(lambda: protokoll.zustaende()[-2:] == ["spricht", "hoert"])
    await t.quelle.senden(rahmen_stille(16, seed=3))  # Folgefenster (1 s) verstreicht
    await warte_bis(lambda: protokoll.zustaende()[-1] == "bereit")
    assert t.anfragen == ["Wie wird das Wetter?", "Und morgen?"]
    assert protokoll.zustaende() == [
        "bereit", "hoert", "denkt", "spricht", "hoert", "denkt", "spricht", "hoert", "bereit",
    ]
    assert t.detektor.geprueft_markiert == 1
    await t.dienst.stop()


async def test_weckwort_ohne_folgende_sprache_kehrt_zurueck(protokoll):
    t = baue(protokoll, {"warte_auf_sprache_s": 1.0})
    await t.dienst.start()
    await weckwort_sagen(t)
    await t.quelle.senden(rahmen_stille(15))
    await warte_bis(lambda: protokoll.zustaende()[-1] == "bereit" and not t.dienst.hoert)
    assert protokoll.zustaende() == ["bereit", "hoert", "bereit"]
    assert t.anfragen == [] and t.stt.aufrufe == []
    # danach funktioniert das Weckwort wieder
    await weckwort_sagen(t)
    await t.dienst.stop()


async def test_selbsthoeren_schutz_waehrend_der_ausgabe(protokoll):
    abspieler = FakeAbspieler(dauer_schritte=40, schritt_s=0.01)
    t = baue(protokoll, abspieler=abspieler)
    await t.dienst.start()
    await weckwort_sagen(t)
    await t.quelle.senden(aeusserung())
    await warte_bis(lambda: abspieler.laeuft.is_set())
    vorher = t.detektor.geprueft
    # Jarvis „hört“ sich selbst – auch das Weckwort im eigenen Text darf nichts auslösen
    await t.quelle.senden([rahmen_weckwort() for _ in range(5)] + rahmen_sprache(5))
    await warte_bis(lambda: protokoll.zustaende()[-1] == "bereit")
    assert t.detektor.geprueft == vorher  # während des Sprechens wird gar nicht ausgewertet
    assert abspieler.abgebrochen == 0
    assert protokoll.zustaende() == ["bereit", "hoert", "denkt", "spricht", "bereit"]
    assert t.anfragen == ["Wie spät ist es?"]
    await t.dienst.stop()


async def test_nachhall_nach_der_ausgabe_wird_ignoriert(protokoll):
    t = baue(protokoll)
    await t.dienst.start()
    t.dienst.nachlauf_s = 0.4
    await t.dienst.sprechen("Hallo, ich bin Jarvis.")
    await t.quelle.senden([rahmen_weckwort()])
    await asyncio.sleep(0.05)
    assert not t.dienst.hoert
    await asyncio.sleep(0.4)
    await weckwort_sagen(t)
    await t.dienst.stop()


async def test_barge_in_weckwort_stoppt_ausgabe(protokoll):
    abspieler = FakeAbspieler(dauer_schritte=300, schritt_s=0.01)
    t = baue(protokoll, {"unterbrechen": True}, stt_texte=("Erzähl was", "Stopp, wie spät ist es?"), abspieler=abspieler)
    await t.dienst.start()
    await weckwort_sagen(t)
    await t.quelle.senden(aeusserung())
    await warte_bis(lambda: abspieler.laeuft.is_set())
    await t.quelle.senden([rahmen_weckwort()])
    await warte_bis(lambda: t.dienst.hoert)
    assert abspieler.abgebrochen >= 1
    await t.quelle.senden(aeusserung())
    await warte_bis(lambda: len(t.anfragen) == 2)
    assert t.anfragen == ["Erzähl was", "Stopp, wie spät ist es?"]
    await t.dienst.stop()


async def test_push_to_talk_ohne_gestartetes_mikrofon(protokoll):
    t = baue(protokoll)
    assert not t.dienst.aktiv
    aufgabe = asyncio.create_task(t.dienst.einmal_zuhoeren(warten=True))
    await warte_bis(lambda: t.dienst.hoert)
    assert t.quelle.gestartet == 1 and not t.dienst.aktiv  # Mikrofon offen, aber kein Weckwort
    await t.quelle.senden(aeusserung())
    assert await asyncio.wait_for(aufgabe, 3) == "Wie spät ist es?"
    assert t.quelle.gestoppt == 1
    assert t.detektor.geprueft == 0
    assert protokoll.zustaende() == ["hoert", "denkt", "spricht", "bereit"]
    assert t.dienst.modus == "aus"


async def test_push_to_talk_bei_aktivem_dienst_kehrt_sofort_zurueck(protokoll):
    t = baue(protokoll)
    await t.dienst.start()
    assert await t.dienst.einmal_zuhoeren() is True
    assert t.dienst.hoert
    await t.quelle.senden(aeusserung())
    await warte_bis(lambda: protokoll.zustaende()[-1] == "bereit" and len(t.anfragen) == 1)
    assert t.quelle.gestoppt == 0 and t.dienst.aktiv
    await t.dienst.stop()


async def test_sprechen_oeffentlich(protokoll):
    t = baue(protokoll)
    await t.dienst.sprechen("## Hinweis\nDer **Timer** ist abgelaufen ⏰ https://example.com/x")
    assert t.tts.texte == ["Hinweis.", "Der Timer ist abgelaufen example.com."]
    assert protokoll.zustaende() == ["spricht", "bereit"]
    await t.dienst.sprechen("   ")
    await t.dienst.sprechen("🎉")
    assert len(t.tts.texte) == 2


async def test_sprechen_mit_tts_aus(protokoll):
    t = baue(protokoll, {"tts": "aus"}, tts=None)
    await t.dienst.sprechen("Hallo")
    assert protokoll.ereignisse == []


async def test_anfrage_ohne_tts_dialog_endet_bereit(protokoll):
    t = baue(protokoll, {"tts": "aus"}, tts=None)
    await t.dienst.start()
    await weckwort_sagen(t)
    await t.quelle.senden(aeusserung())
    await warte_bis(lambda: len(t.anfragen) == 1 and protokoll.zustaende()[-1] == "bereit")
    assert protokoll.zustaende() == ["bereit", "hoert", "denkt", "bereit"]
    await t.dienst.stop()


async def test_rahmen_aus_fremdem_thread(protokoll):
    """Der Rückruf kommt im echten Betrieb aus dem PortAudio-Thread."""
    t = baue(protokoll)
    await t.dienst.start()
    rahmen = rahmen_stille(5) + [rahmen_weckwort()]
    thread = threading.Thread(target=lambda: [t.quelle.rueckruf(r) for r in rahmen])
    thread.start()
    thread.join()
    await warte_bis(lambda: t.dienst.hoert)
    await t.dienst.stop()


async def test_stop_waehrend_des_dialogs(protokoll):
    gestartet = asyncio.Event()

    async def langsame_anfrage(text):
        gestartet.set()
        await asyncio.sleep(10)
        return "zu spät"

    t = baue(protokoll, anfrage=langsame_anfrage)
    await t.dienst.start()
    await weckwort_sagen(t)
    await t.quelle.senden(aeusserung())
    await asyncio.wait_for(gestartet.wait(), 3)
    await asyncio.wait_for(t.dienst.stop(), 2)
    assert not t.dienst.aktiv and t.dienst.modus == "aus"
    assert protokoll.zustaende()[-1] == "bereit"
    assert t.tts.texte == []


# ---------------------------------------------------------------------------------------- Fehlerpfade


class PortAudioError(Exception):
    pass


async def test_portaudio_fehler_wird_fehler_event(protokoll, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")

    class InputStream:
        def __init__(self, **kwargs):
            raise PortAudioError("Error opening InputStream: Internal PortAudio error [PaErrorCode -9986]")

    sd = types.SimpleNamespace(
        PortAudioError=PortAudioError,
        check_input_settings=lambda **k: None,
        query_devices=lambda *a, **k: {"default_samplerate": 16000.0},
        InputStream=InputStream,
    )
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    t = baue(protokoll, quelle=None)  # Standard: echte MikrofonQuelle (mit gefälschtem sounddevice)
    await t.dienst.start()  # darf nicht werfen
    assert not t.dienst.aktiv
    (text,) = protokoll.fehlertexte()
    assert "Datenschutz & Sicherheit → Mikrofon → Terminal" in text


async def test_kein_mikrofon_ohne_portaudio(protokoll, monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", None)  # Import schlägt fehl
    t = baue(protokoll, quelle=None)
    await t.dienst.start()
    assert not t.dienst.aktiv
    assert "sounddevice" in protokoll.fehlertexte()[0]
    assert await t.dienst.einmal_zuhoeren() is False


async def test_beliebige_ausnahme_der_quelle(protokoll):
    t = baue(protokoll, quelle=FakeQuelle(fehler=RuntimeError("Error querying device -1")))
    await t.dienst.start()
    assert not t.dienst.aktiv
    assert protokoll.fehlertexte()[0].startswith("Kein Mikrofon gefunden")


async def test_weckwort_modell_nicht_ladbar(protokoll):
    class KaputterDetektor(FakeDetektor):
        _modell = None

        def laden(self):
            raise StimmFehler("Weckwort-Modell konnte nicht heruntergeladen werden (offline).")

    t = baue(protokoll, detektor=KaputterDetektor())
    await t.dienst.start()
    assert not t.dienst.aktiv and t.quelle.gestartet == 0
    assert protokoll.fehlertexte() == ["Weckwort-Modell konnte nicht heruntergeladen werden (offline)."]


async def test_detektor_faellt_im_betrieb_aus(protokoll):
    class Wackelig(FakeDetektor):
        def pruefen(self, rahmen):
            raise RuntimeError("onnx kaputt")

    t = baue(protokoll, detektor=Wackelig())
    await t.dienst.start()
    await t.quelle.senden(rahmen_stille(5))
    await warte_bis(lambda: protokoll.fehlertexte())
    assert "Weckwort-Erkennung ausgefallen" in protokoll.fehlertexte()[0]
    assert len(protokoll.fehlertexte()) == 1  # kein Fehler-Spam
    await t.dienst.stop()


async def test_fehler_in_anfrage_stt_und_tts(protokoll):
    async def kaputte_anfrage(text):
        raise RuntimeError("LLM nicht erreichbar")

    t = baue(protokoll, anfrage=kaputte_anfrage)
    await t.dienst.start()
    await weckwort_sagen(t)
    await t.quelle.senden(aeusserung())
    await warte_bis(lambda: protokoll.fehlertexte() and protokoll.zustaende()[-1] == "bereit")
    assert "LLM nicht erreichbar" in protokoll.fehlertexte()[0]
    await t.dienst.stop()

    class KaputteSTT(FakeSTT):
        async def transkribieren(self, audio):
            raise StimmFehler("Spracherkennung fehlgeschlagen (kaputt).")

    class KaputteTTS(FakeTTS):
        async def synthetisieren(self, text, ziel):
            raise StimmFehler("say ist fehlgeschlagen: kaputt")

    for name, wert in (("stt", KaputteSTT()), ("tts", KaputteTTS())):
        protokoll.ereignisse.clear()
        t = baue(protokoll)
        setattr(t.dienst, f"_{name}_vorgabe", wert)
        await t.dienst.start()
        await weckwort_sagen(t)
        await t.quelle.senden(aeusserung())
        await warte_bis(lambda: protokoll.fehlertexte() and protokoll.zustaende()[-1] == "bereit")
        assert "fehlgeschlagen" in protokoll.fehlertexte()[0]
        await weckwort_sagen(t)  # Dienst läuft weiter
        await t.dienst.stop()


async def test_defekter_ereignis_empfaenger_stoppt_nichts():
    zaehler = {"n": 0}

    async def kaputt(ereignis):
        zaehler["n"] += 1
        raise ConnectionError("WebSocket zu")

    t = baue(kaputt)
    await t.dienst.start()
    await weckwort_sagen(t)
    await t.quelle.senden(aeusserung())
    await warte_bis(lambda: len(t.anfragen) == 1 and not t.dienst.hoert and t.dienst.modus == "bereit")
    assert zaehler["n"] > 5
    await t.dienst.stop()


async def test_fehlende_mikrofonberechtigung_nur_nullen(protokoll, monkeypatch):
    monkeypatch.setenv("JARVIS_PLATTFORM", "mac")  # Hinweistext des Macs (Windows/Linux: tests/test_plattform_stimme.py)
    t = baue(protokoll)
    await t.dienst.start()
    await t.quelle.senden([np.zeros(1280, dtype=np.int16) for _ in range(40)])
    await warte_bis(lambda: protokoll.fehlertexte())
    assert "Berechtigung" in protokoll.fehlertexte()[0]
    assert "Datenschutz & Sicherheit" in protokoll.fehlertexte()[0]
    await t.dienst.stop()


async def test_start_und_stop_mehrfach(protokoll):
    t = baue(protokoll)
    await t.dienst.start()
    await t.dienst.start()
    assert t.quelle.gestartet == 1
    await t.dienst.stop()
    await t.dienst.stop()
    await t.dienst.start()
    assert t.dienst.aktiv and t.quelle.gestartet == 2
    await weckwort_sagen(t)
    await t.dienst.stop()


async def test_rueckfrage_per_sprache_waehrend_der_anfrage(protokoll):
    """Freigabe per Sprache: die Anfrage fragt nach („Soll ich …?“) und hört auf „Ja“."""
    holder = {}

    async def anfrage_mit_rueckfrage(text):
        dienst = holder["t"].dienst
        await dienst.sprechen("Soll ich die Datei wirklich löschen?")
        holder["antwort"] = await dienst.antwort_abhoeren(warte_s=2)
        return "Erledigt." if holder["antwort"] == "Ja." else "Abgebrochen."

    t = baue(protokoll, anfrage=anfrage_mit_rueckfrage, stt_texte=("Lösche die Datei", "Ja."))
    holder["t"] = t
    await t.dienst.start()
    await weckwort_sagen(t)
    await t.quelle.senden(aeusserung())
    await warte_bis(lambda: protokoll.zustaende().count("hoert") == 2)
    await t.quelle.senden(aeusserung(sprache=5))
    await warte_bis(lambda: protokoll.zustaende()[-1] == "bereit" and "antwort" in holder)
    assert holder["antwort"] == "Ja."
    assert t.tts.texte == ["Soll ich die Datei wirklich löschen?", "Erledigt."]
    assert protokoll.zustaende() == ["bereit", "hoert", "denkt", "spricht", "hoert", "denkt", "spricht", "bereit"]
    assert [e["text"] for e in protokoll.typen("transkript")] == ["Lösche die Datei", "Ja."]
    await t.dienst.stop()


async def test_antwort_abhoeren_ohne_mikrofon_und_ohne_sprache(protokoll):
    t = baue(protokoll, {"warte_auf_sprache_s": 1.0})
    aufgabe = asyncio.create_task(t.dienst.antwort_abhoeren())
    await warte_bis(lambda: t.dienst.hoert)
    await t.quelle.senden(rahmen_stille(15))
    assert await asyncio.wait_for(aufgabe, 3) is None
    assert t.quelle.gestoppt == 1 and t.dienst.modus == "aus"
    assert protokoll.zustaende() == ["hoert", "bereit"]
