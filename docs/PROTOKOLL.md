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

---

## 27.10.2026 – Freigaben nach Bereich: technisch ohne Rückfrage, fachlich bestätigen

- Wunsch des Nutzers: technische Dinge (Dateisystem, Umgebung, Shell, Installationen) ohne Berechtigungsfrage mit
  den Rechten des Systembenutzers; fachliche Dinge bestätigen lassen; Ausnahme: Dateien löschen bleibt
  bestätigungspflichtig (dazu Zugangsdaten lesen als Vorschlag, angenommen).
- Befund vorher: Freigabe nur bei Stufe „kritisch“ – Dienst-Werkzeuge mit „ändern“ (Notion-Seite, Aufgabe,
  Termin) liefen ohne Rückfrage, Shell/Löschen/Installieren fragten. Also fast umgekehrt.
- Kern: `werkzeuge.Bereich` (`technisch`|`fachlich`), `Werkzeug.bereich`/`schutz`, Regel `freigabe_noetig()`
  (fachlich ab `aendern` je `freigabe_fachlich`; technisch nur bei `freigabe_technisch` oder `schutz`).
  Eingebaute Werkzeuge technisch, `termin_anlegen`/`erinnerung_anlegen`/`notiz_anlegen` fachlich (über
  `FACHLICH_EINGEBAUT`, ohne `mac.py` anzufassen); `datei_loeschen`/`datei_lesen` mit `schutz`. Katalog `bereich`
  (20 technische Einträge: dateisystem, git, browser, fetch, Suchen, Doku-Server, Zeitzonen, Obsidian, Spotify,
  Hue, Home Assistant, Wetter, Petstore), Manager `bereich_von()`/`bereich_setzen()`, Werkzeuge werden nach dem
  Bau markiert; `PUT /api/integrationen/{id}/bereich`; Ereignis `freigabe_noetig` mit `risiko`/`bereich`;
  Systemprompt angepasst.
- Oberfläche: Einstellungen „Freigaben“ (Schalter + Stufe), Detailseite „Freigaben“ mit Technisch/Fachlich,
  Freigabedialog nennt den Bereich.
- Tests: `tests/test_freigaben.py` (5), `freigaben.test.tsx` (2); E2E „Mini Test“ bekommt `bereich: technisch`,
  sonst bräuchte `echo` (ändern, fachlich) jetzt eine Freigabe – genau die neue Regel.

## 28.10.2026 – Schwarze Oberfläche unter Windows: MIME-Typen

- Befund (Nutzer: Windows-Installation zeigt nur eine schwarze Seite): Pythons `mimetypes.init()` liest unter
  Windows die Registry (`HKCR\.js` → „Content Type“) und überschreibt damit den eingebauten Wert
  `text/javascript`; auf vielen Rechnern steht dort `text/plain`. Starlettes `FileResponse` übernimmt das,
  Browser verweigern Modul-Skripte mit falschem MIME-Typ, React startet nie – wegen `color-scheme: dark`
  bleibt die Seite schwarz. Unter Linux hängt das Ergebnis von `/etc/mime.types` ab (dort üblicherweise korrekt).
- Behebung: `server.MIME_TYPEN`/`mime_typ()` – feste Typen für die Vite-Ausgabe (js/mjs/css/svg/woff2/json …),
  `index.html` immer `text/html`; Test `test_oberflaeche_mime_typen_unabhaengig_vom_system` (gefälschtes
  `guess_type` → `text/plain`). Live am Mac geprüft (GET der Assets auf Port 8766).
- Zusätzlich zeigt `index.html` nach 4 s einen lesbaren Hinweis (Neu laden, F12-Konsole, `/api/status`), falls
  das Modul-Skript nicht läuft – statt einer leeren schwarzen Fläche.
- Linux-Skripte (`install-linux.sh`, `autostart-linux.sh`) gegengelesen: keine Auffälligkeit; die feste
  MIME-Tabelle gilt dort ebenso.

## 28.10.2026 – Unterhaltungen und Gedächtnis-Optimierung

