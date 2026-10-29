"""Bühne: JSON-Pointer, Abbildung Werkzeugergebnis → Datenmodell, Ergebnis parsen, Signatur, Standardvorlage."""

from __future__ import annotations

import json

from jarvis.buehne.daten import (
    abbildung_anwenden,
    ergebnis_parsen,
    json_pointer_holen,
    json_pointer_setzen,
    signatur,
    spalten_zu_zeilen,
    standardvorlage,
)
from jarvis.buehne.katalog import komponenten_pruefen


def test_json_pointer():
    obj = {"a": {"b": [10, {"c": "x"}]}, "k~1/": 5}
    assert json_pointer_holen(obj, "/a/b/1/c") == "x" and json_pointer_holen(obj, "/a/b/0") == 10
    assert json_pointer_holen(obj, "/") == obj and json_pointer_holen(obj, "") == obj
    assert json_pointer_holen(obj, "/k~01~1") == 5
    assert json_pointer_holen(obj, "/fehlt/x") is None and json_pointer_holen(obj, "/a/b/9") is None
    ziel: dict = {}
    json_pointer_setzen(ziel, "/eintraege", [1, 2])
    json_pointer_setzen(ziel, "/meta/anzahl", 2)
    json_pointer_setzen(ziel, "/eintraege/-", 3)
    assert ziel == {"eintraege": [1, 2, 3], "meta": {"anzahl": 2}}
    assert json_pointer_setzen({"x": 1}, "/", {"neu": True}) == {"neu": True}


def test_abbildung_mit_formatierern():
    ergebnis = {"items": [{"id": 1, "preis": 450000, "datum": "2026-03-01T10:00:00"}], "total": 1, "stand": "01.03.2026 10:00"}
    modell = abbildung_anwenden(
        {"/immobilien": "/items", "/anzahl": "/total", "/preis_text": "/items/0/preis|waehrung:EUR", "/stand": "/stand|datum", "/anteil": "/total|zahl:1", "/fehlt": "/nix"},
        ergebnis,
    )
    assert modell["immobilien"] == ergebnis["items"] and modell["anzahl"] == 1
    assert modell["preis_text"].replace("\xa0", " ") == "450.000,00 €"
    assert modell["stand"] == "2026-03-01T10:00:00" and modell["anteil"] == "1,0" and modell["fehlt"] is None
    assert abbildung_anwenden({}, ergebnis) == ergebnis  # ohne Abbildung: Ergebnis selbst
    assert abbildung_anwenden({"/": "/"}, [1, 2]) == {"eintraege": [1, 2]}  # Listen landen unter /eintraege


def test_ergebnis_parsen():
    assert ergebnis_parsen('{"a": 1}') == {"a": 1}
    assert ergebnis_parsen("[1, 2]") == [1, 2]
    assert ergebnis_parsen("nur Text") == {"text": "nur Text"}
    assert ergebnis_parsen({"schon": "objekt"}) == {"schon": "objekt"}
    tabelle = "| Name | Preis |\n|---|---|\n| A | 1 |\n| B | 2 |\n"
    assert ergebnis_parsen(tabelle) == {"eintraege": [{"Name": "A", "Preis": "1"}, {"Name": "B", "Preis": "2"}], "text": tabelle}
    zaun = "Ergebnis:\n```json\n{\"x\": [1]}\n```"
    assert ergebnis_parsen(zaun) == {"x": [1]}


def test_ergebnis_parsen_json_hinter_praefix_und_spalten():
    rest = 'HTTP 200\n{\n "latitude": 48.78,\n "daily": {"time": ["2026-10-29", "2026-10-30"], "temperature_2m_max": [13.1, 11.0]}\n}'
    d = ergebnis_parsen(rest)
    assert d["latitude"] == 48.78 and signatur("wetter__wetter_abrufen", rest)["schluessel"] == ["daily", "latitude"]
    assert ergebnis_parsen("Ergebnis: [1, 2]") == [1, 2]
    assert ergebnis_parsen("x" * 200 + "{\"a\": 1}") == {"text": "x" * 200 + "{\"a\": 1}"}  # Präfix zu lang → Text
    tage = abbildung_anwenden({"/tage": "/daily|zeilen", "/ort": "/latitude"}, d)
    assert tage == {"tage": [{"time": "2026-10-29", "temperature_2m_max": 13.1}, {"time": "2026-10-30", "temperature_2m_max": 11.0}], "ort": 48.78}
    assert spalten_zu_zeilen({"a": [1, 2, 3], "b": [4], "einheit": "°C"}) == [{"a": 1, "b": 4, "einheit": "°C"}, {"a": 2, "b": None, "einheit": "°C"}, {"a": 3, "b": None, "einheit": "°C"}]
    assert spalten_zu_zeilen([{"x": 1}]) == [{"x": 1}] and spalten_zu_zeilen({"kein": "listen"}) == {"kein": "listen"}


