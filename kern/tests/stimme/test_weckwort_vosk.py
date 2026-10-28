"""Freies Weckwort „Javit“ mit Vosk – offline mit gefälschtem ``vosk``-Modul (KaldiRecognizer)."""

from __future__ import annotations

import io
import json
import sys
import types
import zipfile

import numpy as np
import pytest
from stimme_hilfen import FakeQuelle, FakeSTT, FakeTTS, rahmen_stille, warte_bis

from jarvis.konfig import weckwort_engine
from jarvis.stimme.einstellungen import StimmEinstellungen
from jarvis.stimme.fehler import StimmFehler
from jarvis.stimme.weckwort import OpenWakeWordDetektor, erzeuge_detektor
from jarvis.stimme.weckwort_vosk import (
    VoskWeckwortDetektor,
    WeckwortAbgleich,
    grammatik_bauen,
    koelner_phonetik,
    varianten_fuer,
    vosk_modell_sicherstellen,
    weckwoerter,
)

#: Wörter, die das (gefälschte) deutsche Kleinmodell kennt – „javit“ gehört bewusst nicht dazu
VOKABULAR = {"ja", "witt", "fit", "wie", "wir", "mit", "bitte", "david", "java", "hey", "hallo", "und", "die", "das",
             "ist", "nicht", "was", "zeit", "danke", "gut", "jetzt", "wird", "nein", "jawohl", "wo", "da", "computer"}


# ---------------------------------------------------------------------------------------
# Gefälschtes vosk-Paket
# ---------------------------------------------------------------------------------------
class FakeKaldi:
    """Liefert je ``AcceptWaveform`` den nächsten Eintrag aus ``skript``: ("p", text) = Teilergebnis,
    ("f", text) = Endergebnis, None = Stille."""

    alle: list["FakeKaldi"] = []

    def __init__(self, modell, rate, grammatik=None):
        self.modell, self.rate = modell, rate
        self.grammatik = json.loads(grammatik) if grammatik else None
        self.skript: list = []
        self.aktuell = ("p", "")
        self.resets = 0
        self.daten = []
        FakeKaldi.alle.append(self)

    def SetWords(self, _):  # noqa: N802 – Vosk-API
        pass

    def AcceptWaveform(self, daten):  # noqa: N802
        self.daten.append(daten)
        self.aktuell = self.skript.pop(0) if self.skript else None
        if self.aktuell is None:
            self.aktuell = ("p", "")
        return self.aktuell[0] == "f"

    def Result(self):  # noqa: N802
        return json.dumps({"text": self.aktuell[1]})

    def PartialResult(self):  # noqa: N802
        return json.dumps({"partial": self.aktuell[1]})

    def Reset(self):  # noqa: N802
        self.resets += 1


@pytest.fixture
def fake_vosk(monkeypatch):
    modul = types.ModuleType("vosk")
    modul.log_level = None
    modul.vokabular = set(VOKABULAR)

    class Model:
        def __init__(self, pfad):
            self.pfad = pfad

        def find_word(self, wort):
            return 7 if wort in modul.vokabular else -1

    def SetLogLevel(stufe):  # noqa: N802
        modul.log_level = stufe

    modul.Model, modul.KaldiRecognizer, modul.SetLogLevel = Model, FakeKaldi, SetLogLevel
    FakeKaldi.alle = []
    monkeypatch.setitem(sys.modules, "vosk", modul)
    return modul


@pytest.fixture
def modell_ordner(tmp_path):
    basis = tmp_path / "vosk"
    ordner = basis / "vosk-model-small-de-0.15"
    (ordner / "am").mkdir(parents=True)
    (ordner / "conf").mkdir()
    (ordner / "am" / "final.mdl").write_bytes(b"x")
    (ordner / "conf" / "model.conf").write_text("--x\n")
    return basis


def detektor_mit(skript, basis, **kw) -> VoskWeckwortDetektor:
    d = VoskWeckwortDetektor(verzeichnis=basis, **kw)
    d.laden()
    d._erkenner.skript = list(skript)
    return d


def rahmen() -> np.ndarray:
    return np.zeros(1280, dtype=np.int16)


