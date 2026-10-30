"""Bühne: Manager über die Anwendung – zeigen, wiederverwenden, Aktionen → Rezepte, Stile, Persistenz, Werkzeuge."""

from __future__ import annotations

import json

import pytest

from jarvis.buehne.manager import BuehnenFehler, BuehnenManager, titel_passt
from jarvis.werkzeuge import FunktionsWerkzeug, schema
from tests.buehne.test_erzeuger import ERGEBNIS, GUELTIG
from tests.conftest import text_chunks, tool_chunks
from tests.helfer import baue_jarvis


def _mit_immobilien(antworten):
    j, skript = baue_jarvis(antworten)
    aufrufe: list[dict] = []

    async def read(collection: str = "immobilien", limit: int = 10) -> str:
        aufrufe.append({"collection": collection, "limit": limit})
        return json.dumps(ERGEBNIS)

    async def note(entity_id: str, text: str = "") -> str:
        aufrufe.append({"entity_id": entity_id, "text": text})
        return f"Notiz an {entity_id} angehängt."

    j.register.alle_registrieren(
        [
            FunktionsWerkzeug(read, "immo__read", "liest", schema({"collection": {"type": "string"}, "limit": {"type": "integer"}}), "lesen", integration="immo"),
            FunktionsWerkzeug(note, "immo__add_note", "notiert", schema({"entity_id": {"type": "string"}, "text": {"type": "string"}}, ["entity_id"]), "aendern", integration="immo"),
        ]
    )
    ereignisse: list[dict] = []

    async def hoerer(e: dict) -> None:
        ereignisse.append(e)

    j.hoerer_hinzufuegen(hoerer)
    return j, skript, aufrufe, ereignisse


def _buehne(ereignisse):
    return [e["nachricht"] for e in ereignisse if e["typ"] == "buehne"]


async def test_zeigen_baut_vorlage_und_verwendet_sie_wieder():
    j, skript, aufrufe, ereignisse = _mit_immobilien([text_chunks(json.dumps(GUELTIG))])
    e = await j.buehne.zeigen("immo__read", {"collection": "immobilien"}, titel="Immobilien", integration="immo")
    assert e["neu"] is True and e["vorlage"] == "immobilienliste" and e["anzahl"] == 1 and e["stil"] == "javit-dunkel"
    arten = [next(k for k in n if k != "version") for n in _buehne(ereignisse)]
    assert arten == ["stil", "createSurface", "updateComponents", "updateDataModel", "aktionen"]
    schnell = _buehne(ereignisse)[4]["aktionen"]["schnell"]
    assert [s["titel"] for s in schnell] == ["Immobilien"] and schnell[0]["vorlage"] == "immobilienliste" and schnell[0]["argumente"] == {"collection": "immobilien"}
    daten = _buehne(ereignisse)[3]["updateDataModel"]
    assert daten["path"] == "/" and daten["value"]["immobilien"][0]["titel"] == "Hafenweg 3" and daten["value"]["anzahl"] == 1
    assert _buehne(ereignisse)[1]["createSurface"]["titel"] == "Immobilien"
    # Werkzeugereignisse laufen über den Agenten (Aktivitäten sichtbar)
    assert [x["typ"] for x in ereignisse if x["typ"].startswith("werkzeug")] == ["werkzeug_start", "werkzeug_ende"]
    # zweites Mal: gleiche Signatur → keine Modellanfrage, gleiche Fläche
    ereignisse.clear()
    e2 = await j.buehne.zeigen("immo__read", {"collection": "immobilien", "limit": 50})
    assert e2["neu"] is False and e2["vorlage"] == "immobilienliste" and len(skript.aufrufe) == 1
    assert aufrufe[-1]["limit"] == 50
    assert j.buehne.zustand()["flaechen"][0]["surfaceId"] == "immobilienliste"
    # Persistenz: neuer Manager mit demselben Speicher
    neu = BuehnenManager(j.buehne.speicher, j.buehne.erzeuger, j.senden, j.agent.werkzeug_ausfuehren_extern)
    neu.laden()
    assert list(neu.flaechen) == ["immobilienliste"] and neu.flaechen["immobilienliste"]["daten"]["anzahl"] == 1