- Spezifikation `docs/superpowers/specs/2026-10-28-unterhaltungen-gedaechtnis-design.md`, Plan
  `docs/superpowers/plans/2026-10-28-unterhaltungen-gedaechtnis.md`. Entscheidung des Nutzers: frühere Unterhaltungen
  nicht auf der Startseite, sondern unter Einstellungen → Unterhaltungen.
- Kern: `gedaechtnis.py` neu geschrieben – Tabellen `unterhaltungen` (titel, titel_fest, zusammenfassung, nachbereitet),
  `meta` (aktuelle Unterhaltung), Spalten `verlauf.unterhaltung_id` und `erinnerungen.{einbettung_modell, quelle,
  unterhaltung_id, aktualisiert}`, Migration alter Datenbanken (Verlauf → „Bisheriger Verlauf“), FTS5 über Trigger
  (Fallback ohne FTS5), Hybridsuche (max aus Kosinus bei gleichem Modell, BM25-Wert, Stichwortmaß).
  `gedaechtnis_pflege.py`: `LokaleEinbettung` (fastembed `paraphrase-multilingual-MiniLM-L12-v2`, 384 Dim., ca. 220 MB,
  Extra `kern[gedaechtnis]`, kein Download bei `JARVIS_KEIN_DOWNLOAD`), `EinbetterKette`, `BenannterEinbetter`,
  `Nachbereiter` (Titel in 3–5 Wörtern mit Fallback aus der ersten Nachricht; JSON-Zusammenfassung + Fakten, Abgleich
  ≥ 0,85 bzw. ≥ 0,6 bei `auto`, Fakten mit Zugangsdaten verworfen). Anwendung: `unterhaltung_neu/aktivieren/
  umbenennen/loeschen` mit Ereignis `unterhaltung`, Pflege-Tasks (`pflege_abwarten`), Nachbereitung alter aktueller
  Unterhaltung (> 6 h) beim Start, Nachbetten fehlender Vektoren; Agent: Kontext nur aktuelle Unterhaltung, Abschnitt
  „Letzte Unterhaltungen“, `nach_antwort`-Haken für den Titel; Werkzeug `unterhaltung_neu`; REST-Endpunkte laut VERTRAEGE.
- Stolpersteine: `threading.Lock` ist nicht reentrant (Deadlock im Schema-Aufbau); `asyncio.gather` über bereits
  fertige Tasks kehrt in 3.12 synchron zurück – der `discard`-Callback kam nie dran (Endlosschleife in
  `pflege_abwarten`, jetzt nur offene Tasks); automatische Titel/Nachbereitung verbrauchen gescriptete LLM-Antworten –
  Testhelfer (`baue_jarvis`, E2E-Umgebung) schalten `gedaechtnis_automatisch` aus, Tests schalten gezielt ein.
- Oberfläche: Ereignis `unterhaltung` (Reducer leert Konsole bei Wechsel, Verbindung lädt Verlauf), Status →
  `lokal_unterhaltung`, Kopfzeile mit Titel und Knopf „Neu“, Palette, Alt+N, Einstellungen „Unterhaltungen“
  (öffnen/umbenennen/löschen) und Gedächtnis mit Herkunft, Einzellöschung, Schalter „Automatisch merken“.
- Tests: `test_unterhaltungen.py` (15), `test_gedaechtnis_pflege.py` (12), `unterhaltungen.test.tsx` (4);
  `test_websocket_ende_zu_ende` toleriert das Titel-Ereignis.

## 28.10.2026 – Flüssige Stimme: Streaming, Stoppwort, Audio im Browser

- Spezifikation `docs/superpowers/specs/2026-10-28-stimme-streaming-browser-design.md`, Plan
  `docs/superpowers/plans/2026-10-28-stimme-streaming-browser.md`. Recherche live: OpenRouter bietet seit 5/2026
  `/audio/speech` (PCM 24 kHz) und `/audio/transcriptions`; OpenAI-TTS dort nicht verfügbar. Gemessen (deutscher
  Satz, 8 s Audio): ElevenLabs Flash v2.5 erster Byte 0,39 s, Microsoft MAI `de-DE-Klaus` 1,0 s, Gemini 2,4 s;
  Whisper large v3 0,96 s. Entscheidung des Nutzers: OpenAI über OpenRouter, sonst lokal Piper → umgesetzt als
  `auto` = OpenRouter mit Schlüssel, Standard ElevenLabs Flash.
