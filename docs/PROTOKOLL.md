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

---

## 27.10.2026 – Anbieterwahl und Modellliste je Anbieter

- Auslöser: OpenRouter-Schlüssel ließ sich eintragen, aber kein OpenRouter-Modell wählen; Wunsch nach
  DeepSeek, Kimi, GLM, OpenCode und eigenen Anbietern. Spezifikation:
  `docs/superpowers/specs/2026-10-27-anbieter-modellwahl-design.md`.
- Kern: neues Register `jarvis/anbieter.py` (12 eingebaute Anbieter, eigene OpenAI-kompatible über
  `anbieter_eigene`), Live-Modelllisten mit 8-s-Zeitlimit und 10-Minuten-Cache, OpenRouter-Gratismodelle
  (`pricing == 0`) und Werkzeugfähigkeit (`supported_parameters`) ausgewertet. `llm.CLOUD_VORSCHLAEGE`
  wird aus dem Register abgeleitet. OpenCode/eigene Anbieter → `openai/<modell>` + `api_base` +
  eigener `api_key` (nie `OPENAI_API_KEY`). `GET /api/modelle?anbieter=&neu=` rückwärtskompatibel erweitert.
- Oberfläche: Anbieterleiste (Chips mit Schlüsselstatus) → Schlüsselfeld des Anbieters → Modellliste
  (Chips „kostenlos“/„Werkzeuge“, „Modelle neu laden“) → Freitext-ID → „Anbieter hinzufügen“/entfernen.
  Ab 9 Einträgen Filterfeld und Schalter „nur kostenlose“ (OpenRouter liefert ~450 Modelle).
  Live geprüft mit zweiter Instanz auf Port 8766 (Gemini- und OpenRouter-Listen, Schlüsselstatus).
- Recherche: OpenCode-Gratismodelle sind laut Doku nur in OpenCode nutzbar („Free-tier chat models
  require OpenCode“) – daher nur bezahlte Modelle, `-free`/`big-pickle` werden ausgefiltert. Modell-IDs
  für DeepSeek (`deepseek-flash`, `deepseek-v4-pro`), Z.AI (`glm-5.3`), xAI (`grok-4.7`), Groq und
  OpenRouter über Doku bzw. Live-Listen geprüft; Kimi-/Mistral-IDs nur plausibel (Live-Liste deckt es ab).
- Tests: `tests/test_anbieter.py` (Register, Übersetzung, Parser, Cache, Fassade, Server),
  Oberfläche `einstellungen.test.tsx` (Anbieterwahl, Schlüssel, Gratis-Chip, eigener Anbieter).
  Kern 478 grün (Mac: `test_kritische_pfade_linux` schlägt vorbestehend fehl), Oberfläche 56 grün.

---

## 27.10.2026 – Integrationen sichtbar, bearbeitbar, geführt (Phase 1)

- Auslöser: Dateisystem war mit `Documents/*` angelegt (relativ + Platzhalter → „None of the specified
  directories are accessible“), Gmail scheiterte an der fehlenden OAuth-Datei; beides war in der
  Oberfläche weder sichtbar noch änderbar. Spezifikation: `docs/superpowers/specs/2026-10-27-integrationen-einrichten-design.md`.
- Sofort behoben: Dateisystem auf `~/Documents` (14 Werkzeuge).
- Kern: Katalogfelder mit `typ` (ordner/datei/url, geprüft beim Anlegen und Ändern), `einrichtung:`-Schritte
  (Link, Datei-Ziel mit Prüfung/Upload, ausführbarer Befehl) in `jarvis/integrationen/einrichtung.py`;
  Manager `details()`/`aendern()`/`protokoll_zeilen()`; MCP-Hub hängt die letzten Fehlerzeilen des
  Server-Protokolls an den Fehlertext (dedupliziert); neue Endpunkte (siehe VERTRAEGE); Agent-Werkzeuge
  `integration_details`, `integration_einrichtung`, `integration_konfigurieren` (ändern),
  `integration_schritt_ausfuehren` (kritisch); Systemprompt nennt nicht verbundene Integrationen mit Grund
  und die Regel, Schritt für Schritt zu führen.
