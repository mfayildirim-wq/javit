#!/usr/bin/env bash
# Javit (Projekt „jarvis“) – Installation auf macOS in einem Schritt:
#     cd ~/Documents/jarvis && ./scripts/install.sh
#
# Installiert (falls nötig) per Homebrew: python@3.12, node, ollama; lädt die lokalen Modelle,
# legt ~/.jarvis/venv an, installiert den Kern (mit Sprachmodul), baut die Oberfläche und
# legt die Befehle `javit` und `jarvis` (gleichwertig) in ~/.local/bin ab. Mehrfaches Ausführen ist unbedenklich.
#
# Optionale Umgebungsvariablen:
#   JARVIS_OHNE_MODELLE=1   keine Ollama-Modelle laden (z. B. wenn nur Cloud-Modelle genutzt werden)
#   JARVIS_MODELL=…         anderes lokales Standardmodell (Standard: qwen2.5:7b)
#   JARVIS_KEIN_PATH=1      ~/.zshrc nicht anpassen
# Deutsche Anführungszeichen („…“) und wörtliche $-Ausdrücke in einfachen Anführungszeichen sind gewollt:
# shellcheck disable=SC1111,SC2016
set -Eeuo pipefail

PROJEKT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JARVIS_DATEN="${JARVIS_HOME:-$HOME/.jarvis}"
VENV="$JARVIS_DATEN/venv"
BIN_DIR="$HOME/.local/bin"
LOKALES_MODELL="${JARVIS_MODELL:-qwen2.5:7b}"
EINBETTUNG="nomic-embed-text"

fett() { printf '\033[1m%s\033[0m\n' "$*"; }
schritt() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
hinweis() { printf '    %s\n' "$*"; }
warnung() { printf '\033[1;33mWarnung:\033[0m %s\n' "$*" >&2; }
abbruch() { printf '\033[1;31mFehler:\033[0m %s\n' "$*" >&2; exit 1; }

trap 'abbruch "Installation in Zeile $LINENO abgebrochen. Einfach erneut ausführen – bereits Erledigtes wird übersprungen."' ERR

# ---------------------------------------------------------------- Voraussetzungen
if [[ "$(uname -s)" == "Linux" ]]; then
  echo "Linux erkannt – es wird der Linux-Installer gestartet: scripts/install-linux.sh"
  trap - ERR
  exec "$PROJEKT/scripts/install-linux.sh" "$@"
fi
[[ "$(uname -s)" == "Darwin" ]] || abbruch "Dieses Skript ist für macOS gedacht (gefunden: $(uname -s))."
[[ -f "$PROJEKT/kern/pyproject.toml" && -f "$PROJEKT/oberflaeche/package.json" ]] \
  || abbruch "Projektordner unvollständig: $PROJEKT"

fett "Javit wird installiert (Projekt: $PROJEKT)"
mkdir -p "$JARVIS_DATEN"

schritt "Homebrew prüfen"
BREW=""
for kandidat in "$(command -v brew || true)" /opt/homebrew/bin/brew /usr/local/bin/brew; do
  if [[ -n "$kandidat" && -x "$kandidat" ]]; then BREW="$kandidat"; break; fi
done
if [[ -z "$BREW" ]]; then
  echo
  fett "Homebrew fehlt. Bitte zuerst mit dem offiziellen Befehl installieren (siehe https://brew.sh):"
  echo
  echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  echo
  echo "Danach dieses Skript erneut starten: $PROJEKT/scripts/install.sh"
  trap - ERR
  exit 1
fi
eval "$("$BREW" shellenv)"
hinweis "Homebrew: $BREW"

brew_paket() {  # brew_paket <formel> [befehl]
  local formel="$1" befehl="${2:-}"
  if brew list --versions "$formel" >/dev/null 2>&1; then
    hinweis "$formel ist bereits installiert."
  elif [[ -n "$befehl" ]] && command -v "$befehl" >/dev/null 2>&1; then
    hinweis "$befehl ist bereits vorhanden ($(command -v "$befehl"))."
  else
    hinweis "Installiere $formel …"
    brew install "$formel"
  fi
}

schritt "Python 3.12, Node.js und Ollama"
brew_paket python@3.12
brew_paket node node
brew_paket ollama ollama
PYTHON="$(brew --prefix python@3.12)/bin/python3.12"
[[ -x "$PYTHON" ]] || abbruch "python3.12 nicht gefunden unter $PYTHON"

