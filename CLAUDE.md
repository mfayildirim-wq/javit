# Hinweise für Claude-Sitzungen

Projekt „jarvis“ (der Assistent heißt beim Nutzer **„Javit“**, Name einstellbar über `einstellungen.name`):
persönlicher KI-Assistent für macOS, Windows und Linux. **Alles auf Deutsch** – Code-Bezeichner,
Kommentare, Meldungen, Commits, Doku.

## Verbindliche Dokumente

* `docs/VERTRAEGE.md` – REST/WebSocket-Schnittstellen und Katalogformat sind **bindend**. Nur
  rückwärtskompatibel erweitern (optionale Felder) und dann Kern, Oberfläche und Doku gemeinsam ändern.
* `docs/ARCHITEKTUR.md` – Grundsätze (modellunabhängig, lokal zuerst, Freigaben für Kritisches).
* `docs/STAND.md` – was fertig, offen und nur am Mac testbar ist. Nach größeren Änderungen pflegen.
* `docs/PROTOKOLL.md` – chronologisches Entwicklungsprotokoll (Entscheidungen, Probleme, Reviews).
  **Nach jeder Arbeitssitzung einen datierten Eintrag unten anfügen.**

## Entwicklung auf dem Mac (Hauptarbeitsplatz ab 27.10.2026)

* Projekt: `~/Documents/jarvis` (Git-Repository). Python immer aus der venv: `~/.jarvis/venv/bin/python`
  (Homebrew-Python ist auf diesem Mac defekt – `platform.mac_ver()` leer; die venv nutzt ein von uv
  verwaltetes Python 3.12). Entwicklerpakete: `~/.jarvis/venv/bin/pip install -e "kern[stimme,dev]"`.
* Tests: `cd kern && ~/.jarvis/venv/bin/python -m pytest -q`; Oberfläche: `cd oberflaeche && npm run typecheck && npm test`.
* Live: `javit start` (Kern auf 127.0.0.1:8765), Oberfläche mit Live-Neuladen: `cd oberflaeche && npm run dev`.
* Auf dem Mac dürfen Installer und echte Integrationen ausgeführt werden – aber nur nach Rückfrage beim Nutzer.
* Die Container-Hinweise unten (Python 3.13, `/opt/pw-browsers`, „nicht ausführen“) gelten für Cloud-Sitzungen.

## Aufbau in Kürze

* `kern/jarvis/` – `server.py` (FastAPI, nur 127.0.0.1, Origin-/Host-Prüfung), `agent.py`
  (Schleife, Freigaben, Abbrechen), `llm.py` (**einziger** LiteLLM-Zugriff), `werkzeuge/`
  (Register + eingebaute Werkzeuge mit Risikostufe), `integrationen/` (Katalog, Manager, MCP-Hub,
  OpenAPI, REST, OAuth, Verzeichnisse = Registry-Suche), `geheimnisse.py` (Schlüsselbund/keyring/Fernet), `stimme/` (Weckwort, STT, TTS),
  `plattform/` (Erkennung `aktuelle_plattform()`, Systemaktionen für mac/windows/linux).
* Weckwort: `stimme/weckwort.py` (openWakeWord, `erzeuge_detektor()` nach `konfig.weckwort_engine()`),
  `stimme/weckwort_vosk.py` (freies Weckwort „Javit“: Grammatik aus Vokabular-Varianten + Kölner Phonetik).
* Werkzeuge: `werkzeuge/mac.py` (nur macOS, **nicht verändern** – Ausnahme: Standard-Mitteilungstitel =
  eingestellter Name), `werkzeuge/desktop.py`
  (gleiche Namen/Risiken für Windows/Linux, ruft `plattform.systemaktionen()`).
* `oberflaeche/` – React 18 + TS + Vite + zustand; Typen der Schnittstelle in `src/api/types.ts`.
* `integrationen/katalog/*.yaml` – eine App je Datei.
* `scripts/` – macOS: `install.sh` (idempotent; leitet unter Linux auf `install-linux.sh` um),
  `autostart.sh`, `start.command`; Linux: `install-linux.sh`, `autostart-linux.sh`; Windows:
  `install-windows.ps1`, `autostart-windows.ps1`, `start-windows.cmd`.

## Regeln

* Nutzersichtbare Texte nennen den Assistenten nie fest „Jarvis“, sondern nutzen den eingestellten
  Namen (`Einstellungen.name`, `konfig.aktueller_name()`, Oberfläche `useName()`); Werkzeug-/
  Katalogbeschreibungen neutral („der Assistent“). Interne Bezeichner (`jarvis`, `~/.jarvis`,
  `JARVIS_*`, Dienst-Kennungen `de.jarvis.agent`/`jarvis.service`/Aufgabe „Jarvis“) bleiben.
