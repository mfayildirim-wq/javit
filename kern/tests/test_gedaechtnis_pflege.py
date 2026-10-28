"""Gedächtnis-Optimierung: Hybridsuche, Einbettungsmodelle, lokale Einbettung, Nachbereitung."""

import json

from jarvis.gedaechtnis import Gedaechtnis


def einbetter_mit_modell(name: str, vektor_fuer):
    async def einbetten(texte):
        return [vektor_fuer(t) for t in texte]

    einbetten.modell = name
    return einbetten


async def test_fts_suche_ohne_vektoren(tmp_path):
    g = Gedaechtnis(tmp_path / "f.db")
    await g.erinnern("Fatih trinkt morgens Espresso ohne Zucker.")
    await g.erinnern("Das Auto ist blau.")
    treffer = await g.suchen("Espresso")
    assert [t["text"] for t in treffer] == ["Fatih trinkt morgens Espresso ohne Zucker."]
    assert treffer[0]["quelle"] == "nutzer" and treffer[0]["relevanz"] > 0
    # Teilwort über das bisherige Stichwortmaß (Präfix) bleibt erhalten
    assert await g.suchen("Espressomaschine", mindestwert=0.2)
    g.schliessen()


async def test_vektoren_verschiedener_modelle_werden_nicht_verglichen(tmp_path):
    # Modell A: alles zeigt in Richtung (1, 0); Modell B: Anfrage (0, 1) – ein Vergleich ergäbe 0
    a = einbetter_mit_modell("A", lambda t: [1.0, 0.0])
    g = Gedaechtnis(tmp_path / "m.db", einbetten=a)
    await g.erinnern("Der Nutzer wohnt in Köln.")
    zeile = g.erinnerungen()[0]
    assert zeile["einbettung_modell"] == "A"

    b = einbetter_mit_modell("B", lambda t: [0.0, 1.0])
    g2 = Gedaechtnis(tmp_path / "m.db", einbetten=b)
    # Vektor aus A wird mit Anfrage aus B nicht verglichen (sonst Kosinus 0 < Textwert); Textsuche findet trotzdem
    treffer = await g2.suchen("Köln")
    assert treffer and treffer[0]["text"] == "Der Nutzer wohnt in Köln."
    # Nachbetten: fehlende Vektoren für Modell B
    assert g2.fehlende_einbettungen("B") == [zeile["id"]]
    await g2.nachbetten(limit=10)
    assert g2.fehlende_einbettungen("B") == []
    assert g2.erinnerungen()[0]["einbettung_modell"] == "B"
    g.schliessen()
    g2.schliessen()


async def test_erinnerung_aktualisieren_und_loeschen(tmp_path):
    g = Gedaechtnis(tmp_path / "a.db")
    kennung = await g.erinnern("Lieblingsfarbe ist grün.", quelle="auto", unterhaltung_id=7)
    await g.erinnerung_aktualisieren(kennung, "Lieblingsfarbe ist blau.")
    e = g.erinnerungen()[0]
    assert e["text"] == "Lieblingsfarbe ist blau." and e["quelle"] == "auto" and e["aktualisiert"]
    assert await g.suchen("blau") and not await g.suchen("grün")
    assert g.erinnerung_loeschen(kennung) == 1
    assert not await g.suchen("blau")
    g.schliessen()


# ---------------------------------------------------------------- lokale Einbettung, Kette
import sys
import types

from jarvis.gedaechtnis_pflege import (
    BenannterEinbetter,
    EinbetterKette,
    LokaleEinbettung,
    Nachbereiter,
    json_block,
    titel_bereinigen,
    titel_fallback,
)
from tests.conftest import text_chunks
from tests.helfer import baue_jarvis


def fastembed_attrappe(monkeypatch, aufrufe: list):
    class TextEmbedding:
        def __init__(self, model_name, cache_dir):
            aufrufe.append(("laden", model_name, cache_dir))

        def embed(self, texte):
            aufrufe.append(("embed", list(texte)))
            for t in texte:
                yield [float(len(t)), 1.0]

    modul = types.ModuleType("fastembed")
    modul.TextEmbedding = TextEmbedding
    monkeypatch.setitem(sys.modules, "fastembed", modul)