def scores(d, n) -> list[float]:
    return [d.pruefen(rahmen()) for _ in range(n)]


# ---------------------------------------------------------------------------------------
# Textvergleich
# ---------------------------------------------------------------------------------------
def test_koelner_phonetik_bekannte_beispiele():
    assert koelner_phonetik("Müller-Lüdenscheidt") == "65752682"
    assert koelner_phonetik("Wikipedia") == "3412"
    assert koelner_phonetik("Breschnew") == "17863"
    # alle Schreibweisen von „Javit“ klingen gleich, „bitte“/„David“ nicht
    assert {koelner_phonetik(w) for w in ("javit", "jawit", "ja witt", "javid", "ja fit")} == {"032"}
    assert koelner_phonetik("ja bitte") != "032" and koelner_phonetik("david") != "032"


def test_weckwoerter_und_varianten():
    assert weckwoerter("Javit, hey Javit; ") == ["javit", "hey javit"]
    assert weckwoerter("hey_jarvis") == ["hey jarvis"]
    v = varianten_fuer("javit")
    assert {"javit", "jawit", "ja wit", "ja witt", "ja vit", "dschawit", "javid"} <= set(v)
    assert all(p.startswith("hey ") for p in varianten_fuer("hey javit"))


@pytest.mark.parametrize(
    ("text", "erwartet"),
    [
        ("ja witt", 1.0),  # bekannte Variante
        ("hallo javit wie spät ist es", 1.0),
        ("javiet", 0.7),  # nicht in der Liste, aber phonetisch gleich
        ("ja wiet", 0.7),
    ],
)
def test_abgleich_erkennt_javit(text, erwartet):
    score, treffer = WeckwortAbgleich(["javit"]).bewerten(text)
    assert score >= erwartet and treffer


@pytest.mark.parametrize(
    "text",
    ["ja", "ja bitte", "ja wie geht es", "david", "java", "jawohl", "ja wird gemacht", "nicht jetzt", "[unk]", "ja [unk] witt", ""],
)
def test_abgleich_keine_fehlausloesung(text):
    score, _ = WeckwortAbgleich(["javit"]).bewerten(text)
    assert score < 0.5, (text, score)


def test_eigene_varianten_ersetzen_standards():
    a = WeckwortAbgleich(["javit"], ["schawitt"])
    assert a.phrasen == ["javit", "schawitt"]
    assert a.bewerten("schawitt")[0] == 1.0


def test_grammatik_nur_aus_bekannten_woertern():
    a = WeckwortAbgleich(["javit"])
    g = grammatik_bauen(a, lambda w: w in VOKABULAR)
    assert "javit" not in g and "ja witt" in g and "ja fit" in g
    assert "bitte" in g and "david" in g and g[-1] == "[unk]"  # Füllwörter fangen Alltagssprache ab
    assert all(all(w in VOKABULAR for w in e.split()) for e in g if e != "[unk]")
    assert grammatik_bauen(a, lambda w: False) == []  # → freie Erkennung


# ---------------------------------------------------------------------------------------
# Detektor mit gefälschtem KaldiRecognizer
# ---------------------------------------------------------------------------------------
def test_detektor_erkennt_bei_teilergebnis_und_setzt_zurueck(fake_vosk, modell_ordner):
    d = detektor_mit([None, ("p", "ja"), ("p", "ja witt"), ("p", "ja witt")], modell_ordner)
    k = FakeKaldi.alle[-1]
    assert d.modus == "grammatik" and k.rate == 16000 and k.grammatik == d.grammatik
    assert fake_vosk.log_level == -1
    werte = scores(d, 3)
    assert werte[:2] == [0.0, pytest.approx(werte[1])] and werte[1] < 0.5
    assert werte[2] == 1.0  # exakte Variante → sofort
    assert k.resets == 1  # nach dem Treffer zurückgesetzt
    assert len(k.daten[0]) == 1280 * 2  # int16 → Bytes