def test_ergebnis_parsen_textlisten():
    # nummerierte Einträge mit Schlüssel: Wert-Zeilen (typisch für Mail-/Suchwerkzeuge)
    mails = "Gefunden: 2 Mails\n\n1. **Von:** Anna <a@x.de>\n   Betreff: Angebot\n   Datum: 2026-10-27\n2. Von: Bernd\n   Betreff: Rückfrage\n   Datum: 2026-10-26\n"
    d = ergebnis_parsen(mails)
    assert d["eintraege"] == [
        {"Von": "Anna <a@x.de>", "Betreff": "Angebot", "Datum": "2026-10-27"},
        {"Von": "Bernd", "Betreff": "Rückfrage", "Datum": "2026-10-26"},
    ] and d["text"] == mails
    # Blöcke durch Leerzeilen, Paare in einer Zeile mit |
    bloecke = "Name: A | Ort: Köln\nPreis: 1\n\nName: B | Ort: Bonn\nPreis: 2\n"
    assert ergebnis_parsen(bloecke)["eintraege"] == [{"Name": "A", "Ort": "Köln", "Preis": "1"}, {"Name": "B", "Ort": "Bonn", "Preis": "2"}]
    # Aufzählung mit Titelzeile
    punkte = "- Hafenweg 3\n  Preis: 450000\n  Status: offen\n- Seeweg 1\n  Preis: 300000\n  Status: verkauft\n"
    assert ergebnis_parsen(punkte)["eintraege"][1] == {"titel": "Seeweg 1", "Preis": "300000", "Status": "verkauft"}
    # Fließtext mit einem Doppelpunkt bleibt Text; ein einzelner Datensatz auch
    assert ergebnis_parsen("Hinweis: alles gut.\nMehr gibt es nicht.") == {"text": "Hinweis: alles gut.\nMehr gibt es nicht."}
    assert ergebnis_parsen("Name: A\nPreis: 1\n") == {"text": "Name: A\nPreis: 1\n"}
    assert signatur("gmail__search", mails)["eintrag"] == ["Betreff", "Datum", "Von"]


def test_signatur():
    assert signatur("gg__read", {"items": [{"b": 1, "a": 2}], "total": 1}) == {"werkzeug": "gg__read", "schluessel": ["items", "total"], "eintrag": ["a", "b"]}
    assert signatur("w", [{"z": 1, "y": 2}]) == {"werkzeug": "w", "schluessel": [], "eintrag": ["y", "z"]}
    assert signatur("w", "text") == {"werkzeug": "w", "schluessel": ["text"], "eintrag": []}


def test_standardvorlage_liste_objekt_text():
    liste = [{"id": 1, "titel": "Hafenweg 3", "preis": 450000, "aktualisiert": "2026-01-01", "aktiv": True}]
    v = standardvorlage("gg__read_collection", {"items": liste, "total": 1}, "Immobilien")
    assert komponenten_pruefen(v["komponenten"]) == []
    tabelle = next(k for k in v["komponenten"] if k["component"] == "Tabelle")
    assert tabelle["zeilen"] == {"path": "/eintraege"}
    assert [s["path"] for s in tabelle["spalten"]] == ["id", "titel", "preis", "aktualisiert", "aktiv"]
    assert next(s for s in tabelle["spalten"] if s["path"] == "preis")["format"] == "waehrung"
    assert next(s for s in tabelle["spalten"] if s["path"] == "aktualisiert")["format"] == "datum"
    assert v["abbildung"] == {"/eintraege": "/items"} and v["name"] == "Immobilien" and "Tabelle" in v["zweck"]
    modell = abbildung_anwenden(v["abbildung"], {"items": liste, "total": 1})
    assert modell["eintraege"] == liste

    flach = standardvorlage("wetter", {"temperatur": 13.5, "ort": "Stuttgart", "regen": "65 %"}, "Wetter")
    assert komponenten_pruefen(flach["komponenten"]) == []
    assert sum(1 for k in flach["komponenten"] if k["component"] == "Kennzahl") == 1  # nur Zahlen werden Kennzahl
    assert flach["abbildung"] == {"/": "/"}

    text = standardvorlage("shell", "Alles ok.\n", "Ausgabe")
    assert komponenten_pruefen(text["komponenten"]) == []
    assert any(k["component"] == "Text" and k.get("text") == {"path": "/text"} for k in text["komponenten"])
    assert json.dumps(text["abbildung"]) == '{"/text": "/text"}'
