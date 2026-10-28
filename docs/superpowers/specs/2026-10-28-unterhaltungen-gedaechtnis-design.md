# Unterhaltungen und Gedächtnis-Optimierung – Design (28.10.2026)

## Ziel

1. **Unterhaltungen**: Der Verlauf ist nicht mehr eine endlose Liste, sondern in Unterhaltungen mit Titel
   gegliedert. Der Agent nimmt nur die aktuelle Unterhaltung als Kontext. Nutzer und Assistent können eine
   neue Unterhaltung beginnen; frühere sind auf einer eigenen Seite (Einstellungen → Unterhaltungen)
   einsehbar, umbenennbar, löschbar und wieder aktivierbar. Die Startseite (Konsole) bleibt unverändert.
2. **Gedächtnis**: Suche hybrid (Vektoren + SQLite-Volltext), Einbettungen auch ohne Ollama über ein kleines
   lokales Modell, und automatisches Merken: Beim Verlassen einer Unterhaltung fasst das Modell sie zusammen
   und zieht dauerhafte Fakten heraus, die mit vorhandenen Erinnerungen abgeglichen werden.

Nicht enthalten (bewusst): Profilschicht, mem0/zentrales Gedächtnis, Unterhaltungsliste auf der Startseite.

## Kern

### Datenmodell (`gedaechtnis.py`, SQLite `~/.jarvis/jarvis.db`)

```
unterhaltungen(id, titel, titel_fest, erstellt, aktualisiert, zusammenfassung, nachbereitet)
verlauf(id, zeit, rolle, inhalt, unterhaltung_id)            -- neue Spalte
erinnerungen(id, zeit, text, einbettung, einbettung_modell,  -- neue Spalten
             quelle 'nutzer'|'auto', unterhaltung_id, aktualisiert)
erinnerungen_fts(text)   -- FTS5, extern gepflegt (INSERT/UPDATE/DELETE spiegeln); fehlt FTS5, Stichwortsuche
meta(schluessel, wert)   -- 'aktuelle_unterhaltung'
```

Migration beim Öffnen: fehlende Spalten per `ALTER TABLE` ergänzen; gibt es Verlaufszeilen ohne
`unterhaltung_id`, entsteht die Unterhaltung „Bisheriger Verlauf“ und bekommt sie. Gibt es keine
Unterhaltung, wird eine leere angelegt. `aktuelle_unterhaltung` zeigt immer auf eine existierende Zeile.

### Unterhaltungen (`Gedaechtnis`)

* `aktuelle() -> dict`, `unterhaltungen() -> list[dict]` (neueste zuerst; `id, titel, erstellt, aktualisiert,
  nachrichten, zusammenfassung, aktuell`), `unterhaltung(id)`.
* `unterhaltung_neu(titel=None) -> dict` – legt an und macht sie aktuell; Titel-Standard „Neue Unterhaltung“.
* `unterhaltung_aktivieren(id)`, `unterhaltung_umbenennen(id, titel)` (1–80 Zeichen),
  `unterhaltung_loeschen(id)` – löscht Verlauf mit; war sie aktuell, wird die neueste verbliebene aktiv,
  sonst eine neue leere angelegt. Erinnerungen bleiben (nur `unterhaltung_id` → NULL).
* `verlauf_hinzufuegen(rolle, inhalt, unterhaltung_id=None)` schreibt in die aktuelle; `aktualisiert` wird gesetzt.
* `verlauf(limit, unterhaltung_id=None)` liefert die aktuelle bzw. gewählte; `verlauf_loeschen()` leert nur die aktuelle.
* `zusammenfassung_setzen(id, zusammenfassung)`, `nachbereitet_setzen(id)`,
  `letzte_zusammenfassungen(anzahl=5)` (ohne die aktuelle, nur mit Zusammenfassung).
* Automatischer Titel: `titel_automatisch` bleibt True, bis der Nutzer umbenennt (Spalte `titel_fest INTEGER`).

### Nachbereitung (`gedaechtnis_pflege.py`, neu)

`Nachbereiter(llm, gedaechtnis, einstellungen)`:

* `titel_erzeugen(unterhaltung_id)` – nach der ersten vollständigen Antwort (ein Nutzer- und ein
  Assistent-Beitrag): ein Modellaufruf ohne Werkzeuge, Temperatur 0.2, „Titel in 3–5 Wörtern, ohne
  Anführungszeichen/Punkt“; Fallback: erste 60 Zeichen der ersten Nutzernachricht. Nur wenn `titel_fest` = 0.