def test_detektor_keine_fehlausloesung_bei_anderen_woertern(fake_vosk, modell_ordner):
    skript = [("p", "ja"), ("p", "ja bitte"), ("f", "ja bitte"), ("p", "david"), ("f", "david ist da"),
              ("p", "wie"), ("p", "wie spät"), ("f", "[unk] [unk]"), ("p", "jawohl"), ("f", "jawohl")]
    d = detektor_mit(skript, modell_ordner)
    assert max(scores(d, len(skript))) < 0.5
    assert FakeKaldi.alle[-1].resets == 0


def test_phonetischer_treffer_erst_wenn_stabil(fake_vosk, modell_ordner):
    # „javiet“ ist keine Variante, aber phonetisch gleich → erst beim zweiten gleichen Teilergebnis
    d = detektor_mit([("p", "javiet"), ("p", "javiet")], modell_ordner)
    erster, zweiter = scores(d, 2)
    assert erster == 0.0 and zweiter >= 0.7
    # flackernde Hypothese löst nicht aus
    d = detektor_mit([("p", "javiet"), ("p", "ja wie"), ("p", "javiet"), ("p", "ja")], modell_ordner)
    assert max(scores(d, 4)) == 0.0
    # im Endergebnis zählt der Treffer sofort
    d = detektor_mit([("f", "javiet")], modell_ordner)
    assert d.pruefen(rahmen()) >= 0.7


def test_schwelle_steuert_empfindlichkeit(fake_vosk, modell_ordner):
    streng = detektor_mit([("f", "javiet")], modell_ordner, schwelle=0.97)
    assert streng.pruefen(rahmen()) < 0.97 and FakeKaldi.alle[-1].resets == 0
    locker = detektor_mit([("f", "ja witz")], modell_ordner, schwelle=0.3)
    assert locker.pruefen(rahmen()) >= 0.3 and FakeKaldi.alle[-1].resets == 1


def test_mehrere_weckwoerter_und_eigene_varianten(fake_vosk, modell_ordner):
    fake_vosk.vokabular |= {"computer"}
    d = detektor_mit([("p", "hallo computer")], modell_ordner, weckwort="javit, computer")
    assert "computer" in d.grammatik
    assert d.pruefen(rahmen()) == 1.0
    d = detektor_mit([("p", "ja fit")], modell_ordner, varianten=["ja fit"])
    assert d.abgleich.phrasen == ["javit", "ja fit"] and d.pruefen(rahmen()) == 1.0


def test_freie_erkennung_ohne_bekannte_variante(fake_vosk, modell_ordner):
    fake_vosk.vokabular = {"hallo"}
    d = detektor_mit([("f", "javiet")], modell_ordner)
    assert d.modus == "frei" and d.grammatik == [] and FakeKaldi.alle[-1].grammatik is None
    assert d.pruefen(rahmen()) >= 0.7


def test_zuruecksetzen_leert_zustand(fake_vosk, modell_ordner):
    d = detektor_mit([("p", "javiet")], modell_ordner)
    assert d.pruefen(rahmen()) == 0.0
    d.zuruecksetzen()
    d._erkenner.skript = [("p", "javiet")]
    assert d.pruefen(rahmen()) == 0.0  # nach Reset gilt das alte Teilergebnis nicht als „stabil“
    assert FakeKaldi.alle[-1].resets == 1


# ---------------------------------------------------------------------------------------
# Modell: fehlt / Download / Prüfung
# ---------------------------------------------------------------------------------------
def test_fehlendes_modell_ohne_download(fake_vosk, tmp_path):
    d = VoskWeckwortDetektor(verzeichnis=tmp_path / "leer")
    with pytest.raises(StimmFehler, match="Vosk-Modell „vosk-model-small-de-0.15“ fehlt und Downloads sind abgeschaltet"):
        d.laden()
    assert not (tmp_path / "leer").exists()


def test_vosk_nicht_installiert(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "vosk", None)
    with pytest.raises(StimmFehler, match="Vosk .*ist nicht installiert.*Installer erneut.*jarvis\\[stimme\\].*hey_jarvis"):
        VoskWeckwortDetektor(verzeichnis=tmp_path).laden()


def _zip(eintraege: dict[str, bytes]) -> bytes:
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        for name, inhalt in eintraege.items():
            z.writestr(name, inhalt)
    return puffer.getvalue()


