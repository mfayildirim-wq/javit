# Bühne: Werkzeugflächen (Browser, Shell, Schrittlisten) – Design

Stand 29.10.2026. Freigegeben vom Nutzer („ja“) nach drei Klarstellungen.

## Ziel

Auf Kommando des Nutzers („Browser: geh auf gg-immobilienhandel und öffne die Deals“, „Shell: zeig den
Speicherplatz“, „öffne das Terminal“) öffnet Javit auf der Bühne eine **Werkzeugfläche** und führt die Schritte dort
sichtbar aus. Werkzeugflächen sind etwas anderes als Datenflächen (Vorlagen aus Werkzeugergebnissen): keine Vorlage
aus dem Modell, kein Rezept, keine Schnellaktion, keine Persistenz über Neustarts. Ohne Kommando bleibt die Bühne
unberührt, auch wenn Javit den Browser still für eine Recherche nutzt.

## Nicht-Ziele

Klicken ins Screenshot-Bild; MCP-Apps (Server mit eigener Oberfläche); Werkzeugflächen je Unterhaltung.

## Aufbau (Kern)

* `integrationen/katalog.py`: optionaler Block `buehne` je Katalogeintrag:
  `{art: live|schritte, titel?, symbol?, bild?: <Werkzeugname mit Bildergebnis>, adresse?: <Argumentname mit URL>,
  veraendernd?: [<Werkzeugnamen, nach denen das Bild neu geholt wird>]}`. `browser.yaml` bekommt `art: live,
  bild: browser_take_screenshot, adresse: url, veraendernd: [browser_navigate, browser_navigate_back, browser_click,
  browser_type, browser_press_key, browser_select_option, browser_hover, browser_drag, browser_fill_form,
  browser_evaluate, browser_file_upload, browser_tabs, browser_handle_dialog]`.
* Eingebaute Werkzeuge erhalten ihre Definition im Kern (`buehne/werkzeugflaechen.py`): `shell` (art terminal,
  Werkzeug `shell_befehl`), `dateien` (art schritte, `datei_*`, `ordner_auflisten`).
* `integrationen/mcp_hub.py`: Bildblöcke eines Werkzeugergebnisses gehen nicht mehr verloren: `McpVerbindung`
  merkt sich je Werkzeug das letzte Bild als `data:image/<typ>;base64,…` (`letztes_bild(tool_name)`), der Text
  behält den Hinweis `[Bild: …]`. `McpWerkzeug.letztes_bild()` reicht es durch.
* `buehne/werkzeugflaechen.py` – Klasse `Werkzeugflaechen`:
  * `definitionen()` – verfügbare Werkzeugflächen (eingebaute + aktive Integrationen mit `buehne`-Block).
  * `oeffnen(kennung, modus=None)` – baut die Fläche (Kern-Vorlage, A2UI aus dem Katalog), sendet `createSurface`
    mit `art: "werkzeug"` und `symbol`, `updateComponents`, `updateDataModel`. Browser: `modus` buehne|fenster.
  * `schliessen(kennung)`.
  * `ereignis(e)` – Hörer auf `werkzeug_start`/`werkzeug_ende` der Anwendung: gehört das Werkzeug zu einer offenen
    Fläche, wird ein Schritt angehängt (Name, Kurzargumente, Zustand läuft/ok/fehler, Ergebnis gekürzt auf 600 Zeichen,
    Zeit); bei `live` nach einem verändernden Werkzeug ein Bild über `werkzeug_ausfuehren_extern(bild)` holen
    (höchstens eines gleichzeitig, eigene Aufrufe `buehne_…` erzeugen keine Schritte). Adresse aus dem Argument
    `adresse` übernehmen.
  * `aktion(flaeche, name, context)` – Knöpfe der Fläche: `werkzeug_oeffnen_url` (Adresse aus `/adresse` oder
    `context.url` → `browser_navigate`), `werkzeug_zurueck` (`browser_navigate_back`), `werkzeug_aktualisieren` (Bild
    neu), `werkzeug_modus` (Bühne ⇄ Fenster), `werkzeug_befehl` (Shell: `shell_befehl` mit `context.werte.befehl`),
    `werkzeug_schliessen`. Alle Aufrufe laufen über `Agent.werkzeug_ausfuehren_extern` (gleiche Freigaben).
  * Browser-Modus: Standard `buehne` = Playwright mit `--headless`; `fenster` = ohne. Umschalten passt `befehl` der
    Integrationskonfiguration an (`--headless` ergänzen/entfernen), speichert und verbindet neu
    (`IntegrationsManager.neu_verbinden`); die Seite wird danach neu geladen (letzte Adresse).
* `buehne/manager.py`: Flächen tragen `art` (`daten` Standard | `werkzeug`) und `symbol`; `aktion()` leitet Aktionen
  auf Werkzeugflächen an `Werkzeugflaechen.aktion` weiter; `laden()` verwirft Werkzeugflächen; Werkzeugflächen
  erscheinen nicht im Verlauf/Varianten; `prompt_abschnitt()` nennt verfügbare Werkzeugflächen und die Regel
  (nur auf Kommando öffnen, dann Schritte dort ausführen; „im Fenster“ = Modus fenster; schließen auf Wunsch).
* `buehne/werkzeuge.py`: `buehne_werkzeug_oeffnen(werkzeug, modus?)` (lesen), `buehne_werkzeug_schliessen(werkzeug)`.
* `buehne/katalog.json`: `Image` erhält Variante `screen` (volle Breite, natürliche Höhe, `fit: contain`).

## Oberfläche

* `createSurface.art?: 'daten'|'werkzeug'`, `createSurface.symbol?: string` (lucide-Name: globe, terminal, folder,
  wrench); Reiter einer Werkzeugfläche zeigt das Symbol vor dem Titel und trägt Klasse `werkzeug`.
* Werkzeugflächen bekommen kein Stil-Menü (Stil folgt `javit-dunkel`/Zuordnung), erscheinen nicht in Varianten.
* `Image` Variante `screen`: `width: 100%; height: auto; max-height: 70vh; object-fit: contain`.

## Vertrag (VERTRAEGE.md)

createSurface um `art`, `symbol` erweitert; GET /api/buehne Flächen tragen `art`; Katalogblock `buehne`; Werkzeuge
`buehne_werkzeug_oeffnen`/`_schliessen`; Aktionsnamen der Werkzeugflächen; Hinweis, dass Werkzeugflächen nicht
persistiert werden.

## Fehlerbilder

* Integration nicht eingerichtet/verbunden → `BuehnenFehler` mit Hinweis („Browser-Integration einrichten“).
* Bild nicht lieferbar (kein Bildblock) → Fläche zeigt „Kein Bild“ und die Schritte weiter.
* Neuverbinden schlägt fehl → Fehler als Schritt in der Fläche, Modus bleibt gespeichert.

## Tests

* `tests/buehne/test_werkzeugflaechen.py`: Fake-Browser-Werkzeuge (integration „browser“, Katalogeintrag mit
  `buehne`-Block, Werkzeug mit `letztes_bild`): öffnen → createSurface art werkzeug; Modellaufruf des Werkzeugs
  (über Agent) erzeugt Schritt + Bild; Knöpfe; Modus wechseln ändert `befehl` und verbindet neu (Fake-Manager);
  Shell-Fläche mit Befehl; Dateien-Schrittliste; schließen; Neustart verwirft Werkzeugflächen; ohne Fläche keine
  Schritte.
* `tests/integrationen/test_mcp_hub.py`: Bildblock → `letztes_bild`.
* Oberfläche: Reiter mit Symbol, kein Stil-Menü, Image `screen`.