- Oberfläche: Reiter „Installiert | Hinzufügen“ + Plus-Knopf; Detailseite (`IntegrationDetail.tsx`) mit
  Fehlerkasten, „Javit um Hilfe bitten“ (sendet die Bitte in die Konsole), Einrichtungs-Checkliste
  (`Einrichtung.tsx`: Upload per Base64, Ausführen mit Stand-Abfrage), Konfiguration + Bearbeiten
  (vorbelegte Formulare, Geheimnisse als „gespeichert“), Werkzeugliste, Protokoll; „JSON einfügen“
  importiert `mcpServers`-Konfigurationen (Vorschau, mehrere auf einmal); Katalogformular belegt
  Standardwerte vor und erklärt Feldtypen.
- Katalog: `dateisystem` (typ ordner), `gmail` und `google-kalender` mit Einrichtungsschritten; Google
  Kalender erwartet die OAuth-Datei standardmäßig unter `~/.jarvis/dateien/google-kalender-oauth.json`.
- Live geprüft (zweite Instanz, Port 8766): Gmail-Detailseite zeigt Grund, Checkliste (Schritt 3 offen),
  Upload- und Ausführen-Knöpfe. Nicht real durchgespielt: der Google-Anmeldelauf selbst.
- Tests: `tests/test_einrichtung.py` (9), Oberfläche `integrationen-ansicht.test.tsx` (3) +
  `integration.test.tsx`; Kern 487 grün (ohne vorbestehenden Linux-Pfad-Test), Oberfläche 61 grün.

---

## 27.10.2026 – Werkzeugaufrufe als Text („DSML“) bei OpenRouter-Modellen

- Symptom: Auf „welche Verzeichnisse gibt es?“ zeigte Javit `<｜DSML｜ calls> <｜DSML｜ invoke name="dateisystem_listallowed_directories">…`
  als Antwort. Ursache: `litellm.supports_function_calling()` kennt die meisten OpenRouter-Modelle nicht
  (GLM 5.3 Flash, DeepSeek V4.1 → False), Javit fiel in den Prompt-Modus, und DeepSeek/GLM antworteten
  dort mit ihrem eigenen DSML-Aufrufformat statt mit dem verlangten JSON; direkt getestet liefern beide
  Modelle über OpenRouter native Tool-Calls, auch im Streaming.
- Behebung in `llm.py`: Cloud-Modelle gelten als tool-fähig; bei OpenRouter entscheidet die Live-Liste
  (`supported_parameters` enthält „tools“), unbekannt → tool-fähig. Zusätzlich DSML-Parser
  (`dsml_aufrufe_parsen`, Vollbreite- und ASCII-Striche, Parameter als JSON oder Text), Markup wird nie
  mehr roh angezeigt (Stream hält `<｜`/`<|` zurück, auch im nativen Modus), und kleine Namensfehler des
  Modells (`dateisystem_listallowed_directories`) werden eindeutig auf das echte Werkzeug aufgelöst.
- Live mit `openrouter/z-ai/glm-5.3-flash`: nativer Modus, Aufruf `dateisystem__list_allowed_directories`.

---

## 27.10.2026 – OAuth-Connectoren und seriöser Katalog (Phase 2a)

- Spezifikation: `docs/superpowers/specs/2026-10-27-oauth-connectoren-design.md`. Recherche vorab: MCP-OAuth-
  Spezifikation, Google-Workspace-MCP-Doku (Client „Webanwendung“ + „für KI-Agenten“, keine dynamische
  Registrierung), AWS MCP Server (OAuth je Region), Microsoft Learn (ohne Anmeldung); 36 Kandidaten-URLs automatisch
  geprüft (401 + `resource_metadata` = Standard; Atlassian/Zapier ohne Metadaten → nicht aufgenommen).
- Kern: `integrationen/oauth.py` – `SchluesselbundSpeicher` (TokenStorage des SDK), `Rueckrufe` (state → Future,
  300 s), `entdeckungs_auth` (SDK `OAuthClientProvider`, Rückruf `http://127.0.0.1:<port>/oauth/rueckruf`,
  Zusatzparameter an die Autorisierungs-URL), `ManuellerOAuth` (httpx2.Auth: PKCE, Code-Tausch, Refresh, 401-Retry).
  Stolperstein: Das MCP-SDK nutzt das Paket **httpx2**, nicht httpx – Auth-Klassen und Tests müssen httpx2 nutzen.
  MCP-Hub reicht `auth` an `create_mcp_http_client`, Startzeitlimit 330 s bei OAuth. Manager: `oauth` in der
  Konfiguration, automatisch `entdeckung` für eigene MCP-URLs ohne Authorization, `abmelden()`, `oauth_stand()`.
  Server: `GET /oauth/rueckruf`, `POST …/abmelden`, `POST …/anmelden`; Ereignis `oauth_anmeldung`.
