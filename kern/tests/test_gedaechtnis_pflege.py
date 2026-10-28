"""Gedächtnis-Optimierung: Hybridsuche, Einbettungsmodelle, lokale Einbettung, Nachbereitung."""

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
