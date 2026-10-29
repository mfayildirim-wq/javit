"""Bühne: dauerhafter Speicher für Vorlagen (mit Versionen), Rezepte, Stile, Zuordnung und Flächen."""

from __future__ import annotations

import pytest

from jarvis.buehne.speicher import BuehnenSpeicher, kennung_aus

KOMP = [{"id": "root", "component": "Text", "text": {"path": "/titel"}}]
QUELLE = {"werkzeug": "gg__read_collection", "argumente": {"collection": "deals"}, "abbildung": {"/eintraege": "/items"}}


def test_kennung_aus():
    assert kennung_aus("Immobilien Liste") == "immobilien-liste"
    assert kennung_aus("Größe & Fläche!") == "groesse-flaeche"
    assert kennung_aus("   ") == "vorlage"


def test_vorlagen_rundreise_und_versionen(tmp_path):
    s = BuehnenSpeicher(tmp_path)
    v = s.vorlage_anlegen("Immobilien Liste", "Objekte aus GG", KOMP, {"type": "object"}, QUELLE, stil="gg-immo",
                          signatur={"werkzeug": "gg__read_collection", "schluessel": ["id", "preis", "titel"]}, modell="x/y")
    assert v["id"] == "immobilien-liste" and v["version"] == 1 and v["versionen"] == 1 and v["komponenten"] == KOMP
    assert v["protokollVersion"] == "v0.9.1" and v["katalogId"] == "jarvis:buehne/1" and v["aktionen"] == {}
    zweite = s.vorlage_anlegen("Immobilien Liste", "zweite", KOMP, {}, QUELLE)
    assert zweite["id"] == "immobilien-liste-2"
    # neue Version
    neu = [{"id": "root", "component": "Text", "text": "neu"}]
    v2 = s.vorlage_neue_version("immobilien-liste", komponenten=neu, modell="x/z")
    assert v2["version"] == 2 and v2["komponenten"] == neu and v2["datenquelle"] == QUELLE and v2["versionen"] == 2
    # zurück = letzte Version verwerfen
    zurueck = s.vorlage_zurueck("immobilien-liste")
    assert zurueck["version"] == 1 and zurueck["komponenten"] == KOMP and zurueck["versionen"] == 1
    assert s.vorlage_zurueck("immobilien-liste")["version"] == 1  # nichts mehr zum Zurücknehmen
    # höchstens 10 Versionen
    for i in range(12):
        s.vorlage_neue_version("immobilien-liste", komponenten=[{"id": "root", "component": "Text", "text": str(i)}])
    v = s.vorlage("immobilien-liste")
    assert v["versionen"] == 10 and v["version"] == 13 and v["komponenten"][0]["text"] == "11"
    # umbenennen, Stil, Aktion, Signatur
    s.vorlage_aendern("immobilien-liste", name="Objekte", stil="javit-hell")
    s.aktion_setzen("immobilien-liste", "notiz_anlegen", "rezept-notiz")
    v = s.vorlage("immobilien-liste")
    assert v["name"] == "Objekte" and v["stil"] == "javit-hell" and v["aktionen"] == {"notiz_anlegen": "rezept-notiz"}
    treffer = s.vorlage_fuer_signatur("gg__read_collection", ["titel", "id", "preis"])
    assert treffer and treffer["id"] == "immobilien-liste"
    assert s.vorlage_fuer_signatur("gg__read_collection", ["id"]) is None
    # Liste ohne Komponenten, zweite Instanz liest dieselben Dateien
    liste = BuehnenSpeicher(tmp_path).vorlagen()
    assert [x["id"] for x in liste] == ["immobilien-liste", "immobilien-liste-2"] and "komponenten" not in liste[0]
    assert s.vorlage_loeschen("immobilien-liste-2") is True and s.vorlage("immobilien-liste-2") is None
    assert s.vorlage_loeschen("gibtsnicht") is False
    with pytest.raises(KeyError):
        s.vorlage_neue_version("gibtsnicht", komponenten=KOMP)


def test_rezepte(tmp_path):
    s = BuehnenSpeicher(tmp_path)
    r = s.rezept_anlegen(name="Notiz anlegen", art="werkzeug", werkzeug="gg__add_note", argumentAbbildung={"entity_id": "context.objekt_id"}, risiko="aendern", vorlage="immobilien-liste")
    assert r["id"] == "notiz-anlegen" and s.rezept("notiz-anlegen")["werkzeug"] == "gg__add_note"
    a = s.rezept_anlegen(name="Makler kontaktieren", art="agent", auftrag="Schreibe einen Entwurf an den Makler von {objekt_id}", risiko="kritisch", vorlage="immobilien-liste")
    assert [x["id"] for x in s.rezepte()] == ["makler-kontaktieren", "notiz-anlegen"]
    assert s.rezept_loeschen(a["id"]) is True and s.rezept_loeschen(a["id"]) is False