- Katalog (56 Einträge): 21 offizielle OAuth-Connectoren, AWS, 5 anmeldefreie, Google Workspace als Gruppe
  (9 Dienste, gemeinsame Felder `GOOGLE_OAUTH_CLIENT_ID/SECRET`, Scopes laut Google-Doku, Einrichtungs-Checkliste);
  `github` jetzt OAuth, `github-token`/`slack-lokal`/`google-kalender-lokal` als Alternativen; Felder `vertrauen`,
  `quelle`, `gruppe`, Sortierung offiziell vor community. Tests auf `github-token` umgestellt; `conftest` setzt
  `JARVIS_OHNE_BROWSER=1` (sonst öffnete ein Test den echten Browser und wartete 300 s).
- Oberfläche: Chips „Offiziell“/„Community“/„Anmeldung im Browser“, Quelle-Link, Kachel „Google Workspace“ mit
  Dienste-Auswahl und gemeinsamen Feldern, OAuth-Hinweis mit „Anmeldeseite öffnen“, Detailseite mit
  angemeldet/Abmelden/Anmelden.
- Tests: `tests/test_oauth.py` (7: Entdeckungsflow gegen gefälschten Autorisierungsserver, manueller Google-Flow
  mit Refresh, Rückrufe, Katalog, Manager, Server), Oberfläche 64 grün.

---

## 27.10.2026 – Verzeichnissuche und Ein-Klick-Installation (Phase 2b)

- Spezifikation: `docs/superpowers/specs/2026-10-27-verzeichnissuche-design.md`. Live geprüft: offizielles Registry
  (`/v0/servers?search=&version=latest`; ohne `version=latest` kommen alle Versionen, Suche ist Teilstring auf dem
  Namen, viel Spam-ähnliches → Duplikate und Status ≠ active filtern), Smithery (`/servers?q=… is:deployed`, Detail
  `/servers/{qualifiedName}` mit `deploymentUrl` = MCP-Endpunkt selbst, **kein** `/mcp`; antwortet 401 +
  `resource_metadata` → OAuth-Entdeckung aus 2a greift; Konfiguration als Query-Parameter laut `configSchema`).
  mcpservers.org (403), PulseMCP (eingestellt), Glama (Schlüssel) nicht angebunden.
- Kern: `integrationen/verzeichnisse.py` (`Treffer`, `OffiziellesRegistry`, `Smithery`, `Verzeichnisse` mit
  Cache/Zeitlimit, `anfrage()` → Manager-Form). Vorlagen nutzen `{NAME}`, beim Installieren wird daraus `${NAME}`;
  Stolperstein: die Vorlagen-Regex matcht auch innerhalb von `${NAME}` → Platzhalter erst ganz am Ende füllen.
  Manager: `werte`/`geheime` für `mcp_url` (geheime Werte als `JARVIS_<KENNUNG>_<NAME>` im Schlüsselbund, auch
  verschachtelt in Kopfzeilen), `verzeichnis` in Konfiguration/Details, `aendern` behält Herkunft und
  URL-Geheimnisse. Domain-Namensräume des Registry (DNS-geprüft) gelten als verifiziert, damit offizielle
  Herausgeber (z. B. `net.todoist/mcp`) vor anonymen Smithery-Konten stehen.
- Tests: `tests/test_verzeichnisse.py` (10) – Achtung: `hinzufuegen` startet die Verbindung; bei Remote-URLs
  wartet die OAuth-Entdeckung 300 s auf den Rückruf → in Tests `manager.starten` ersetzen (`_ohne_start`).
  Kern 508 grün, Oberfläche 68 grün (`verzeichnisse.test.tsx`: Trefferliste, Detail/Installation, Smithery-Nachladen,
  Einstellungen).
- Oberfläche: `views/Verzeichnisse.tsx` (Suche, Trefferliste, Detail mit Warnkasten und Feldern), Segment „Suchen“
  unter Hinzufügen, Einstellungen „Verzeichnisse“, Detailseite „Aus Verzeichnis“.