# ---------------------------------------------------------------- Ollama + Modelle
ollama_laeuft() { curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; }

if [[ "${JARVIS_OHNE_MODELLE:-0}" != "1" ]]; then
  schritt "Ollama starten und lokale Modelle laden"
  if ! ollama_laeuft; then
    if brew list --versions ollama >/dev/null 2>&1; then
      brew services start ollama >/dev/null 2>&1 || true
    fi
    if ! ollama_laeuft; then
      # z. B. Ollama.app installiert, aber nicht gestartet
      (nohup ollama serve >"$JARVIS_DATEN/ollama.log" 2>&1 &) || true
    fi
    for _ in $(seq 1 30); do ollama_laeuft && break; sleep 1; done
  fi
  if ollama_laeuft; then
    hinweis "Das Sprachmodell $LOKALES_MODELL ist ca. 4–5 GB groß – der erste Download kann einige Minuten dauern."
    ollama pull "$LOKALES_MODELL"
    hinweis "Einbettungsmodell $EINBETTUNG (ca. 270 MB) für das Gedächtnis …"
    ollama pull "$EINBETTUNG"
  else
    warnung "Ollama antwortet nicht auf http://127.0.0.1:11434. Später manuell: ollama serve && ollama pull $LOKALES_MODELL"
  fi
else
  hinweis "JARVIS_OHNE_MODELLE=1 – lokale Modelle werden übersprungen."
fi

# ---------------------------------------------------------------- Python-Umgebung
schritt "Python-Umgebung in $VENV"
mkdir -p "$JARVIS_DATEN"
if [[ -x "$VENV/bin/python" ]] && ! "$VENV/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  warnung "Vorhandene Umgebung ist zu alt – wird neu angelegt."
  rm -rf "$VENV"
fi
# Störende Nutzer-Einstellungen (z. B. pip.conf mit "user = true" oder PYTHONPATH) lassen
# ensurepip scheitern – für die Einrichtung ausblenden.
unset PYTHONPATH PYTHONHOME PIP_USER PIP_TARGET PIP_PREFIX PIP_REQUIRE_VIRTUALENV || true
export PIP_CONFIG_FILE=/dev/null

venv_ok() { [[ -x "$VENV/bin/python" ]] && "$VENV/bin/python" -m pip --version >/dev/null 2>&1; }

if ! venv_ok; then
  rm -rf "$VENV"
  VENV_LOG="$JARVIS_DATEN/venv-fehler.log"
  if ! "$PYTHON" -m venv "$VENV" >"$VENV_LOG" 2>&1 || ! venv_ok; then
    warnung "Python konnte pip nicht selbst einrichten (Details: $VENV_LOG) – nutze stattdessen uv."
    rm -rf "$VENV"
    command -v uv >/dev/null 2>&1 || brew install uv
    if ! uv venv --seed --python "$PYTHON" "$VENV" 2>>"$VENV_LOG"; then
      warnung "Homebrew-Python ist defekt – lade ein eigenständiges Python 3.12 über uv."
      rm -rf "$VENV"
      uv venv --seed --python 3.12 --python-preference only-managed "$VENV" 2>>"$VENV_LOG" \
        || abbruch "Python-Umgebung ließ sich nicht anlegen. Bitte die Ausgabe von
    sw_vers; ls -l /System/Library/CoreServices/SystemVersion.plist; $PYTHON -c 'import platform; print(platform.mac_ver())'
an Claude schicken (Details: $VENV_LOG)."
    fi
  fi
fi
venv_ok || abbruch "pip fehlt weiterhin in $VENV. Bitte die Datei $JARVIS_DATEN/venv-fehler.log an Claude schicken."
"$VENV/bin/python" -m pip install --quiet --upgrade pip
hinweis "Installiere den Kern mit Sprachmodul (das dauert beim ersten Mal etwas) …"
"$VENV/bin/python" -m pip install --quiet -e "$PROJEKT/kern[stimme]"

# ---------------------------------------------------------------- Oberfläche
schritt "Oberfläche bauen"
(
  cd "$PROJEKT/oberflaeche"
  npm ci --no-audit --no-fund --loglevel=error
  npm run build --silent
)
[[ -f "$PROJEKT/oberflaeche/dist/index.html" ]] || abbruch "Oberfläche wurde nicht gebaut."