* Neue Werkzeuge: `@werkzeug(...)` mit ehrlicher Risikostufe. Alles, was Daten löscht/sendet/
  bezahlt/installiert, Code ausführt oder Persistenz schaffen kann, ist `kritisch`. Risiko kann je
  Aufruf über `risiko_fuer` verschärft werden (siehe `werkzeuge/dateien.py`).
* Geheimnisse nie in Logs, Events oder `integrationen.json` (dort nur `${NAME}`); Events über
  `geheimnisse.schwaerzen` leiten.
* Modellaufrufe nur über `LLMFassade`. Anbieter und Modell-Vorschläge stehen in `anbieter.py`
  (`EINGEBAUTE`; `llm.CLOUD_VORSCHLAEGE` wird daraus abgeleitet)
  (LiteLLM-Schreibweise) – vor Änderungen die aktuellen IDs bei den Anbietern prüfen.
* Keine fremden Pakete im Container ausführen (`npx -y …`, `uvx …`). Für MCP-Tests nur
  `kern/tests/mini_mcp_server.py`. Installer nur statisch prüfen (`bash -n`, `shellcheck`;
  `.ps1`/`.cmd` über `tests/test_installer.py`), nie ausführen.
* Plattformen: Die macOS-Version darf sich nicht ändern. Neue Systemaktionen in alle drei
  `plattform/*.py` einbauen. Windows: Skripte als fester Text per `-EncodedCommand`, Werte nur über
  `JARVIS_ARG_*`-Umgebungsvariablen oder Base64-stdin (nie in den Skripttext einsetzen), keine
  typografischen Anführungszeichen in PowerShell-Code. Linux: Argumentlisten, Werte hinter `--`,
  fehlende Hilfsprogramme mit `gemeinsam.fehlt_meldung()` (Installationsbefehl je Distribution).
* `.ps1` als UTF-8 mit BOM und CRLF speichern, `.cmd` nur ASCII + CRLF; PowerShell 5.1-kompatibel.

## Tests

```bash
cd kern && python3 -m pytest -q                       # inkl. tests/e2e (echter Server + Fake-LLM)
cd oberflaeche && npm run typecheck && npm test && npm run build
cd kern && PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python3 -m tests.e2e.browser_durchlauf  # Screenshots
shellcheck scripts/*.sh scripts/start.command
JARVIS_PWSH=/pfad/zu/pwsh python3 -m pytest -q tests/test_installer.py   # optional: echter PowerShell-Parser (nur Parsen)
```

* Kern-Tests laufen offline: `tests/conftest.py` (isoliertes `JARVIS_HOME`, `SkriptLLM` mit echten
  LiteLLM-Chunks), `tests/helfer.py` (`baue_jarvis`).
* Server-Tests mit `TestClient(app, base_url="http://127.0.0.1:8765")` und WebSocket-URL
  `ws://127.0.0.1:8765/ws` – die Host-Prüfung weist `testserver` ab.
* E2E: `tests/e2e/fake_llm.py` (deterministische Tool-Calls), `tests/e2e/umgebung.py` startet
  Fake-LLM + `python -m jarvis start` mit temporärem `JARVIS_HOME`.
* Im Container: Python 3.13 (`pip install --break-system-packages`), Node 22, Chromium unter
  `/opt/pw-browsers`. macOS-spezifisches (osascript, `say`, `security`, Mikrofon) und alles von
  Windows (PowerShell) wird gemockt. Plattform in Tests per `JARVIS_PLATTFORM=mac|windows|linux`
  setzen (`monkeypatch.setenv`). Linux-Tests laufen teils echt (Xvfb, xclip, pkill, espeak-ng …,
  per `apt install xvfb xclip libnotify-bin playerctl espeak-ng scrot imagemagick`); fehlen die Programme,
  werden diese Tests übersprungen. `conftest.py` setzt `JARVIS_KEIN_DOWNLOAD=1` (auch für das Vosk-Modell; `vosk`
  ist im Container nicht installiert – Tests fälschen das Modul, siehe `tests/stimme/test_weckwort_vosk.py`) und schaltet echte
  Desktop-Mitteilungen/Sprachausgaben aus Tests stumm (`jarvis.stille_aufrufe`).

Nach der Arbeit aufräumen: `__pycache__`, `.pytest_cache`, `.ruff_cache`, temporäre Dateien
(`node_modules` bleibt).