- Kern: `stimme/sprecher.py` (Satzstrom mit Abkürzungs-/Zahlen-Schutz, erster Satz sofort, kurze Folgesätze
  verschmolzen; `OpenRouterTTS` streamt PCM, Stereo→Mono, Rate aus dem Content-Type; `LautsprecherZiel` über
  `sounddevice.OutputStream` mit Rückstau 2 s; `BrowserZiel` Binärframes ≤ 9600 Bytes mit Spieldauer-Wartezeit;
  `BrowserQuelle` über `Rahmenbildner`; `Sprecher`-Warteschlange mit zwei Synthesen voraus, Dateiweg für
  say/SAPI/Piper/cloud; Modellkatalog `openrouter_sprachmodelle`). `StimmDienst`: `sprecher_beginnen/
  sprecher_abschliessen` (Zustand `spricht` erst beim ersten Ton), `sprechen()` reiht in eine laufende Sitzung ein
  (keine Verklemmung bei Freigabefragen), Stoppwort-Detektor (zweiter `VoskWeckwortDetektor`, lazy),
  `quelle_setzen`/`ausgabe_setzen`; Dialog spricht nicht doppelt (`antwort=True`-Sitzungen). Agent: `sprecher`-Fabrik,
  Deltas → Sitzung, `abschliessen` nach `antwort_ende`, `stoppen` bei Abbruch, `antwort_gesprochen`. Anwendung:
  `browser_audio_start/daten/stop`, `stimme_probe`, `stimme_modelle`. Server: `ws.receive()` mit Binärframes,
  `audio_start/audio_stop`, Sender je Verbindung, `/api/stimme/probe`, `/api/stimme/modelle`.
- Oberfläche: `lib/audio.ts` (AudioWorklet aus Blob-URL, int16-Blöcke, lückenlose Wiedergabe, Fakes für Tests),
  Socket binär, `audioBrowser` (localStorage, Standard an bei Touch-Geräten), Mikrofon-Knopf sendet
  `audio_start` + `stimme`, Umschalter im Composer, Reducer `sprachausgabe` (Stoppwort-Hinweis), Einstellungen →
  Stimme mit OpenRouter-Modellen/Stimmen, Preis je Minute, Stoppwort, „Probe sprechen“.
- Stolpersteine: `Sprecher.warten_bis_leer` wartete ewig, weil das „leer“-Ereignis erst nach dem Blockieren in
  `queue.get()` gesetzt wurde; Testmarker 54321 passte nicht in int16; `Satzstrom` erster Satz anfangs ab 12 Zeichen –
  bestehende Tests erwarten den sofortigen kurzen ersten Satz (jetzt `min_erster=1`); Flag „Antwort schon
  gesprochen“ darf nur von Antwort-Sitzungen gesetzt werden, sonst verschluckt der Dialog die Antwort nach
  einer Rückfrage; `getByLabelText('Stimme')` kollidiert mit dem gleichnamigen Abschnitt (Selector eingrenzen).
- Live am Mac (Port 8766, echte Schlüssel): Audio-Sitzung per WebSocket, Antwort als PCM-Binärframes (7 s,
  erster Frame 0,9 s nach dem ersten Text), per Whisper gegengeprüft; Probe über Lautsprecher ok.

## 28.10.2026 – Einstellungen mit Reitern

- Nutzerwunsch: Bereiche als Reiter, Anbieter- und Modellwahl übersichtlicher, Unnötiges weg. Umgesetzt in
  `Settings.tsx`: fünf Reiter Modell / Stimme / Freigaben / Gedächtnis / Erweitert (Wahl in `localStorage`
  `jarvis.einstellungen.reiter`), nur der aktive Reiter wird gerendert.
