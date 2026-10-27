# Javit – Kern (Python-Paket `jarvis`)

Python-Paket `jarvis`: FastAPI-Server, Agent-Schleife, LLM-Fassade (LiteLLM), Werkzeuge,
MCP-Hub, Integrationen, Gedächtnis, Konfiguration und CLI. Läuft auf macOS (Apple Silicon),
Windows 10/11 und Linux (GNOME/KDE, X11/Wayland), Python ≥ 3.11. Schnittstellen: siehe `../docs/VERTRAEGE.md`, Architektur: `../docs/ARCHITEKTUR.md`.

## Installation

```bash
cd kern
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[stimme,dev]'     # ohne Sprachmodul: pip install -e .
brew install node uv                # für MCP-Server per npx / uvx (Linux/Windows: siehe ../README.md)
ollama pull qwen2.5:7b              # Standardmodell (lokal)
ollama pull nomic-embed-text        # optional: Embeddings fürs Gedächtnis
```

## Benutzung

Die Befehle `javit` und `jarvis` sind gleichwertig (beide in `[project.scripts]`).

```bash
javit start                         # = jarvis start
jarvis start                        # Server auf http://127.0.0.1:8765 + Browser
jarvis start --kein-browser
jarvis sag "Wie wird das Wetter morgen?"
jarvis modell                       # Modelle anzeigen (Ollama live + Cloud-Vorschläge)
jarvis modell anthropic/claude-sonnet-5-5
jarvis schluessel ANTHROPIC_API_KEY # verdeckt eingeben → Schlüsselbund / Anmeldeinformationsverwaltung / Secret Service
jarvis katalog [suchbegriff]        # Integrationskatalog
jarvis add spotify                  # fragt benötigte Werte interaktiv ab
jarvis add "npx -y @modelcontextprotocol/server-everything"
jarvis add https://homeassistant.local:8123/api/mcp
jarvis add https://petstore3.swagger.io/api/v3/openapi.json
jarvis list
jarvis remove spotify
jarvis spotify-anmelden             # optional: Spotify-Konto für Web-API-Wiedergabe
```

Läuft der Server bereits, sprechen `add`, `remove`, `list`, `modell` und `schluessel` mit ihm
über die REST-API, damit Änderungen sofort wirken.

## Daten

| Pfad | Inhalt |
|---|---|
| `~/.jarvis/einstellungen.json` | Einstellungen (Modell, Persona, Anrede, Sprache, Stimme …) |
| `~/.jarvis/integrationen.json` | installierte Integrationen (Geheimnisse nur als `${NAME}`) |
| `~/.jarvis/jarvis.db` | SQLite: Verlauf und Erinnerungen (mit Embeddings) |
| `~/.jarvis/logs/mcp-<id>.log` | stderr der MCP-Server |
| Schlüsselbund, Dienst `jarvis` | API-Schlüssel; Windows: Anmeldeinformationsverwaltung, Linux: Secret Service über `keyring` (Fallback überall: `~/.jarvis/geheimnisse.enc`, Fernet) |

Eigene OpenAI-kompatible Endpunkte: `"api_basen": {"openai/mein-modell": "http://127.0.0.1:1234/v1"}`
in `einstellungen.json` (gilt nur für genau diese Modell-ID).

`JARVIS_HOME` verlegt das Datenverzeichnis, `JARVIS_KATALOG` den Katalog,
`JARVIS_OBERFLAECHE` das `dist`-Verzeichnis der Oberfläche,
`JARVIS_GEHEIMNIS_BACKEND=datei|schluesselbund|keyring` erzwingt ein Backend,
`JARVIS_PLATTFORM=mac|windows|linux` überschreibt die erkannte Plattform (für Tests),
`JARVIS_KEIN_DOWNLOAD=1` verhindert das Nachladen von Piper-Stimmen.

## Aufbau

