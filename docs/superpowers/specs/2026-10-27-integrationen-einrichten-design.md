# Integrationen sichtbar, bearbeitbar, geführt – Design (27.10.2026)

## Ziel

Installierte Integrationen zeigen ihre Konfiguration, lassen sich bearbeiten und erklären bei
Fehlern, was zu tun ist. Dienste mit Einrichtungsschritten (Gmail, Google Kalender) bekommen eine
Checkliste mit Prüfungen, Datei-Upload und ausführbaren Schritten. Ein Plus-Knopf macht das
Hinzufügen beliebiger Server so leicht wie Connectoren bei Claude, inklusive Einfügen einer
Claude-JSON-Konfiguration. Der Agent kennt Status und Einrichtungsschritte und führt den Nutzer.

**Phase 1 (dieses Dokument):** Detailseite, Bearbeiten, Feldtypen mit Prüfung, Einrichtungsschritte,
Plus-Dialog mit JSON-Import, Agent-Führung.
**Phase 2 (eigene Spezifikation):** OAuth für entfernte MCP-Server, Connector-Katalog.

## Katalogformat (Erweiterung, rückwärtskompatibel)

```yaml
benoetigt:
  - {name: VERZEICHNIS, titel: Freigegebener Ordner, typ: ordner, standard: "~/Documents"}
  # typ: text (Standard) | geheim (= geheim: true) | ordner | datei | url
einrichtung:                       # optional, in Reihenfolge
  - titel: OAuth-Client anlegen
    text: In der Google Cloud Console …
    link: https://console.cloud.google.com/apis/credentials
  - titel: OAuth-Datei ablegen
    datei: ~/.gmail-mcp/gcp-oauth.keys.json     # Prüfung „Datei vorhanden“ + Upload-Ziel
  - titel: Bei Google anmelden
    befehl: npx -y @gongrzhe/server-gmail-autoauth-mcp auth   # ausführbar aus der Oberfläche
    text: Der Browser öffnet sich zur Anmeldung.
```

`als_info()` liefert zusätzlich `typ` je Feld, `standard`, `einrichtung`, `webseite`.

## Kern

### Prüfung von Werten (`manager.werte_pruefen`)

Beim Hinzufügen und Bearbeiten: `ordner`/`datei` → Tilde auflösen, `*`/`?` ablehnen, Existenz prüfen
(„Ordner nicht gefunden: /Users/x/Dokumente“ bzw. „Datei nicht gefunden: …“); `url` → http(s).
Gespeichert wird der eingegebene Wert (mit `~`), nicht der aufgelöste.

### Details (`manager.details(id)`) → `GET /api/integrationen/{id}`

```json
{"id","name","art","status","werkzeuge": 14, "fehler"?,
 "katalog"?: {"id","name","hinweis","webseite","einrichtung":[{"titel","text","link","datei","befehl","erfuellt": true|false|null}]},
 "konfig": {"befehl": ["npx", …], "url", "kopfzeilen": {"Authorization": "gespeichert"}, "umgebung": {"VERZEICHNIS": "~/Documents"},
            "geheimnisse": ["NAME"], "risiko_standard", "werkzeug_risiko"},
 "werte": {"VERZEICHNIS": "~/Documents"},            // nur nicht-geheime Katalogfelder
 "werkzeug_liste": [{"name","beschreibung","risiko"}],
 "protokoll": ["letzte Zeilen …"]}
```

Geheime Werte erscheinen nie; Kopfzeilen/Umgebung mit `${…}` werden als „gespeichert“ ausgegeben.

### Bearbeiten (`manager.aendern(id, anfrage)`) → `PUT /api/integrationen/{id}`

Body wie beim Anlegen (`{werte}` für Katalogeinträge; `{name, mcp_befehl, umgebung}` /
`{name, mcp_url, kopfzeilen}` / `{name, openapi_url, auth}` / `{name, rest}` für eigene). Vorhandene
Geheimnisse bleiben, wenn der Wert leer bleibt oder „gespeichert“ lautet. Ablauf: stoppen, Konfiguration
ersetzen (gleiche `id`, `hinzugefuegt` und `werkzeug_risiko` bleiben), speichern, starten → Details.

### Einrichtung

* `GET /api/integrationen/katalog/{id}` → `als_info()` + `einrichtung[].erfuellt` (Datei-Schritte: existiert).
* `POST /api/integrationen/katalog/{id}/einrichtung/{n}/datei` `{inhalt_base64, dateiname?}` →
  schreibt in das `datei`-Ziel des Schritts (nur Schritte mit `datei`; max. 1 MB; Ordner wird angelegt;
  JSON-Ziele werden als JSON geprüft) → `{pfad, erfuellt: true}`.
