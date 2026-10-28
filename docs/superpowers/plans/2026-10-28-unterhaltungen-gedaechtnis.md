# Unterhaltungen und Gedächtnis-Optimierung – Umsetzungsplan

> **Für ausführende Agenten:** Aufgaben nacheinander mit `superpowers:executing-plans` abarbeiten; je Aufgabe
> erst Test (rot), dann Code (grün), dann Commit. Spezifikation:
> `docs/superpowers/specs/2026-10-28-unterhaltungen-gedaechtnis-design.md`.

**Ziel:** Verlauf in Unterhaltungen gliedern (Nutzer und Assistent können neue beginnen, frühere auf einer
Einstellungsseite), Gedächtnis hybrid durchsuchen, Einbettungen ohne Ollama, Unterhaltungen beim Verlassen
automatisch zusammenfassen und Fakten merken.

**Architektur:** `gedaechtnis.py` bekommt Tabellen `unterhaltungen`/`meta`, Spalten in `verlauf`/`erinnerungen`
und FTS5. Neues Modul `gedaechtnis_pflege.py` (Titel, Nachbereitung, lokale Einbettung) nutzt `LLMFassade` ohne
Werkzeuge. `Jarvis` (anwendung.py) orchestriert Wechsel + Ereignis `unterhaltung`; Server und Werkzeug rufen nur
`Jarvis`. Oberfläche: Ereignis leert Konsole, Einstellungen-Abschnitt „Unterhaltungen“, Knopf in der Kopfzeile.

**Technik:** Python 3.12, SQLite (FTS5), fastembed (optional, Extra `gedaechtnis`), FastAPI, React 18 + zustand, vitest.

Befehle: Kern `cd kern && ~/.jarvis/venv/bin/python -m pytest -q <datei>`; Oberfläche
`cd oberflaeche && npm run typecheck && npx vitest run && npm run build`.

---

### Aufgabe 1: Datenmodell und Unterhaltungen im Gedächtnis

**Dateien:** Ändern `kern/jarvis/gedaechtnis.py`; Test `kern/tests/test_unterhaltungen.py` (neu).

- [ ] Test schreiben (`test_unterhaltungen.py`):
  * `test_migration_alter_verlauf(tmp_path)`: DB mit altem Schema (`verlauf` ohne `unterhaltung_id`, zwei Zeilen)
    anlegen, `Gedaechtnis(pfad)` öffnen → `unterhaltungen()` hat genau eine mit Titel „Bisheriger Verlauf“,
    `nachrichten == 2`, `aktuell is True`; `verlauf()` liefert beide Zeilen.
  * `test_neu_aktivieren_umbenennen_loeschen(tmp_path)`: `unterhaltung_neu("Urlaub")` wird aktuell; Nachricht
    hinzufügen landet dort; `unterhaltung_aktivieren(alt)` → `verlauf()` zeigt alten Inhalt;
    `unterhaltung_umbenennen(id, "Reise")` setzt `titel_fest`; `unterhaltung_umbenennen(id, "")` → `ValueError`;
    `unterhaltung_loeschen(aktuelle)` → neueste verbliebene ist aktuell; alle löschen → neue leere entsteht.
  * `test_verlauf_loeschen_nur_aktuelle(tmp_path)`.
  * `test_zusammenfassungen(tmp_path)`: `zusammenfassung_setzen`, `letzte_zusammenfassungen()` ohne aktuelle.
- [ ] Laufen lassen → rot (AttributeError).
- [ ] Umsetzen in `gedaechtnis.py`: `_migrieren()` (PRAGMA table_info, ALTER TABLE, Tabellen `unterhaltungen`,
  `meta`), Methoden laut Spezifikation (`aktuelle`, `unterhaltungen`, `unterhaltung`, `unterhaltung_neu`,
  `unterhaltung_aktivieren`, `unterhaltung_umbenennen`, `unterhaltung_loeschen`, `zusammenfassung_setzen`,
  `nachbereitet_setzen`, `letzte_zusammenfassungen`, `verlauf(limit, unterhaltung_id=None)`,
  `verlauf_hinzufuegen(..., unterhaltung_id=None)`, `verlauf_loeschen()` nur aktuelle).
- [ ] Grün; bestehende Tests `test_agent.py`, `test_server.py` laufen weiter.
- [ ] Commit „Gedächtnis: Unterhaltungen (Tabellen, Migration, Verwaltung)“.

### Aufgabe 2: Hybridsuche, Erinnerungs-Spalten, FTS5

**Dateien:** Ändern `kern/jarvis/gedaechtnis.py`; Test `kern/tests/test_gedaechtnis_pflege.py` (neu, Teil 1).