def test_stile_und_zuordnung(tmp_path):
    s = BuehnenSpeicher(tmp_path)
    stile = s.stile()
    assert len(stile) >= 8 and all(st["eigen"] is False for st in stile)
    assert s.stil("javit-dunkel")["werte"]["farben"]["primaer"] == "#7fe8ff"
    assert s.stil_loeschen("javit-dunkel") is False  # vordefinierte bleiben
    eigen = dict(s.stil("javit-dunkel"))
    eigen.update(id="gg-immo", name="GG Immo", quelle={"art": "url", "wert": "https://gg.example"})
    gespeichert = s.stil_speichern(eigen)
    assert gespeichert["eigen"] is True and s.stil("gg-immo")["name"] == "GG Immo"
    assert any(st["id"] == "gg-immo" for st in s.stile())
    # vordefinierten Stil ändern → Kopie
    kopie = s.stil_speichern({**s.stil("neutral"), "name": "Neutral eigen"})
    assert kopie["id"] == "neutral-eigen" and s.stil("neutral")["name"] == "Neutral"
    s.zuordnung_setzen({"gg_immobilien_vercel_test": "gg-immo"})
    assert BuehnenSpeicher(tmp_path).zuordnung() == {"gg_immobilien_vercel_test": "gg-immo"}
    assert s.stil_loeschen("gg-immo") is True and s.stil("gg-immo") is None


def test_flaechen(tmp_path):
    s = BuehnenSpeicher(tmp_path)
    assert s.flaechen_laden() == []
    s.flaechen_speichern([{"surfaceId": "immobilien", "titel": "Immobilien", "catalogId": "jarvis:buehne/1", "stil": "gg-immo", "components": KOMP, "daten": {"titel": "x"}, "vorlage": "immobilien-liste"}])
    assert BuehnenSpeicher(tmp_path).flaechen_laden()[0]["daten"] == {"titel": "x"}


def test_vorlagen_fuer_signatur_liste(tmp_path):
    sp = BuehnenSpeicher(tmp_path)
    a = sp.vorlage_anlegen("Immobilien", "", [], None, {"werkzeug": "w"}, signatur={"werkzeug": "w", "schluessel": ["zeilen"], "eintrag": ["id", "objekt"]})
    b = sp.vorlage_anlegen("Makler", "", [], None, {"werkzeug": "w"}, signatur={"werkzeug": "w", "schluessel": ["zeilen"], "eintrag": ["id", "name"]})
    sp.vorlage_anlegen("Andere", "", [], None, {"werkzeug": "x"}, signatur={"werkzeug": "x", "schluessel": ["zeilen"], "eintrag": ["id"]})
    # passender Listeneintrag zuerst, dann die übrigen mit gleichen Schlüsseln; vollständige Vorlagen (mit Komponenten)
    kandidaten = sp.vorlagen_fuer_signatur("w", ["zeilen"], ["name", "id"])
    assert [k["id"] for k in kandidaten] == [b["id"], a["id"]] and "komponenten" in kandidaten[0]
    assert sp.vorlage_fuer_signatur("w", ["zeilen"], ["id", "objekt"])["id"] == a["id"]
    assert sp.vorlagen_fuer_signatur("w", ["anders"]) == []


def test_verlauf_schnellaktionen_und_varianten(tmp_path):
    sp = BuehnenSpeicher(tmp_path)
    a = sp.verlauf_merken("wetter", "Wetter Stuttgart", "wetter__abrufen", {"latitude": 48.7, "longitude": 9.1})
    sp.verlauf_merken("wetter", "Wetter Frankfurt", "wetter__abrufen", {"longitude": 8.6, "latitude": 50.1})
    b = sp.verlauf_merken("wetter", "Wetter Stuttgart", "wetter__abrufen", {"longitude": 9.1, "latitude": 48.7})  # gleiche Argumente, andere Reihenfolge
    sp.verlauf_merken("immobilien", "Immobilien", "gg__read", {"collection": "deals"})
    assert a["id"] == b["id"] and b["zaehler"] == 2 and len(sp.verlauf()) == 3
    assert [v["titel"] for v in sp.varianten("wetter")] == ["Wetter Stuttgart", "Wetter Frankfurt"]
    assert sp.schnellaktionen()[0]["titel"] == "Wetter Stuttgart" and len(sp.schnellaktionen(2)) == 2
    assert a["app"] == "wetter" and sp.verlauf()[0]["app"] == "gg"
    sp.verlauf_vergessen("wetter")
    assert [e["vorlage"] for e in sp.verlauf()] == ["immobilien"]
    r = sp.rezept_anlegen("Öffnen", "zeigen", "immobilien", werkzeug="gg__read_entity")
    assert sp.rezept_aendern(r["id"], vorlageZiel="objekt-details")["vorlageZiel"] == "objekt-details" and sp.rezept(r["id"])["vorlageZiel"] == "objekt-details"
    assert sp.rezept_aendern("nix", vorlageZiel="x") is None
