# OAuth-Connectoren und seriöser Katalog – Design Phase 2a (27.10.2026)

## Ziel

Entfernte MCP-Server mit OAuth-Anmeldung (Notion, Linear, GitHub, AWS, Stripe …) sind mit einem Klick
anbindbar: Hinzufügen → Browser öffnet sich → anmelden → verbunden. Google Workspace läuft über die
offiziellen Google-Server mit einem einmal angelegten OAuth-Client. Der Katalog kennzeichnet offizielle
Anbieter-Server („Offiziell“, Quelle = Anbieter-Doku) gegenüber Community-Servern.

Phase 2b (Suche über Verzeichnisse) folgt getrennt.

## Recherche-Ergebnis (27.10.2026, automatisch geprüft)

* MCP-OAuth-Standard (401 + `resource_metadata`, dynamische Registrierung, PKCE S256): Notion, Linear,
  GitHub, Sentry, Stripe (`https://mcp.stripe.com`), Cloudflare Bindings, Asana, Intercom, HubSpot
  (`/anthropic`), PayPal, Square, Figma, Vercel, Supabase, Neon, Canva, Monday, Webflow, Slack, Box,
  Dropbox; AWS (`aws-mcp.<region>.api.aws/mcp`, AS `<region>.oauth.signin.aws` mit Registrierung).
* Ohne Anmeldung: Microsoft Learn, Cloudflare Docs, Context7, DeepWiki, Hugging Face, Shopify Dev.
* Google Workspace (`gmailmcp.googleapis.com/mcp/v1` u. a.): keine dynamische Registrierung; eigener
  OAuth-Client „Webanwendung“ + „für KI-Agenten“; AS `accounts.google.com/o/oauth2/v2/auth`,
  Token `oauth2.googleapis.com/token`; `access_type=offline&prompt=consent` für Refresh-Tokens.
* Atlassian, Zapier: 401 ohne Metadaten → nicht im Katalog (Phase 2b über Verzeichnisse).

## Kern

### `integrationen/oauth.py`

* `OAuthKonfig` (pydantic): `modus: "entdeckung" | "manuell"`; manuell zusätzlich `autorisierung_url`,
  `token_url`, `scopes: list[str]`, `client_id`, `client_secret` (Platzhalter `${…}`), `extra: dict`
  (z. B. `access_type=offline`, `prompt=consent`).
* `SchluesselbundSpeicher(TokenStorage)`: Tokens und Client-Registrierung als JSON im Geheimnisspeicher
  (`JARVIS_OAUTH_<ID>_TOKENS`, `JARVIS_OAUTH_<ID>_CLIENT`). Nie in `integrationen.json`.
* `Rueckrufe`: wartende Anmeldungen je `state` (Future); `erwarten(state)`, `erfuellen(code, state, error)`;
  Zeitlimit 300 s.
* `entdeckungs_auth(kennung, url, rueckruf_url, speicher, melden)` → SDK `OAuthClientProvider`
  (client_name „Javit“, `redirect_uris=[rueckruf_url]`, `token_endpoint_auth_method="none"`,
  Grants `authorization_code`+`refresh_token`). `redirect_handler` hängt `extra` an, meldet
  `{"typ": "oauth_anmeldung", "integration", "url"}` und öffnet den Browser; `callback_handler` wartet
  auf den Rückruf.
* `ManuellerOAuth(httpx.Auth)` für Anbieter ohne Registrierung: Token aus Speicher, sonst
  Authorization-Code-Flow mit PKCE (Browser, Rückruf, Tausch an `token_url` mit Client-ID/Secret),
  Refresh bei Ablauf oder 401, danach einmal wiederholen.
* `auth_fuer(konfig, …)` baut aus `IntegrationsKonfig.oauth` das passende `httpx.Auth`.

### MCP-Hub / Manager

* `McpVerbindung(url=…, kopfzeilen=…, auth=…)` übergibt `auth` an `create_mcp_http_client`;
  `start_timeout` 330 s bei OAuth (Anmeldung im Browser).
* `IntegrationsKonfig.oauth: dict | None`. Katalogeinträge kopieren `oauth` aus dem Katalog. Eigene
  `mcp_url`-Einträge ohne `Authorization`-Kopfzeile bekommen automatisch `{"modus": "entdeckung"}`
  (greift nur, wenn der Server 401 antwortet).
* `abmelden(kennung)`: Tokens/Client löschen, stoppen, Status „aus“; `starten` meldet dann neu an.
* `details()` liefert `oauth: {"modus", "angemeldet": bool}`.
* Rückruf-URL: `http://127.0.0.1:<port>/oauth/rueckruf` (Port der Einstellungen).

