# Bühne: generative Oberfläche über dem Chat – Design (28.10.2026)

## Ziel

Oberhalb des Chats entsteht eine **Bühne**, auf der der Assistent Ergebnisse als lebende Oberfläche aufbaut:
Immobilienliste aus GG, Posteingang, Wetterkarte – mit Aktionsknöpfen, die weitere Arbeit auslösen. Die
Oberfläche wird **generativ** vom Modell beschrieben (kein HTML, kein Code), aber **nur einmal**: Beim ersten
Aufruf baut die KI eine **Vorlage** (Struktur mit Datenbindungen), danach wird die Vorlage nur noch mit Daten
befüllt und auf Wunsch angepasst. Vorlagen, Aktionsrezepte und Stile gelten dauerhaft über alle Unterhaltungen.
Jede App bekommt ihren Stil: vordefiniert (5–10, erweiterbar) oder generativ aus App-Link, Stil-Link oder
hochgeladenen Stilklassen abgeleitet.

Anbieterunabhängig: jedes Modell über `LLMFassade`; kleine lokale Modelle bekommen Schema-gebundene Ausgabe,
Reparaturschleife und einen deterministischen Fallback.

Nicht enthalten (spätere Stufen): Browser-Fläche für Javits eigene Browserarbeit, MCP Apps (iframe-Flächen von
MCP-Servern), Vorlagen-Editor per Hand.

## Recherche (28.10.2026)

Verglichen: A2UI (Google, Apache-2.0, v0.9.1, v1.0 Q4 2026), MCP Apps (MCP-Erweiterung 2026-01-26), MCP-UI,
AG-UI/CopilotKit, Vercel json-render und AI SDK, OpenAI Apps SDK, Thesys OpenUI/C1, assistant-ui, Tambo (Cloud
schließt 31.10.2026), Flutter GenUI, Adaptive Cards, react-jsonschema-form. Ergebnis: **A2UI als
Beschreibungsformat** (Struktur, Datenmodell und Aktionen getrennt, JSON-Pointer-Bindung, Listen-Templates,
flache Komponentenliste für Streaming, Python-SDK `a2ui-agent-sdk` mit Prompt-Erzeugung und JSON-Reparatur),
**eigener schlanker React-Renderer** (offizieller `@a2ui/react` ist Preview mit eigenem Design; Format bleibt
kompatibel), **Vorlagen- und Rezeptspeicher im Kern**, MCP Apps später als gesandboxte Zusatzfläche.
Quellen: a2ui.org (Spezifikation v0.9.1, Basic-Katalog, Renderer), modelcontextprotocol.io/extensions/apps,
github.com/vercel-labs/json-render.

## Begriffe

* **Fläche** (A2UI *surface*): ein Bereich auf der Bühne mit Kennung, Katalog, Komponenten, Datenmodell, Stil.
  Mehrere Flächen als Reiter („Immobilien“, „Posteingang“, „Wetter“).
* **Vorlage**: gespeicherte Komponentenliste einer Fläche mit Datenschema, Datenquelle (Werkzeug + Argumente +
  Abbildung Ergebnis → Datenmodell), Aktionen und Standardstil. Vorlagen sind global.
* **Rezept**: was ein Aktionsknopf auslöst (Werkzeug mit Argumentabbildung oder Auftrag an den Agenten).
* **Stil**: Gestaltungswerte (Farben, Schrift, Rundung, Abstände, Dichte, Schema hell/dunkel, Bausteinvorlieben),
  vordefiniert oder abgeleitet; je Integration zugewiesen, je Vorlage überschreibbar.

## Format (A2UI v0.9.1-Teilmenge)

Kern → Oberfläche (über den bestehenden WebSocket, Ereignis `buehne` mit A2UI-Nachricht als `nachricht`):

```json
{"typ": "buehne", "nachricht": {"version": "v0.9.1", "createSurface": {"surfaceId": "immobilien", "catalogId": "jarvis:buehne/1", "theme": {"stil": "gg-immo"}, "titel": "Immobilien"}}}
{"typ": "buehne", "nachricht": {"version": "v0.9.1", "updateComponents": {"surfaceId": "immobilien", "components": [ … ]}}}
{"typ": "buehne", "nachricht": {"version": "v0.9.1", "updateDataModel": {"surfaceId": "immobilien", "path": "/", "value": { … }}}}
{"typ": "buehne", "nachricht": {"version": "v0.9.1", "deleteSurface": {"surfaceId": "immobilien"}}}
```