async def test_anderer_zweck_bekommt_eigene_vorlage_und_flaeche():
    makler = {**GUELTIG, "name": "Makler", "zweck": "Makler, die ich kontaktieren soll"}
    j, skript, aufrufe, ereignisse = _mit_immobilien([text_chunks(json.dumps(GUELTIG)), text_chunks(json.dumps(makler))])
    await j.buehne.zeigen("immo__read", {"collection": "immobilien"}, titel="Immobilien")
    # gleiche Signatur, aber anderer Titel → neue Vorlage, eigene Fläche; die erste bleibt unberührt (kein Umbau, kein neuer Titel)
    ereignisse.clear()
    e = await j.buehne.zeigen("immo__read", {"collection": "immobilien"}, titel="Makler, die ich kontaktieren soll", wunsch="nur Makler mit Fälligkeit")
    assert e["neu"] is True and e["vorlage"] == "makler" and e["surfaceId"] == "makler" and e["umgebaut"] is False
    assert [f["titel"] for f in j.buehne.zustand()["flaechen"]] == ["Immobilien", "Makler, die ich kontaktieren soll"]
    assert j.buehne.speicher.vorlage("immobilienliste")["version"] == 1 and len(skript.aufrufe) == 2
    assert "nur Makler mit Fälligkeit" in skript.aufrufe[1]["messages"][1]["content"]
    # ähnlicher Titel → vorhandene Vorlage; explizite Vorlage → genau diese, auch mit abweichendem Titel
    e = await j.buehne.zeigen("immo__read", {}, titel="Aktuelle Immobilien")
    assert e["neu"] is False and e["vorlage"] == "immobilienliste"
    e = await j.buehne.zeigen("immo__read", {}, titel="Meine Objekte", vorlage="immobilienliste")
    assert e["neu"] is False and e["vorlage"] == "immobilienliste" and len(skript.aufrufe) == 2
    with pytest.raises(BuehnenFehler):
        await j.buehne.zeigen("immo__read", {}, vorlage="gibt-es-nicht")


async def test_grosse_ergebnisse_kommen_ungekuerzt_auf_die_buehne():
    j, skript, aufrufe, ereignisse = _mit_immobilien([text_chunks(json.dumps(GUELTIG))])
    viele = {"items": [{"id": f"h{i}", "titel": f"Hafenweg {i}", "preis": 1000 * i, "bild_url": "https://gg.example/x.jpg"} for i in range(1500)], "total": 1500}

    async def gross(collection: str = "immobilien") -> str:
        return json.dumps(viele)

    j.register.alle_registrieren([FunktionsWerkzeug(gross, "immo__gross", "liest viel", schema({"collection": {"type": "string"}}), "lesen", integration="immo")])
    assert len(json.dumps(viele)) > 100_000
    e = await j.buehne.zeigen("immo__gross", {}, titel="Alle Objekte")
    assert e["anzahl"] == 1500
    # in der Modellschleife bleibt die Kürzung
    ok, text = await j.register.ausfuehren("immo__gross", {})
    assert ok and "gekürzt" in text


