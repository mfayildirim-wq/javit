# Verzeichnissuche und Ein-Klick-Installation – Design Phase 2b (27.10.2026)

## Ziel

Unter „Integrationen → Hinzufügen → Suchen“ findet der Nutzer MCP-Server aus seriösen Verzeichnissen
(offizielles MCP-Registry, Smithery, eigene Registries) und installiert sie mit einem Klick: Remote-Server
mit OAuth oder Kopfzeile, lokale Server als `npx`/`uvx` mit Umgebungsvariablen aus den
Registry-Metadaten. Jeder Treffer zeigt Herkunft und Vertrauensmerkmale; unbekannte Herausgeber werden
deutlich gekennzeichnet. Der Agent kann suchen und (nach Freigabe) installieren.

## Recherche (27.10.2026, live geprüft)

* Offizielles Registry `https://registry.modelcontextprotocol.io/v0/servers?search=&limit=&version=latest`
  → `servers[].server` (`name` reverse-DNS, `title`, `description`, `websiteUrl`, `repository.url`,
  `remotes[]{type, url, headers[]{name, value, isRequired, isSecret}}`,
  `packages[]{registryType npm|pypi|oci|mcpb, identifier, version, runtimeHint, runtimeArguments,
  packageArguments, environmentVariables[]{name, description, isRequired, isSecret, default}}`),
  `_meta["io.modelcontextprotocol.registry/official"].status` (`active`/`deprecated`/`deleted`).
  Namensräume sind vom Registry verifiziert: `io.github.<nutzer>` (GitHub-Konto) oder eigene Domain
  (`com.firma`). Suche ist Teilstring auf dem Namen; Ergebnisse enthalten ohne `version=latest` alle Versionen.
* Smithery `https://registry.smithery.ai/servers?q=&pageSize=` → `servers[]{qualifiedName, displayName,
  description, verified, useCount, remote, isDeployed, homepage, bySmithery}`; Filter `is:deployed`,
  `is:verified` im Suchtext. Detail `GET /servers/{qualifiedName}` → `deploymentUrl`,
  `connections[]{type: http, deploymentUrl, configSchema{required, properties{… x-from{query}}}}`.
  Der MCP-Endpunkt ist die `deploymentUrl` selbst (kein `/mcp`); ohne Token antwortet sie mit 401 +
  `resource_metadata` → OAuth-Entdeckung aus Phase 2a greift. Konfigurationswerte gehen als Query-Parameter.
* mcpservers.org, PulseMCP, Glama: keine nutzbare API (403, eingestellt, Schlüsselpflicht) → nicht angebunden.

## Kern

### `integrationen/verzeichnisse.py`

* `Treffer` (pydantic): `quelle` (Verzeichnis-ID), `kennung` (Name im Verzeichnis), `name`, `beschreibung`,
  `webseite`, `repository`, `herausgeber` (z. B. „GitHub-Konto foo“, „Domain firma.com“, „Smithery“),
  `verifiziert: bool` (Smithery `verified`, Registry-Namensraum mit eigener Domain), `nutzungen: int | None`,
  `art: "mcp_http" | "mcp_stdio" | None` (None = nicht installierbar, z. B. nur Docker/SSE),
  `laufzeit` (`npx`/`uvx`/`fern`), `oauth: bool`, `felder: [{name, titel, geheim, optional, beschreibung}]`,
  `warnungen: [str]`, `installierbar: bool`, `aktualisiert`.
* `Verzeichnis` (Protocol): `id`, `name`, `url`, `async suchen(begriff, limit) -> list[Treffer]`,
  `async details(kennung) -> Treffer` (vollständig, inkl. Felder) und `anfrage(treffer, werte, name) -> dict`
  (Form für `IntegrationsManager.hinzufuegen`).
* `OffiziellesRegistry(url)`: Suche mit `version=latest`, Duplikate nach Name entfernen, nur `active`.
  Installation: bevorzugt `remotes[type=streamable-http]` (→ `mcp_url`; Kopfzeilen mit `{VAR}`-Vorlagen
  werden Felder, Wert wird eingesetzt), sonst Paket `npm` (→ `npx -y identifier@version`) oder `pypi`
  (→ `uvx identifier`), `runtimeArguments`/`packageArguments` mit festem `value` werden übernommen;
  variable Pflichtargumente → Feld mit Platzhalter `{NAME}`; `environmentVariables` → Felder
  (`isSecret` → geheim). `oci`, `mcpb`, nur-SSE → `installierbar=False` mit Begründung.
* `Smithery(url)`: Suche `q=<begriff> is:deployed`; Details über `/servers/{qualifiedName}`;
  `mcp_url = deploymentUrl`; `configSchema.properties` → Felder (required → Pflicht; Name/Beschreibung mit
  key/token/secret/password → geheim), Werte als Query-Parameter (geheime als `${PLATZHALTER}`).
  Nicht-Remote-Server erscheinen nicht (lokale Smithery-Server sind nur über deren CLI lauffähig).