Oberfläche → Kern:

```json
{"typ": "buehne_aktion", "name": "makler_kontaktieren", "surfaceId": "immobilien", "sourceComponentId": "k_12", "timestamp": "…", "context": {"objekt_id": "hafenweg-3"}}
```

Komponenten: flache Liste, `id`, `component`, Eigenschaften, `children` (Liste von IDs) oder `child`; Listen über
`"children": {"path": "/immobilien", "componentId": "karte_vorlage"}`; dynamische Werte `{"path": "/…"}`;
im Template relative Pfade. Aktionen `"action": {"event": {"name": "…", "context": {"objekt_id": {"path": "id"}}}}`.
Eigene Erweiterungen bleiben in `theme` und in Katalog-Eigenschaften; `version`-Feld und Nachrichtennamen bleiben
A2UI-konform, damit Vorlagen mit anderen Renderern lesbar bleiben.

### Katalog `jarvis:buehne/1` (JSON-Schema in `kern/jarvis/buehne/katalog.json`, Register in der Oberfläche)

Layout: `Column`, `Row`, `Card`, `List` (vertical/horizontal, Template), `Tabs`, `Divider`, `Grid` (Spalten 1–4).
Anzeige: `Text` (variant h1–h5/body/caption, Markdown ohne HTML), `Image` (nur https/data:image; fit, variant),
`Icon` (Material-Symbol-Name), `Badge` (text, ton: neutral/ok/warn/fehler), `Kennzahl` (wert, label, einheit, trend),
`Fortschritt` (0–1), `Tabelle` (spalten[], zeilen {path}, Zeilenaktion), `Karte` (Adresse/Koordinaten → statische
Kartenkachel oder Link), `Diagramm` (typ: balken/linie/kreis, serien aus path).
Eingabe/Aktion: `Button` (variant, action), `TextField`, `CheckBox`, `ChoicePicker`, `DateTimeInput`, `Formular`
(JSON-Schema → Felder, Absenden = Aktion mit Formularwerten).
Client-Funktionen: `formatString`, `formatNumber`, `formatCurrency`, `formatDate`, `pluralize`, `openUrl` (nur
https, neues Fenster). Limits: 300 Komponenten je Fläche, Tiefe 12, Listen 500 Einträge, Nachricht 512 KB.

## Kern

### `buehne/` (neues Paket)

* `katalog.py`: lädt `katalog.json`, prüft Komponenten (Schema, Limits, verbotene Eigenschaften), erzeugt die
  Katalogbeschreibung für den Prompt (Komponenten, Eigenschaften, je ein Beispiel).
* `speicher.py`: Vorlagen, Rezepte, Stile als JSON unter `~/.jarvis/buehne/{vorlagen,rezepte,stile}/<id>.json`
  (global, nicht je Unterhaltung); `flaechen.json` = zuletzt offene Flächen mit Datenmodell (Wiederherstellung
  beim Start). Felder Vorlage: `id, name, zweck, version, protokollVersion, katalogId, komponenten[], datenschema,
  datenquelle {werkzeug, argumente, abbildung}, aktionen {name: rezeptId}, stil, signatur {werkzeug, schluessel[]},
  erstellt, geaendert, modell`. Rezept: `id, name, art: werkzeug|agent, werkzeug, argumentAbbildung, auftrag,
  bestaetigung, risiko`. Stil: `id, name, quelle {art: vordefiniert|url|datei|klassen, wert}, werte {schema,
  farben{primär, akzent, hintergrund, fläche, text, dezent, ok, warn, fehler}, schrift{familie, basisgroesse},
  rundung, abstand, dichte, schatten}, vorlieben {liste: kacheln|zeilen|tabelle, bildgroesse, kennzahlenOben}`.
