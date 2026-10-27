# Entwicklungsprotokoll Javit (Projekt „jarvis“)

Chronologisches Protokoll der Entwicklung bis zur Übergabe an die lokale Weiterentwicklung auf dem Mac.
Ziel: nachvollziehbar machen, **was** gebaut wurde, **warum** so entschieden wurde und **welche Probleme**
auftraten. Neue Einträge unten anfügen.

---

## 26.10.2026 – Auftrag und Grundgerüst

**Auftrag des Nutzers:** Eigener „Jarvis“ auf dem Mac: hört auf „Hey Jarvis“, beliebige Modelle (lokal
und Cloud), erledigt beliebige Aufgaben, Apps einfach integrierbar (MCP, REST, Browser, Tool-Installation –
z. B. Spotify „schnell integriert“), futuristische Oberfläche. Umsetzung „in Loops mit Experten bis zum
Schluss“, ohne Rückfragen.

**Vorab-Recherche:** GitHub-Thema `jarvis-ai` gesichtet. Kein bestehendes Projekt passte: meist
Hobby-Skripte mit festen Befehlen; `akshayaggarwal99/jarvis-ai-assistant` ist eine Diktier-App,
`IRISX-AI/IRIS-AI` ist Open-Core mit verschlossener Kernlogik. → Eigenentwicklung.

**Architektur (docs/ARCHITEKTUR.md, docs/VERTRAEGE.md):**

| Entscheidung | Begründung |
|---|---|
| Python/FastAPI-Kern, React/TS-Oberfläche, WebSocket `/ws` | Agent-Ökosystem in Python, reaktive UI, Streaming |
| Alle Modellaufrufe nur über LiteLLM (`llm.py`) | Modellunabhängigkeit: Ollama, Claude, GPT, Gemini |
| Eigene Agent-Schleife mit Tool-Calling statt Framework | schlank, volle Kontrolle über Freigaben und Abbruch |
| MCP-Hub (stdio + HTTP) mit offiziellem `mcp`-SDK | jede MCP-fähige App in einem Schritt integrierbar |
| OpenAPI- und REST-Integrationen | auch Apps ohne MCP-Server |
| Integrationskatalog als YAML (eine Datei je App) | „Spotify hinzufügen“ per Klick, CLI oder Sprache |
| Risikostufen `lesen`/`aendern`/`kritisch` + Freigabe-Dialog | Löschen, Senden, Shell, Installieren nie ohne Zustimmung |
| Weckwort openWakeWord (`hey_jarvis`), STT faster-whisper, TTS macOS `say` | läuft komplett lokal/offline |
| Server nur auf 127.0.0.1:8765 | nichts im Netzwerk erreichbar |

**Parallel gebaut von drei Experten-Agenten:**
- **Kern** (`kern/jarvis`): Agent, LLM-Fassade (inkl. Zusammensetzen gestreamter Tool-Call-Deltas,
  JSON-Fallback für Modelle ohne Tool-Calling), 17 Mac-Werkzeuge per AppleScript, Dateien, Shell, Web,
  Gedächtnis (SQLite + Embeddings), Integrationsmanager, MCP-Hub, OpenAPI/REST, CLI, Geheimnisse im
  macOS-Schlüsselbund. Katalog mit 22 Einträgen, Paketnamen per `npm view`/`pip index` geprüft
  (veraltete offizielle Server wie `server-github`/`-slack` bewusst nicht genommen). Spotify eingebaut
  über Web-API + AppleScript, weil kein vertrauenswürdiges npm-Paket existierte. → 214 Tests.
- **Stimme** (`kern/jarvis/stimme`): Weckwort, Energie-/WebRTC-VAD mit Sprachpausen-Erkennung,
  faster-whisper lokal / Cloud-STT, `say` mit automatischer Wahl der besten deutschen Stimme,
  Selbsthören-Schutz, Folgefrage-Modus, Freigabe per „Ja“. → 84 Tests.
- **Oberfläche** (`oberflaeche`): HUD-Design (Blau-Schwarz, Eis-Cyan), Canvas-„Reaktor-Orb“ mit
  Zuständen bereit/hört/denkt/arbeitet/spricht, Aktivitäts-Zeitleiste, Freigabe-Dialog, Integrationen
  (Katalog + 4 eigene Varianten), Einstellungen, Befehlspalette, Mock-Server. → 41 Tests.

**Unabhängiger Review + Ende-zu-Ende-Test** (Fake-LLM, projekteigener MCP-Testserver, Browser):