MODELL_ZIP = {
    "vosk-model-small-de-0.15/am/final.mdl": b"mdl",
    "vosk-model-small-de-0.15/conf/model.conf": b"--x",
    "vosk-model-small-de-0.15/graph/Gr.fst": b"g",
}


def _lader(daten: bytes, aufrufe: list):
    import hashlib

    def herunterladen(url, ziel):
        aufrufe.append(url)
        ziel.write_bytes(daten)
        return hashlib.sha256(daten).hexdigest()

    return herunterladen


def test_download_pruefen_und_entpacken(monkeypatch, tmp_path):
    monkeypatch.delenv("JARVIS_KEIN_DOWNLOAD", raising=False)
    import hashlib

    daten, aufrufe = _zip(MODELL_ZIP), []
    ordner = vosk_modell_sicherstellen(verzeichnis=tmp_path, sha256=hashlib.sha256(daten).hexdigest(), herunterladen=_lader(daten, aufrufe))
    assert aufrufe == ["https://alphacephei.com/vosk/models/vosk-model-small-de-0.15.zip"]
    assert ordner == tmp_path / "vosk-model-small-de-0.15" and (ordner / "graph" / "Gr.fst").read_bytes() == b"g"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["vosk-model-small-de-0.15"]  # keine Reste
    # zweiter Aufruf: kein erneuter Download
    vosk_modell_sicherstellen(verzeichnis=tmp_path, herunterladen=_lader(daten, aufrufe))
    assert len(aufrufe) == 1


@pytest.mark.parametrize(
    ("eintraege", "sha", "meldung"),
    [
        ({"../boese.txt": b"x", **MODELL_ZIP}, "", "unzulässigen Pfad"),
        ({"/abs/boese.txt": b"x", **MODELL_ZIP}, "", "unzulässigen Pfad"),
        ({"vosk-model-small-de-0.15/README": b"x"}, "", "unvollständig"),
        (MODELL_ZIP, "0" * 64, "Prüfsumme"),
    ],
)
def test_download_abgelehnt(monkeypatch, tmp_path, eintraege, sha, meldung):
    monkeypatch.delenv("JARVIS_KEIN_DOWNLOAD", raising=False)
    with pytest.raises(StimmFehler, match=meldung):
        vosk_modell_sicherstellen(verzeichnis=tmp_path, sha256=sha, herunterladen=_lader(_zip(eintraege), []))
    assert not (tmp_path.parent / "boese.txt").exists()
    assert [p.name for p in tmp_path.iterdir()] == []  # Reste aufgeräumt


@pytest.mark.parametrize("name", [".", "..", "a..b", "-x", "ä-modell", ""])
def test_ungueltiger_modellname_loescht_nichts(monkeypatch, tmp_path, name):
    """„.“/„..“ als Modellname dürfen nie zu shutil.rmtree auf den Modell- bzw. Elternordner führen."""
    monkeypatch.delenv("JARVIS_KEIN_DOWNLOAD", raising=False)
    basis = tmp_path / "modelle" / "vosk"
    basis.mkdir(parents=True)
    (basis / "wichtig.txt").write_text("bleibt")
    (tmp_path / "modelle" / "auch_wichtig.txt").write_text("bleibt")
    aufrufe: list = []
    if name == "":  # leer = Standardmodell (gültig)
        vosk_modell_sicherstellen(name, basis, herunterladen=_lader(_zip(MODELL_ZIP), aufrufe))
        assert len(aufrufe) == 1
    else:
        with pytest.raises(StimmFehler, match="Ungültiger Vosk-Modellname"):
            vosk_modell_sicherstellen(name, basis, herunterladen=_lader(_zip(MODELL_ZIP), aufrufe))
        assert aufrufe == []
    assert (basis / "wichtig.txt").read_text() == "bleibt"
    assert (tmp_path / "modelle" / "auch_wichtig.txt").read_text() == "bleibt"