* `nachbereiten(unterhaltung_id)` – beim Verlassen einer Unterhaltung (durch „neu“ oder „aktivieren“, nicht beim Löschen) mit
  mindestens zwei Beiträgen und neuen Beiträgen seit `nachbereitet`: ein Modellaufruf liefert JSON
  `{"zusammenfassung": "2–3 Sätze", "fakten": ["…"]}`. Prompt-Regeln: nur dauerhafte Fakten über den
  Nutzer (Vorlieben, Lebensumstände, Projekte, Absprachen), keine Gesprächsdetails, keine Geheimnisse
  (Passwörter, Schlüssel), Deutsch, höchstens 8 Fakten. JSON tolerant parsen (erster `{…}`-Block).
* Abgleich je Fakt: `suchen(fakt, anzahl=1)`; Relevanz ≥ 0.85 → vorhandene Erinnerung aktualisieren
  (Text ersetzen, `aktualisiert`, neu einbetten); ≥ 0.6 und gleiche Herkunft `auto` → ebenfalls ersetzen;
  sonst neu anlegen mit `quelle='auto'`, `unterhaltung_id`.
* Läuft als Hintergrundaufgabe (`asyncio.create_task`), Fehler werden protokolliert, nie an den Nutzer.
  Einstellung `gedaechtnis_automatisch: bool = True` schaltet Nachbereitung und Titel ab (Titel-Fallback bleibt).
* Beim Serverstart: ist die aktuelle Unterhaltung nicht nachbereitet und älter als 6 Stunden
  (`aktualisiert`), wird sie nachbereitet, bleibt aber aktuell.

### Suche und Einbettungen

* `Einbetter`-Kette in `anwendung.py`: `llm.einbetten` (Ollama/Cloud laut `einbettungs_modell`) → bei None
  `lokale_einbettung` (fastembed, Modell `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`,
  384 Dimensionen, erster Download ≈ 120 MB nach `~/.jarvis/modelle/einbettung`, nicht bei
  `JARVIS_KEIN_DOWNLOAD=1`, Paket optional: Extra `kern[gedaechtnis]`, Installer installieren
  `kern[stimme,gedaechtnis]`) → sonst None (Stichwort + FTS).
* Jede Einbettung speichert ihren Modellnamen; die Suche vergleicht nur Vektoren desselben Modells wie die
  Anfrage-Einbettung. Beim Start werden bis zu 200 Erinnerungen ohne Vektor des aktuellen Modells im
  Hintergrund nachgebettet.
* Hybrid: Vektorwert (Kosinus) und Textwert (FTS5-BM25 normiert auf 0–1 über `1/(1+rank/5)`, sonst das
  bisherige Stichwortmaß) → `wert = max(vektor, text)`; Rückgabe wie bisher (`id, zeit, text, relevanz`)
  plus `quelle`.

### Agent (`agent.py`)

* Kontext aus `gedaechtnis.verlauf(limit, aktuelle)` – unverändert in der Form.
* Systemprompt: zusätzlich „## Letzte Unterhaltungen“ mit bis zu 5 Zeilen `- <Datum> „<Titel>“: <Zusammenfassung>`,
  wenn vorhanden. Regel: „Kündigt der Nutzer ein neues Thema an oder bittet um eine neue Unterhaltung,
  rufe unterhaltung_neu auf (optional mit Titel) und bestätige kurz.“
* Nach `antwort_ende` der ersten Antwort einer Unterhaltung: Titel-Aufgabe starten.

### Werkzeug (`werkzeuge/system.py`)

`unterhaltung_neu(titel?: str)` – Risiko `aendern`, Bereich technisch (keine Rückfrage). Ruft
`anwendung.unterhaltung_neu(titel, grund="assistent")`, antwortet „Neue Unterhaltung begonnen.“ Die
Nutzernachricht, die den Wechsel auslöste, bleibt in der alten Unterhaltung; die Antwort landet in der neuen.

### Anwendung (`anwendung.py`)

`unterhaltung_neu(titel=None)`, `unterhaltung_aktivieren(id)`, `unterhaltung_loeschen(id)`,
`unterhaltung_umbenennen(id, titel)`: ändern das Gedächtnis, stoßen Nachbereitung der verlassenen
Unterhaltung an und senden das Ereignis `unterhaltung`. `status()` enthält `unterhaltung: {id, titel}`.