| Schwere | Fund | Behebung |
|---|---|---|
| Hoch | DNS-Rebinding: Host-Kopfzeile ungeprüft | Host-Prüfung für HTTP + WebSocket (421) |
| Hoch | Datei-Werkzeuge konnten Autostart-Einträge/Skripte ohne Freigabe schreiben, Schlüsseldateien lesen | kritische Pfade/Endungen → Freigabe |
| Mittel | Schlüsselbund-Wert als Prozessargument sichtbar | `security -i`, Wert hexkodiert über stdin |
| Mittel | API-Schlüssel in UI-Events | Schwärzen von Geheimnissen |
| Mittel | Abbrechen stoppte wartende Nachrichten nicht; keine Timeouts | Abbruch-Zähler, `werkzeug_timeout`, `llm_timeout` |
| Mittel | Kurzbefehle ohne Freigabe | `shortcuts_ausfuehren` kritisch |
| Niedrig | Prompt-Injection über Werkzeugergebnisse | Systemprompt-Regel + Test |

Außerdem: Ein-Befehl-Installer `scripts/install.sh` (Homebrew, Python 3.12, Node, Ollama +
`qwen2.5:7b` + `nomic-embed-text`, venv `~/.jarvis/venv`, Oberfläche bauen, Befehl `jarvis`),
`autostart.sh` (launchd), `start.command`. → Kern 237 Tests, Oberfläche 44 Tests.

Übertragen nach `~/Documents/jarvis`.

---

## 27.10.2026 – Installation auf dem Mac (Praxistest)

| Problem beim Nutzer | Ursache | Lösung im Installer |
|---|---|---|
| `No module named pip` in `~/.jarvis/venv` | venv ohne pip angelegt; Skript nutzte die kaputte venv bei jedem Lauf wieder | pip-Prüfung, `ensurepip`, sonst Neuanlage |
| `ensurepip … returned non-zero exit status 1` | Homebrew-Python 3.12 konnte pip nicht einrichten | Nutzer-Einstellungen ausblenden (`PIP_CONFIG_FILE=/dev/null`, `PYTHONPATH` u. a.), Rückfall auf **uv** |
| uv: „Broken Python installation, `platform.mac_ver()` returned an empty value“ | Homebrew-Python erkennt die macOS-Version nicht | uv lädt ein eigenständiges Python 3.12 (`--python-preference only-managed`) |
| Anderes Programm („OMH“) auf Port 8765 | Portkonflikt | Programm beenden (`lsof -i :8765`, `kill`) oder `jarvis start --port 8766` |

Nebenbei geklärt: Ollama beenden/starten, Port 11434.

---

## 27.10.2026 – Windows und Linux

**Wunsch:** ein Projekt, installierbar auf Mac, Windows und Linux (keine getrennten Projekte).

**Entscheidung:** gemeinsamer Kern + **Plattform-Schicht** `kern/jarvis/plattform/` (mac/windows/linux).
Werkzeuge haben überall gleiche Namen und Risikostufen; Mac-exklusive (Erinnerungen, Kalender, Notizen,
Kurzbefehle) nur auf dem Mac, sonst Verweis auf Katalog-Integrationen.

- Windows: PowerShell 5.1 mit festen Skripten per `-EncodedCommand`, Werte nur über Umgebungsvariablen
  (keine Injection), SAPI-Stimme, `keyring` (Anmeldeinformationsverwaltung), `install-windows.ps1`
  (winget), `autostart-windows.ps1` (Aufgabenplanung), `start-windows.cmd`.
- Linux: Argumentlisten ohne Shell, xdg-open/gtk-launch, wpctl/pactl, notify-send, playerctl,
  wl-clipboard/xclip, Piper → espeak-ng, `keyring` (Secret Service), `install-linux.sh`
  (apt/dnf/pacman), `autostart-linux.sh` (systemd --user), `.desktop`-Eintrag.
- Mac-Verhalten unverändert. → Kern 367 Tests.

---

## 27.10.2026 – Name „Javit“ und freies Weckwort

**Wunsch:** Der Assistent heißt „Javit“ und hört auf „Javit“.

- Einstellung `name` (Standard „Javit“), Persona mit Platzhalter `{name}`, Name in Oberfläche, Ansagen,
  Meldungen, CLI. Befehl `javit` zusätzlich zu `jarvis`. Interne Bezeichner (`jarvis`, `~/.jarvis`) bleiben.