def test_zip_mit_symlink_und_zip_bombe_abgelehnt(monkeypatch, tmp_path):
    monkeypatch.delenv("JARVIS_KEIN_DOWNLOAD", raising=False)
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        for name, inhalt in MODELL_ZIP.items():
            z.writestr(name, inhalt)
        link = zipfile.ZipInfo("vosk-model-small-de-0.15/link")
        link.external_attr = (0o120777 << 16)
        z.writestr(link, "/etc/passwd")
    with pytest.raises(StimmFehler, match="symbolischen Link"):
        vosk_modell_sicherstellen(verzeichnis=tmp_path / "a", herunterladen=_lader(puffer.getvalue(), []))
    import jarvis.stimme.weckwort_vosk as wv

    monkeypatch.setattr(wv, "MAX_ENTPACKT_BYTES", 5)
    with pytest.raises(StimmFehler, match="entpackt unerwartet groß"):
        vosk_modell_sicherstellen(verzeichnis=tmp_path / "b", herunterladen=_lader(_zip(MODELL_ZIP), []))
    assert [p.name for p in (tmp_path / "b").iterdir()] == []


def test_download_fehler_und_kaputtes_zip(monkeypatch, tmp_path):
    monkeypatch.delenv("JARVIS_KEIN_DOWNLOAD", raising=False)

    def offline(url, ziel):
        raise OSError("Netz weg")

    with pytest.raises(StimmFehler, match="nicht heruntergeladen.*alphacephei.com"):
        vosk_modell_sicherstellen(verzeichnis=tmp_path, herunterladen=offline)
    with pytest.raises(StimmFehler, match="kein gültiges ZIP"):
        vosk_modell_sicherstellen(verzeichnis=tmp_path, herunterladen=_lader(b"kein zip", []))


def test_eigener_modellordner(modell_ordner, tmp_path):
    eigener = modell_ordner / "vosk-model-small-de-0.15"
    assert vosk_modell_sicherstellen(str(eigener), tmp_path / "egal") == eigener
    with pytest.raises(StimmFehler, match="nicht gefunden"):
        vosk_modell_sicherstellen(str(tmp_path / "gibtsnicht"), tmp_path)


# ---------------------------------------------------------------------------------------
# Engine-Auswahl und eigenes openWakeWord-Modell
# ---------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("stimme", "engine"),
    [
        ({}, "vosk"),
        ({"weckwort": "javit"}, "vosk"),
        ({"weckwort": "javit, hey javit"}, "vosk"),
        ({"weckwort": "hey_jarvis"}, "openwakeword"),
        ({"weckwort": "Hey Jarvis"}, "openwakeword"),
        ({"weckwort": "computer"}, "vosk"),
        ({"weckwort": "javit", "weckwort_modell_pfad": "~/javit.onnx"}, "openwakeword"),
        ({"weckwort": "hey_jarvis", "weckwort_engine": "vosk"}, "vosk"),
        ({"weckwort": "javit", "weckwort_engine": "openwakeword"}, "openwakeword"),
    ],
)
def test_engine_auswahl(stimme, engine):
    e = StimmEinstellungen.aus({"stimme": stimme})
    assert weckwort_engine(e) == engine
    d = erzeuge_detektor(e)
    assert d.engine == engine
    assert isinstance(d, VoskWeckwortDetektor if engine == "vosk" else OpenWakeWordDetektor)


def test_vosk_detektor_uebernimmt_einstellungen(tmp_path):
    e = StimmEinstellungen.aus({"stimme": {"weckwort": "javit", "weckwort_varianten": "ja fit; jawitt", "schwelle": 0.8,
                                           "modell_verzeichnis": str(tmp_path)}})
    d = erzeuge_detektor(e)
    assert d.abgleich.phrasen == ["javit", "ja fit", "jawitt"] and d.schwelle == 0.8
    assert d.verzeichnis == tmp_path / "vosk" and d.modell_name == "vosk-model-small-de-0.15"