* `POST /api/integrationen/katalog/{id}/einrichtung/{n}/ausfuehren` → startet den `befehl` des Schritts
  im Hintergrund (Ausgabe nach `~/.jarvis/logs/einrichtung-<id>.log`, Zeitlimit 300 s, PATH wie MCP-Server)
  → `{status: "laeuft"}`; `GET …/einrichtung/{n}/stand` → `{status: laeuft|fertig|fehler|nie, ausgabe: [..]}`.
  Nur Befehle aus dem Katalog werden ausgeführt (nie aus dem Request).
* `GET /api/integrationen/{id}/protokoll?zeilen=50` → `{zeilen: [...]}`.

### Fehler verständlich

Stirbt ein stdio-Server beim Start, hängt der MCP-Hub die letzten Fehlerzeilen des Protokolls an
`fehler` an (max. 3 Zeilen, je 200 Zeichen), statt nur auf die Logdatei zu verweisen.

### Agent

* Systemprompt: „Verbundene Integrationen“ wird zu „Integrationen“ und nennt auch fehlerhafte mit
  Grund (`Gmail (gmail): FEHLER – OAuth keys file not found …`) sowie die Regel: Bei Fehlern oder
  fehlender Einrichtung dem Nutzer anbieten, ihn Schritt für Schritt zu führen (`integration_einrichtung`).
* Neue Werkzeuge: `integration_details(id)` (lesen) – Status, Konfiguration ohne Geheimnisse,
  Einrichtungsschritte mit Status, letzte Protokollzeilen; `integration_einrichtung(id)` (lesen) –
  nur die Schritte mit Status und was der Nutzer als Nächstes tun muss; `integration_konfigurieren(id,
  werte)` (aendern) – ruft `aendern`; `integration_schritt_ausfuehren(id, n)` (kritisch, Freigabe).

## Oberfläche

* **Installiert** → Klick auf Eintrag öffnet die **Detailseite**: Kopf mit Status; bei Fehler roter Kasten
  mit Text, Protokollzeilen und Knopf „Javit um Hilfe bitten“ (sendet „Hilf mir, <Name> einzurichten“
  in die Konsole und wechselt dorthin); Abschnitt **Einrichtung** als Checkliste (Häkchen aus `erfuellt`,
  Link-Knopf, Datei-Upload-Knopf für `datei`-Schritte, „Ausführen“ für `befehl`-Schritte mit Live-Ausgabe,
  „Erneut prüfen“); Abschnitt **Konfiguration** mit Werten (Geheimnisse als „gespeichert“) und Knopf
  **Bearbeiten** (öffnet das passende Formular vorbelegt); Abschnitt **Werkzeuge** (Name, Risiko,
  Beschreibung); Knöpfe Neu verbinden / Entfernen.
* **Plus-Knopf** oben rechts („Hinzufügen“) → Reiter „Hinzufügen“ mit Suchfeld über dem Katalog und
  Segmenten: Katalog | MCP-Befehl | MCP-URL | OpenAPI | REST | **JSON einfügen**. JSON akzeptiert das
  Format von Claude Desktop/Code (`{"mcpServers": {"name": {"command","args","env"} | {"type":"http","url","headers"}}}`)
  und legt je Server eine Integration an (Vorschau vor dem Anlegen). Der Reiter „Eigene“ entfällt.
* **Katalogformular**: `standard` vorbelegt; Feldtyp bestimmt Hilfetext und Eingabe (`ordner`: Hinweis
  „absoluter Pfad oder ~/…“); Einrichtungs-Checkliste erscheint schon vor dem Hinzufügen, damit die
  Vorbereitung (Datei, Anmeldung) vorher erledigt werden kann.
* Formulare bekommen `start`-Werte zum Vorbelegen (Bearbeiten).

## Katalog-Änderungen

* `dateisystem.yaml`: `typ: ordner`. `google-kalender.yaml`: Feld `typ: datei`, Standard
  `~/.jarvis/dateien/google-kalender-oauth.json`, Einrichtung (OAuth-Client, Datei hochladen).
* `gmail.yaml`: Einrichtung (OAuth-Client anlegen, Datei nach `~/.gmail-mcp/gcp-oauth.keys.json`
  hochladen, Anmeldung per `npx -y @gongrzhe/server-gmail-autoauth-mcp auth`).

## Tests

Kern: Feldtyp-Prüfung, Details ohne Geheimnisse, Ändern behält Geheimnisse und `id`, Einrichtung mit
Datei-Prüfung/Upload (JSON-Prüfung, Größe), Schritt-Ausführung (gemockter Befehl), Protokoll-Endpunkt,
Fehlertext mit Logzeilen, Agent-Werkzeuge, Prompt mit fehlerhaften Integrationen.
Oberfläche: Detailseite (Fehler, Checkliste, Bearbeiten → PUT), JSON-Import (Parser + Anlegen),
Plus-Reiter, Katalogformular mit Standardwert.

## Dokumentation

VERTRAEGE.md (neue Endpunkte, Katalogfelder), README de/en (Integrationen), STAND.md, PROTOKOLL.md.
