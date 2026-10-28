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


# ---------------------------------------------------------------- Anwendung, Agent, Werkzeug
import json

from tests.conftest import text_chunks, tool_chunks
from tests.helfer import baue_jarvis


def _mit_ereignissen(j):
    ereignisse = []

    async def hoerer(e):
        ereignisse.append(e)

    j.hoerer_hinzufuegen(hoerer)
    return ereignisse


async def test_agent_sieht_nur_aktuelle_unterhaltung():
    j, skript = baue_jarvis([text_chunks("Zwei.")])
    j.gedaechtnis.verlauf_hinzufuegen("nutzer", "alte Frage")
    j.gedaechtnis.verlauf_hinzufuegen("jarvis", "alte Antwort")
    j.gedaechtnis.unterhaltung_neu("Neu")
    await j.agent.verarbeiten("zweite Frage")
    nachrichten = skript.aufrufe[0]["messages"]
    assert [m["role"] for m in nachrichten] == ["system", "user"]
    assert "alte Frage" not in json.dumps(nachrichten, ensure_ascii=False)


async def test_letzte_unterhaltungen_im_systemprompt():
    j, skript = baue_jarvis([text_chunks("Ja.")])
    alt = j.gedaechtnis.aktuelle()["id"]
    j.gedaechtnis.unterhaltung_umbenennen(alt, "Rom-Reise")
    j.gedaechtnis.zusammenfassung_setzen(alt, "Reise nach Rom im Mai geplant.")
    j.gedaechtnis.unterhaltung_neu()
    await j.agent.verarbeiten("Wie neulich besprochen?")
    system = skript.aufrufe[0]["messages"][0]["content"]
    assert "## Letzte Unterhaltungen" in system and "„Rom-Reise“: Reise nach Rom im Mai geplant." in system
    assert "unterhaltung_neu" in system


async def test_werkzeug_unterhaltung_neu():
    j, skript = baue_jarvis([
        tool_chunks("c1", "unterhaltung_neu", {"titel": "Neues Thema"}),
        text_chunks("Gern, worum geht es?"),
    ])
    ereignisse = _mit_ereignissen(j)
    alt = j.gedaechtnis.aktuelle()["id"]
    antwort = await j.agent.verarbeiten("Lass uns über etwas anderes reden")
    assert antwort == "Gern, worum geht es?"
    neu = j.gedaechtnis.aktuelle()
    assert neu["id"] != alt and neu["titel"] == "Neues Thema" and neu["titel_fest"] is True
    assert [e["typ"] for e in ereignisse if e["typ"] == "freigabe_noetig"] == []
    wechsel = [e for e in ereignisse if e["typ"] == "unterhaltung"]
    assert wechsel[0] == {"typ": "unterhaltung", "id": neu["id"], "titel": "Neues Thema", "grund": "neu"}
    assert [v["inhalt"] for v in j.gedaechtnis.verlauf(unterhaltung_id=alt)] == ["Lass uns über etwas anderes reden"]
    assert [v["inhalt"] for v in j.gedaechtnis.verlauf()] == ["Gern, worum geht es?"]


async def test_titel_nach_erster_antwort_und_ereignis():
    j, skript = baue_jarvis([text_chunks("Rom ist im Mai wunderbar."), text_chunks("Reise nach Rom")])
    j.konfig.aktualisieren({"gedaechtnis_automatisch": True})
    ereignisse = _mit_ereignissen(j)
    kennung = j.gedaechtnis.aktuelle()["id"]
    await j.agent.verarbeiten("Erzähl mir von Rom im Mai")
    await j.pflege_abwarten()
    assert j.gedaechtnis.unterhaltung(kennung)["titel"] == "Reise nach Rom"
    assert {"typ": "unterhaltung", "id": kennung, "titel": "Reise nach Rom", "grund": "titel"} in ereignisse
    assert len(skript.aufrufe) == 2
    # Zweite Antwort: kein weiterer Titelaufruf
    skript.antworten.append(text_chunks("Und Florenz."))
    await j.agent.verarbeiten("Und sonst?")
    await j.pflege_abwarten()
    assert len(skript.aufrufe) == 3


async def test_wechsel_bereitet_alte_unterhaltung_nach():
    antwort = {"zusammenfassung": "Über Rom gesprochen.", "fakten": ["Der Nutzer mag Italien."]}
    j, skript = baue_jarvis([text_chunks(json.dumps(antwort))])
    j.konfig.aktualisieren({"gedaechtnis_automatisch": True})
    ereignisse = _mit_ereignissen(j)
    alt = j.gedaechtnis.aktuelle()["id"]
    j.gedaechtnis.verlauf_hinzufuegen("nutzer", "Rom?")
    j.gedaechtnis.verlauf_hinzufuegen("jarvis", "Rom!")
    neu = await j.unterhaltung_neu()
    await j.pflege_abwarten()
    assert j.gedaechtnis.unterhaltung(alt)["zusammenfassung"] == "Über Rom gesprochen."
    assert [e["text"] for e in j.gedaechtnis.erinnerungen()] == ["Der Nutzer mag Italien."]
    assert ereignisse[0]["typ"] == "unterhaltung" and ereignisse[0]["id"] == neu["id"]
    # Zurückwechseln und umbenennen/löschen senden ebenfalls Ereignisse
    await j.unterhaltung_aktivieren(alt)
    assert ereignisse[-1] == {"typ": "unterhaltung", "id": alt, "titel": "Neue Unterhaltung", "grund": "gewechselt"}
    await j.unterhaltung_umbenennen(alt, "Rom")
    assert ereignisse[-1]["grund"] == "titel" and ereignisse[-1]["titel"] == "Rom"
    ergebnis = await j.unterhaltung_loeschen(alt)
    assert ergebnis["aktuell"]["id"] == neu["id"] and ereignisse[-1] == {
        "typ": "unterhaltung", "id": neu["id"], "titel": "Neue Unterhaltung", "grund": "geloescht",
    }
    assert j.status()["unterhaltung"] == {"id": neu["id"], "titel": "Neue Unterhaltung"}