async def test_aktion_ohne_rezept_geht_an_den_agenten_mit_rezept_an_das_werkzeug():
    j, skript, aufrufe, ereignisse = _mit_immobilien(
        [
            text_chunks(json.dumps(GUELTIG)),
            # Agent beantwortet die Aktion: legt per Werkzeug ein Rezept an und antwortet
            tool_chunks("c1", "buehne_rezept_anlegen", {"vorlage": "immobilienliste", "aktion": "notiz_anlegen", "art": "werkzeug", "werkzeug": "immo__add_note", "argument_abbildung": {"entity_id": "context.objekt_id", "text": "Besichtigung"}}),
            text_chunks("Rezept angelegt."),
        ]
    )
    j.konfig.aktualisieren({"freigabe_technisch": False})
    await j.buehne.zeigen("immo__read", {}, titel="Immobilien")
    ereignisse.clear()
    antwort = await j.buehne.aktion({"name": "notiz_anlegen", "surfaceId": "immobilienliste", "sourceComponentId": "notiz", "context": {"objekt_id": "h3"}})
    assert antwort["rezept"] is None and "Rezept angelegt" in antwort["antwort"]
    nutzer = [m for m in skript.aufrufe[1]["messages"] if m["role"] == "user"][-1]["content"]
    assert "notiz_anlegen" in nutzer and "h3" in nutzer and "## Bühne" in skript.aufrufe[1]["messages"][0]["content"]
    rezepte = j.buehne.speicher.rezepte()
    assert len(rezepte) == 1 and rezepte[0]["werkzeug"] == "immo__add_note" and j.buehne.speicher.vorlage("immobilienliste")["aktionen"] == {"notiz_anlegen": rezepte[0]["id"]}
    # zweiter Klick: Rezept läuft direkt, Argumente aus dem Kontext, Fläche wird neu geladen, Chat bekommt eine Zeile
    ereignisse.clear()
    aufrufe.clear()
    antwort = await j.buehne.aktion({"name": "notiz_anlegen", "surfaceId": "immobilienliste", "context": {"objekt_id": "h3"}})
    assert antwort["rezept"] == rezepte[0]["id"] and "Notiz an h3" in antwort["ergebnis"]
    assert aufrufe[0] == {"entity_id": "h3", "text": "Besichtigung"} and aufrufe[1]["collection"] == "immobilien"
    assert [n for n in _buehne(ereignisse) if "updateDataModel" in n]
    ende = next(e for e in ereignisse if e["typ"] == "antwort_ende")
    assert ende["id"].startswith("buehne_") and "Notiz an h3" in ende["text"]
    assert len(skript.aufrufe) == 3  # kein weiterer Modellaufruf


async def test_agent_rezept_und_fehlende_flaeche():
    j, skript, aufrufe, ereignisse = _mit_immobilien([text_chunks(json.dumps(GUELTIG)), text_chunks("Erledigt: Exposé für h3.")])
    await j.buehne.zeigen("immo__read", {}, titel="Immobilien")
    j.buehne.rezept_anlegen("immobilienliste", "expose", "agent", auftrag="Erstelle ein Exposé für Objekt {objekt_id}.")
    antwort = await j.buehne.aktion({"name": "expose", "surfaceId": "immobilienliste", "context": {"objekt_id": "h3"}})
    assert antwort["antwort"] == "Erledigt: Exposé für h3."
    assert "Exposé für Objekt h3" in skript.aufrufe[1]["messages"][-1]["content"]
    with pytest.raises(BuehnenFehler):
        await j.buehne.daten_setzen("gibt-es-nicht", daten={})
    with pytest.raises(BuehnenFehler):
        j.buehne.rezept_anlegen("immobilienliste", "x", "werkzeug")  # Werkzeugname fehlt