* `erzeuger.py`: Modellaufrufe ohne Werkzeuge über `LLMFassade` mit Schema-gebundener Ausgabe (`response_format`
  JSON-Schema, bei Ollama `format`), A2UI-Systemprompt aus Katalog + Beispielen + Stilvorlieben; Reparaturschleife
  (Validierung → Fehlertext zurück, max. 2 Versuche); Fallback `standardvorlage(ergebnis)` ohne Modell (Tabelle
  für Listen von Objekten, Kennzahlen für flache Objekte, Markdown für Text).
  Funktionen: `vorlage_bauen(werkzeug, argumente, ergebnis, wunsch, stil)`, `vorlage_aendern(vorlage, wunsch)`,
  `abbildung_anwenden(vorlage, ergebnis) -> datenmodell` (deterministisch, JSON-Pointer-Abbildung mit Formatierern),
  `stil_ableiten(quelle)` (Seite laden mit bestehendem Web-Werkzeug/httpx, CSS-Variablen/Farben/Schriften
  extrahieren, Modell wählt Palette → Stilwerte; aus Datei: CSS/JSON/Tailwind-Konfiguration; aus Klassen: Text).
* `manager.py`: Flächen-Lebenszyklus (anlegen, befüllen, ändern, schließen), Zuordnung Integration → Stil
  (`stile.json`: `{integration_id: stil_id}`, Standard „javit-dunkel“), Signaturerkennung (gleiches Werkzeug +
  gleiche Ergebnis-Schlüssel → vorhandene Vorlage), Ereignisse `buehne` senden, Aktionen entgegennehmen und als
  Rezept ausführen (Werkzeug über Register mit `freigabe_noetig`, oder Auftrag als Agenten-Nachricht mit Kontext).

### Werkzeuge (Bereich technisch)

| Werkzeug | Risiko | Zweck |
|---|---|---|
| `buehne_zeigen(werkzeug, argumente?, titel?, wunsch?)` | aendern | Werkzeug ausführen und Ergebnis auf die Bühne bringen: vorhandene Vorlage (Signatur) befüllen, sonst Vorlage bauen |
| `buehne_vorlage_aendern(vorlage, wunsch)` | aendern | Vorlage nach Nutzerwunsch umbauen („zeig den Makler dazu“) |
| `buehne_daten(flaeche, daten)` | aendern | Datenmodell einer Fläche direkt setzen (z. B. Wetter aus einem Werkzeugergebnis) |
| `buehne_rezept_anlegen(vorlage, aktion, art, werkzeug?, argumentAbbildung?, auftrag?)` | kritisch | Aktionsknopf mit Ausführung verknüpfen (dauerhaft) |
| `buehne_stil_ableiten(name, quelle)` | aendern | Stil aus URL, Datei oder Klassen erzeugen |
| `buehne_stil_zuweisen(integration, stil)` | aendern | Stil einer Integration zuordnen |
| `buehne_schliessen(flaeche?)` | lesen | Fläche(n) schließen |

Systemprompt-Regeln: Listen, Datensätze, Mails, Wetter, Vergleiche gehören auf die Bühne (`buehne_zeigen`), der
Chat fasst kurz zusammen; vorhandene Vorlagen (Namen + Zweck im Prompt) wiederverwenden; Aktionen beim ersten Klick
als Rezept anlegen; Stilwünsche über `buehne_stil_*`.

### Aktionsschleife

Klick → `buehne_aktion` → Manager sucht Rezept (Vorlage.aktionen[name]): `werkzeug` → Argumente aus `context`
per Abbildung, Ausführung über das Register mit Freigaberegeln, Ergebnis → Datenmodell-Update oder neue Fläche;
`agent` → Auftrag mit Kontext als Nachricht an den Agenten („Aktion „makler_kontaktieren“ für Objekt … – Entwurf
schreiben“), sichtbar im Chat. Ohne Rezept → Agent bekommt die Aktion als Nachricht und legt (nach Rückfrage bei
`kritisch`) ein Rezept an.