### REST (`server.py`) – Erweiterung von `docs/VERTRAEGE.md`

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/unterhaltungen` | Liste (neueste zuerst) |
| POST | `/api/unterhaltungen` `{titel?}` | neue Unterhaltung, wird aktuell → Detail |
| GET | `/api/unterhaltungen/{id}` | Detail |
| PUT | `/api/unterhaltungen/{id}` `{titel}` | umbenennen (setzt `titel_fest`) |
| DELETE | `/api/unterhaltungen/{id}` | löschen → `{geloescht, aktuell}` |
| POST | `/api/unterhaltungen/{id}/aktivieren` | aktuell machen → Detail |
| GET | `/api/unterhaltungen/{id}/verlauf?limit=` | Nachrichten dieser Unterhaltung |
| GET | `/api/verlauf?limit=` | wie bisher: aktuelle Unterhaltung |
| DELETE | `/api/verlauf` | leert nur die aktuelle Unterhaltung |
| GET | `/api/gedaechtnis` | zusätzlich `quelle`, `aktualisiert` je Erinnerung |

Fehler: 404 unbekannte Kennung, 400 ungültiger Titel. WebSocket-Ereignis
`{"typ": "unterhaltung", "id", "titel", "grund": "neu"|"gewechselt"|"titel"|"geloescht"}`.
Einstellung `gedaechtnis_automatisch` in `GET/PUT /api/einstellungen`.

## Oberfläche

* **Konsole**: Beim Ereignis `unterhaltung` mit anderer Kennung als der bekannten: Nachrichten leeren und den
  Verlauf der neuen Unterhaltung laden (`lokal_verlauf` darf dann ersetzen → neue Aktion
  `lokal_unterhaltung` setzt `unterhaltung` und leert die Nachrichten). Kopfzeile zeigt den Titel der
  aktuellen Unterhaltung dezent (aus `Status.unterhaltung` bzw. Ereignis).
* **Neue Unterhaltung**: Knopf in der Kopfzeile (Icon „Plus im Sprechblasen-Symbol“, Tooltip
  „Neue Unterhaltung“), Eintrag in der Befehlspalette, Tastenkürzel Alt+N.
* **Einstellungen → Abschnitt „Unterhaltungen“**: Liste (Titel, Datum, Anzahl Nachrichten, aktuelle markiert)
  mit „Öffnen“ (aktivieren + zur Konsole), „Umbenennen“ (Inline-Feld), „Löschen“ (Bestätigung inline),
  Knopf „Neue Unterhaltung“. Gedächtnis-Abschnitt: Erinnerungen zeigen Herkunft („automatisch“/„von Ihnen“),
  einzeln löschbar (vorhandener `DELETE /api/gedaechtnis?id=`), Schalter „Automatisch merken“.
* `types.ts`: `Unterhaltung`, `EvUnterhaltung`, `Status.unterhaltung?`, `Erinnerung.quelle?`,
  `Einstellungen.gedaechtnis_automatisch`. `rest.ts`: `unterhaltungen`, `unterhaltungNeu`, `unterhaltungAktivieren`,
  `unterhaltungUmbenennen`, `unterhaltungLoeschen`, `unterhaltungVerlauf`.

## Tests

* Kern `tests/test_unterhaltungen.py`: Migration alter DB (Verlauf → „Bisheriger Verlauf“), neu/aktivieren/
  umbenennen/löschen inkl. Fallback auf neue leere, Kontextgrenze (Agent sieht nur aktuelle Unterhaltung),
  Werkzeug `unterhaltung_neu` über den Agenten (SkriptLLM mit Tool-Call) und Ereignis, REST-Endpunkte,
  `DELETE /api/verlauf` leert nur die aktuelle.
* Kern `tests/test_gedaechtnis_pflege.py`: Titel aus SkriptLLM und Fallback, Nachbereitung (JSON-Antwort →
  Zusammenfassung + Fakten; Abgleich aktualisiert statt dupliziert; `gedaechtnis_automatisch=False` tut nichts),
  Hybridsuche (FTS-Treffer ohne Vektoren; Vektoren verschiedener Modelle werden nicht verglichen),
  lokale Einbettung wird bei `JARVIS_KEIN_DOWNLOAD` übersprungen (fastembed gemockt).
* Oberfläche `unterhaltungen.test.tsx`: Liste in Einstellungen, Öffnen wechselt zur Konsole und lädt Verlauf,
  Ereignis `unterhaltung` leert die Konsole, Knopf „Neue Unterhaltung“ ruft POST.
* Bestehende Tests: `test_server` Status/Verlauf, `test_agent` Verlauf-Kontext anpassen.

## Doku

`docs/VERTRAEGE.md` (Endpunkte, Ereignis, Einstellung), `README.md`/`README.de.md` (Unterhaltungen,
automatisches Gedächtnis), `docs/STAND.md`, `docs/PROTOKOLL.md`, `CLAUDE.md` (Aufbau: `gedaechtnis_pflege.py`).