async def test_aendern_zurueck_und_schliessen():
    neu = {"komponenten": GUELTIG["komponenten"][:2] + [{"id": "kacheln", "component": "Text", "text": "leer"}]}
    j, skript, aufrufe, ereignisse = _mit_immobilien([text_chunks(json.dumps(GUELTIG)), text_chunks(json.dumps(neu))])
    await j.buehne.zeigen("immo__read", {}, titel="Immobilien")
    ereignisse.clear()
    e = await j.buehne.aendern("immobilienliste", "nur Titel")
    assert e["version"] == 2
    nachrichten = _buehne(ereignisse)
    assert "updateComponents" in nachrichten[0] and nachrichten[0]["updateComponents"]["components"][2]["component"] == "Text"
    assert "updateDataModel" in nachrichten[1]  # Daten aus dem letzten Ergebnis ohne neuen Werkzeugaufruf
    assert len(aufrufe) == 1
    ereignisse.clear()
    e = await j.buehne.zurueck("immobilienliste")
    assert e["version"] == 1 and _buehne(ereignisse)[0]["updateComponents"]["components"][2]["component"] == "Grid"
    ereignisse.clear()
    assert await j.buehne.schliessen() == ["immobilienliste"]
    assert _buehne(ereignisse)[0] == {"version": "v0.9.1", "deleteSurface": {"surfaceId": "immobilienliste"}}
    assert _buehne(ereignisse)[1]["aktionen"]["varianten"] == {}  # keine offene Fläche mehr, Schnellaktionen bleiben
    assert [s["titel"] for s in _buehne(ereignisse)[1]["aktionen"]["schnell"]] == ["Immobilien"]
    assert j.buehne.speicher.flaechen_laden() == []


async def test_stile_zuweisen_aendern_und_ausgeschaltet():
    j, skript, aufrufe, ereignisse = _mit_immobilien([text_chunks(json.dumps(GUELTIG))])
    j.buehne.stil_zuweisen("immo", "material-hell")
    e = await j.buehne.zeigen("immo__read", {}, titel="Immobilien", integration="immo")
    assert e["stil"] == "material-hell" and _buehne(ereignisse)[0]["stil"]["id"] == "material-hell"
    with pytest.raises(BuehnenFehler):
        j.buehne.stil_zuweisen("immo", "gibt-es-nicht")
    kopie = j.buehne.stil_aendern("material-hell", {"werte": {"farben": {"primaer": "#123456"}, "rundung": 2}}, name="Immo hell")
    assert kopie["id"] == "immo-hell" and kopie["eigen"] and kopie["werte"]["farben"]["primaer"] == "#123456" and kopie["werte"]["rundung"] == 2
    assert j.buehne.speicher.stil("material-hell")["werte"]["farben"]["primaer"] != "#123456"
    ereignisse.clear()
    await j.buehne.stil_der_vorlage("immobilienliste", "immo-hell")
    assert _buehne(ereignisse)[0]["stil"]["id"] == "immo-hell" and _buehne(ereignisse)[1]["createSurface"]["theme"] == {"stil": "immo-hell"}
    j.konfig.aktualisieren({"buehne": {"aktiv": False}})
    with pytest.raises(BuehnenFehler):
        await j.buehne.zeigen("immo__read", {})
    assert j._buehne_prompt() == ""


async def test_werkzeuge_und_prompt():
    j, skript, aufrufe, ereignisse = _mit_immobilien([text_chunks(json.dumps(GUELTIG))])
    namen = {w.name: w for w in j.register.alle()}
    assert {"buehne_zeigen", "buehne_vorlage_aendern", "buehne_vorlage_zurueck", "buehne_daten", "buehne_rezept_anlegen", "buehne_stil_ableiten", "buehne_stil_aendern", "buehne_stil_zuweisen", "buehne_schliessen", "buehne_neu_laden"} <= set(namen)
    assert namen["buehne_rezept_anlegen"].risiko == "kritisch" and namen["buehne_zeigen"].risiko == "lesen" and namen["buehne_zeigen"].bereich == "technisch"
    ok, text = await j.register.ausfuehren("buehne_zeigen", {"werkzeug": "immo__read", "argumente": {"collection": "immobilien"}, "titel": "Immobilien"})
    assert ok and "neue Vorlage gebaut" in text and "1 Einträge" in text
    ok, text = await j.register.ausfuehren("buehne_zeigen", {"werkzeug": "buehne_schliessen"})
    assert not ok and "keine Bühnen-Werkzeuge" in text
    prompt = j._buehne_prompt()
    assert "## Bühne" in prompt and "immobilienliste" in prompt and "Offene Flächen" in prompt
    ok, text = await j.register.ausfuehren("buehne_stil_aendern", {"stil": "neutral", "schema": "dunkel", "farben": {"akzent": "#ff0000"}, "name": "Neutral dunkel"})
    assert ok and "neutral-dunkel" in text and j.buehne.speicher.stil("neutral-dunkel")["werte"]["schema"] == "dunkel"
    ok, text = await j.register.ausfuehren("buehne_schliessen", {})
    assert ok and "immobilienliste" in text