- **Weckwort-Problem:** openWakeWord kennt nur fertig trainierte Wörter („hey_jarvis“). Training eines
  eigenen Modells ist aufwendig. → Zweite Engine **Vosk** (offline, deutsches Kleinmodell ~50 MB).
  Da „Javit“ nicht im Vosk-Vokabular steht: Grammatik aus bekannten Silbenvarianten („ja wit“, „ja vit“,
  „jawit“ …) + ähnlich klingende Alltagswörter gegen Fehlauslösung + Abgleich per Kölner Phonetik und
  Levenshtein, Stabilitätsprüfung über zwei Teilergebnisse.
- Optional: Anleitung + Skript zum Training eines eigenen openWakeWord-Modells (`scripts/weckwort-trainieren.md`).
- Migration: alte Standard-Persona → neue; altes Standard-Weckwort `hey_jarvis` → `javit` (nur Engine „auto“).

**Unabhängiger Review:**

| Schwere | Fund | Behebung |
|---|---|---|
| Hoch | Vosk-Modellname „..“ hätte Modellordner löschen können | Namensprüfung, Größenlimit (ZIP-Bombe) |
| Hoch | Linux-Installer brach mit NodeSource-Node ab | nodejs/npm nur ohne vorhandenes `node` |
| Hoch | Windows-Befehl kaputt bei Umlauten im Benutzernamen | relative Pfade, reines ASCII |
| Hoch | „App öffnen“ konnte Systemprogramme (reboot, logoff, sudo) ohne Freigabe starten | Sperrliste |
| Mittel | Windows-Lautstärke 0 %, Pfad-Tricks (`x.ps1.`, `::$DATA`), alte Geheimnisse, Weckwort-Migration, Leerzeichen in Linux-Pfaden | jeweils behoben + Tests |

→ Kern 477 Tests, Oberfläche 54 Tests, Browser-Durchlauf grün, shellcheck sauber, PowerShell-Skripte
mit pwsh geparst (nicht ausgeführt).

---

## Stand bei Übergabe (27.10.2026)

- Mac: installiert und genutzt; nach diesem Stand `./scripts/install.sh` erneut ausführen (Vosk).
- Windows/Linux: gebaut und getestet (gemockt bzw. im Container), **noch nie auf echtem System gelaufen**.
- Ungetestet in echt: Vosk-Erkennung von „Javit“ am Mikrofon, Katalog-Integrationen über npx/uvx,
  Cloud-Modelle mit echten Schlüsseln.
- Offene Punkte: siehe `docs/STAND.md`.
- Weiterentwicklung ab jetzt lokal auf dem Mac (`~/Documents/jarvis`), die Cloud-Kopie wird nicht weitergepflegt.

---

## 27.10.2026 – Integration „GG Immobilien (Vercel Test)“ ohne Codeänderung

- MCP-Server `https://gg-immobilienhandel-test.vercel.app/api/mcp` (HTTP, Bearer-Kopfzeile) – derselbe
  Connector, der für Claude Code als `gg-test-vercel` konfiguriert ist – über den Integrationsmanager
  der App hinzugefügt (Form `{"name", "mcp_url", "kopfzeilen"}` aus `docs/VERTRAEGE.md`, kein Code geändert).
- Ergebnis: Kennung `gg_immobilien_vercel_test`, Status verbunden, 9 Werkzeuge (Bestände/Datensätze/
  Dokumente/Verlauf lesen, Notiz an Deal, Gedächtnis suchen/lesen/merken).
- Authorization-Wert liegt im macOS-Schlüsselbund als `JARVIS_GG_IMMOBILIEN_VERCEL_TEST_AUTHORIZATION`;
  `~/.jarvis/integrationen.json` enthält nur den Platzhalter `${…}`.
- Beobachtung: `gedaechtnis_eintraege` (nur lesend) bekommt per Namensheuristik Risiko „aendern“ – bei
  Bedarf über `werkzeug_risiko` in `integrationen.json` auf `lesen` setzen.
- Nachtrag 14:20 Uhr: Nach dem Neuaufbau des gg-Branches `test` (12:46 Uhr) lehnte der Server mit
  „Anmeldung ungültig“ ab – die MCP-Route lag wieder hinter der JWT-Anmeldung der App, der Schlüssel
  wurde nie gegen `MCP_API_KEYS` geprüft. Behoben auf gg-Seite (Commit 89392fe, Deployment 14:14 Uhr,
  Schlüsseleintrag `cowork:read+write:<sha256>`); in Javit „neu verbinden“ → verbunden, 9 Werkzeuge.
  Keine Änderung in Javit nötig.