@pytest.fixture
def fake_oww(monkeypatch):
    aufrufe = {"download": [], "model": []}
    paket = types.ModuleType("openwakeword")
    paket.MODELS = {"hey_jarvis": {}, "alexa": {}}
    modell_modul = types.ModuleType("openwakeword.model")
    utils = types.ModuleType("openwakeword.utils")

    class Model:
        def __init__(self, **kw):
            aufrufe["model"].append(kw)
            self.zurueck = 0

        def predict(self, rahmen):
            return {"javit": 0.93 if int(rahmen[0]) == 777 else 0.02}

        def reset(self):
            self.zurueck += 1

    def download_models(model_names, target_directory):
        aufrufe["download"].append(model_names)
        for m in ("melspectrogram.onnx", "embedding_model.onnx"):
            (__import__("pathlib").Path(target_directory) / m).write_bytes(b"m")

    modell_modul.Model, utils.download_models = Model, download_models
    for name, modul in (("openwakeword", paket), ("openwakeword.model", modell_modul), ("openwakeword.utils", utils)):
        monkeypatch.setitem(sys.modules, name, modul)
    return aufrufe


def test_eigenes_onnx_modell(fake_oww, tmp_path):
    oww = tmp_path / "openwakeword"
    oww.mkdir()
    (oww / "javit.onnx").write_bytes(b"onnx")
    e = StimmEinstellungen.aus({"stimme": {"weckwort": "javit", "weckwort_modell_pfad": "javit.onnx",
                                           "modell_verzeichnis": str(tmp_path)}})
    d = erzeuge_detektor(e)
    d.laden()
    # nur Merkmalsmodelle nachgeladen – kein offizielles Weckwort-Modell
    assert fake_oww["download"] == [["__nur_merkmale__"]]
    kw = fake_oww["model"][0]
    assert kw["wakeword_models"] == [str(oww / "javit.onnx")] and kw["inference_framework"] == "onnx"
    assert kw["melspec_model_path"] == str(oww / "melspectrogram.onnx")
    r = np.zeros(1280, dtype=np.int16)
    assert d.pruefen(r) < 0.5
    r[0] = 777
    assert d.pruefen(r) > 0.9 and d.weckwort == "javit"
    # zweites Laden: Merkmale vorhanden → kein Download
    erzeuge_detektor(e).laden()
    assert len(fake_oww["download"]) == 1


def test_eigenes_onnx_modell_absolut_und_fehlend(fake_oww, tmp_path):
    datei = tmp_path / "irgendwo" / "mein.onnx"
    datei.parent.mkdir()
    datei.write_bytes(b"x")
    d = OpenWakeWordDetektor("javit", tmp_path / "oww", modell_pfad=str(datei))
    d.laden()
    assert fake_oww["model"][0]["wakeword_models"] == [str(datei)]
    with pytest.raises(StimmFehler, match="Eigenes Weckwort-Modell nicht gefunden.*weckwort-trainieren.md"):
        OpenWakeWordDetektor("javit", tmp_path / "oww", modell_pfad="fehlt.onnx").laden()
    with pytest.raises(StimmFehler, match="muss eine .onnx-Datei sein"):
        OpenWakeWordDetektor("javit", tmp_path / "oww", modell_pfad=str(tmp_path / "irgendwo")).laden()


# ---------------------------------------------------------------------------------------
# Im StimmDienst
# ---------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dienst_fehlendes_vosk_modell_meldet_fehler(fake_vosk, protokoll, tmp_path):
    from jarvis.stimme import StimmDienst

    quelle = FakeQuelle()
    dienst = StimmDienst(
        {"stimme": {"weckwort": "javit", "modell_verzeichnis": str(tmp_path), "vad": "energie"}},
        protokoll, lambda t: None, audioquelle=quelle, stt=FakeSTT(()), tts=FakeTTS(),
    )
    await dienst.start()
    assert not dienst.aktiv and quelle.gestartet == 0
    assert "Vosk-Modell „vosk-model-small-de-0.15“ fehlt" in protokoll.fehlertexte()[0]
    await dienst.stop()


@pytest.mark.asyncio
async def test_dienst_mit_vosk_detektor_wacht_auf(fake_vosk, protokoll, modell_ordner):
    from jarvis.stimme import StimmDienst

    quelle = FakeQuelle()
    dienst = StimmDienst(
        {"stimme": {"weckwort": "javit", "modell_verzeichnis": str(modell_ordner.parent), "vad": "energie",
                    "folgemodus_s": 0, "warte_auf_sprache_s": 1.0}},
        protokoll, lambda t: None, audioquelle=quelle, stt=FakeSTT(()), tts=FakeTTS(), ton=lambda: None,
    )
    # modell_verzeichnis/vosk/<modell> – die Fixture legt das Modell unter <tmp>/vosk an
    await dienst.start()
    assert dienst.aktiv and getattr(dienst._detektor, "engine", "") == "vosk"
    FakeKaldi.alle[-1].skript = [None, ("p", "hallo"), ("p", "hallo ja witt")]
    await quelle.senden(rahmen_stille(3))
    await warte_bis(lambda: "hoert" in protokoll.zustaende())
    assert FakeKaldi.alle[-1].resets >= 1
    await dienst.stop()


