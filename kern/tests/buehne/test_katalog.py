"""Bühne: Katalog laden, Komponenten prüfen und säubern."""

from __future__ import annotations

import copy

from jarvis.buehne.katalog import katalog_laden, komponenten_pruefen, komponenten_saeubern


def test_katalog_laden():
    k = katalog_laden()
    assert k.id == "jarvis:buehne/1" and len(k.komponenten) == 22
    assert k.limits["komponenten"] == 300 and k.limits["tiefe"] == 12
    text = k.beschreibung_fuer_prompt()
    assert "Column" in text and "Tabelle" in text and '"component": "Button"' in text
    assert "formatCurrency" in text


def test_beispiele_des_katalogs_sind_gueltig():
    k = katalog_laden()
    # alle Beispiele zusammen, root = Column über alle anderen
    beispiele = [copy.deepcopy(e["beispiel"]) for e in k.komponenten.values()]
    ids = [b["id"] for b in beispiele if b["id"] != "root"]
    wurzel = {"id": "root", "component": "Column", "children": ids}
    komponenten = [wurzel] + [b for b in beispiele if b["id"] != "root"]
    # Verweise der Beispiele auf nicht vorhandene Kinder ergänzen
    bekannt = {b["id"] for b in komponenten}
    for b in komponenten:
        for schluessel in ("children", "child"):
            v = b.get(schluessel)
            if isinstance(v, list):
                for kind in v:
                    if kind not in bekannt:
                        komponenten.append({"id": kind, "component": "Text", "text": kind})
                        bekannt.add(kind)
            elif isinstance(v, dict) and v.get("componentId") not in bekannt:
                komponenten.append({"id": v["componentId"], "component": "Text", "text": "x"})
                bekannt.add(v["componentId"])
            elif isinstance(v, str) and v not in bekannt:
                komponenten.append({"id": v, "component": "Text", "text": v})
                bekannt.add(v)
    assert komponenten_pruefen(komponenten) == []


def _basis():
    return [
        {"id": "root", "component": "Column", "children": ["t", "b"]},
        {"id": "t", "component": "Text", "text": {"path": "/titel"}, "variant": "h2"},
        {"id": "b", "component": "Button", "text": "Los", "action": {"event": {"name": "los", "context": {"id": {"path": "/id"}}}}},
    ]


def test_pruefung_findet_fehler():
    assert komponenten_pruefen(_basis()) == []
    ohne_root = [k for k in _basis() if k["id"] != "root"]
    assert any("root" in f for f in komponenten_pruefen(ohne_root))
    doppelt = _basis() + [{"id": "t", "component": "Text", "text": "x"}]
    assert any("doppelt" in f.lower() for f in komponenten_pruefen(doppelt))
    unbekannt = _basis() + [{"id": "u", "component": "Hologramm"}]
    assert any("Hologramm" in f for f in komponenten_pruefen(unbekannt))
    verweis = _basis()
    verweis[0]["children"].append("gibtsnicht")
    assert any("gibtsnicht" in f for f in komponenten_pruefen(verweis))
    zyklus = [{"id": "root", "component": "Column", "children": ["a"]}, {"id": "a", "component": "Column", "children": ["root"]}]
    assert any("Zyklus" in f or "zyklisch" in f.lower() for f in komponenten_pruefen(zyklus))
    aktion = _basis()
    aktion[2]["action"] = {"event": {"name": "Böse Aktion!"}}
    assert any("Aktionsname" in f for f in komponenten_pruefen(aktion))
    bild = _basis() + [{"id": "i", "component": "Image", "url": "http://unsicher.example/x.png"}]
    bild[0]["children"].append("i")
    assert any("https" in f for f in komponenten_pruefen(bild))
    typ = _basis()
    typ[1]["text"] = {"call": "zaubern", "args": {}}
    assert any("zaubern" in f for f in komponenten_pruefen(typ))
    typ2 = _basis()
    typ2[1]["variant"] = "riesig"
    assert any("variant" in f for f in komponenten_pruefen(typ2))


def test_limits():
    viele = [{"id": "root", "component": "Column", "children": [f"k{i}" for i in range(301)]}]
    viele += [{"id": f"k{i}", "component": "Text", "text": "x"} for i in range(301)]
    assert any("300" in f for f in komponenten_pruefen(viele))
    tief = [{"id": "root", "component": "Column", "children": ["e1"]}]
    for i in range(1, 15):
        tief.append({"id": f"e{i}", "component": "Column", "children": [f"e{i + 1}"]})
    tief.append({"id": "e15", "component": "Text", "text": "unten"})
    assert any("Tiefe" in f for f in komponenten_pruefen(tief))


def test_saeubern_entfernt_unbekannte_eigenschaften():
    komponenten = _basis()
    komponenten[1]["farbe"] = "rot"
    komponenten[1]["onclick"] = "alert(1)"
    sauber = komponenten_saeubern(komponenten)
    assert "farbe" not in sauber[1] and "onclick" not in sauber[1] and sauber[1]["text"] == {"path": "/titel"}
    assert komponenten[1]["farbe"] == "rot"  # Eingabe unverändert