- [ ] Tests: `test_fts_suche_ohne_vektoren` (Erinnerung „Fatih trinkt morgens Espresso“, Suche „Espresso“ →
  Treffer, `quelle == "nutzer"`); `test_vektoren_verschiedener_modelle` (Einbetter mit `modell`-Attribut; Vektor
  aus Modell A gespeichert, Anfrage mit Modell B → kein Vektorvergleich, Textwert zählt);
  `test_erinnerung_aktualisieren` (`erinnerung_aktualisieren(id, text)` ersetzt Text und FTS-Eintrag);
  `test_nachbetten` (`fehlende_einbettungen(modell)` liefert IDs ohne Vektor des Modells; `einbettung_setzen`).
- [ ] Rot → Umsetzen: Spalten `einbettung_modell`, `quelle`, `unterhaltung_id`, `aktualisiert`; `erinnerungen_fts`
  (FTS5, `try/except sqlite3.OperationalError` → `self._fts = False`); `erinnern(text, quelle="nutzer",
  unterhaltung_id=None)`; `erinnerung_aktualisieren`; `erinnerung_loeschen` spiegelt FTS; `suchen` hybrid
  (`_fts_werte(anfrage) -> dict[id, wert]`, `1/(1+rank/5)`; Vektor nur bei gleichem Modell; `wert = max`).
  Einbetter-Protokoll: Callable mit optionalem Attribut `modell: str` (Standard „unbekannt“).
- [ ] Grün, Commit „Gedächtnis: Hybridsuche mit FTS5, Einbettungsmodell je Erinnerung“.

### Aufgabe 3: Lokale Einbettung (fastembed, optional)

**Dateien:** Neu `kern/jarvis/gedaechtnis_pflege.py` (Teil: `LokaleEinbettung`), `kern/pyproject.toml` (Extra
`gedaechtnis = ["fastembed>=0.4"]`), `scripts/install*.{sh,ps1}` (`kern[stimme,gedaechtnis]`),
Ändern `kern/jarvis/anwendung.py` (Einbetter-Kette); Test Teil 2.

- [ ] Tests: `test_lokale_einbettung_kein_download(monkeypatch)` (`JARVIS_KEIN_DOWNLOAD=1`, Modell nicht im
  Cache → `None`, kein Import); `test_lokale_einbettung_mit_fake(monkeypatch)` (Modul `fastembed` mit
  `TextEmbedding.embed` gefälscht → Vektoren, `modell`-Attribut gesetzt); `test_einbetter_kette`
  (erster liefert None → zweiter wird gefragt).