### Server

* `GET /oauth/rueckruf?code=&state=[&error=]` → erfüllt den wartenden Flow, antwortet mit einer kleinen
  HTML-Seite („Anmeldung abgeschlossen – Fenster schließen“ bzw. Fehler). Kein `/api`-Pfad, damit die
  Browser-Weiterleitung ohne Origin-Prüfung ankommt (GET ohne Nebenwirkung außer dem Future).
* `POST /api/integrationen/{id}/abmelden` → `{id, abgemeldet: true}`.
* `POST /api/integrationen/{id}/anmelden` → wie neu-verbinden (löst die Anmeldung aus).
* WebSocket-Ereignis `oauth_anmeldung {integration, url}` (Oberfläche zeigt Hinweis mit Link, falls das
  Browserfenster nicht automatisch aufging).

### Katalog

* Neue Felder: `oauth` (s. o.), `vertrauen: offiziell | community` (Standard `community`), `quelle`
  (Doku-URL des Anbieters), `gruppe` (z. B. `google-workspace`). `als_info()` liefert sie mit.
* Neue offizielle Einträge (geprüft): notion, linear, github (OAuth statt Token; Token weiterhin optional),
  sentry, stripe, cloudflare, asana, intercom, hubspot, paypal, square, figma, vercel, supabase, neon,
  canva, monday, webflow, slack (Remote statt npx), box, dropbox, aws (Region als Feld, Standard
  eu-central-1, URL mit `?oauth=initialize`), microsoft-learn, cloudflare-docs, context7 (Remote statt npx),
  deepwiki, huggingface.
* Google Workspace: neun Einträge `google-gmail`, `google-kalender`, `google-drive`, `google-docs`,
  `google-sheets`, `google-slides`, `google-chat`, `google-kontakte`, `google-classroom` mit
  `gruppe: google-workspace`, gemeinsamen Feldern `GOOGLE_OAUTH_CLIENT_ID` (text) und
  `GOOGLE_OAUTH_CLIENT_SECRET` (geheim), Scopes laut Google-Doku, `oauth: manuell`, und einer
  gemeinsamen Einrichtung (Zustimmungsbildschirm, APIs + MCP-APIs aktivieren, Client „Webanwendung“ +
  „für KI-Agenten“, Rückruf-URL eintragen, Client-ID/Secret übernehmen). Die bisherigen npx-Einträge
  `gmail` und `google-kalender` bleiben als Community-Alternative (`google-kalender` → `google-kalender-lokal`).
* Bestehende Einträge erhalten `vertrauen` und `quelle`; Katalogsortierung: offiziell vor community.

### Agent

Systemprompt-Regel: Bei OAuth-Integrationen die Anmeldung im Browser erklären; nach „Anmeldung
abgeschlossen“ neu verbinden. Werkzeug `integration_details` zeigt `angemeldet`.

## Oberfläche

* Katalogkacheln und -detail: Chips „Offiziell“/„Community“, „Anmeldung im Browser“ (OAuth) oder
  „ohne Schlüssel“; Link „Quelle“ (Anbieter-Doku). Offizielle zuerst.
* Google Workspace als **eine** Kachel: Dienste per Häkchen wählen, Client-ID/Secret einmal eingeben,
  Einrichtungs-Checkliste aus Phase 1 davor. Beim Anlegen entstehen die gewählten Einträge.
* Beim Hinzufügen eines OAuth-Servers: Meldung „Anmeldung im Browser … falls kein Fenster aufgeht:
  [Anmeldeseite öffnen]“ (aus `oauth_anmeldung`), danach Status verbunden.
* Detailseite: Chip „angemeldet“, Knöpfe „Abmelden“ und „Neu anmelden“.

## Tests

* `tests/test_oauth.py`: Entdeckungsflow gegen gemockten Autorisierungsserver (401 → Metadaten →
  Registrierung → Redirect-Handler → Rückruf → Token → Wiederholung), Token im Geheimnisspeicher,
  Refresh; manueller Flow (Google-Form) mit PKCE und Extra-Parametern; Rückruf-Zeitlimit und Fehler.
* Manager/Server: automatisches `oauth` bei `mcp_url`, `abmelden`, Rückruf-Route, Katalog-Validierung
  (Offizielle Einträge haben `quelle` und https-URL), Details mit `angemeldet`.
* Oberfläche: Chips, Google-Gruppenkarte erzeugt die gewählten Einträge, OAuth-Hinweis mit Link.

## Dokumentation

VERTRAEGE (Endpunkte, Ereignis, Katalogfelder), README de/en (Connectoren, Google), STAND, PROTOKOLL.