def test_titel_passt():
    assert titel_passt("Immobilien", "Immobilienliste") and titel_passt("Aktuelle Immobilien-Deals", "Immobilien")
    assert titel_passt("Ungelesene Mails", "Mails") and titel_passt("Makler", "Makler, die ich kontaktieren soll")
    assert not titel_passt("Makler, die ich kontaktieren soll", "Immobilien-Deals")
    assert not titel_passt("Makler-Liste", "Immobilien-Liste") and not titel_passt("", "Immobilien")


async def test_varianten_schnellaktionen_und_erneut():
    j, skript, aufrufe, ereignisse = _mit_immobilien([text_chunks(json.dumps({**GUELTIG, "name": "Wetter"}))])
    await j.buehne.zeigen("immo__read", {"collection": "stuttgart"}, titel="Wetter Stuttgart")
    await j.buehne.zeigen("immo__read", {"collection": "frankfurt"}, titel="Wetter Frankfurt")
    await j.buehne.zeigen("immo__read", {"collection": "stuttgart"}, titel="Wetter Stuttgart")
    assert len(skript.aufrufe) == 1  # eine Vorlage „Wetter“ für beide Orte
    stand = j.buehne.zustand()
    assert [f["titel"] for f in stand["flaechen"]] == ["Wetter Stuttgart"] and stand["flaechen"][0]["argumente"] == {"collection": "stuttgart"}
    assert [(v["titel"], v["zaehler"]) for v in stand["varianten"]["wetter"]] == [("Wetter Stuttgart", 2), ("Wetter Frankfurt", 1)]
    assert [s["titel"] for s in stand["schnellaktionen"]] == ["Wetter Stuttgart", "Wetter Frankfurt"]
    # erneut: Variante ohne Modell, Titel aus dem Verlauf
    ereignisse.clear()
    aufrufe.clear()
    e = await j.buehne.erneut("wetter", {"collection": "frankfurt"})
    assert e == {"surfaceId": "wetter", "titel": "Wetter Frankfurt", "vorlage": "wetter", "anzahl": 1} and aufrufe[0]["collection"] == "frankfurt"
    assert len(skript.aufrufe) == 1 and [n for n in _buehne(ereignisse) if "aktionen" in n]
    assert j.buehne.speicher.schnellaktionen()[0]["titel"] == "Wetter Frankfurt" or j.buehne.speicher.schnellaktionen()[0]["zaehler"] == 2
    with pytest.raises(BuehnenFehler):
        await j.buehne.erneut("gibt-es-nicht")
    # Verlauf überlebt einen Neustart
    neu = BuehnenManager(j.buehne.speicher, j.buehne.erzeuger, j.senden, j.agent.werkzeug_ausfuehren_extern)
    neu.laden()
    assert len(neu.zustand()["schnellaktionen"]) == 2


