🇬🇧 [English](README.md) · 🇩🇪 **Deutsch**

# Javit – Ihr persönlicher KI-Assistent für Mac, Windows und Linux

Javit hört auf **„Javit“** (Name und Weckwort sind frei einstellbar), versteht Deutsch, erledigt Aufgaben auf Ihrem Rechner (Apps,
Musik, Lautstärke, Zwischenablage, Dateien, Web – auf dem Mac zusätzlich Kalender, Erinnerungen,
Notizen und Kurzbefehle) und lässt sich in Sekunden
um weitere Apps erweitern – per Katalog („Javit, integriere Spotify“), MCP-Server, OpenAPI oder
einfache REST-Endpunkte. Als Gehirn dient ein **beliebiges Sprachmodell**: lokal und offline über
Ollama oder in der Cloud (Claude, GPT, Gemini …). Kritische Aktionen führt Javit nur nach Ihrer
**Freigabe** aus.

![Javit-Konsole: Orb, Systeme-Leiste mit Modell, Stimme, Integrationen und Werkzeugen, Aktivitätsbereich](docs/bilder/konsole.png)

```
„Javit“ → Weckwort → Spracherkennung → Agent (Modell + Werkzeuge) → Antwort (Text + Sprache)
                                               │
          System-Werkzeuge (Mac/Windows/Linux) · Integrationen (MCP/REST/OpenAPI) · Gedächtnis · Freigaben
```

---

## Inhalt