async def test_start_bereitet_alte_aktuelle_nach():
    antwort = {"zusammenfassung": "Alt.", "fakten": []}
    j, skript = baue_jarvis([text_chunks(json.dumps(antwort))])
    j.konfig.aktualisieren({"gedaechtnis_automatisch": True})
    kennung = j.gedaechtnis.aktuelle()["id"]
    j.gedaechtnis.verlauf_hinzufuegen("nutzer", "a")
    j.gedaechtnis.verlauf_hinzufuegen("jarvis", "b")
    j.gedaechtnis._db.execute("UPDATE unterhaltungen SET aktualisiert = '2026-01-01T10:00:00' WHERE id = ?", (kennung,))
    j.gedaechtnis._db.commit()
    await j.starten(integrationen=False, stimme=False)
    await j.pflege_abwarten()
    assert j.gedaechtnis.unterhaltung(kennung)["zusammenfassung"] == "Alt."
    assert j.gedaechtnis.aktuelle()["id"] == kennung  # bleibt aktuell
    await j.stoppen()


# ---------------------------------------------------------------- REST
from fastapi.testclient import TestClient

from jarvis.server import create_app


def _client(antworten=None):
    j, skript = baue_jarvis(antworten)
    app = create_app(j, integrationen_starten=False, stimme_starten=False)
    return TestClient(app, base_url="http://127.0.0.1:8765"), j


def test_rest_unterhaltungen():
    client, j = _client()
    with client as c:
        erste = c.get("/api/status").json()["unterhaltung"]
        assert erste["titel"] == "Neue Unterhaltung"
        j.gedaechtnis.verlauf_hinzufuegen("nutzer", "alt")
        neu = c.post("/api/unterhaltungen", json={"titel": "Rom"}).json()
        assert neu["titel"] == "Rom" and neu["aktuell"] is True and neu["titel_fest"] is True
        assert c.post("/api/unterhaltungen", json={"titel": "x" * 81}).status_code == 400
        leer = c.post("/api/unterhaltungen").json()
        assert leer["titel"] == "Neue Unterhaltung"
        liste = c.get("/api/unterhaltungen").json()
        assert [u["id"] for u in liste] == [leer["id"], neu["id"], erste["id"]]
        assert liste[2]["nachrichten"] == 1 and liste[0]["aktuell"] is True

        assert c.get(f"/api/unterhaltungen/{erste['id']}").json()["titel"] == "Neue Unterhaltung"
        assert c.get("/api/unterhaltungen/999").status_code == 404
        assert c.get(f"/api/unterhaltungen/{erste['id']}/verlauf").json()[0]["inhalt"] == "alt"
        assert c.get("/api/unterhaltungen/999/verlauf").status_code == 404
        assert c.get("/api/verlauf").json() == []  # aktuelle (leere) Unterhaltung

        assert c.put(f"/api/unterhaltungen/{erste['id']}", json={"titel": "Anfang"}).json()["titel"] == "Anfang"
        assert c.put(f"/api/unterhaltungen/{erste['id']}", json={"titel": ""}).status_code == 400
        assert c.put("/api/unterhaltungen/999", json={"titel": "x"}).status_code == 404

        aktiv = c.post(f"/api/unterhaltungen/{erste['id']}/aktivieren").json()
        assert aktiv["aktuell"] is True and c.get("/api/verlauf").json()[0]["inhalt"] == "alt"
        assert c.post("/api/unterhaltungen/999/aktivieren").status_code == 404
        assert c.get("/api/status").json()["unterhaltung"] == {"id": erste["id"], "titel": "Anfang"}

        # DELETE /api/verlauf leert nur die aktuelle
        c.post(f"/api/unterhaltungen/{neu['id']}/aktivieren")
        j.gedaechtnis.verlauf_hinzufuegen("nutzer", "rom")
        assert c.delete("/api/verlauf").json() == {"geloescht": True}
        assert c.get("/api/verlauf").json() == []
        assert len(c.get(f"/api/unterhaltungen/{erste['id']}/verlauf").json()) == 1

        ergebnis = c.delete(f"/api/unterhaltungen/{neu['id']}").json()
        assert ergebnis["geloescht"] is True and ergebnis["aktuell"]["id"] in (erste["id"], leer["id"])
        assert c.delete("/api/unterhaltungen/999").status_code == 404
        assert len(c.get("/api/unterhaltungen").json()) == 2


async def test_rest_gedaechtnis_mit_quelle():
    client, j = _client()
    with client as c:
        await j.gedaechtnis.erinnern("Mag Tee.", quelle="auto")
        e = c.get("/api/gedaechtnis").json()
        assert e[0]["quelle"] == "auto" and e[0]["text"] == "Mag Tee."
        assert c.get("/api/einstellungen").json()["gedaechtnis_automatisch"] is False  # Testhelfer schaltet aus
        assert c.put("/api/einstellungen", json={"gedaechtnis_automatisch": True}).json()["gedaechtnis_automatisch"] is True
