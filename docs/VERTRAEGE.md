# Javit (Projekt „jarvis“) – Schnittstellen (bindend)

Server: `http://127.0.0.1:8765` (nur localhost). Oberfläche wird unter `/` ausgeliefert (aus `oberflaeche/dist`).

## REST (`/api`)

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/status` | `{version, name?, modell, stimme:{aktiv, weckwort, hoert, engine?: openwakeword|vosk}, integrationen: n, werkzeuge: n, zustand?, plattform?: mac|windows|linux}` – `name` = Name des Assistenten (Standard „Javit“) |
| GET | `/api/modelle[?anbieter=<id>&neu=1]` | `{aktuell, anbieter:[{id, name, schluessel, verfuegbar, lokal, eigen}], vorschlaege:[{id, name, lokal, verfuegbar, anbieter, kostenlos?: bool\|null, werkzeuge?: bool\|null, live}]}` – ohne `anbieter`: Ollama live + feste Vorschläge aller Anbieter; mit `anbieter`: nur dieser Anbieter, live vom Anbieter, wenn Schlüssel/Endpunkt es erlauben (`neu=1` umgeht den 10-Minuten-Cache); unbekannter Anbieter → 404 |
| PUT | `/api/modelle` | `{modell}` – Modell wechseln (z. B. `ollama/qwen2.5:7b`, `anthropic/claude-sonnet-5-5`, `openai/gpt-6.1-sol`) |
| GET | `/api/einstellungen` | Einstellungen (ohne Geheimnisse) |
| PUT | `/api/einstellungen` | Teilupdate |
| PUT | `/api/geheimnisse/{name}` | `{wert}` – API-Schlüssel speichern (Schlüsselbund) |
| GET | `/api/werkzeuge` | `[{name, beschreibung, quelle, integration?, risiko, bereich}]` |
| GET | `/api/integrationen` | installierte Integrationen `[{id, name, art, status: verbunden|fehler|aus, werkzeuge:n, fehler?}]` |
| GET | `/api/integrationen/katalog` | Katalog `[{id, name, beschreibung, kategorie, icon, art, benoetigt:[{name, titel, geheim}]}]` |
| POST | `/api/integrationen` | Integration hinzufügen (s. u.) → Integration |
| DELETE | `/api/integrationen/{id}` | entfernen |
| POST | `/api/integrationen/{id}/neu-verbinden` | neu starten |
| GET | `/api/integrationen/{id}` | Details ohne Geheimnisse: `{…wie Liste, katalog?: {id, name, hinweis, webseite, benoetigt, einrichtung:[{titel, text, link, datei, befehl, erfuellt: bool\|null}]}, werte?: {NAME: wert\|"gespeichert"}, konfig: {befehl, url, kopfzeilen, umgebung, auth, rest, geheimnisse, risiko_standard, werkzeug_risiko, aktiv, hinzugefuegt}, werkzeug_liste:[{name, beschreibung, risiko}], protokoll:[…], oauth?: {modus, angemeldet}, verzeichnis?: {quelle, kennung}, bereich: technisch\|fachlich}` – Werte mit `${…}` erscheinen als „gespeichert“ |
| PUT | `/api/integrationen/{id}` | Konfiguration ersetzen (Body wie POST; Katalog: `{werte, name?}`), Geheimnisse mit leerem Wert oder „gespeichert“ bleiben; stoppt, speichert, startet neu → Details; 400 bei ungültigen Werten |
| PUT | `/api/integrationen/{id}/bereich` | `{bereich: technisch\|fachlich}` – Bereich umstellen (ohne Neustart, markiert registrierte Werkzeuge) → Details; 400 ungültig, 404 unbekannt |
| POST | `/api/integrationen/{id}/abmelden` | OAuth: Tokens und Client-Registrierung aus dem Schlüsselbund löschen, Integration stoppen (Status `aus`) |
| POST | `/api/integrationen/{id}/anmelden` | OAuth: neu verbinden und damit die Anmeldung im Browser auslösen |
| GET | `/oauth/rueckruf?code=&state=[&error=]` | Rückruf des Autorisierungsservers nach der Browser-Anmeldung (HTML-Seite; kein `/api`-Pfad, ohne Origin-Prüfung, wirkt nur auf einen wartenden Flow mit passendem `state`) |
| GET | `/api/integrationen/{id}/protokoll?zeilen=50` | `{zeilen:[…]}` letzte Zeilen des Server-Protokolls (`mcp-<id>.log`) |
| GET | `/api/integrationen/katalog/{id}` | Katalogeintrag + `einrichtung[].erfuellt` (Datei vorhanden) + `installiert` |
| POST | `/api/integrationen/katalog/{id}/einrichtung/{n}/datei` | `{inhalt_base64}` – schreibt an das `datei`-Ziel des Schritts n (0-basiert; max. 1 MB; `.json` wird geprüft) → `{pfad, erfuellt, einrichtung}` |
| POST | `/api/integrationen/katalog/{id}/einrichtung/{n}/ausfuehren` | startet den `befehl` des Schritts im Hintergrund (nur Befehle aus dem Katalog; Ausgabe in `logs/einrichtung-<id>.log`, 300 s) → `{status: laeuft}` |
| GET | `/api/integrationen/katalog/{id}/einrichtung/{n}/stand` | `{status: nie\|laeuft\|fertig\|fehler, rueckgabe, ausgabe:[…], sekunden}` |
| GET | `/api/verzeichnisse` | Verzeichnisse für die Suche `[{id, name, url, eigen}]` – eingebaut `mcp-registry`, `smithery`, dazu `Einstellungen.verzeichnisse_eigene` |
| GET | `/api/verzeichnisse/suche?q=&quelle=&limit=` | `{treffer:[{quelle, kennung, name, beschreibung, webseite, repository, herausgeber, verifiziert, nutzungen, art: mcp_http\|mcp_stdio\|null, laufzeit: fern\|npx\|uvx\|null, oauth, felder:[{name, titel, geheim, optional, beschreibung, standard}], warnungen:[…], installierbar, vollstaendig, aktualisiert}], fehler:{quelle: text}}` – parallel über alle Quellen (10 s je Quelle, 10 min Cache), sortiert verifiziert → installierbar → Nutzungen; `q` min. 2 Zeichen (sonst 400) |
| GET | `/api/verzeichnisse/{quelle}/{kennung}` | vollständiger Treffer (Felder, Warnungen); 404 wenn unbekannt |
| POST | `/api/verzeichnisse/installieren` | `{quelle, kennung, werte?, name?}` – baut aus dem Treffer eine Integration (`mcp_url` mit OAuth/Kopfzeilen oder `mcp_befehl` per npx/uvx) und legt sie wie `POST /api/integrationen` an; 400 + `fehlend` bei fehlenden Pflichtfeldern, 400 bei nicht installierbaren Treffern |
| GET | `/api/verlauf?limit=` | Nachrichten der **aktuellen** Unterhaltung `[{id, zeit, rolle: nutzer\|jarvis, inhalt}]` |
| DELETE | `/api/verlauf` | leert nur die aktuelle Unterhaltung |
| POST | `/api/stimme/probe` | `{text?}` – spricht einen Probesatz über den aktuellen Weg (Lautsprecher des Kerns oder Browser-Sitzung) → `{ok, art, modell, stimme, ziel: lautsprecher\|browser}`; 400 bei `tts: aus`, fehlendem OpenRouter-Schlüssel oder fehlendem Sprachmodul |
| GET | `/api/stimme/modelle` | OpenRouter-Sprachmodelle `{tts: [{id, name, stimmen[], preis_je_1m_zeichen, standard_stimme}], stt: [{id, name}], fehler}` (10 min Cache; ohne Netz `tts: []` + `fehler`) |
| GET | `/api/unterhaltungen` | alle Unterhaltungen, neueste zuerst `[{id, titel, titel_fest, erstellt, aktualisiert, zusammenfassung, nachbereitet, nachrichten, aktuell}]` |
| POST | `/api/unterhaltungen` | `{titel?}` – neue Unterhaltung, wird aktuell (die verlassene wird im Hintergrund nachbereitet) → Unterhaltung; 400 bei ungültigem Titel (1–80 Zeichen) |
| GET | `/api/unterhaltungen/{id}` | eine Unterhaltung; 404 |
| PUT | `/api/unterhaltungen/{id}` | `{titel}` – umbenennen (setzt `titel_fest`, kein automatischer Titel mehr); 400/404 |
| DELETE | `/api/unterhaltungen/{id}` | löschen samt Verlauf (Erinnerungen bleiben) → `{geloescht, aktuell}`; war sie aktuell, wird die neueste verbliebene aktuell, sonst eine neue leere |
| POST | `/api/unterhaltungen/{id}/aktivieren` | aktuell machen → Unterhaltung; 404 |
| GET | `/api/unterhaltungen/{id}/verlauf?limit=` | Nachrichten dieser Unterhaltung; 404 |
| GET | `/api/gedaechtnis` | Erinnerungen `[{id, zeit, text, quelle: nutzer\|auto, unterhaltung_id, aktualisiert, einbettung_modell}]` |
| DELETE | `/api/gedaechtnis?id=` | alle bzw. eine Erinnerung löschen → `{geloescht: n}` |
| GET | `/api/buehne` | Zustand der Bühne `{flaechen: [Flaeche…], stile: [Stil…], zuordnung: {integration: stilId}}` – die Oberfläche lädt ihn beim Verbinden (offene Flächen überleben Neustarts) |
| GET | `/api/buehne/vorlagen` | `[Vorlage…]` ohne `komponenten`, mit `versionen: n` |
| GET | `/api/buehne/vorlagen/{id}` | Vorlage vollständig; 404 |
| PUT | `/api/buehne/vorlagen/{id}` | `{name?, stil?}` (`stil: null` = Stil der Integration/Standard) → Vorlage; eine offene Fläche wechselt sofort den Stil (`stil` + `createSurface`) |
| DELETE | `/api/buehne/vorlagen/{id}` | schließt die Fläche und löscht die Vorlage → `{geloescht: bool}` |
| POST | `/api/buehne/vorlagen/{id}/zurueck` | neueste Version verwerfen (Rückgängig; mind. eine bleibt) → Vorlage; 404 |
| GET | `/api/buehne/rezepte` | `[Rezept…]` |
| DELETE | `/api/buehne/rezepte/{id}` | löscht das Rezept und die Zuordnung in den Vorlagen → `{geloescht: bool}` |
| GET | `/api/buehne/stile` | `[Stil…]` – vordefinierte (`eigen: false`) + eigene |
| POST | `/api/buehne/stile` | `{name, quelle: {art: url\|klassen\|datei\|werte, wert?, inhalt_base64?, werte?}, basis?, vorlieben?}` – `url`/`klassen`/`datei`: Stil über das Modell ableiten (Kandidaten aus CSS: Variablen, Farben, Schriften, Rundungen; Fallback ohne Modell); `werte`: Kopie von `basis` (Standard `javit-dunkel`) mit den Werten → Stil; 400 bei http-URL/Fehler |
| PUT | `/api/buehne/stile/{id}` | `{name?, werte?: {farben?, schema?, rundung?, abstand?, dichte?, schatten?, schrift?}, vorlieben?}` → Stil; ein vordefinierter wird als eigene Kopie gespeichert (Kennung aus `name`, sonst `<id>-eigen`) |
| DELETE | `/api/buehne/stile/{id}` | `{geloescht: bool}` (vordefinierte nie) |
| PUT | `/api/buehne/zuordnung` | `{integration: stilId}` ersetzt die ganze Zuordnung → Zuordnung; 400 bei unbekanntem Stil |
| POST | `/api/buehne/aktion` | wie `buehne_aktion` (WebSocket) → `{ok, rezept, ergebnis?\|antwort?}`; 400 bei unbekannter Fläche |
| DELETE | `/api/buehne/flaechen/{surfaceId}` | Fläche schließen (`deleteSurface`) → `{geschlossen: [surfaceId…]}` |

Integration hinzufügen – eine der Formen:
```json
{"katalog": "spotify", "werte": {"SPOTIFY_CLIENT_ID": "…", "SPOTIFY_CLIENT_SECRET": "…"}}
{"name": "Mein Tool", "mcp_befehl": "npx -y @modelcontextprotocol/server-everything", "umgebung": {}}
{"name": "Home Assistant", "mcp_url": "http://homeassistant.local:8123/mcp", "kopfzeilen": {"Authorization": "Bearer …"}}
{"name": "Notion (Smithery)", "mcp_url": "https://notion.run.tools?NOTION_API_KEY=${NOTION_API_KEY}", "werte": {"NOTION_API_KEY": "…"}, "geheime": ["NOTION_API_KEY"], "verzeichnis": {"quelle": "smithery", "kennung": "node2flow/notion"}}
{"name": "Petstore", "openapi_url": "https://petstore3.swagger.io/api/v3/openapi.json", "auth": {"art": "bearer", "wert": "…"}}
{"name": "Wetter", "rest": [{"name": "wetter_abrufen", "methode": "GET", "url": "https://api.open-meteo.com/v1/forecast", "parameter": {"latitude": "zahl", "longitude": "zahl", "current_weather": "text"}, "beschreibung": "…"}]}
```

Für `mcp_url` und `mcp_befehl` optional: `werte` (Werte für `${NAME}`-Platzhalter in URL/Kopfzeilen; geheime
Namen – per `ist_geheimer_name` oder in `geheime` aufgeführt – landen als `JARVIS_<KENNUNG>_<NAME>` im
Schlüsselbund, andere werden direkt eingesetzt), `geheime` (zusätzlich geheime Namen von Werten, Kopfzeilen oder
Umgebungsvariablen) und `verzeichnis: {quelle, kennung}` (Herkunft, erscheint in den Details).
`Einstellungen.verzeichnisse_eigene: [{id, name, url}]` – eigene Registries mit der API des offiziellen
MCP-Registry (`<url>/v0/servers`); Kennung `a-z0-9_-`, https-URL, `mcp-registry`/`smithery` sind reserviert.

## WebSocket `/ws`

Client → Server (JSON):
| typ | Felder |
|---|---|
| `nachricht` | `text`, `sprechen?: bool` (Antwort vorlesen) |
| `freigabe` | `id`, `erlaubt: bool` |
| `abbrechen` | – |
| `stimme` | `aktiv: bool` (Mikrofon/Weckwort an/aus) |
| `zuhoeren` | – (Push-to-talk: einmal zuhören ohne Weckwort) |
| `audio_start` | `rate` (Hz) – Audio im Browser: diese Verbindung liefert danach **Binärframes** (int16 mono, `rate`) als Mikrofon und erhält die Sprachausgabe als Binärframes; der Kern schaltet das Sprachmodul auf diese Quelle um (genau eine Sitzung je Kern, eine neue ersetzt die alte) |
| `buehne_aktion` | `name`, `surfaceId`, `sourceComponentId?`, `timestamp?`, `context` (Objekt aus der Vorlage, Bindungen aufgelöst) – Knopf/Formular auf der Bühne. Rezept der Vorlage → Werkzeug (Argumente aus `context` per `argumentAbbildung`, danach Datenquelle neu laden) oder Auftrag an den Assistenten; ohne Rezept geht eine Nachricht an den Assistenten, der danach ein Rezept anlegt |
| `buehne_daten` | `surfaceId`, `path` (JSON-Pointer), `value` – Eingabefelder (zweiseitige Bindung, bei Blur/Enter); kein Ereignis zurück; Eingaben bleiben beim Neuladen der Daten erhalten |
| `audio_stop` | – beendet die Audio-Sitzung (auch beim Trennen der Verbindung); das Sprachmodul bleibt danach aus, bis `stimme {aktiv: true}` es mit dem Mikrofon des Kerns neu startet |

Server → Client:
| typ | Felder |
|---|---|
| `zustand` | `zustand: bereit|hoert|denkt|spricht|arbeitet` (steuert den Orb) |
| `pegel` | `wert: 0..1` (Audiopegel, ~15/s während hoert/spricht) |
| `transkript` | `text`, `final: bool` (was der Nutzer gesagt hat) |
| `antwort_start` | `id` |
| `antwort_text` | `id`, `delta` (Streaming) |
| `antwort_ende` | `id`, `text` |
| `werkzeug_start` | `id`, `name`, `argumente`, `integration?` |
| `werkzeug_ende` | `id`, `ok: bool`, `ergebnis` (gekürzt, max 2000 Zeichen) |
| `freigabe_noetig` | `id`, `werkzeug`, `argumente`, `grund`, `risiko` (`aendern`\|`kritisch`), `bereich` (`technisch`\|`fachlich`), `timeout?` (Sekunden bis „abgelehnt“) |
| `integration_geaendert` | `integration` |
| `oauth_anmeldung` | `integration`, `url` – Anmeldeseite wurde im Browser geöffnet; die Oberfläche zeigt den Link, falls kein Fenster aufging |
| `fehler` | `text` |
| `sprachausgabe` | `zustand: start` (`rate`, danach PCM-**Binärframes** int16 mono an die Verbindung mit Audio-Sitzung, ≤ 9600 Bytes je Frame) \| `ende` \| `gestoppt` (`grund?: stoppwort\|ersetzt`; Wiedergabe sofort verwerfen) – kommt nur bei einer Audio-Sitzung im Browser; am Lautsprecher des Kerns gibt es nur `zustand spricht` und `pegel` |
| `unterhaltung` | `id`, `titel`, `grund` (`neu` \| `gewechselt` \| `geloescht` – die aktuelle Unterhaltung ist eine andere, die Oberfläche leert die Konsole und lädt `/api/verlauf`; `titel` – nur der Titel hat sich geändert, z. B. automatisch nach der ersten Antwort) |
| `buehne` | `nachricht` – eine A2UI-Nachricht (`version: "v0.9.1"`) mit genau einem Schlüssel: `stil` (Stil-Objekt, kommt vor `createSurface`), `createSurface {surfaceId, catalogId: "jarvis:buehne/1", theme: {stil}, titel, vorlage?}`, `updateComponents {surfaceId, components[]}`, `updateDataModel {surfaceId, path, value}` (`path: "/"` = ganzes Modell), `deleteSurface {surfaceId}`. Antworten auf Rezepte erscheinen als `antwort_start`/`antwort_ende` mit `id` `buehne_…` |

## Bühne (`jarvis/buehne/`, Katalog `jarvis:buehne/1`)

Die Bühne ist eine generative Oberfläche über dem Chat im A2UI-Format (v0.9.1, flache Komponentenliste mit `root`,
Bindungen `{"path": "/…"}`, Listen `children: {path, componentId}`, Aktionen `action.event {name, context}`).
Erlaubt sind nur Komponenten und Eigenschaften aus `buehne/katalog.json` (`komponenten_pruefen` weist alles
andere ab: unbekannte Komponenten/Eigenschaften, fehlende `root`, Zyklen, Tiefe > 12, > 300 Komponenten, Bilder ohne
https/data-URL); die Oberfläche rendert den Katalog mit eigenen React-Komponenten – nie HTML aus dem Modell.

* **Vorlage** (`~/.jarvis/buehne/vorlagen/<id>.json`): `{id, name, zweck, version, protokollVersion, katalogId,
  komponenten, datenschema, datenquelle: {werkzeug, argumente, abbildung}, aktionen: {aktion: rezeptId}, stil,
  signatur: {werkzeug, schluessel[], eintrag[]}, erstellt, geaendert, modell, versionen}`; bis zu 10 Versionen,
  `zurueck` verwirft die neueste. Vorlagen gelten global (nicht je Unterhaltung) und werden über die Signatur
  (Werkzeug + Schlüssel des Ergebnisses) wiedergefunden – aber nur, wenn der Titel der Anfrage zur Vorlage passt
  (gemeinsames tragendes Wort, z. B. „Immobilien“ ↔ „Immobilienliste“); ein anderer Titel („Makler“) ergibt eine
  eigene Vorlage mit eigener Fläche. `buehne_zeigen` kann die Vorlage auch explizit angeben (`vorlage`). Ergebnisse
  für die Bühne werden nicht auf Modellmaß gekürzt (`Agent.werkzeug_ausfuehren_extern`, bis 4 Mio. Zeichen).
* **Abbildung** `{"/ziel": "/quelle|formatierer"}` – Ziel-JSON-Pointer im Datenmodell ← Quell-Pointer im
  Werkzeugergebnis; Formatierer `datum`, `waehrung:EUR`, `zahl:n`. Ergebnisse ohne JSON: Markdown-Tabellen und
  listenartiger Text (Aufzählung/Blöcke mit `Schlüssel: Wert`-Zeilen, mehrere Paare je Zeile durch `|`) →
  `eintraege`, sonst `text`. Fehlt `anzahl`, ergänzt der Manager sie aus `eintraege`/der einzigen Liste.
* **Rezept** (`rezepte/<id>.json`): `{id, name, art: werkzeug|agent, vorlage, aktion, werkzeug?, argumentAbbildung?:
  {"arg": "context.feld"}, auftrag? (mit `{feld}`-Platzhaltern), risiko, bestaetigung?}`.
* **Stil** (`stile/*.json` im Paket = vordefiniert, `~/.jarvis/buehne/stile/` = eigene): `{id, name, beschreibung,
  quelle: {art: vordefiniert|url|datei|klassen|werte, wert?}, werte: {schema: hell|dunkel, farben: {primaer, akzent,
  hintergrund, flaeche, text, dezent, ok, warn, fehler}, schrift: {familie, basisgroesse}, rundung, abstand, dichte:
  dicht|normal|luftig, schatten: keiner|weich|stark}, vorlieben: {liste: kacheln|zeilen|tabelle, bildgroesse,
  kennzahlenOben}, eigen}`. Stil einer Fläche: Vorlage.stil → Zuordnung der Integration (`zuordnung.json`) →
  `javit-dunkel`.
* **Werkzeuge des Modells**: `buehne_zeigen` (lesen; führt das Datenwerkzeug über den Agenten aus – Freigaben und
  Aktivitäten wie sonst), `buehne_vorlage_aendern`, `buehne_vorlage_zurueck`, `buehne_daten`, `buehne_neu_laden`,
  `buehne_rezept_anlegen` (kritisch), `buehne_stil_ableiten`, `buehne_stil_aendern`, `buehne_stil_zuweisen`,
  `buehne_schliessen`. Einstellung `buehne: {aktiv, hoehe}`.

## Integrationskatalog (`integrationen/katalog/*.yaml`)

```yaml
id: spotify
name: Spotify
beschreibung: Musik abspielen, suchen, Playlists steuern
kategorie: Musik
icon: music
art: mcp_stdio            # mcp_stdio | mcp_http | openapi | rest | eingebaut
befehl: npx -y <paket>    # bei mcp_stdio
url: null                 # bei mcp_http / openapi
benoetigt:
  - {name: SPOTIFY_CLIENT_ID, titel: Client ID, geheim: false}
  - {name: SPOTIFY_CLIENT_SECRET, titel: Client Secret, geheim: true}
  # optional je Feld: typ: text | geheim | ordner | datei | url (ordner/datei: Tilde erlaubt, keine
  # Platzhalter, Existenz wird beim Anlegen/Ändern geprüft), standard, beschreibung, optional
hinweis: "Schlüssel unter developer.spotify.com anlegen …"
webseite: https://…           # optional, Anleitung des Servers
einrichtung:                   # optional: Schritte vor der ersten Verbindung (Oberfläche: Checkliste)
  - {titel: OAuth-Client anlegen, text: "…", link: https://console…}
  - {titel: OAuth-Datei ablegen, datei: ~/.gmail-mcp/gcp-oauth.keys.json}   # prüfbar + Upload-Ziel
  - {titel: Anmelden, befehl: "npx -y paket auth"}                            # aus der Oberfläche ausführbar
risiko_standard: aendern
bereich: fachlich              # technisch (Dateien, Entwicklung, Web, Umgebung – ohne Rückfrage) | fachlich (Standard)
```

**Freigaben nach Bereich** (`werkzeuge.freigabe_noetig`): Jedes Werkzeug hat `risiko` (lesen|aendern|kritisch) und
`bereich` (technisch|fachlich). Technische Werkzeuge laufen ohne Rückfrage – Ausnahme `schutz` (Dateien löschen,
Zugangsdaten lesen) und die Einstellung `freigabe_technisch: true` (dann kritische technische Aufrufe). Fachliche
Werkzeuge werden ab `aendern` vorgelegt (`freigabe_fachlich: aendern|kritisch|nie`). Eingebaute Werkzeuge sind
technisch außer `termin_anlegen`, `erinnerung_anlegen`, `notiz_anlegen`; Integrationen erben den Katalogwert
(`bereich`), eigene Integrationen sind fachlich, umstellbar per `bereich` im POST/PUT oder `PUT …/bereich`.

**Unterhaltungen und Gedächtnis**: `GET /api/status` enthält `unterhaltung: {id, titel}`. Der Agent nimmt nur die aktuelle
Unterhaltung als Kontext (`verlauf_kontext`) und bekommt die Zusammenfassungen der letzten fünf Unterhaltungen in den
Systemprompt; das Werkzeug `unterhaltung_neu(titel?)` (aendern, technisch) beginnt eine neue. Einstellung
`gedaechtnis_automatisch: bool` (Standard true): nach der ersten Antwort ein automatischer Titel, beim Verlassen einer
Unterhaltung Zusammenfassung plus dauerhafte Fakten als Erinnerungen mit `quelle: auto` (`gedaechtnis_pflege.Nachbereiter`;
ähnliche Erinnerungen werden aktualisiert statt dupliziert; Fakten mit Zugangsdaten werden verworfen). Einbettungen:
`einbettungs_modell` (Ollama/Cloud), sonst lokal über fastembed (Extra `kern[gedaechtnis]`), sonst Volltext (FTS5) und
Stichwortmaß; jede Erinnerung speichert ihr Einbettungsmodell, verglichen wird nur bei gleichem Modell.

`GET /api/integrationen/katalog` liefert je Eintrag zusätzlich `webseite`, `einrichtung`, `oauth` (Modus oder null),
`vertrauen` (`offiziell` | `community`), `quelle`, `gruppe` und je Feld `typ`, `standard`, `beschreibung`.

OAuth (`mcp_http`): `oauth: {modus: entdeckung}` = MCP-Standard (401 mit `resource_metadata`, dynamische
Registrierung, PKCE S256, Rückruf `http://127.0.0.1:<port>/oauth/rueckruf`); `oauth: {modus: manuell,
autorisierung_url, token_url, scopes: [...], client_id: "${FELD}", client_secret: "${FELD}", extra: {...}}` für
Anbieter ohne dynamische Registrierung (Google Workspace). Eigene `mcp_url`-Integrationen ohne
`Authorization`-Kopfzeile bekommen automatisch `{modus: entdeckung}` (`"oauth": false` im POST schaltet es ab).
Tokens und Client-Registrierung liegen im Schlüsselbund (`JARVIS_OAUTH_<ID>_TOKENS`/`_CLIENT`), nie in
`integrationen.json`. `vertrauen: offiziell` verlangt `quelle` (Doku des Anbieters); `gruppe` fasst Einträge mit
gemeinsamen Feldern zusammen (Oberfläche zeigt eine Kachel, z. B. `google-workspace`).

Installierte Integrationen: `~/.jarvis/integrationen.json`. Einstellungen: `~/.jarvis/einstellungen.json`.
Daten (Verlauf, Gedächtnis): `~/.jarvis/jarvis.db`.

Anbieter (`jarvis/anbieter.py`): eingebaut `ollama`, `anthropic`, `openai`, `gemini`, `openrouter`,
`deepseek`, `moonshot` (Kimi), `zai` (GLM), `opencode` (nur bezahlte Modelle, OpenAI-kompatibel),
`groq`, `mistral`, `xai`. Modell-IDs sind `<anbieter>/<modell>` in LiteLLM-Schreibweise; `opencode/…`
und eigene Anbieter werden intern nach `openai/<modell>` mit eigener Basis-URL und eigenem Schlüssel
übersetzt. Eigene OpenAI-kompatible Anbieter: `einstellungen.anbieter_eigene` =
`[{id, name?, api_base, schluessel?, modelle?: [..]}]` (`id` `[a-z0-9][a-z0-9_-]{0,30}`, keine eingebaute
Kennung; `api_base` mit http(s); `schluessel` Großbuchstaben/Ziffern/_; Liste wird komplett ersetzt,
ungültig → 422). `PUT /api/geheimnisse/{name}` leert den Cache der Live-Modelllisten.

Einstellungen (Auszug): `name` (Standard „Javit“; leer → Standard) – Name des Assistenten für
Persona (Platzhalter `{name}` in `persona`), Oberfläche, Ansagen und Meldungen. Fehlt `name` in einer
älteren Datei, gilt „Javit“; die frühere Standard-Persona („Du bist Jarvis …“) wird durch die neue
ersetzt, eine eigene Persona bleibt unverändert; ein altes Standard-Weckwort `hey_jarvis` wird dann zu
`javit` (nur bei `weckwort_engine` „auto“ und ohne eigenes `weckwort_modell_pfad`).

Weckwort (`einstellungen.stimme`): `weckwort` (Text, mehrere durch Komma, Standard `javit`),
`weckwort_engine` = `auto` (Standard: `hey_jarvis`/„hey jarvis“, andere fertige openWakeWord-Wörter
oder `weckwort_modell_pfad` → `openwakeword`, sonst `vosk`) | `openwakeword` | `vosk`,
`weckwort_varianten` (Liste oder kommagetrennter Text; Schreibvarianten für Vosk, leer = Standards),
`weckwort_modell_pfad` (eigenes openWakeWord-`.onnx`), `vosk_modell` (Name oder Ordner, Standard
`vosk-model-small-de-0.15`), `schwelle` (0..1, beide Engines). Eine Änderung dieser Felder per
`PUT /api/einstellungen` startet ein laufendes Sprachmodul neu.

Stimm-Einstellungen (`einstellungen.stimme`, Auszug): `tts` = `auto` (Standard: `openrouter`, sobald
`OPENROUTER_API_KEY` hinterlegt ist; sonst Mac `say`, Windows `sapi`, Linux `piper` mit Fallback `espeak`)
| `openrouter` | `say` | `sapi` | `piper` | `espeak` | `cloud` | `aus`. `say` wird außerhalb des Macs wie
`auto` behandelt. `tts_openrouter_modell` (Standard `elevenlabs/eleven-flash-v2.5`), `tts_stimme` (leer =
Standardstimme je Modell: ElevenLabs `daniel`, Microsoft MAI `de-DE-Klaus:…`, Google `Kore`), `stt` = `auto`
(`openrouter` mit Schlüssel, sonst `lokal`) | `lokal` | `openrouter` | `cloud`, `stt_openrouter_modell`
(Standard `openai/whisper-large-v3`), `stoppwort` (Komma-getrennt, Standard `stopp`, leer = aus), `aec` = `auto` |
`an` | `aus` (macOS: Mikrofon über den Helfer `~/.jarvis/bin/javit-mikrofon` mit Apples Echounterdrückung; Quelle
`stimme/mac_mikrofon.swift`, gebaut vom Installer bzw. beim ersten Start mit `xcrun swiftc`; ohne Helfer das normale
Mikrofon). Stoppwort-Regel: mit Echounterdrückung (Helfer, Browser) zählt ein stabiler exakter Treffer irgendwo im
Ergebnis; ohne sie nur eine alleinstehende, stabile Äußerung.

**Streaming-Sprachausgabe** (`stimme/sprecher.py`): Bei `sprechen: true` speist der Agent jedes Text-Delta
in eine Sprechsitzung; fertige Sätze gehen sofort an die Synthese (bis zu zwei voraus), die Wiedergabe läuft als
Warteschlange – `openrouter` als PCM-Strom (24 kHz) über `sounddevice` bzw. als Binärframes an den Browser, die
anderen Arten dateiweise je Satz. Der Zustand `spricht` kommt mit dem ersten Ton. Das **Stoppwort** wird während
`spricht` über einen zweiten Vosk-Abgleich erkannt (Schwelle `schwelle + 0,2`), bricht Ausgabe und Dialog ab
(kein Folgefrage-Fenster) und sendet `sprachausgabe gestoppt`; das Weckwort unterbricht weiterhin
(`unterbrechen`).