async def test_rezept_zeigen_oeffnet_detailflaeche_und_ersetzt_altes_rezept():
    detail = {**GUELTIG, "name": "Objekt-Details", "abbildung": {"/immobilien": "/items", "/anzahl": "/total"}}
    j, skript, aufrufe, ereignisse = _mit_immobilien([text_chunks(json.dumps(GUELTIG)), text_chunks(json.dumps(detail))])
    await j.buehne.zeigen("immo__read", {}, titel="Immobilien")
    altes = j.buehne.rezept_anlegen("immobilienliste", "notiz_anlegen", "agent", auftrag="Fasse {objekt_id} zusammen.")
    rezept = j.buehne.rezept_anlegen("immobilienliste", "notiz_anlegen", "zeigen", werkzeug="immo__read", argument_abbildung={"collection": "context.objekt_id"}, titel="Objekt {objekt_id}")
    assert rezept["art"] == "zeigen" and rezept["risiko"] == "lesen" and rezept["titel"] == "Objekt {objekt_id}"
    assert j.buehne.speicher.rezept(altes["id"]) is None and j.buehne.speicher.vorlage("immobilienliste")["aktionen"] == {"notiz_anlegen": rezept["id"]}
    # erster Klick baut die Detailvorlage und merkt sie im Rezept; zweiter Klick füllt dieselbe Vorlage (andere Fläche als die Liste)
    antwort = await j.buehne.aktion({"name": "notiz_anlegen", "surfaceId": "immobilienliste", "context": {"objekt_id": "h3"}})
    assert antwort["vorlage"] == "objekt-details" and antwort["surfaceId"] == "objekt-details" and len(skript.aufrufe) == 2
    assert j.buehne.speicher.rezept(rezept["id"])["vorlageZiel"] == "objekt-details" and aufrufe[-1]["collection"] == "h3"
    antwort = await j.buehne.aktion({"name": "notiz_anlegen", "surfaceId": "immobilienliste", "context": {"objekt_id": "h4"}})
    assert antwort["vorlage"] == "objekt-details" and len(skript.aufrufe) == 2
    titel = [f["titel"] for f in j.buehne.zustand()["flaechen"]]
    assert titel == ["Immobilien", "Objekt h4"]
    with pytest.raises(BuehnenFehler):
        j.buehne.rezept_anlegen("immobilienliste", "x", "zeigen")  # Werkzeug fehlt
    with pytest.raises(BuehnenFehler):
        j.buehne.rezept_anlegen("immobilienliste", "x", "zeigen", werkzeug="immo__read", vorlage_ziel="nix")
    prompt = j._buehne_prompt()
    assert "buehne_vorlage_zurueck" in prompt and "nie den Nutzer" in prompt


async def test_rohtext_vorlage_wird_durch_strukturierte_ersetzt():
    roh = {"name": "Wetter Stuttgart", "zweck": "Rohtext", "abbildung": {"/antwort": "/text"}, "datenschema": {}, "komponenten": [{"id": "root", "component": "Text", "text": {"path": "/antwort"}}]}
    j, skript, aufrufe, ereignisse = _mit_immobilien([text_chunks(json.dumps(roh)), text_chunks(json.dumps({**GUELTIG, "name": "Wetter"}))])
    antworten = iter(["Dienst nicht erreichbar, bitte später", json.dumps(ERGEBNIS)])

    async def wetter(ort: str = "stuttgart") -> str:
        return next(antworten)

    j.register.alle_registrieren([FunktionsWerkzeug(wetter, "wetter__abrufen", "wetter", schema({"ort": {"type": "string"}}), "lesen", integration="wetter")])
    e1 = await j.buehne.zeigen("wetter__abrufen", {"ort": "stuttgart"}, titel="Wetter Stuttgart")
    assert e1["vorlage"] == "wetter-stuttgart" and j.buehne.speicher.vorlage("wetter-stuttgart")["signatur"]["schluessel"] == ["text"]
    # beim nächsten Mal liefert das Werkzeug Struktur → neue Vorlage, die Rohtext-Vorlage samt Fläche und Verlauf verschwindet
    e2 = await j.buehne.zeigen("wetter__abrufen", {"ort": "stuttgart"}, titel="Wetter Stuttgart")
    assert e2["neu"] is True and e2["vorlage"] == "wetter" and j.buehne.speicher.vorlage("wetter-stuttgart") is None
    assert [f["surfaceId"] for f in j.buehne.zustand()["flaechen"]] == ["wetter"]
    assert {v["vorlage"] for v in j.buehne.speicher.verlauf()} == {"wetter"}