- [ ] Umsetzen: `LokaleEinbettung(ordner)` async-fähig über `asyncio.to_thread`, Modellname
  `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, Cache `~/.jarvis/modelle/einbettung`;
  `einbetter_kette(*einbetter)`; in `Jarvis.__init__`: `Gedaechtnis(einbetten=einbetter_kette(llm.einbetten,
  LokaleEinbettung(...)))`; `llm.einbetten` bekommt Attribut `modell` = `einstellungen.einbettungs_modell`.
- [ ] Grün, Commit „Gedächtnis: lokale Einbettung über fastembed als Fallback“.

### Aufgabe 4: Nachbereiter (Titel, Zusammenfassung, Fakten)

**Dateien:** `kern/jarvis/gedaechtnis_pflege.py` (`Nachbereiter`), `kern/jarvis/konfig.py`
(`gedaechtnis_automatisch: bool = True`); Test Teil 3.

- [ ] Tests mit `baue_jarvis([...])`/SkriptLLM: `test_titel_erzeugen` (Antwort „Urlaub in Italien“ → Titel; bei
  Fehler Fallback auf erste 60 Zeichen); `test_nachbereiten` (JSON-Antwort mit Zusammenfassung + 2 Fakten →
  `zusammenfassung`, `nachbereitet` gesetzt, 2 Erinnerungen `quelle="auto"`); `test_nachbereiten_aktualisiert`
  (vorhandene ähnliche Erinnerung wird ersetzt, keine Dublette); `test_nachbereiten_aus`
  (`gedaechtnis_automatisch=False` → kein LLM-Aufruf); `test_nachbereiten_zu_kurz` (eine Nachricht → nichts).
- [ ] Umsetzen: `Nachbereiter(llm, gedaechtnis, einstellungen)`, `_vervollstaendigen(prompt, temperatur)` über
  `llm.antwort_streamen` (Ende-Text sammeln), `titel_erzeugen(id)`, `nachbereiten(id)`, `_json_block(text)`.
- [ ] Grün, Commit „Gedächtnis: Nachbereitung – Titel, Zusammenfassung, automatische Fakten“.

### Aufgabe 5: Anwendung, Agent, Werkzeug, Ereignis

**Dateien:** Ändern `kern/jarvis/anwendung.py`, `kern/jarvis/agent.py`, `kern/jarvis/werkzeuge/system.py`;
Tests `test_unterhaltungen.py` (Teil 2).

- [ ] Tests: `test_agent_sieht_nur_aktuelle_unterhaltung` (alte Unterhaltung mit Nachrichten, neue aktiv →
  Nachrichten an SkriptLLM enthalten nur neue); `test_werkzeug_unterhaltung_neu` (Tool-Call
  `unterhaltung_neu` → Ereignis `unterhaltung` mit `grund="neu"`, Antwort landet in neuer Unterhaltung,
  keine Freigabe); `test_titel_nach_erster_antwort` (SkriptLLM: Antwort, dann Titelantwort → Titel gesetzt);
  `test_status_enthaelt_unterhaltung`.
- [ ] Umsetzen: `Jarvis.unterhaltung_neu/aktivieren/umbenennen/loeschen` (+ `_nachbereiten_starten(alt_id)`,
  `_melden({"typ": "unterhaltung", ...})`), `status()["unterhaltung"]`, Startprüfung (6 h) in `starten()`;
  Agent: Prompt-Abschnitt „Letzte Unterhaltungen“, Regel, Titel-Task nach erster Antwort; Werkzeug
  `unterhaltung_neu` (aendern, technisch).
- [ ] Grün, Commit „Unterhaltungen: Anwendung, Agent-Kontext, Werkzeug unterhaltung_neu“.

### Aufgabe 6: REST-Endpunkte

**Dateien:** Ändern `kern/jarvis/server.py`; Test `test_unterhaltungen.py` (Teil 3, TestClient wie
`test_server._client`).

- [ ] Tests: Liste/POST/PUT/DELETE/aktivieren/verlauf, 404, 400, `DELETE /api/verlauf` nur aktuelle,
  `GET /api/gedaechtnis` enthält `quelle`.
- [ ] Umsetzen laut Tabelle in der Spezifikation.
- [ ] Grün, Commit „Unterhaltungen: REST-Endpunkte“.

### Aufgabe 7: Oberfläche – Typen, API, Zustand, Ereignis

**Dateien:** `src/api/types.ts`, `src/api/rest.ts`, `src/state/reducer.ts`, `src/state/store.ts`,
`src/state/verbindung.ts`; Test `src/__tests__/unterhaltungen.test.tsx` (Teil 1: Reducer).

- [ ] Reducer-Test: `unterhaltung`-Ereignis mit neuer Kennung leert `nachrichten`, setzt `unterhaltung`; gleiche
  Kennung mit `grund: 'titel'` ändert nur den Titel; `lokal_verlauf` ersetzt nach Wechsel.
- [ ] Umsetzen: Typen, `api.unterhaltungen…`, Zustand `unterhaltung: {id, titel} | null`, Verbindung lädt nach
  Wechsel den Verlauf neu (`verlaufLaden()` nach `unterhaltung`-Ereignis), Status setzt `unterhaltung`.
- [ ] Grün (`npx vitest run`), Commit.

### Aufgabe 8: Oberfläche – Kopfzeile, Palette, Tastenkürzel, Einstellungen

**Dateien:** `src/components/TopBar.tsx`, `src/components/CommandPalette.tsx`, `src/lib/tasten.ts`,
`src/views/Settings.tsx`, `src/styles/app.css`; Test Teil 2.

- [ ] Tests: Knopf „Neue Unterhaltung“ → `POST /api/unterhaltungen`; Einstellungen-Abschnitt listet
  Unterhaltungen, „Öffnen“ ruft `aktivieren` und wechselt zur Konsole, Umbenennen ruft PUT, Löschen mit
  Bestätigung ruft DELETE; Gedächtnis-Abschnitt zeigt Herkunft und Schalter „Automatisch merken“.
- [ ] Umsetzen; `npm run typecheck && npx vitest run && npm run build`.
- [ ] Commit „Oberfläche: Unterhaltungen (Kopfzeile, Palette, Einstellungen), Gedächtnis-Herkunft“.

### Aufgabe 9: Doku und Abschluss

- [ ] `docs/VERTRAEGE.md` (Endpunkte, Ereignis, Einstellung), `README.md`/`README.de.md`, `docs/STAND.md`,
  `docs/PROTOKOLL.md` (Eintrag 28.10.2026), `CLAUDE.md` (Aufbau).
- [ ] Gesamte Kern-Suite (`--deselect tests/test_plattform.py::test_kritische_pfade_linux`), Oberfläche komplett,
  Live-Prüfung auf Port 8766 (neue Unterhaltung über Oberfläche, Liste in Einstellungen).
- [ ] Caches aufräumen, Commit, Push.