```
jarvis/
  konfig.py          Einstellungen (Pydantic), Standardmodell ollama/qwen2.5:7b, Persona
  geheimnisse.py     Schlüsselbund (security-CLI) / keyring (Windows, Linux) / Fernet-Datei;
                     lädt API-Schlüssel in os.environ
  llm.py             einzige LiteLLM-Fassade: Streaming + Tool-Call-Deltas, JSON-Fallback-Format
                     für Modelle ohne Tool-Calling, Einbettungen, Ollama-Modellliste
  gedaechtnis.py     SQLite: Verlauf, Erinnerungen (Embedding- oder Schlüsselwortsuche)
  agent.py           Agent-Schleife (max. 12 Werkzeugrunden), Events, Freigaben, Abbrechen
  anwendung.py       verdrahtet alles (Jarvis-Klasse), Timer, Sprachmodul-Anbindung
  server.py          FastAPI: /api, /ws, Oberfläche (SPA-Fallback), nur 127.0.0.1
  cli.py             Befehl `jarvis`
  plattform/         Plattform-Schicht: Erkennung + Systemaktionen (mac.py → AppleScript-Werkzeuge,
                     windows.py → PowerShell, linux.py → xdg-open/playerctl/pactl/notify-send …)
  werkzeuge/         Register + eingebaute Werkzeuge (mac, desktop = neutral für Windows/Linux,
                     dateien, shell, web, system)
  integrationen/     katalog, manager, mcp_hub (stdio + Streamable HTTP), openapi, rest,
                     eingebaut/spotify (Spotify-Web-API)
  stimme/            Sprachmodul (eigener Baustein)
```

### Sicherheit

* Jedes Werkzeug hat eine Risikostufe `lesen | aendern | kritisch`. Kritische Aufrufe
  (Shell, Löschen, Senden, Bezahlen, Integration installieren, Überschreiben von Dateien)
  erzeugen `freigabe_noetig`; ohne Antwort innerhalb von 120 s gilt „abgelehnt“.
  Antworten per Klick (`freigabe`), per Text/Sprache („ja“, „mach das“, „bestätigt“ /
  „nein“, „abbrechen“) oder – bei Sprachanfragen – per Rückfrage über das Mikrofon.
* MCP-Werkzeuge: Risiko aus dem Katalog (`werkzeug_risiko`), sonst Heuristik
  (delete/remove/send/pay/purchase/transfer … → kritisch, get/list/search/read … → lesen).
* Server bindet nur an 127.0.0.1; CORS nur für Vite (localhost:5173–5179, 4173);
  schreibende API-Aufrufe und WebSocket-Verbindungen (Prüfung im Handshake) von fremden Origins
  werden abgewiesen; Host-Kopfzeilen außer 127.0.0.1/localhost/[::1] werden mit 421 abgelehnt
  (Schutz gegen DNS-Rebinding).
* Datei-Werkzeuge: Schreiben in versteckte Ordner, ~/Library, ~/.jarvis, außerhalb von ~ oder
  ausführbare Dateien sowie Lesen von Schlüsseldateien (~/.ssh, .env, …) sind kritisch;
  `shortcuts_ausfuehren` ist immer kritisch.
* Geheime Argumente (z. B. `werte` von `integration_hinzufuegen`) werden in Events geschwärzt;
  der Schlüsselbund wird über `security -i` beschrieben (Wert nicht in der Prozessliste).
* Werkzeugergebnisse gelten als Daten; Freigaben kommen ausschließlich vom Nutzer.
* Zeitlimits: `llm_timeout` (180 s), `werkzeug_timeout` (300 s), `freigabe_timeout` (120 s).

### Integrationskatalog

`../integrationen/katalog/*.yaml` (eine Datei je App, Format in VERTRAEGE.md). Zusätzliche
Felder: `kopfzeilen`, `auth`, `rest`, `eingebaut`, `werkzeug_risiko`, `webseite`.
Platzhalter `${NAME}` in `befehl`, `url`, `kopfzeilen` und `rest` werden aus `benoetigt`
befüllt; geheime Werte liegen im Schlüsselbund. Eigene Einträge: `~/.jarvis/katalog/*.yaml`.

## Tests

```bash
cd kern && python3 -m pytest -q
python3 -m tests.e2e.browser_durchlauf   # optional: Browser-Durchlauf + Screenshots (Playwright)
```

Die Tests laufen offline: LLM als Skript mit echten LiteLLM-Stream-Chunks, MCP gegen einen
echten Mini-Server (`tests/mini_mcp_server.py`, stdio und Streamable HTTP), HTTP über
`httpx.MockTransport`, macOS-Befehle über einen gemockten Prozessaufruf. `tests/e2e/` startet einen
echten Server mit deterministischem Fake-LLM (`tests/e2e/fake_llm.py`, Modell `openai/fake`).