1. [Installation in einem Schritt](#installation-in-einem-schritt) (macOS)
   · [Installation unter Linux](#installation-unter-linux)
   · [Installation unter Windows](#installation-unter-windows)
   · [Plattform-Unterschiede](#plattform-unterschiede)
2. [Erster Start](#erster-start)
3. [„Javit“ – Sprache, Name und Weckwort](#javit--sprache-name-und-weckwort)
4. [Modelle](#modelle)
5. [Integrationen](#integrationen)
6. [Beispielsätze](#beispielsätze)
7. [Sicherheit und Freigaben](#sicherheit-und-freigaben)
8. [Datenablage](#datenablage)
9. [Fehlerbehebung](#fehlerbehebung)
10. [Entwicklung und Tests](#entwicklung-und-tests)
11. [Aufbau](#aufbau)

---

## Installation in einem Schritt

**macOS** (für Linux und Windows siehe die folgenden Abschnitte). Voraussetzungen: macOS (Apple Silicon empfohlen), [Homebrew](https://brew.sh), ca. 8 GB freier
Speicher für das lokale Modell.

```bash
cd ~/Documents/jarvis && ./scripts/install.sh
```

Das Skript

* prüft Homebrew (fehlt es, zeigt es den offiziellen Installationsbefehl und bricht ab),
* installiert bei Bedarf `python@3.12`, `node` und `ollama`,
* lädt das lokale Sprachmodell `qwen2.5:7b` (ca. 4,7 GB) und `nomic-embed-text` fürs Gedächtnis –
  **der erste Download dauert je nach Leitung einige Minuten**,
* legt die Python-Umgebung `~/.jarvis/venv` an und installiert den Kern mit Sprachmodul,
* baut die Oberfläche (`npm ci && npm run build`),
* legt die gleichwertigen Befehle `javit` und `jarvis` in `~/.local/bin` ab (und ergänzt bei Bedarf
  den `PATH` in `~/.zshrc`),
* lädt die Weckwort-Modelle vorab: das Vosk-Modell `vosk-model-small-de-0.15` (ca. 45 MB) für
  „Javit“ und zusätzlich openWakeWord „Hey Jarvis“.

Mehrfaches Ausführen ist unbedenklich (z. B. nach einem Update). Optionen:
`JARVIS_OHNE_MODELLE=1` (keine Ollama-Modelle laden), `JARVIS_MODELL=llama3.1:8b` (anderes lokales
Modell), `JARVIS_KEIN_PATH=1` (`~/.zshrc` nicht anfassen).

## Installation unter Linux

Unterstützt: Ubuntu/Debian, Fedora, Arch (auch Manjaro/EndeavourOS) und openSUSE; GNOME, KDE und
andere Desktops; X11 und Wayland.

```bash
cd ~/jarvis && ./scripts/install-linux.sh               # mit lokalem Modell: JARVIS_OLLAMA=1 ./scripts/install-linux.sh
```

Das Skript

* erkennt die Paketverwaltung (apt, dnf, pacman, zypper) und installiert per `sudo` (nur dafür):
  Python 3 mit venv, Node.js/npm, PortAudio, `playerctl`, libnotify (`notify-send`),
  `wl-clipboard`/`xclip`, `pulseaudio-utils` (`pactl`) und `espeak-ng`,
* prüft Node.js (benötigt 20.19+ bzw. 22.12+); ist es zu alt, zeigt es den Weg über
  [nvm](https://github.com/nvm-sh/nvm) bzw. [NodeSource](https://github.com/nodesource/distributions) – es installiert
  nichts an der Paketverwaltung vorbei,
* installiert **Ollama nur mit `JARVIS_OLLAMA=1`** über das offizielle Skript (`ollama.com/install.sh`),
  sonst gibt es einen Hinweis; mit Ollama werden `qwen2.5:7b` und `nomic-embed-text` geladen,
* legt `~/.jarvis/venv` an (bei Problemen oder zu altem Python über `uv` mit eigenem Python 3.12),
  installiert den Kern mit Sprachmodul (inkl. Piper) und baut die Oberfläche,
* legt `~/.local/bin/javit` und `~/.local/bin/jarvis` sowie den Startmenü-Eintrag „Javit“
  (`~/.local/share/applications/jarvis.desktop`) an und lädt die Weckwort-Modelle (Vosk für „Javit“).

Optionen wie beim Mac: `JARVIS_OHNE_MODELLE=1`, `JARVIS_MODELL=…`, `JARVIS_KEIN_PATH=1`, außerdem
`JARVIS_OHNE_PAKETE=1` (keine Systempakete, kein sudo). Autostart als systemd-Benutzerdienst:

```bash
./scripts/autostart-linux.sh an | aus | status      # ~/.config/systemd/user/jarvis.service
```

Hinweise: Die Sprachausgabe nutzt **Piper** mit der Stimme `de_DE-thorsten-medium` (wird beim ersten
Sprechen nach `~/.jarvis/modelle/piper` geladen, ca. 60 MB), sonst `espeak-ng`. Das Mikrofon läuft über
PipeWire/PulseAudio (Eingabegerät in den Toneinstellungen bzw. mit `pavucontrol` wählen). Unter
Wayland gibt es keine allgemeine Fensterliste – `laufende_apps` gleicht dann laufende Prozesse mit
den installierten Apps ab. API-Schlüssel landen im Secret Service (GNOME-Schlüsselbund/KWallet),
ohne laufenden Dienst in der verschlüsselten Datei.

## Installation unter Windows

Windows 10 (ab 1809) oder 11 mit `winget` (App-Installer). In PowerShell im Projektordner:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1          # ohne Ollama: … -OhneOllama
```

`-ExecutionPolicy Bypass` gilt nur für diesen einen Aufruf – die Systemeinstellung bleibt unverändert.
Das Skript

* installiert per winget bei Bedarf **Python 3.12** (`Python.Python.3.12`), **Node.js LTS**
  (`OpenJS.NodeJS.LTS`) und **Ollama** (`Ollama.Ollama`, abschaltbar mit `-OhneOllama`) und lädt die
  lokalen Modelle (`-OhneModelle` überspringt das, `-Modell llama3.1:8b` wählt ein anderes),
* legt `%USERPROFILE%\.jarvis\venv` an (Fallback: `uv`), installiert den Kern mit Sprachmodul und baut
  die Oberfläche,
* legt `javit.cmd` und `jarvis.cmd` in `%USERPROFILE%\.jarvis\bin` ab, ergänzt den **Benutzer-PATH**
  (`-KeinPath` verhindert das), erstellt eine **Startmenü-Verknüpfung** „Javit“ und lädt die
  Weckwort-Modelle (Vosk für „Javit“).

Starten: `javit start` in einem neuen Terminal, über das Startmenü oder per Doppelklick auf
`scripts\start-windows.cmd`. Autostart bei der Anmeldung (Aufgabenplanung, ohne Konsolenfenster):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\autostart-windows.ps1 -An    # bzw. -Aus / -Status
```

Hinweise: Mikrofonzugriff unter Einstellungen → Datenschutz und Sicherheit → Mikrofon erlauben
(auch „Desktop-Apps den Zugriff erlauben“). Die Sprachausgabe nutzt die Windows-Stimmen (SAPI);
fehlt eine deutsche Stimme: Einstellungen → Zeit und Sprache → Sprache → Deutsch → Sprachausgabe.
API-Schlüssel landen in der Windows-Anmeldeinformationsverwaltung. Mitteilungen erscheinen als
Toast (mit dem PowerShell-Modul BurntToast, falls installiert).

## Plattform-Unterschiede

| Funktion | macOS | Windows | Linux |
|---|---|---|---|
| Apps öffnen/beenden, laufende Apps | AppleScript, `open` | Startmenü/Store-Apps, `CloseMainWindow` | Desktop-Dateien (`gtk-launch`), `pkill`; Fensterliste über `wmctrl` (X11) |
| Lautstärke | AppleScript | Core-Audio (COM), Fallback Medientasten | `wpctl` / `pactl` / `amixer` |
| Musik | Apple Music und Spotify (inkl. Suche in der Mediathek) | Medientasten, Titel aus dem Spotify-Fenster | `playerctl` (Spotify und alle MPRIS-Player) |
| Mitteilungen | Mitteilungszentrale | Toast (BurntToast bzw. WinRT) | `notify-send` |
| Zwischenablage, Bildschirmfoto | `pbcopy`, `screencapture` | `Get/Set-Clipboard`, System.Drawing | `wl-copy`/`xclip`/`xsel`; `gnome-screenshot`/`spectacle`/`grim`/`scrot` |
| Dateisuche | Spotlight (auch Inhalte) | Windows-Suchindex (auch Inhalte), sonst Namenssuche | `plocate`/`locate`, sonst Namenssuche |
| Papierkorb | Finder | Papierkorb (send2trash) | Freedesktop-Papierkorb (send2trash) |
| Shell-Werkzeug | zsh | Windows PowerShell | bash |
| **Erinnerungen, Kalender, Notizen** | ✓ (Apple-Apps) | – → Integrationen `google-kalender`, `todoist`, `notion`, `obsidian` | – → dieselben Integrationen |
| **Apple-Kurzbefehle** | ✓ | – (Home Assistant o. Ä. als Integration) | – |
| Sprachausgabe (lokal) | `say` | SAPI (z. B. Microsoft Hedda) | Piper, Fallback espeak-ng |
| API-Schlüssel | Schlüsselbund | Anmeldeinformationsverwaltung | Secret Service (keyring) |
| Autostart | `scripts/autostart.sh` (launchd) | `scripts/autostart-windows.ps1` (Aufgabenplanung) | `scripts/autostart-linux.sh` (systemd --user) |

Die Werkzeugnamen und Risikostufen sind überall gleich; Mac-exklusive Werkzeuge werden unter
Windows/Linux gar nicht erst angeboten – stattdessen schlägt Javit passende Katalog-Integrationen vor.

## Erster Start

```bash
javit start             # startet den Server auf http://127.0.0.1:8765 und öffnet den Browser
                        # („jarvis start“ funktioniert genauso)
```

Alternativ: Doppelklick auf `scripts/start.command` im Finder. Automatisch bei jeder Anmeldung
starten:

```bash
./scripts/autostart.sh an      # launchd-Dienst de.jarvis.agent (Kennung bleibt für bestehende Autostarts)
./scripts/autostart.sh aus
./scripts/autostart.sh status
```

macOS fragt beim ersten Zugriff nach Rechten – bitte erlauben:

* **Mikrofon** (für das Weckwort „Javit“): Systemeinstellungen → Datenschutz & Sicherheit → Mikrofon →
  Terminal (bzw. Ihr Terminalprogramm; beim Autostart „python3.12“).
* **Automation** (Musik, Kalender, Erinnerungen, Notizen, Finder): Datenschutz & Sicherheit →
  Automation.

## „Javit“ – Sprache, Name und Weckwort

* Mikrofon-Knopf in der Oberfläche (oder `Strg/⌘ + K` → „Mikrofon“) schaltet das Weckwort an/aus.
* Danach genügt **„Javit, …“** – Javit hört bis zur Sprechpause zu und antwortet per Sprache.
* **Leertaste** (außerhalb von Eingabefeldern) = Push-to-talk: einmal zuhören ohne Weckwort.
* Spracherkennung lokal mit faster-whisper (Modell wird beim ersten Mal geladen), über OpenRouter
  (Whisper, ca. 1 s) oder per Cloud; Sprachausgabe „Automatisch“ = OpenRouter-Stimme, sobald ein
  OpenRouter-Schlüssel hinterlegt ist (ElevenLabs Flash, Microsoft MAI mit deutschen Stimmen, Google),
  sonst macOS `say`, Windows SAPI, Linux Piper/espeak-ng – alles unter **Einstellungen → Stimme**
  mit Modell- und Stimmenliste, Preis je Minute und Knopf „Probe sprechen“.
* **Flüssig:** Javit spricht, sobald der erste Satz der Antwort feststeht, während das Modell noch
  schreibt (Streaming, erster Ton nach unter einer Sekunde). **„Stopp“** während der Ausgabe beendet
  sie sofort (Stoppwort unter Einstellungen → Stimme, mehrere durch Komma); das Weckwort unterbricht
  und nimmt direkt die nächste Frage auf.
* **Audio im Browser:** Umschalter neben dem Mikrofon-Knopf (auf Handy/Tablet Standard an) – dann
  nimmt der Browser auf und spielt die Antwort ab, der Kern kann auf einem anderen Rechner laufen.
  Weckwort, Stoppwort und Push-to-talk funktionieren unverändert.
* Freigaben lassen sich per Sprache beantworten („Ja“, „Mach das“ / „Nein“, „Abbrechen“).

### Name ändern

**Einstellungen → Persona → Name des Assistenten** (oder `"name": "…"` in
`~/.jarvis/einstellungen.json`). Der Name erscheint in Kopfzeile, Fenstertitel, Boot-Animation,
Freigabe-Dialog, Ansagen und Fehlermeldungen und wird über den Platzhalter `{name}` in die Persona
(Systemprompt) eingesetzt. Ältere Einstellungsdateien mit der früheren Standard-Persona („Du bist
Jarvis …“) erhalten automatisch die neue Standard-Persona; eine selbst geschriebene Persona bleibt
unverändert (dort wirkt nur `{name}`). Das Weckwort wird **getrennt** eingestellt (siehe unten).
Interne Bezeichner bleiben gleich: Python-Paket `jarvis`, Ordner `~/.jarvis`, Umgebungsvariablen
`JARVIS_*`, Befehl `jarvis` (zusätzlich `javit`).

### Weckwort und Engines

**Einstellungen → Stimme → Weckwort** (Text, mehrere durch Komma, z. B. `javit, hey javit`) und
**Weckwort-Erkennung**:

| Engine | Wann | Eigenschaften |
|---|---|---|
| **Vosk** (Standard für „Javit“) | jedes freie Wort | offline, kein Training; deutsches Kleinmodell `vosk-model-small-de-0.15` (~45 MB, wird beim ersten Einschalten nach `~/.jarvis/modelle/vosk` geladen) |
| **openWakeWord** | `hey_jarvis` oder eigenes `.onnx`-Modell | sehr sparsam; fertige Modelle nur für englische Phrasen |
| **Automatisch** (`auto`) | – | `hey_jarvis`/„hey jarvis“ (und andere fertige openWakeWord-Wörter) oder ein eigenes Modell → openWakeWord, alles andere → Vosk |

So erkennt Vosk „Javit“, obwohl das Wort nicht im Vokabular des Modells steht: Vosk ignoriert
unbekannte Wörter einer Grammatik. Javit baut deshalb eine kleine Grammatik aus **bekannten
Silben/Wörtern** („ja witt“, „ja vit“, „jawit“, „javid“, „dschawit“ … – nur was laut
`Model.find_word()` im Vokabular steht) plus ähnlich klingender Alltagswörter („ja“, „bitte“, „mit“,
„david“ …) und `[unk]`. Das (Teil-)Ergebnis wird dann **phonetisch** verglichen: zusammengezogene
Wörter („ja witt“ → „jawitt“) mit gleichem Code nach **Kölner Phonetik** (032) und ähnlicher
Schreibweise (Levenshtein) zählen als Treffer, exakte Varianten sofort, phonetische erst, wenn sie
in zwei aufeinanderfolgenden Teilergebnissen stehen. Eigene Schreibvarianten:
`"weckwort_varianten": ["ja witt", "dschawit"]` unter `stimme` (ersetzt die Standardliste).
Die **Weckwort-Empfindlichkeit** (`schwelle`) gilt für beide Engines: bei Vosk 0,5 = exakte oder
phonetisch gleiche Treffer, 0,9 = nur sehr ähnliche Schreibweisen, kleiner = auch unscharfe Treffer.

Vorab laden bzw. testen: `~/.jarvis/venv/bin/python -m jarvis.stimme --modelle-laden --alle` bzw.
`python -m jarvis.stimme --weckwort javit` (Echo-Test). Ohne Internet beim ersten Start: Modell von
alphacephei.com/vosk/models laden und nach `~/.jarvis/modelle/vosk/vosk-model-small-de-0.15/`
entpacken (oder `"vosk_modell": "/pfad/zum/modell"`).

### Eigenes Weckwort-Modell trainieren (optional)

Für ein besonders sparsames, robustes Weckwort lässt sich ein openWakeWord-Modell „javit“ mit dem
offiziellen Trainings-Notebook (synthetische Daten, Google Colab) trainieren:
[scripts/weckwort-trainieren.md](scripts/weckwort-trainieren.md). Die `.onnx`-Datei kommt nach
`~/.jarvis/modelle/openwakeword/` und wird über `"weckwort_modell_pfad"` geladen
(`python3 scripts/weckwort_trainieren.py installieren javit.onnx` erledigt beides).

## Modelle

Standard ist das lokale Modell `ollama/qwen2.5:7b` – läuft komplett offline. Weitere lokale Modelle
mit zuverlässigem Werkzeug-Aufruf: `qwen3:8b`, `llama3.1:8b`, `llama3.2:3b`
(`ollama pull <name>`).

```bash
javit modell                               # alle Modelle anzeigen (Ollama live + Cloud-Vorschläge)
javit modell ollama/qwen3:8b               # wechseln (gilt ab der nächsten Anfrage)
```

Cloud-Modelle (Schreibweise von LiteLLM) brauchen einen API-Schlüssel, der im
**macOS-Schlüsselbund** (Windows: Anmeldeinformationsverwaltung, Linux: Secret Service) gespeichert wird.
In der Oberfläche unter **Einstellungen → Modell** wählt man oben den **Anbieter**, trägt direkt
darunter dessen Schlüssel ein und bekommt dann die **Modellliste live vom Anbieter** (ohne Schlüssel
eine feste Vorschlagsliste). Kostenlose Modelle sind als „kostenlos“ markiert.

| Anbieter | Schlüssel | Beispiel-Modell-IDs |
|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY` | `anthropic/claude-sonnet-5-5`, `anthropic/claude-opus-5-5` |
| OpenAI | `OPENAI_API_KEY` | `openai/gpt-6.1-sol`, `openai/gpt-5.4-mini` |
| Google Gemini | `GEMINI_API_KEY` | `gemini/gemini-4-argon`, `gemini/gemini-3.8-flash` (Gratis-Kontingent) |
| OpenRouter | `OPENROUTER_API_KEY` | `openrouter/deepseek/deepseek-v4.1-flash`, `openrouter/moonshotai/kimi-k3`, `openrouter/z-ai/glm-5.3-flash`; **Gratis-Modelle** mit Endung `:free` |
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek/deepseek-flash`, `deepseek/deepseek-v4-pro` |
| Kimi (Moonshot) | `MOONSHOT_API_KEY` | `moonshot/kimi-k3` |
| GLM (Z.AI) | `ZAI_API_KEY` | `zai/glm-5.3`, `zai/glm-5.3-flash` |
| OpenCode | `OPENCODE_API_KEY` | `opencode/kimi-k2.5`, `opencode/glm-5.3-flash` – nur **bezahlte** Modelle (die Gratis-Modelle von OpenCode laufen laut OpenCode-Doku nur in OpenCode selbst) |
| Groq, Mistral, xAI | `GROQ_API_KEY`, `MISTRAL_API_KEY`, `XAI_API_KEY` | `groq/llama-3.3-70b-versatile`, `mistral/mistral-large-latest`, `xai/grok-4.7` |

Schlüssel per Terminal: `javit schluessel OPENROUTER_API_KEY` (verdeckte Eingabe). Modelle lassen sich
auch per Sprache umschalten („Wechsle auf Claude Sonnet“). **Eigene OpenAI-kompatible Anbieter**
(LM Studio, vLLM, Proxy …) legt man in der Oberfläche über „Anbieter hinzufügen“ an (Name, Basis-URL,
optional Schlüssel) – sie erscheinen als eigener Anbieter mit Modell-IDs `<kennung>/<modell>`
(`einstellungen.json`: `anbieter_eigene`). Alternativ bleibt `api_basen` je Modell-ID, z. B.
`{"openai/mein-modell": "http://127.0.0.1:1234/v1"}`.

## Integrationen

**Aus dem Katalog** (`integrationen/katalog/*.yaml`, 22 Einträge: Spotify, GitHub, Notion, Slack,
Gmail, Google Kalender, Todoist, Obsidian, Home Assistant, Philips Hue, Wetter, Browser, …):

```bash
javit katalog              # alle Einträge
javit katalog musik        # suchen
javit add spotify          # fragt fehlende Werte (Client ID/Secret) ab
javit list                 # installierte Integrationen und Status
javit remove spotify
```

**Per Sprache oder Chat:** „Javit, integriere Notion.“ – Javit sucht im Katalog, fragt nach
fehlenden Schlüsseln und legt die Integration nach Ihrer Freigabe an.

**Connectoren mit Anmeldung im Browser (OAuth):** Offizielle Server von Notion, Linear, GitHub, Sentry, Stripe,
Cloudflare, Asana, Intercom, HubSpot, PayPal, Square, Figma, Vercel, Supabase, Neon, Canva, monday.com, Webflow,
Slack, Box, Dropbox und AWS sind im Katalog als **Offiziell** gekennzeichnet (mit Link zur Anbieter-Doku).
Hinzufügen → der Browser öffnet sich → anmelden → verbunden; Tokens liegen im Schlüsselbund, „Abmelden“ auf der
Detailseite. **Google Workspace** (Gmail, Kalender, Drive, Docs, Sheets, Slides, Chat, Kontakte, Classroom) läuft
über die offiziellen Google-Server mit **einem** selbst angelegten OAuth-Client – die Kachel „Google Workspace“
führt durch die Schritte und legt die gewählten Dienste an. Ohne Anmeldung nutzbar: Microsoft Learn, Cloudflare
Docs, Context7, DeepWiki, Hugging Face. Community-Server (von Dritten) sind entsprechend markiert.

**Suche in Verzeichnissen:** Fehlt ein Dienst im Katalog, findet **Hinzufügen → Suchen** MCP-Server im
offiziellen MCP-Registry und bei Smithery (eigene Registries mit derselben API lassen sich in den Einstellungen
unter „Verzeichnisse“ eintragen). Jeder Treffer zeigt Herausgeber (GitHub-Konto, bestätigte Domain,
Smithery-Konto), ob das Verzeichnis ihn als **verifiziert** führt, ob er fern läuft oder lokal per npx/uvx
ausgeführt wird, und welche Angaben er braucht. Ein Klick installiert: Remote-Server verbinden sich (bei Bedarf
mit Anmeldung im Browser), lokale Server werden als Befehl mit Umgebungsvariablen angelegt – mit deutlicher
Warnung, dass fremder Code ausgeführt wird. Auch per Chat: „Javit, suche einen MCP-Server für Jira“ – Javit
nennt Herausgeber und Verifizierung und installiert erst nach Zustimmung.

**In der Oberfläche:** Integrationen → **Hinzufügen** (Plus-Knopf): Katalog, **Suchen**, MCP-Befehl, MCP-URL,
OpenAPI, REST oder **JSON einfügen** (eine Konfiguration im Format von Claude Desktop/Claude Code wird
erkannt und übernommen). Unter **Installiert** öffnet ein Klick die **Detailseite**: Status mit
Fehlergrund und Protokoll, **Einrichtung** als Checkliste (Links, Datei-Upload, ausführbare Schritte wie
die Google-Anmeldung), **Konfiguration** mit **Bearbeiten**, Werkzeugliste. Bei Problemen hilft der Knopf
„Javit um Hilfe bitten“: Der Assistent kennt Status und Einrichtungsschritte und führt Schritt für Schritt.

**Eigene Integrationen:**

```bash
javit add "npx -y @modelcontextprotocol/server-everything"        # MCP-Server (stdio)
javit add https://homeassistant.local:8123/api/mcp                # MCP über HTTP
javit add https://petstore3.swagger.io/api/v3/openapi.json        # OpenAPI → Werkzeuge
```

Einfache REST-Endpunkte und Kopfzeilen/Authentifizierung lassen sich in der Oberfläche
(„Eigene“ → REST) anlegen. Eigene Katalogeinträge: YAML-Datei in `~/.jarvis/katalog/`
(Format: [docs/VERTRAEGE.md](docs/VERTRAEGE.md)).

**Browser:** `javit add browser` bindet den Playwright-MCP-Server ein – Javit kann dann Webseiten
im echten Browser öffnen, klicken und Formulare ausfüllen. Fehlt der Browser:
`npx playwright install chromium`.

## Beispielsätze

* „Javit, wie spät ist es?“ · „Was steht heute in meinem Kalender?“
* „Spiel etwas Jazz auf Spotify.“ · „Lauter.“ · „Nächstes Lied.“
* „Erinnere mich morgen um 9 an den Zahnarzt.“ · „Stell einen Timer auf zehn Minuten.“
* „Leg eine Notiz ‚Einkauf: Milch, Brot‘ an.“
* „Merk dir, dass ich Earl Grey ohne Zucker trinke.“
* „Such die PDF mit der Steuererklärung und öffne den Ordner.“
* „Fasse diese Webseite zusammen: https://…“ · „Suche im Web nach …“
* „Führe den Kurzbefehl ‚Licht aus‘ aus.“ (mit Freigabe)
* „Integriere GitHub.“ · „Welche Integrationen sind verbunden?“

## Sicherheit und Freigaben

* Jedes Werkzeug hat eine Risikostufe (**lesen**, **ändern**, **kritisch**) und einen **Bereich**:
  * **Technisch** (Dateien, Shell, Apps, Installationen, Entwicklung, Web lesen, Smart Home, Musik) läuft
    **ohne Rückfrage** mit den Rechten deines Benutzers. Nur **Dateien löschen** (Papierkorb) und das
    **Lesen von Zugangsdaten-Dateien** (`.ssh`, `.env`, `.pem` …) werden immer bestätigt. Wer alles sehen
    will, schaltet in den Einstellungen „Technische Aktionen bestätigen“ ein – dann erscheinen auch Shell,
    Installationen und Schreiben in Autostart-/Konfigurationsordner wieder im Dialog.
  * **Fachlich** (Nachrichten und Mails, Termine, Aufgaben, Notizen, Einträge in Diensten wie Notion, GitHub,
    Slack, Todoist, Zahlungen) zeigt einen **Freigabe-Dialog** für alles außer Lesen – ohne Antwort gilt nach
    120 s „abgelehnt“. Einstellbar: ab Ändern (Standard), nur Kritisches oder nie. Welche Integration als
    technisch oder fachlich gilt, steht im Katalog und lässt sich je Integration auf der Detailseite umstellen.
* Inhalte aus Werkzeugen (Webseiten, Mails, Dateien) gelten als Daten, nicht als Anweisungen; sie
  können keine Freigabe erteilen.
* Der Server lauscht **nur auf 127.0.0.1**. Fremde Webseiten können weder die API noch den
  WebSocket nutzen (Origin-Prüfung, auch im WebSocket-Handshake; Host-Prüfung gegen DNS-Rebinding).
* API-Schlüssel liegen im **macOS-Schlüsselbund** (Dienst `jarvis`; Windows/Linux: über `keyring` in
  der Anmeldeinformationsverwaltung bzw. im Secret Service) und werden ohne Prozessargument übergeben; in Ereignissen an die Oberfläche werden geheime Werte geschwärzt.
* `Esc` bricht die laufende Antwort ab und lehnt offene Freigaben ab.

## Datenablage

Alles liegt in `~/.jarvis/` (Windows: `%USERPROFILE%\.jarvis`, verlegbar mit `JARVIS_HOME`):

| Pfad | Inhalt |
|---|---|
| `einstellungen.json` | Name, Modell, Persona, Anrede, Stimme/Weckwort, Zeitlimits … |
| `integrationen.json` | installierte Integrationen (Geheimnisse nur als `${NAME}`) |
| `jarvis.db` | Unterhaltungen, Verlauf und Erinnerungen (SQLite, Volltextindex) |
| `logs/` | Protokolle (`mcp-<id>.log`, `jarvis.log` beim Autostart) |
| `modelle/` | Weckwort-Modelle (`modelle/vosk`, `modelle/openwakeword`), unter Linux auch Piper-Stimmen (`modelle/piper`) |
| `venv/` | Python-Umgebung der Installation |

**Unterhaltungen:** Der Verlauf ist in Unterhaltungen gegliedert; nur die aktuelle ist Kontext für das Modell.
Eine neue beginnt über den Knopf „Neu“ in der Kopfzeile, Alt+N, die Befehlspalette oder indem du dem Assistenten
ein neues Thema ankündigst (Werkzeug `unterhaltung_neu`). Frühere Unterhaltungen stehen unter Einstellungen →
Unterhaltungen (öffnen, umbenennen, löschen). Nach der ersten Antwort bekommt jede Unterhaltung automatisch einen
Titel; beim Verlassen fasst das Modell sie zusammen und merkt sich dauerhafte Fakten über dich (Einstellungen →
Gedächtnis, Schalter „Automatisch merken“; jede Erinnerung zeigt ihre Herkunft und lässt sich einzeln löschen).
Die Suche im Gedächtnis läuft hybrid über Volltext und Einbettungen – mit Ollama (`nomic-embed-text`), sonst mit
einem kleinen lokalen Modell (`fastembed`, ca. 220 MB beim ersten Gebrauch), sonst rein über Volltext.

Das Gedächtnis lässt sich in der Oberfläche (Einstellungen → Gedächtnis) löschen, Verlauf und
Gedächtnis auch per `curl -X DELETE http://127.0.0.1:8765/api/verlauf` bzw. `…/api/gedaechtnis`.

## Fehlerbehebung

| Problem | Lösung |
|---|---|
| `javit: command not found` | Neues Terminal öffnen bzw. Installer erneut ausführen (legt `javit` an) oder `source ~/.zshrc` (Linux: `~/.bashrc`); notfalls `~/.jarvis/venv/bin/jarvis start` (Windows: `%USERPROFILE%\.jarvis\venv\Scripts\jarvis.exe start`) |
| Linux: „Für … fehlt ein Hilfsprogramm“ | Den angezeigten Installationsbefehl ausführen (z. B. `sudo apt install playerctl`) |
| Windows: Skript „kann nicht geladen werden“ | Mit `powershell -ExecutionPolicy Bypass -File …` starten |
| „Ollama ist nicht erreichbar“ | `brew services start ollama` (oder `ollama serve`), dann `ollama pull qwen2.5:7b` |
| Modell antwortet ohne Werkzeuge | ein Tool-fähiges Modell wählen (`qwen2.5`, `qwen3`, `llama3.1`, `llama3.2`) |
| „API-Schlüssel fehlt“ | `javit schluessel ANTHROPIC_API_KEY` (bzw. OPENAI/GEMINI), Server neu starten nicht nötig |
| „Javit“ reagiert nicht | Mikrofonrecht prüfen; Einstellungen → Stimme → Empfindlichkeit senken; eigene Schreibvarianten (`weckwort_varianten`); `python -m jarvis.stimme --geraete` |
| „Vosk-Modell … fehlt“ | Internetverbindung beim ersten Einschalten oder Modell von Hand entpacken (siehe oben); `pip install vosk` (Teil von `jarvis[stimme]`) |
| Weckwort löst zu oft aus | Empfindlichkeit erhöhen (z. B. 0,7–0,9) oder ein eigenes openWakeWord-Modell trainieren |
| Musik/Kalender verweigert | Datenschutz & Sicherheit → Automation: Terminal/Python erlauben |
| Integration „fehler“ | Status in Integrationen ansehen, Protokoll `~/.jarvis/logs/mcp-<id>.log`, „Neu verbinden“ |
| Port 8765 belegt | `javit start --port 8766` |
| Oberfläche fehlt („nicht gebaut“) | `cd oberflaeche && npm ci && npm run build` |

## Entwicklung und Tests

```bash
# Kern
cd kern && python3 -m pip install -e '.[stimme,dev]'
python3 -m pytest -q                      # Unit- und Ende-zu-Ende-Tests (offline)

# Oberfläche
cd oberflaeche && npm ci
npm run dev                               # Vite auf :5173, Proxy zum Kern auf :8765
npm run typecheck && npm test && npm run build

# Browser-Durchlauf (Playwright, Screenshots nach /tmp/jarvis-e2e)
cd kern && python3 -m tests.e2e.browser_durchlauf
```

Die Ende-zu-Ende-Tests (`kern/tests/e2e/`) starten einen echten Server mit einem
deterministischen, OpenAI-kompatiblen Fake-LLM (`openai/fake`) und binden den projekteigenen
Mini-MCP-Server als Integration ein. Hinweise für Beiträge mit Claude: [CLAUDE.md](CLAUDE.md);
Projektstand: [docs/STAND.md](docs/STAND.md).

## Aufbau

```
jarvis/
├── kern/                     Python-Paket „jarvis“ (FastAPI, Agent, LiteLLM, Werkzeuge, MCP-Hub, CLI)
│   ├── jarvis/plattform/     Plattform-Schicht (macOS, Windows, Linux)
│   ├── jarvis/stimme/        Weckwort (Vosk/openWakeWord), Aufnahme, Spracherkennung, Sprachausgabe
│   └── tests/                pytest (inkl. e2e/ mit Fake-LLM und Browser-Durchlauf)
├── oberflaeche/              React + TypeScript + Vite (wird unter / ausgeliefert)
├── integrationen/katalog/    Integrationskatalog (eine YAML-Datei je App)
├── scripts/                  install.sh/autostart.sh/start.command (macOS), install-linux.sh/autostart-linux.sh,
│                             weckwort-trainieren.md + weckwort_trainieren.py (eigenes Weckwort-Modell),
│                             install-windows.ps1/autostart-windows.ps1/start-windows.cmd
└── docs/                     ARCHITEKTUR.md, VERTRAEGE.md (bindende Schnittstellen), STAND.md
```

Architektur und Schnittstellen: [docs/ARCHITEKTUR.md](docs/ARCHITEKTUR.md),
[docs/VERTRAEGE.md](docs/VERTRAEGE.md), Details zum Kern: [kern/README.md](kern/README.md).