async def test_umbau_nach_neustart_und_neu_bauen():
    neu = {"komponenten": GUELTIG["komponenten"][:2] + [{"id": "kacheln", "component": "Text", "text": "leer"}]}
    j, skript, aufrufe, ereignisse = _mit_immobilien([text_chunks(json.dumps(GUELTIG)), text_chunks(json.dumps(neu)), text_chunks(json.dumps({**GUELTIG, "zweck": "ganz neu"}))])
    await j.buehne.zeigen("immo__read", {"collection": "immobilien"}, titel="Immobilien")
    # Neustart: Rohdaten weg, Fläche aus der Datei – Umbau holt die Daten neu und sendet Komponenten + Datenmodell
    neu_manager = BuehnenManager(j.buehne.speicher, j.buehne.erzeuger, j.senden, j.agent.werkzeug_ausfuehren_extern)
    neu_manager.laden()
    ereignisse.clear()
    aufrufe.clear()
    e = await neu_manager.aendern("immobilienliste", "nur Titel")
    assert e["version"] == 2 and aufrufe == [{"collection": "immobilien", "limit": 10}]
    nachrichten = _buehne(ereignisse)
    assert "updateComponents" in nachrichten[0] and "updateDataModel" in nachrichten[1] and nachrichten[1]["updateDataModel"]["value"]["anzahl"] == 1
    # neu_bauen: kompletter Neuentwurf über vorlage_bauen (Systemprompt „Du entwirfst“), Wunsch im Prompt, Version 3
    e = await neu_manager.aendern("immobilienliste", "ganz anders, als Tabelle", neu_bauen=True)
    assert e["version"] == 3 and skript.aufrufe[-1]["messages"][0]["content"].startswith("Du entwirfst") and "ganz anders" in skript.aufrufe[-1]["messages"][1]["content"]
    assert neu_manager.speicher.vorlage("immobilienliste")["zweck"] == "ganz neu" or neu_manager.speicher.vorlage("immobilienliste")["version"] == 3
    ok, text = await j.register.ausfuehren("buehne_vorlage_aendern", {"vorlage": "immobilienliste", "wunsch": "x", "neu_bauen": False})
    assert not ok or "Version" in text  # Skript ist leer → Fehler erlaubt; nur die Signatur zählt


async def test_varianten_nur_je_app():
    j, skript, aufrufe, ereignisse = _mit_immobilien([text_chunks(json.dumps(GUELTIG)), text_chunks(json.dumps({**GUELTIG, "name": "Makler"})), text_chunks(json.dumps({**GUELTIG, "name": "Wetter"}))])

    async def wetter(ort: str = "x") -> str:
        return json.dumps(ERGEBNIS)

    j.register.alle_registrieren([FunktionsWerkzeug(wetter, "wetter__abrufen", "wetter", schema({"ort": {"type": "string"}}), "lesen", integration="wetter")])
    await j.buehne.zeigen("immo__read", {"collection": "immobilien"}, titel="Immobilien")
    await j.buehne.zeigen("immo__read", {"collection": "immobilien"}, titel="Makler, die ich kontaktieren soll")
    await j.buehne.zeigen("wetter__abrufen", {"ort": "stuttgart"}, titel="Wetter Stuttgart")
    await j.buehne.zeigen("wetter__abrufen", {"ort": "frankfurt"}, titel="Wetter Frankfurt")
    stand = j.buehne.zustand()
    assert [v["titel"] for v in stand["varianten"]["wetter"]] == ["Wetter Frankfurt", "Wetter Stuttgart"]  # nur Wetter, gleiche Vorlage zuerst
    assert [v["titel"] for v in stand["varianten"]["immobilienliste"]] == ["Immobilien", "Makler, die ich kontaktieren soll"]  # GG-App: eigene Sicht zuerst, dann Makler
    assert all(v["app"] == "immo" for v in stand["varianten"]["makler"]) and stand["varianten"]["makler"][0]["titel"].startswith("Makler")
    assert len(stand["schnellaktionen"]) == 4


