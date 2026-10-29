# Bühne: Werkzeugflächen – Umsetzungsplan

> Spezifikation: `docs/superpowers/specs/2026-10-29-buehne-werkzeugflaechen-design.md`. Reihenfolge je Aufgabe:
> Test schreiben → rot → umsetzen → grün → nächster Schritt. Abschluss: Gesamtsuite Kern, Oberfläche typecheck/test/
> build, Doku, Commit, Push.

- [ ] 1 Katalog: `BuehnenBlock` in `integrationen/katalog.py`, `browser.yaml` ergänzen; Test in `tests/integrationen/test_katalog.py`.
- [ ] 2 MCP-Hub: Bildblöcke merken (`letztes_bild`), Test mit Fake-CallToolResult.
- [ ] 3 Katalog `Image` Variante `screen` (Kern + Prüfung + Oberfläche CSS).
- [ ] 4 `buehne/werkzeugflaechen.py`: Definitionen, Vorlagenbau (Browser live, Shell terminal, Schritte), öffnen/schließen.
- [ ] 5 Hörer: Schritte aus `werkzeug_start`/`werkzeug_ende`, Bild nach verändernden Werkzeugen, Adresse.
- [ ] 6 Aktionen der Fläche (URL öffnen, zurück, aktualisieren, Modus, Befehl, schließen) + Browser-Modus über Integrationskonfig.
- [ ] 7 Manager: `art`/`symbol` an Flächen, Weiterleitung von Aktionen, `laden()` verwirft Werkzeugflächen, Prompt.
- [ ] 8 Werkzeuge `buehne_werkzeug_oeffnen`/`_schliessen`, Verdrahtung in `anwendung.py`.
- [ ] 9 Oberfläche: Typen, Store `art`/`symbol`, Reiter-Symbol, kein Stil-Menü, CSS; Tests.
- [ ] 10 Doku: VERTRAEGE, STAND, PROTOKOLL, README (de/en), CLAUDE.md; Gesamttests; Commit; Push.