### REST (Erweiterung `docs/VERTRAEGE.md`)

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/buehne` | offene Flächen mit Komponenten, Datenmodell, Stil |
| GET/DELETE | `/api/buehne/vorlagen[/{id}]` | Vorlagen lesen/löschen |
| PUT | `/api/buehne/vorlagen/{id}` | `{name?, stil?}` umbenennen/Stil setzen |
| GET/DELETE | `/api/buehne/rezepte[/{id}]` | Rezepte |
| GET/POST/PUT/DELETE | `/api/buehne/stile[/{id}]` | Stile (POST `{name, quelle:{art, wert}}` leitet ab; Datei als `inhalt_base64`) |
| PUT | `/api/buehne/zuordnung` | `{integration: stil}` |
| POST | `/api/buehne/aktion` | wie WebSocket `buehne_aktion` (für Tests) |

Einstellung `buehne: {aktiv: true, hoehe: 0.45}`.

## Oberfläche

* `src/buehne/`: `store.ts` (Flächen, Datenmodelle, Reiter, Höhe), `renderer.tsx` (Komponentenregister, JSON-Pointer-
  Binder, Listen-Template mit relativen Pfaden, Client-Funktionen, Aktionsdispatch mit Kontextauflösung,
  Streaming: Komponenten puffern bis `root` da ist), `komponenten/*.tsx` (Katalog im Javit-Design über
  CSS-Variablen des Stils), `stile.ts` (Stilwerte → CSS-Variablen am Flächen-Container, Schema hell/dunkel).
* Konsole: Bühne oben (ausblendbar, Höhe ziehbar, gemerkt), Chat unten; leer → Orb wie heute. Reiter je Fläche mit
  Schließen; Reiter „Stil“-Menü je Fläche (Stil wechseln = `PUT /api/buehne/vorlagen/{id}`).
* Einstellungen → neuer Reiter **Bühne**: Vorlagen (Liste, umbenennen, Stil, löschen, Rezepte ansehen), Stile
  (vordefinierte, eigene: aus URL ableiten, Datei hochladen, Klassen einfügen; Vorschau mit Beispielfläche), Zuordnung
  Integration → Stil.
* Sicherheit: Text nur als Text, Markdown ohne HTML, Bilder nur https/data:image, `openUrl` nur https und nach Klick,
  Kontextwerte nur aus Bindungen; keine Skripte, kein fremdes CSS (Stile sind reine Werte).

## Beispiele (Abnahme)

1. „Zeige mir aktuelle Immobilien“ → `buehne_zeigen("gg_immobilien_vercel_test__read_collection", …)` → Vorlage
   „Immobilienliste“ (Kacheln mit Bild, Adresse, Preis, Status; Knöpfe Exposé, Notiz, Makler), Stil „gg-immo“
   (aus `https://gg-immobilienhandel-test.vercel.app` abgeleitet). Zweiter Aufruf: nur Daten. Klick „Notiz“ →
   Rezept `gg…__add_note` mit Formular.
2. „Habe ich ungelesene Mails?“ → Vorlage „Posteingang“ (Tabelle: Absender, Betreff, Zeit; Knöpfe Öffnen,
   Zusammenfassen), Chat: „fünf neue, zwei wichtig“.
3. „Wetter Stuttgart“ → Vorlage „Wetterkarte“ (Symbol, Temperatur, Kennzahlen, Vorhersage-Liste) oder nur Chat.

## Tests

* Kern: Katalogvalidierung (gültig/ungültig/Limits), Abbildung (JSON-Pointer, Formatierer), Signaturerkennung,
  Erzeuger mit SkriptLLM (gültig, kaputt → Reparatur, Fallback), Stil ableiten mit MockTransport (CSS-Variablen,
  Tailwind-JSON), Manager (zeigen → Ereignisse, Aktion → Rezept → Werkzeug mit Freigabe), Werkzeuge, REST,
  Persistenz (global über Unterhaltungen).
* Oberfläche: Renderer-Snapshot je Komponente, Binder/Template, Aktionsdispatch mit Kontext, Streaming-Pufferung,
  Stil → CSS-Variablen, Bühnenreiter und Höhe, Einstellungen „Bühne“.
* E2E (Fake-LLM): Immobilienbeispiel von der Nachricht bis zur Fläche und zurück über eine Aktion.

## Doku

`docs/VERTRAEGE.md` (Ereignisse `buehne`/`buehne_aktion`, Endpunkte, Einstellung), READMEs (Abschnitt „Bühne“),
`docs/STAND.md`, `docs/PROTOKOLL.md`, `CLAUDE.md` (Paket `buehne/`, Regel: Bühne nie mit HTML füttern).