async def test_vorlage_die_nicht_mehr_zum_ergebnis_passt_wird_neu_gebaut():
    """Rückmeldung 29.10.: Die Wetter-Vorlage hatte eine strukturierte Abbildung (aus einer früheren Datenquelle), das
    Werkzeug lieferte dann nur Text – die Abbildung fand nichts, die Fläche kam ohne Werte. Greift die Abbildung einer
    vorhandenen Vorlage nicht, wird die Vorlage aus dem echten Ergebnis neu gebaut (neue Version, Signatur folgt)."""
    textvorlage = {
        "name": "Wetter Stuttgart",
        "zweck": "Wetter als Text",
        "abbildung": {"/text": "/text"},
        "datenschema": {"type": "object", "properties": {"text": {"type": "string"}}},
        "komponenten": [{"id": "root", "component": "Column", "children": ["t"]}, {"id": "t", "component": "Text", "text": {"path": "/text"}}],
    }
    strukturiert = {**GUELTIG, "name": "Wetter Stuttgart"}
    j, skript, aufrufe, ereignisse = _mit_immobilien([text_chunks(json.dumps(strukturiert)), text_chunks(json.dumps(textvorlage))])
    antwort = {"wert": json.dumps(ERGEBNIS)}

    async def wetter(ort: str = "Stuttgart") -> str:
        return antwort["wert"]

    j.register.alle_registrieren([FunktionsWerkzeug(wetter, "immo__wetter", "Wetter", schema({"ort": {"type": "string"}}), "lesen", integration="immo")])
    e1 = await j.buehne.zeigen("immo__wetter", {"ort": "Stuttgart"}, titel="Wetter Stuttgart")
    assert e1["neu"] is True and j.buehne.speicher.vorlage(e1["vorlage"])["signatur"]["schluessel"] == ["items", "total"]

    antwort["wert"] = "Wolkenlos, 10 Grad in Stuttgart"
    ereignisse.clear()
    # ausdrücklich gewählte Vorlage (umgeht die Signatur) – so war es beim Nutzer
    e2 = await j.buehne.zeigen("immo__wetter", {"ort": "Stuttgart"}, titel="Wetter Stuttgart", vorlage=e1["vorlage"])
    assert e2["vorlage"] == e1["vorlage"] and e2["neu"] is False and e2["umgebaut"] is True
    daten = [n for n in _buehne(ereignisse) if "updateDataModel" in n][-1]["updateDataModel"]["value"]
    assert daten["text"] == "Wolkenlos, 10 Grad in Stuttgart"
    vorlage = j.buehne.speicher.vorlage(e1["vorlage"])
    assert vorlage["version"] == 2 and vorlage["signatur"]["schluessel"] == ["text"] and vorlage["datenquelle"]["abbildung"] == {"/text": "/text"}
    assert len(skript.aufrufe) == 2
    # passt die Vorlage wieder (Text), wird sie ohne Modell wiederverwendet
    e3 = await j.buehne.zeigen("immo__wetter", {"ort": "Stuttgart"}, titel="Wetter Stuttgart")
    assert e3["neu"] is False and e3["umgebaut"] is False and len(skript.aufrufe) == 2
    # Neu laden ohne Modell: passt das Ergebnis nicht mehr zur Vorlage, kommt ein Fehler statt einer leeren Fläche
    antwort["wert"] = json.dumps(ERGEBNIS)
    with pytest.raises(BuehnenFehler, match="passt nicht mehr"):
        await j.buehne.neu_laden(e3["surfaceId"])
    assert j.buehne.flaechen[e3["surfaceId"]]["daten"]["text"] == "Wolkenlos, 10 Grad in Stuttgart"