* Eigene Verzeichnisse (`Einstellungen.verzeichnisse_eigene: [{id, name, url}]`) sprechen die API des
  offiziellen Registry (`<url>/v0/servers`) – z. B. ein firmeninternes Registry.
* `Verzeichnisse` (Aggregator): `quellen()`; `suchen(begriff, quelle=None, limit=8)` parallel mit 10 s
  Zeitlimit je Quelle, Ergebnis `{"treffer": [...], "fehler": {quelle: text}}`, sortiert verifiziert →
  nutzungen → Name; Zwischenspeicher 10 min je (Quelle, Begriff). `details(quelle, kennung)`.
  `anfrage(quelle, kennung, werte, name)` → Form für den Manager (prüft Pflichtfelder → `FehlendeWerte`).

### Manager

`mcp_url`-Form erhält optional `werte: {NAME: wert}`: geheime Namen (`ist_geheimer_name`) landen als
`JARVIS_<KENNUNG>_<NAME>` im Schlüsselbund und ersetzen `${NAME}` in URL/Kopfzeilen durch den
Schlüsselbund-Platzhalter; andere Werte werden direkt eingesetzt. `mcp_befehl` nutzt wie bisher `umgebung`
(geheime Namen → Schlüsselbund). Eine Integration aus einem Verzeichnis merkt sich `quelle` und `kennung`
(`IntegrationsKonfig.verzeichnis: {quelle, kennung} | None`), die Detailseite zeigt sie.

### Server

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/verzeichnisse` | `[{id, name, url, eigen}]` |
| GET | `/api/verzeichnisse/suche?q=&quelle=&limit=` | `{treffer: [Treffer], fehler: {quelle: text}}` |
| GET | `/api/verzeichnisse/{quelle}/{kennung:path}` | vollständiger Treffer mit Feldern |
| POST | `/api/verzeichnisse/installieren` | `{quelle, kennung, werte?, name?}` → wie `POST /api/integrationen` (400 + `fehlend` bei fehlenden Pflichtfeldern) |

Eigene Verzeichnisse über `PUT /api/einstellungen {verzeichnisse_eigene}` (Validierung: Kennung
`a-z0-9_-`, https-URL, keine Kollision mit `mcp-registry`/`smithery`).

### Agent

Werkzeuge `verzeichnis_suchen(begriff)` (lesen; nennt Quelle, Herausgeber, Verifizierung, Art,
Pflichtfelder) und `verzeichnis_installieren(quelle, kennung, werte, name)` (**kritisch** – installiert
fremden Code bzw. verbindet fremde Server). Systemprompt: Fehlt ein Dienst im Katalog, erst Katalog, dann
Verzeichnisse durchsuchen; Herkunft und Verifizierung nennen; nur nach ausdrücklicher Zustimmung
installieren; bei lokalen Servern erwähnen, dass fremder Code ausgeführt wird.

## Oberfläche

* „Hinzufügen“ bekommt ein zweites Segment **„Suchen“** (nach Katalog): Suchfeld, Quellen-Chips
  (Alle / MCP-Registry / Smithery / eigene), Trefferliste. Je Treffer: Name, Beschreibung, Chips „Verifiziert“
  bzw. „Unbekannter Herausgeber“, Quelle, „Fern“/„Lokal (npx)“/„Lokal (uvx)“, „Anmeldung im Browser“,
  Nutzungen, Link zu Webseite/Repository. Katalogtreffer zum selben Begriff stehen als „Im Katalog“ oben
  (offizielle Einträge bevorzugt).
* Treffer-Detail: Warnkasten („Von Dritten veröffentlicht – Javit hat diesen Server nicht geprüft. Lokale
  Server führen fremden Code aus.“), Felder-Formular (geheim → Passwortfeld), Name, „Installieren“.
  Nicht installierbare Treffer zeigen den Grund und den Link zur Quelle.
* Einstellungen: Abschnitt „Verzeichnisse“ mit Liste der eigenen Registries (Name, URL, Entfernen) und
  Formular „Registry hinzufügen“.
* Detailseite einer installierten Integration: Zeile „Aus Verzeichnis: <Quelle> · <Kennung>“.

## Tests

* `tests/test_verzeichnisse.py`: Registry-Parsing (Remote mit Kopfzeilenvorlage, npm mit env, pypi,
  nicht installierbar oci/sse, Duplikate/Status), Smithery (Suche + Details mit configSchema → Felder,
  Query-Parameter, geheime Werte), Aggregator (Zeitlimit/Fehler je Quelle, Sortierung, Cache), `anfrage`
  mit fehlenden Pflichtfeldern, Manager `mcp_url` mit `werte` (Schlüsselbund + Platzhalter), Server-Endpunkte,
  Einstellungs-Validierung, Agent-Werkzeuge (Risiko kritisch).
* Oberfläche: Suche zeigt Treffer mit Chips, Detail mit Feldern, Installation ruft
  `POST /api/verzeichnisse/installieren`; Einstellungen legen/entfernen eigene Registries.

## Dokumentation

VERTRAEGE (Endpunkte, Einstellungsfeld, `verzeichnis` in Details), README de/en, STAND, PROTOKOLL.