async def test_lokale_einbettung_kein_download(tmp_path, monkeypatch):
    aufrufe: list = []
    fastembed_attrappe(monkeypatch, aufrufe)
    monkeypatch.setenv("JARVIS_KEIN_DOWNLOAD", "1")
    lokal = LokaleEinbettung(tmp_path / "einbettung")
    assert await lokal(["hallo"]) is None
    assert aufrufe == []  # Modell wurde nicht geladen


async def test_lokale_einbettung_aus_cache(tmp_path, monkeypatch):
    aufrufe: list = []
    fastembed_attrappe(monkeypatch, aufrufe)
    monkeypatch.setenv("JARVIS_KEIN_DOWNLOAD", "1")
    ordner = tmp_path / "einbettung"
    (ordner / "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2").mkdir(parents=True)
    lokal = LokaleEinbettung(ordner)
    assert lokal.modell.endswith("MiniLM-L12-v2")
    assert await lokal(["ab", "abcd"]) == [[2.0, 1.0], [4.0, 1.0]]
    assert aufrufe[0][0] == "laden" and aufrufe[0][2] == str(ordner)
    await lokal(["x"])
    assert sum(1 for a in aufrufe if a[0] == "laden") == 1  # nur einmal geladen


async def test_lokale_einbettung_ohne_paket(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "fastembed", None)  # ImportError
    assert await LokaleEinbettung(tmp_path)(["x"]) is None


async def test_einbetter_kette_und_name():
    async def leer(texte):
        return None

    async def fehler(texte):
        raise RuntimeError("kaputt")

    zweiter = BenannterEinbetter(lambda texte: _vektoren(texte), lambda: "ollama/nomic")
    kette = EinbetterKette(BenannterEinbetter(leer, "erster"), None, fehler, zweiter)
    assert kette.modell == "erster"
    assert await kette(["a"]) == [[1.0]]
    assert kette.modell == "ollama/nomic"


async def _vektoren(texte):
    return [[1.0] for _ in texte]


# ---------------------------------------------------------------- Nachbereiter
def test_json_block_und_titel():
    assert json_block('Hier:\n```json\n{"zusammenfassung": "x", "fakten": []}\n```') == {"zusammenfassung": "x", "fakten": []}
    assert json_block('{"a": 1} und {"b": 2}') == {"a": 1}
    assert json_block("kein json") is None
    assert titel_bereinigen('Titel: "Urlaub in Italien."') == "Urlaub in Italien"
    assert titel_fallback("  Was   ist " + "x" * 100) == "Was ist " + "x" * 51 + "…"


def _nachbereiter(antworten, automatisch=True):
    j, skript = baue_jarvis(antworten)
    j.konfig.aktualisieren({"gedaechtnis_automatisch": automatisch})
    return j, skript, Nachbereiter(j.llm, j.gedaechtnis, lambda: j.einstellungen)


async def test_titel_erzeugen_und_fallback():
    j, skript, n = _nachbereiter([text_chunks("„Urlaub in Italien.“"), RuntimeError("Modell weg")])
    kennung = j.gedaechtnis.aktuelle()["id"]
    assert await n.titel_erzeugen(kennung) is None  # noch keine Nutzernachricht
    j.gedaechtnis.verlauf_hinzufuegen("nutzer", "Ich möchte im Mai nach Italien fahren, was empfiehlst du?")
    j.gedaechtnis.verlauf_hinzufuegen("jarvis", "Rom oder die Amalfiküste.")
    assert await n.titel_erzeugen(kennung) == "Urlaub in Italien"
    assert j.gedaechtnis.unterhaltung(kennung)["titel_fest"] is False
    assert skript.aufrufe[-1]["messages"][0]["content"].startswith("Du gibst Unterhaltungen")
    # Fehler beim Modell → Fallback aus der ersten Nachricht
    zweite = j.gedaechtnis.unterhaltung_neu()["id"]
    j.gedaechtnis.verlauf_hinzufuegen("nutzer", "Wie spät ist es?")
    assert await n.titel_erzeugen(zweite) == "Wie spät ist es?"
    # Vom Nutzer festgelegter Titel bleibt
    j.gedaechtnis.unterhaltung_umbenennen(zweite, "Mein Titel")
    assert await n.titel_erzeugen(zweite) is None
    assert j.gedaechtnis.unterhaltung(zweite)["titel"] == "Mein Titel"


