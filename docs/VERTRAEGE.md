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
| GET | `/api/werkzeuge` | `[{name, beschreibung, quelle, integration?, risiko}]` |
| GET | `/api/integrationen` | installierte Integrationen `[{id, name, art, status: verbunden|fehler|aus, werkzeuge:n, fehler?}]` |
| GET | `/api/integrationen/katalog` | Katalog `[{id, name, beschreibung, kategorie, icon, art, benoetigt:[{name, titel, geheim}]}]` |
| POST | `/api/integrationen` | Integration hinzufügen (s. u.) → Integration |
| DELETE | `/api/integrationen/{id}` | entfernen |
| POST | `/api/integrationen/{id}/neu-verbinden` | neu starten |
| GET | `/api/verlauf?limit=` | letzte Unterhaltung |
| GET/DELETE | `/api/gedaechtnis` | Erinnerungen lesen/löschen |

Integration hinzufügen – eine der Formen:
```json
{"katalog": "spotify", "werte": {"SPOTIFY_CLIENT_ID": "…", "SPOTIFY_CLIENT_SECRET": "…"}}
{"name": "Mein Tool", "mcp_befehl": "npx -y @modelcontextprotocol/server-everything", "umgebung": {}}
{"name": "Home Assistant", "mcp_url": "http://homeassistant.local:8123/mcp", "kopfzeilen": {"Authorization": "Bearer …"}}
{"name": "Petstore", "openapi_url": "https://petstore3.swagger.io/api/v3/openapi.json", "auth": {"art": "bearer", "wert": "…"}}
{"name": "Wetter", "rest": [{"name": "wetter_abrufen", "methode": "GET", "url": "https://api.open-meteo.com/v1/forecast", "parameter": {"latitude": "zahl", "longitude": "zahl", "current_weather": "text"}, "beschreibung": "…"}]}
```

## WebSocket `/ws`

Client → Server (JSON):
| typ | Felder |
|---|---|
| `nachricht` | `text`, `sprechen?: bool` (Antwort vorlesen) |
| `freigabe` | `id`, `erlaubt: bool` |
| `abbrechen` | – |
| `stimme` | `aktiv: bool` (Mikrofon/Weckwort an/aus) |
| `zuhoeren` | – (Push-to-talk: einmal zuhören ohne Weckwort) |

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
| `freigabe_noetig` | `id`, `werkzeug`, `argumente`, `grund`, `risiko`, `timeout?` (Sekunden bis „abgelehnt“) |
| `integration_geaendert` | `integration` |
| `fehler` | `text` |

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
hinweis: "Schlüssel unter developer.spotify.com anlegen …"
risiko_standard: aendern
```

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

Stimm-Einstellungen (`einstellungen.stimme`, Auszug): `tts` = `auto` (Standard: Mac `say`, Windows
`sapi`, Linux `piper` mit Fallback `espeak`) | `say` | `sapi` | `piper` | `espeak` | `cloud` | `aus`.
`say` wird außerhalb des Macs wie `auto` behandelt.