def test_modelle_laden_fuer_installer(fake_vosk, fake_oww, modell_ordner, capsys, monkeypatch):
    """``python -m jarvis.stimme --modelle-laden --alle`` (Installer): Vosk „javit“ + openWakeWord."""
    import argparse

    from jarvis.konfig import KonfigSpeicher
    from jarvis.stimme.__main__ import modelle_laden

    KonfigSpeicher().aktualisieren({"stimme": {"modell_verzeichnis": str(modell_ordner.parent)}})
    oww = modell_ordner.parent / "openwakeword"
    oww.mkdir()
    for datei in ("melspectrogram.onnx", "embedding_model.onnx", "hey_jarvis_v0.1.onnx"):
        (oww / datei).write_bytes(b"x")
    args = argparse.Namespace(alle=True, weckwort=None, weckwort_engine=None, weckwort_modell_pfad=None,
                              stt=None, stt_modell=None, tts=None, tts_stimme=None, schwelle=None)
    assert modelle_laden(args) == 0
    ausgabe = capsys.readouterr().out
    assert "Vosk: Weckwort-Modell „javit“ bereit." in ausgabe and "openWakeWord: Weckwort-Modell „hey_jarvis“ bereit." in ausgabe
    # fehlendes Vosk-Modell → Rückgabe 1 und deutsche Meldung
    KonfigSpeicher().aktualisieren({"stimme": {"modell_verzeichnis": str(modell_ordner.parent / "leer")}})
    args.alle = False
    assert modelle_laden(args) == 1
    assert "Downloads sind abgeschaltet" in capsys.readouterr().out


def test_nur_ganz_erkennt_stoppwort_nur_allein(fake_vosk, modell_ordner):
    from jarvis.stimme.weckwort_vosk import ganze_aeusserung

    assert ganze_aeusserung("stopp", "stopp") and ganze_aeusserung("[unk] stopp [unk]", "stopp")
    assert not ganze_aeusserung("das ist stopp und so", "stopp") and not ganze_aeusserung("stopp halt", "stopp")
    fake_vosk.vokabular.update({"stopp", "stop", "halt"})
    skript = [("p", "stopp halt"), ("p", "das ist stopp"), ("f", "halt mal stopp"), ("p", "stopp"), ("p", "stopp")]
    d = detektor_mit(skript, modell_ordner, weckwort="stopp", varianten=["stop", "stopp", "halt"], nur_ganz=True)
    werte = scores(d, len(skript))
    assert max(werte[:3]) == 0.0  # Stoppwort mitten in anderer Sprache zählt nicht
    assert werte[3] == 0.0 and werte[4] == 1.0  # alleinstehend, aber erst beim zweiten gleichen Teilergebnis


def test_nur_ganz_loest_nicht_beim_ersten_teilergebnis_aus(fake_vosk, modell_ordner):
    fake_vosk.vokabular.update({"stopp", "stop", "halt"})
    # ein einzelnes „stopp“-Teilergebnis zählt nicht, erst das zweite gleiche – oder ein Endergebnis
    skript = [("p", "stopp"), ("p", "halt"), ("p", "stopp"), ("p", "stopp"), None, ("f", "stopp")]
    d = detektor_mit(skript, modell_ordner, weckwort="stopp", varianten=["stop", "stopp", "halt"], nur_ganz=True)
    werte = scores(d, len(skript))
    assert werte[0] == 0.0 and werte[1] == 0.0 and werte[2] == 0.0
    assert werte[3] == 1.0 and d.letzter_treffer_text == "stopp"
    assert werte[5] == 1.0  # Endergebnis löst direkt aus