- Modell: Anbieter als Auswahlliste mit Statuszeile (Schlüssel hinterlegt / fehlt, Ollama erreichbar) statt
  Chip-Wolke; Modelle sortiert nach `versionsZahl()` (neueste zuerst, Datumsanhänge ignoriert), ab neun Einträgen
  nur die acht neuesten plus das aktive, Rest hinter „n ältere Modelle anzeigen“.
- Entfernt: eigener Abschnitt „API-Schlüssel“ (der Anbieter-Schlüssel steht beim Anbieter; eigene Schlüssel unter
  Erweitert → „Weitere Schlüssel“); „Verzeichnisse“ nach Erweitert verschoben; „Audio im Browser“ als Schalter im
  Reiter Stimme (zusätzlich zum Knopf im Composer).
- Tests klicken jetzt zuerst den Reiter; Anbieterwahl über `combobox`; neuer Test `versionsZahl`.
- Kopfzeile kompakt (44 px statt 56): Reiter Konsole/Integrationen/Einstellungen als Symbole rechts neben „Neu“, „Befehle“ und Verbindungsstatus; Titel der Unterhaltung mittig. Der Orb bekommt dadurch mehr Platz nach oben.
- Kopfzeile ganz entfernt: Marke (Symbol + Name + Titel der Unterhaltung) oben im linken Bereich, Symbolleiste (Ansichten, Neu, Befehle, Verbindungspunkt) oben im rechten Bereich über „Aktivität“; auf schmalen Bildschirmen (≤ 760 px) eine mobile Symbolleiste über der Konsole. `TopBar` bleibt als Alias der mobilen Leiste.
- Abbruch beim Sprechen nachgestellt (Prüfinstanz, Mac-Lautsprecher + Mikrofon): nach 13 s „sprachausgabe gestoppt (stoppwort)“ – ein einzelnes Vosk-Teilergebnis „stopp“ aus der eigenen Stimme löste sofort aus (exakte Variante = sofort). Im Modus `nur_ganz` zählt ein Treffer jetzt erst, wenn das Teilergebnis zweimal gleich ist oder abgeschlossen wurde; der Treffertext steht im Protokoll (WARNING). Danach lief eine 46-s-Antwort vollständig durch. Dazu: fehlgeschlagene Satz-Synthese wird einmal wiederholt.

## 28.10.2026 – Stoppwort löst sich selbst aus: Echounterdrückung am Mac

- Live mitgeschrieben (Hauptinstanz): 14 s nach Sprechbeginn `sprachausgabe gestoppt (stoppwort)`. Nachgestellt mit
  eigener Stimme über Lautsprecher + Mikrofon: Aufnahme übersteuert (Spitze 20987), die kleine Vosk-Grammatik
  bildet die eigene Stimme laufend auf „stopp“, „halt“, „sei still“ ab (4 Kandidaten in 37 s). Freie Erkennung kennt
  „stopp“ nicht („stab“), Energie-Gating trennt nicht sauber, die Ganzheitsregel verhindert echte Stopps während
  der Ausgabe. Lösung: Apples Voice Processing (AVAudioEngine `setVoiceProcessingEnabled`) – Echo im Mikrofon 13×
  leiser (Spitze 2843, RMS 173 statt 2357), auch für Ausgabe aus einem anderen Prozess (sounddevice).
- Umgesetzt: `stimme/mac_mikrofon.swift` (Helfer, PCM 16 kHz int16 auf stdout, Ende über stdin), `stimme/mac_aec.py`
  (`MikrofonAEC` als AudioQuelle, `helfer_sicherstellen` baut mit `xcrun swiftc` nach `~/.jarvis/bin`, nicht bei
  `JARVIS_KEIN_DOWNLOAD`; Hintergrundbau beim ersten Start), Einstellung `aec: auto|an|aus`, `install.sh` baut den
  Helfer; Dienst wählt ihn auf dem Mac (kein eigenes `geraet`), Stoppwort-Regel je nach Echounterdrückung
  (`echo_unterdrueckung` an `MikrofonAEC` und `BrowserQuelle`). Tests `tests/stimme/test_mac_aec.py` (5).
- Live: 61-s-Antwort über Lautsprecher mit Helfer ohne Abbruch; Helferprozess endet mit dem Dienst.