async def test_nachbereiten_zusammenfassung_und_fakten():
    antwort = {
        "zusammenfassung": "Der Nutzer hat eine Reise nach Rom im Mai geplant.",
        "fakten": ["Der Nutzer reist gern nach Italien.", "Der Nutzer bevorzugt Hotels mit Frühstück.", "Passwort ist geheim123"],
    }
    j, skript, n = _nachbereiter([text_chunks(json.dumps(antwort))])
    kennung = j.gedaechtnis.aktuelle()["id"]
    j.gedaechtnis.verlauf_hinzufuegen("nutzer", "Plane mir Rom im Mai")
    assert await n.nachbereiten(kennung) is None  # weniger als zwei Beiträge
    j.gedaechtnis.verlauf_hinzufuegen("jarvis", "Gern, hier ein Plan …")
    ergebnis = await n.nachbereiten(kennung)
    assert ergebnis == {"zusammenfassung": antwort["zusammenfassung"], "neu": 2, "aktualisiert": 0}
    u = j.gedaechtnis.unterhaltung(kennung)
    assert u["zusammenfassung"] == antwort["zusammenfassung"] and u["nachbereitet"]
    erinnerungen = j.gedaechtnis.erinnerungen()
    assert [e["text"] for e in erinnerungen] == antwort["fakten"][:2]
    assert all(e["quelle"] == "auto" and e["unterhaltung_id"] == kennung for e in erinnerungen)
    assert "Passwort" not in " ".join(e["text"] for e in erinnerungen)
    # Keine neuen Beiträge → kein zweiter Modellaufruf
    assert await n.nachbereiten(kennung) is None
    assert len(skript.aufrufe) == 1


async def test_nachbereiten_aktualisiert_statt_dublette():
    antwort = {"zusammenfassung": "Farben besprochen.", "fakten": ["Der Nutzer hat die Lieblingsfarbe Blau."]}
    j, skript, n = _nachbereiter([text_chunks(json.dumps(antwort))])
    alt = await j.gedaechtnis.erinnern("Der Nutzer hat die Lieblingsfarbe Grün.", quelle="auto")
    kennung = j.gedaechtnis.aktuelle()["id"]
    j.gedaechtnis.verlauf_hinzufuegen("nutzer", "Meine Lieblingsfarbe ist jetzt Blau")
    j.gedaechtnis.verlauf_hinzufuegen("jarvis", "Gemerkt.")
    ergebnis = await n.nachbereiten(kennung)
    assert ergebnis["neu"] == 0 and ergebnis["aktualisiert"] == 1
    erinnerungen = j.gedaechtnis.erinnerungen()
    assert len(erinnerungen) == 1 and erinnerungen[0]["id"] == alt
    assert erinnerungen[0]["text"].endswith("Blau.") and erinnerungen[0]["aktualisiert"]


async def test_nachbereiten_abgeschaltet():
    j, skript, n = _nachbereiter([], automatisch=False)
    kennung = j.gedaechtnis.aktuelle()["id"]
    j.gedaechtnis.verlauf_hinzufuegen("nutzer", "Hallo")
    j.gedaechtnis.verlauf_hinzufuegen("jarvis", "Hallo!")
    assert await n.nachbereiten(kennung) is None
    assert await n.titel_erzeugen(kennung) == "Hallo"  # Fallback ohne Modell
    assert skript.aufrufe == []
