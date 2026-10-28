"""Unterhaltungen: Datenmodell, Migration, Verwaltung im Gedächtnis."""

import sqlite3

from jarvis.gedaechtnis import Gedaechtnis


def test_migration_alter_verlauf(tmp_path):
    pfad = tmp_path / "alt.db"
    db = sqlite3.connect(pfad)
    db.executescript(
        """
        CREATE TABLE verlauf (id INTEGER PRIMARY KEY AUTOINCREMENT, zeit TEXT NOT NULL, rolle TEXT NOT NULL, inhalt TEXT NOT NULL);
        CREATE TABLE erinnerungen (id INTEGER PRIMARY KEY AUTOINCREMENT, zeit TEXT NOT NULL, text TEXT NOT NULL, einbettung TEXT);
        INSERT INTO verlauf (zeit, rolle, inhalt) VALUES ('2026-10-01T10:00:00', 'nutzer', 'Hallo');
        INSERT INTO verlauf (zeit, rolle, inhalt) VALUES ('2026-10-01T10:00:05', 'jarvis', 'Guten Tag.');
        INSERT INTO erinnerungen (zeit, text) VALUES ('2026-10-01T10:00:00', 'Mag Espresso');
        """
    )
    db.commit()
    db.close()

    g = Gedaechtnis(pfad)
    liste = g.unterhaltungen()
    assert len(liste) == 1
    assert liste[0]["titel"] == "Bisheriger Verlauf"
    assert liste[0]["nachrichten"] == 2
    assert liste[0]["aktuell"] is True
    assert [v["inhalt"] for v in g.verlauf()] == ["Hallo", "Guten Tag."]
    assert g.erinnerungen()[0]["quelle"] == "nutzer"
    # Zweites Öffnen: keine zweite Migration
    g.schliessen()
    g = Gedaechtnis(pfad)
    assert len(g.unterhaltungen()) == 1
    g.schliessen()


def test_leere_datenbank_hat_eine_unterhaltung(tmp_path):
    g = Gedaechtnis(tmp_path / "neu.db")
    aktuelle = g.aktuelle()
    assert aktuelle["titel"] == "Neue Unterhaltung" and aktuelle["nachrichten"] == 0
    assert g.unterhaltungen()[0]["id"] == aktuelle["id"]
    g.schliessen()


def test_neu_aktivieren_umbenennen_loeschen(tmp_path):
    g = Gedaechtnis(tmp_path / "u.db")
    erste = g.aktuelle()["id"]
    g.verlauf_hinzufuegen("nutzer", "Alte Frage")
    g.verlauf_hinzufuegen("jarvis", "Alte Antwort")

    neu = g.unterhaltung_neu("Urlaub")
    assert neu["titel"] == "Urlaub" and neu["aktuell"] is True and neu["id"] != erste
    assert g.verlauf() == []
    g.verlauf_hinzufuegen("nutzer", "Wohin?")
    assert [v["inhalt"] for v in g.verlauf()] == ["Wohin?"]
    assert [v["inhalt"] for v in g.verlauf(unterhaltung_id=erste)] == ["Alte Frage", "Alte Antwort"]

    zurueck = g.unterhaltung_aktivieren(erste)
    assert zurueck["aktuell"] is True and g.aktuelle()["id"] == erste
    assert [v["inhalt"] for v in g.verlauf()] == ["Alte Frage", "Alte Antwort"]

    umbenannt = g.unterhaltung_umbenennen(neu["id"], "  Reise nach Rom  ")
    assert umbenannt["titel"] == "Reise nach Rom" and umbenannt["titel_fest"] is True
    for schlecht in ("", "   ", "x" * 81):
        try:
            g.unterhaltung_umbenennen(neu["id"], schlecht)
        except ValueError:
            pass
        else:
            raise AssertionError("ungültiger Titel wurde angenommen")

    # Liste: neueste Aktivität zuerst, Zähler stimmen
    liste = g.unterhaltungen()
    assert [u["id"] for u in liste][:2] == [erste, neu["id"]] or [u["id"] for u in liste][:2] == [neu["id"], erste]
    assert {u["id"]: u["nachrichten"] for u in liste} == {erste: 2, neu["id"]: 1}

    # Aktuelle löschen → andere wird aktuell
    ergebnis = g.unterhaltung_loeschen(erste)
    assert ergebnis["geloescht"] is True and ergebnis["aktuell"]["id"] == neu["id"]
    assert g.verlauf(unterhaltung_id=erste) == []
    # Letzte löschen → neue leere entsteht
    ergebnis = g.unterhaltung_loeschen(neu["id"])
    aktuelle = g.aktuelle()
    assert ergebnis["aktuell"]["id"] == aktuelle["id"] and aktuelle["nachrichten"] == 0
    assert g.unterhaltung(999) is None
    g.schliessen()


def test_verlauf_loeschen_nur_aktuelle(tmp_path):
    g = Gedaechtnis(tmp_path / "v.db")
    erste = g.aktuelle()["id"]
    g.verlauf_hinzufuegen("nutzer", "eins")
    zweite = g.unterhaltung_neu()["id"]
    g.verlauf_hinzufuegen("nutzer", "zwei")
    g.verlauf_loeschen()
    assert g.verlauf() == []
    assert [v["inhalt"] for v in g.verlauf(unterhaltung_id=erste)] == ["eins"]
    assert g.unterhaltung(zweite)["nachrichten"] == 0
    g.schliessen()


def test_zusammenfassungen(tmp_path):
    g = Gedaechtnis(tmp_path / "z.db")
    erste = g.aktuelle()["id"]
    g.verlauf_hinzufuegen("nutzer", "Plan für Rom")
    g.zusammenfassung_setzen(erste, "Der Nutzer plant eine Reise nach Rom im Mai.")
    g.nachbereitet_setzen(erste)
    zweite = g.unterhaltung_neu("Kaffee")["id"]
    g.zusammenfassung_setzen(zweite, "Kaffeesorten verglichen.")
    dritte = g.unterhaltung_neu("Aktuell")["id"]
    letzte = g.letzte_zusammenfassungen(anzahl=5)
    assert [z["id"] for z in letzte] == [zweite, erste]
    assert letzte[1]["zusammenfassung"].startswith("Der Nutzer plant")
    assert g.unterhaltung(erste)["nachbereitet"] is not None
    assert g.unterhaltung(dritte)["zusammenfassung"] is None
    g.schliessen()