# ---------------------------------------------------------------- Befehle `javit` und `jarvis`
schritt "Befehle „javit“ und „jarvis“ einrichten"
mkdir -p "$BIN_DIR"
for BEFEHL in javit jarvis; do
  WRAPPER="$BIN_DIR/$BEFEHL"
  cat >"$WRAPPER" <<WRAPPER_ENDE
#!/usr/bin/env bash
# Von scripts/install.sh erzeugt – startet Javit aus $VENV
export PATH="/opt/homebrew/bin:/usr/local/bin:\$PATH"
exec "$VENV/bin/$BEFEHL" "\$@"
WRAPPER_ENDE
  chmod +x "$WRAPPER"
  hinweis "$WRAPPER → $VENV/bin/$BEFEHL"
done

PATH_HINWEIS=""
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    ZSHRC="$HOME/.zshrc"
    MARKE="# jarvis: ~/.local/bin im PATH"
    if [[ "${JARVIS_KEIN_PATH:-0}" != "1" ]]; then
      if ! grep -qF "$MARKE" "$ZSHRC" 2>/dev/null; then
        printf '\n%s\nexport PATH="$HOME/.local/bin:$PATH"\n' "$MARKE" >>"$ZSHRC"
        hinweis "$BIN_DIR wurde in $ZSHRC zum PATH hinzugefügt."
      fi
      PATH_HINWEIS="Öffnen Sie ein neues Terminal-Fenster (oder: source ~/.zshrc), damit „javit“ gefunden wird."
    else
      PATH_HINWEIS="Bitte ~/.local/bin zum PATH hinzufügen: echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc"
    fi
    ;;
esac

# ---------------------------------------------------------------- Weckwort-Modelle
# Vosk-Modell für das freie Weckwort „Javit“ (vosk-model-small-de-0.15, ~45 MB, nach
# ~/.jarvis/modelle/vosk) und zusätzlich openWakeWord „Hey Jarvis“
schritt "Weckwort-Modelle („Javit“ über Vosk, „Hey Jarvis“ über openWakeWord) vorab laden"
if "$VENV/bin/python" -m jarvis.stimme --modelle-laden --alle; then
  hinweis "Weckwort-Modelle bereit."
else
  warnung "Weckwort-Modelle konnten nicht vollständig geladen werden (wird beim ersten Einschalten des Mikrofons erneut versucht)."
fi

chmod +x "$PROJEKT/scripts/"*.sh "$PROJEKT/scripts/start.command" 2>/dev/null || true
trap - ERR

# ---------------------------------------------------------------- Abschluss
cat <<ANLEITUNG

$(fett "Fertig! Javit ist installiert.")

  ${PATH_HINWEIS:+$PATH_HINWEIS
}
  Starten:            javit start           (öffnet http://127.0.0.1:8765 im Browser;
                                             „jarvis start“ funktioniert genauso)
                      oder Doppelklick auf  scripts/start.command
  Automatisch starten: ./scripts/autostart.sh an     (wieder aus: ./scripts/autostart.sh aus)

  Erste Schritte
  1. Mikrofon: in der Oberfläche auf das Mikrofon klicken und „Javit“ sagen.
     macOS fragt beim ersten Mal nach dem Mikrofonzugriff – bitte erlauben
     (Systemeinstellungen → Datenschutz & Sicherheit → Mikrofon → Terminal bzw. Ihr Terminalprogramm).
  2. Automation: Für Musik, Kalender, Erinnerungen, Notizen und Finder fragt macOS beim ersten
     Zugriff nach „Automation“-Rechten – bitte erlauben
     (Systemeinstellungen → Datenschutz & Sicherheit → Automation).
  3. Modell wechseln:  javit modell                          (zeigt alle Modelle)
                       javit modell anthropic/claude-sonnet-5-5
                       javit schluessel ANTHROPIC_API_KEY    (Schlüssel verdeckt eingeben)
     Lokal bleibt alles offline mit ollama/$LOKALES_MODELL.
  4. Apps integrieren: javit katalog                         (verfügbare Integrationen)
                       javit add spotify                     (fragt nötige Schlüssel ab)
                       oder einfach sagen: „Javit, integriere Spotify.“
  5. Name/Weckwort ändern: Oberfläche → Einstellungen (Name des Assistenten, Stimme → Weckwort).

  Daten, Einstellungen und Protokolle liegen in $JARVIS_DATEN.
ANLEITUNG
