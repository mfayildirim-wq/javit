#!/usr/bin/env bash
# Javit (Projekt „jarvis“) – Installation unter Linux (Ubuntu/Debian, Fedora, Arch, openSUSE) in einem Schritt:
#     cd ~/jarvis && ./scripts/install-linux.sh
#
# Installiert per Paketverwaltung (apt/dnf/pacman/zypper, nur dafür sudo): Python 3 mit venv,
# Node.js/npm, PortAudio (Mikrofon), playerctl (Musik), libnotify (Mitteilungen), wl-clipboard/xclip
# (Zwischenablage), pulseaudio-utils (Lautstärke/Wiedergabe) und espeak-ng (Sprachausgabe-Fallback).
# Legt ~/.jarvis/venv an, installiert den Kern mit Sprachmodul (inkl. Piper), baut die Oberfläche,
# legt die Befehle `javit` und `jarvis` (gleichwertig) in ~/.local/bin und einen Startmenü-Eintrag
# „Javit“ an und lädt das Vosk-Modell für das Weckwort „Javit“.
# Mehrfaches Ausführen ist unbedenklich.
#
# Optionale Umgebungsvariablen:
#   JARVIS_OLLAMA=1         Ollama über das offizielle Installationsskript (ollama.com/install.sh) installieren
#   JARVIS_OHNE_MODELLE=1   keine Ollama-Modelle laden
#   JARVIS_MODELL=…         anderes lokales Standardmodell (Standard: qwen2.5:7b)
#   JARVIS_KEIN_PATH=1      Shell-Startdatei (~/.bashrc bzw. ~/.zshrc) nicht anpassen
#   JARVIS_OHNE_PAKETE=1    keine Systempakete installieren (kein sudo)
# Deutsche Anführungszeichen („…“) und wörtliche $-Ausdrücke in einfachen Anführungszeichen sind gewollt:
# shellcheck disable=SC1111,SC2016
set -Eeuo pipefail

PROJEKT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JARVIS_DATEN="${JARVIS_HOME:-$HOME/.jarvis}"
VENV="$JARVIS_DATEN/venv"
BIN_DIR="$HOME/.local/bin"
ANWENDUNGEN="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
LOKALES_MODELL="${JARVIS_MODELL:-qwen2.5:7b}"
EINBETTUNG="nomic-embed-text"
NODE_MINDEST="20.19"

fett() { printf '\033[1m%s\033[0m\n' "$*"; }
schritt() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
hinweis() { printf '    %s\n' "$*"; }
warnung() { printf '\033[1;33mWarnung:\033[0m %s\n' "$*" >&2; }
abbruch() { printf '\033[1;31mFehler:\033[0m %s\n' "$*" >&2; exit 1; }

trap 'abbruch "Installation in Zeile $LINENO abgebrochen. Einfach erneut ausführen – bereits Erledigtes wird übersprungen."' ERR

# ---------------------------------------------------------------- Voraussetzungen
[[ "$(uname -s)" == "Linux" ]] || abbruch "Dieses Skript ist für Linux gedacht (gefunden: $(uname -s)). macOS: ./scripts/install.sh"
[[ -f "$PROJEKT/kern/pyproject.toml" && -f "$PROJEKT/oberflaeche/package.json" ]] \
  || abbruch "Projektordner unvollständig: $PROJEKT"
[[ "$(id -u)" -ne 0 ]] || abbruch "Bitte nicht als root starten – das Skript fragt selbst nach sudo (nur für die Paketverwaltung)."

fett "Javit wird installiert (Projekt: $PROJEKT)"
mkdir -p "$JARVIS_DATEN"

# ---------------------------------------------------------------- Systempakete
paketverwaltung() {
  if command -v apt-get >/dev/null 2>&1; then echo apt
  elif command -v dnf >/dev/null 2>&1; then echo dnf
  elif command -v pacman >/dev/null 2>&1; then echo pacman
  elif command -v zypper >/dev/null 2>&1; then echo zypper
  else echo unbekannt
  fi
}
PV="$(paketverwaltung)"

als_root() {
  if [[ "$(id -u)" -eq 0 ]]; then "$@"
  elif command -v sudo >/dev/null 2>&1; then sudo "$@"
  else abbruch "sudo fehlt – bitte die Pakete manuell installieren: $*"
  fi
}

# Node.js nur über die Paketverwaltung, wenn noch keins vorhanden ist: ein Node.js von NodeSource
# bringt npm selbst mit und kollidiert mit dem Distributionspaket „npm“ (apt bricht sonst ab);
# ein Node.js aus nvm o. Ä. soll ohnehin nicht ersetzt werden.
NODE_PAKETE=()
if ! command -v node >/dev/null 2>&1; then
  case "$PV" in
    zypper) NODE_PAKETE=(nodejs-default npm-default) ;;
    *) NODE_PAKETE=(nodejs npm) ;;
  esac
fi

schritt "Systempakete (Paketverwaltung: $PV)"
if [[ "${JARVIS_OHNE_PAKETE:-0}" == "1" ]]; then
  hinweis "JARVIS_OHNE_PAKETE=1 – Systempakete werden übersprungen."
else
  case "$PV" in
    apt)
      PAKETE=(python3 python3-venv python3-pip "${NODE_PAKETE[@]}" libportaudio2 playerctl libnotify-bin
              wl-clipboard xclip pulseaudio-utils espeak-ng curl)
      hinweis "sudo apt-get install ${PAKETE[*]}"
      als_root apt-get update -qq || warnung "apt-get update meldete Fehler (z. B. eine defekte Paketquelle) – versuche trotzdem die Installation."
      als_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${PAKETE[@]}"
      ;;
    dnf)
      PAKETE=(python3 python3-pip "${NODE_PAKETE[@]}" portaudio playerctl libnotify wl-clipboard xclip
              pulseaudio-utils espeak-ng curl)
      hinweis "sudo dnf install ${PAKETE[*]}"
      als_root dnf install -y -q "${PAKETE[@]}"
      ;;
    pacman)
      PAKETE=(python python-pip "${NODE_PAKETE[@]}" portaudio playerctl libnotify wl-clipboard xclip libpulse
              espeak-ng curl)
      hinweis "sudo pacman -S --needed ${PAKETE[*]}"
      als_root pacman -S --needed --noconfirm "${PAKETE[@]}"
      ;;
    zypper)
      PAKETE=(python3 python3-pip "${NODE_PAKETE[@]}" portaudio playerctl libnotify-tools
              wl-clipboard xclip pulseaudio-utils espeak-ng curl)
      hinweis "sudo zypper install ${PAKETE[*]}"
      als_root zypper --non-interactive install "${PAKETE[@]}"
      ;;
    *)
      warnung "Keine unterstützte Paketverwaltung gefunden (apt, dnf, pacman, zypper)."
      hinweis "Bitte selbst installieren: Python ≥ 3.11 mit venv, Node.js ≥ $NODE_MINDEST mit npm, PortAudio,"
      hinweis "playerctl, libnotify, wl-clipboard oder xclip, pulseaudio-utils, espeak-ng."
      ;;
  esac
fi

# ---------------------------------------------------------------- Python
schritt "Python prüfen"
PYTHON=""
for kandidat in python3.13 python3.12 python3.11 python3; do
  if command -v "$kandidat" >/dev/null 2>&1 \
    && "$kandidat" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PYTHON="$(command -v "$kandidat")"
    break
  fi
done
if [[ -n "$PYTHON" ]]; then
  hinweis "Python: $PYTHON ($("$PYTHON" --version 2>&1))"
else
  warnung "Kein Python ≥ 3.11 gefunden – es wird ein eigenständiges Python 3.12 über uv geladen."
fi

# ---------------------------------------------------------------- Node.js
schritt "Node.js prüfen"
NODE_OK=0
if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
  NODE_VERSION="$(node -p 'process.versions.node' 2>/dev/null || echo 0.0.0)"
  if node -e '
    const [ma, mi] = process.versions.node.split(".").map(Number);
    process.exit(ma > 22 || (ma === 22 && mi >= 12) || (ma === 20 && mi >= 19) ? 0 : 1);
  ' 2>/dev/null; then
    NODE_OK=1
    hinweis "Node.js $NODE_VERSION"
  else
    warnung "Node.js $NODE_VERSION ist zu alt (benötigt: 20.19+ oder 22.12+)."
  fi
else
  warnung "Node.js/npm nicht gefunden."
fi
if [[ "$NODE_OK" != "1" ]]; then
  hinweis "Aktuelles Node.js installieren – z. B. über nvm (ohne sudo):"
  hinweis "  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash && nvm install 22"
  hinweis "oder über NodeSource (https://github.com/nodesource/distributions), danach dieses Skript erneut starten."
fi

# ---------------------------------------------------------------- Ollama (optional)
ollama_laeuft() { curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; }

schritt "Ollama (lokale Sprachmodelle)"
if ! command -v ollama >/dev/null 2>&1; then
  if [[ "${JARVIS_OLLAMA:-0}" == "1" ]]; then
    hinweis "Installiere Ollama über das offizielle Skript (https://ollama.com/install.sh) …"
    curl -fsSL https://ollama.com/install.sh | sh
  else
    hinweis "Ollama ist nicht installiert. Für lokale Modelle (offline) entweder dieses Skript mit"
    hinweis "  JARVIS_OLLAMA=1 ./scripts/install-linux.sh"
    hinweis "erneut starten oder selbst installieren: https://ollama.com/download/linux"
    hinweis "Ohne Ollama funktionieren Cloud-Modelle (javit schluessel ANTHROPIC_API_KEY …)."
  fi
fi
if command -v ollama >/dev/null 2>&1 && [[ "${JARVIS_OHNE_MODELLE:-0}" != "1" ]]; then
  if ! ollama_laeuft; then
    (nohup ollama serve >"$JARVIS_DATEN/ollama.log" 2>&1 &) || true
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
fi

# ---------------------------------------------------------------- Python-Umgebung
schritt "Python-Umgebung in $VENV"
if [[ -x "$VENV/bin/python" ]] && ! "$VENV/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  warnung "Vorhandene Umgebung ist zu alt – wird neu angelegt."
  rm -rf "$VENV"
fi
unset PYTHONPATH PYTHONHOME PIP_USER PIP_TARGET PIP_PREFIX PIP_REQUIRE_VIRTUALENV || true
export PIP_CONFIG_FILE=/dev/null

venv_ok() { [[ -x "$VENV/bin/python" ]] && "$VENV/bin/python" -m pip --version >/dev/null 2>&1; }

uv_bereitstellen() {
  if command -v uv >/dev/null 2>&1; then return 0; fi
  if [[ -x "$HOME/.local/bin/uv" ]]; then export PATH="$HOME/.local/bin:$PATH"; return 0; fi
  hinweis "Installiere uv (offizielles Installationsskript von astral.sh) nach ~/.local/bin …"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
  export PATH="$HOME/.local/bin:$PATH"
}

if ! venv_ok; then
  rm -rf "$VENV"
  VENV_LOG="$JARVIS_DATEN/venv-fehler.log"
  if [[ -z "$PYTHON" ]] || ! "$PYTHON" -m venv "$VENV" >"$VENV_LOG" 2>&1 || ! venv_ok; then
    warnung "Python konnte die Umgebung nicht selbst einrichten (Details: $VENV_LOG) – nutze stattdessen uv."
    rm -rf "$VENV"
    uv_bereitstellen
    if [[ -z "$PYTHON" ]] || ! uv venv --seed --python "$PYTHON" "$VENV" 2>>"$VENV_LOG"; then
      rm -rf "$VENV"
      uv venv --seed --python 3.12 --python-preference only-managed "$VENV" 2>>"$VENV_LOG" \
        || abbruch "Python-Umgebung ließ sich nicht anlegen (Details: $VENV_LOG)."
    fi
  fi
fi
venv_ok || abbruch "pip fehlt weiterhin in $VENV. Details: $JARVIS_DATEN/venv-fehler.log"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
hinweis "Installiere den Kern mit Sprachmodul (inkl. Piper-Sprachausgabe; dauert beim ersten Mal etwas) …"
if ! "$VENV/bin/python" -m pip install --quiet -e "$PROJEKT/kern[stimme,gedaechtnis]"; then
  warnung "Installation mit Sprachmodul fehlgeschlagen – installiere den Kern ohne Sprachmodul."
  "$VENV/bin/python" -m pip install --quiet -e "$PROJEKT/kern"
fi

# ---------------------------------------------------------------- Oberfläche
schritt "Oberfläche bauen"
if [[ "$NODE_OK" == "1" ]]; then
  (
    cd "$PROJEKT/oberflaeche"
    npm ci --no-audit --no-fund --loglevel=error
    npm run build --silent
  )
  [[ -f "$PROJEKT/oberflaeche/dist/index.html" ]] || abbruch "Oberfläche wurde nicht gebaut."
elif [[ -f "$PROJEKT/oberflaeche/dist/index.html" ]]; then
  warnung "Node.js fehlt/ist zu alt – die vorhandene, bereits gebaute Oberfläche wird verwendet."
else
  warnung "Oberfläche nicht gebaut (Node.js fehlt/ist zu alt). Javit läuft trotzdem im Terminal (javit sag …)."
fi

# ---------------------------------------------------------------- Befehle `javit` und `jarvis`
schritt "Befehle „javit“ und „jarvis“ und Startmenü-Eintrag einrichten"
mkdir -p "$BIN_DIR" "$ANWENDUNGEN"
for BEFEHL in javit jarvis; do
  cat >"$BIN_DIR/$BEFEHL" <<WRAPPER_ENDE
#!/usr/bin/env bash
# Von scripts/install-linux.sh erzeugt – startet Javit aus $VENV
export PATH="\$HOME/.local/bin:/usr/local/bin:\$PATH"
exec "$VENV/bin/$BEFEHL" "\$@"
WRAPPER_ENDE
  chmod +x "$BIN_DIR/$BEFEHL"
  hinweis "$BIN_DIR/$BEFEHL → $VENV/bin/$BEFEHL"
done
WRAPPER="$BIN_DIR/javit"

# Exec-Wert nach der Desktop-Entry-Spezifikation: in "…" mit \\, \", \` und \$ maskiert, % als %%
# (sonst bricht ein Benutzerordner mit Leerzeichen den Start aus dem Startmenü)
desktop_argument() {
  local wert="$1"
  wert="${wert//\\/\\\\}"
  wert="${wert//\"/\\\"}"
  wert="${wert//\`/\\\`}"
  wert="${wert//\$/\\\$}"
  wert="${wert//%/%%}"
  printf '"%s"' "$wert"
}
DESKTOP_EXEC="$(desktop_argument "$WRAPPER") start"

# Dateiname jarvis.desktop bleibt (bestehende Verknüpfungen/Favoriten), angezeigt wird „Javit“
cat >"$ANWENDUNGEN/jarvis.desktop" <<DESKTOP_ENDE
[Desktop Entry]
Type=Application
Name=Javit
GenericName=KI-Assistent
Comment=Persönlicher KI-Assistent – startet den Server und öffnet die Oberfläche
Exec=$DESKTOP_EXEC
Icon=$PROJEKT/oberflaeche/public/favicon.svg
Terminal=true
Categories=Utility;
Keywords=KI;Assistent;Sprache;AI;Javit;Jarvis;
StartupNotify=false
DESKTOP_ENDE
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$ANWENDUNGEN" >/dev/null 2>&1 || true
hinweis "Startmenü-Eintrag: $ANWENDUNGEN/jarvis.desktop"

PATH_HINWEIS=""
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    case "${SHELL:-}" in
      */zsh) RC="$HOME/.zshrc" ;;
      *) RC="$HOME/.bashrc" ;;
    esac
    MARKE="# jarvis: ~/.local/bin im PATH"
    if [[ "${JARVIS_KEIN_PATH:-0}" != "1" ]]; then
      if ! grep -qF "$MARKE" "$RC" 2>/dev/null; then
        printf '\n%s\nexport PATH="$HOME/.local/bin:$PATH"\n' "$MARKE" >>"$RC"
        hinweis "$BIN_DIR wurde in $RC zum PATH hinzugefügt."
      fi
      PATH_HINWEIS="Öffnen Sie ein neues Terminal (oder: source $RC), damit „javit“ gefunden wird."
    else
      PATH_HINWEIS="Bitte ~/.local/bin zum PATH hinzufügen: echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc"
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

chmod +x "$PROJEKT/scripts/"*.sh 2>/dev/null || true
trap - ERR

# ---------------------------------------------------------------- Abschluss
SITZUNG="${XDG_SESSION_TYPE:-unbekannt}"
cat <<ANLEITUNG

$(fett "Fertig! Javit ist installiert.")

  ${PATH_HINWEIS:+$PATH_HINWEIS
}
  Starten:             javit start           (öffnet http://127.0.0.1:8765 im Browser;
                                             „jarvis start“ funktioniert genauso)
                       oder im Startmenü:    „Javit“
  Automatisch starten: ./scripts/autostart-linux.sh an   (wieder aus: ./scripts/autostart-linux.sh aus)

  Erste Schritte
  1. Mikrofon: in der Oberfläche auf das Mikrofon klicken und „Javit“ sagen. Der Ton läuft über
     PipeWire/PulseAudio – Eingabegerät in den Toneinstellungen bzw. mit pavucontrol wählen.
     Geräte anzeigen: $VENV/bin/python -m jarvis.stimme --geraete
  2. Sprachausgabe: Piper mit der Stimme „de_DE-thorsten-medium“ (wird beim ersten Sprechen
     nach ~/.jarvis/modelle/piper geladen, ca. 60 MB); Fallback espeak-ng.
  3. Sitzung: $SITZUNG. Unter Wayland funktionieren Fensterlisten nur eingeschränkt; Zwischenablage
     über wl-clipboard, Bildschirmfotos über gnome-screenshot/spectacle/grim.
  4. Modell wechseln:  javit modell                          (zeigt alle Modelle)
                       javit modell anthropic/claude-sonnet-5-5
                       javit schluessel ANTHROPIC_API_KEY    (landet im Schlüsselbund/Secret Service)
  5. Apps integrieren: javit katalog · javit add spotify · „Javit, integriere Notion.“
     Kalender, Erinnerungen und Notizen gibt es unter Linux über Integrationen
     (google-kalender, todoist, notion, obsidian).

  Daten, Einstellungen und Protokolle liegen in $JARVIS_DATEN.
ANLEITUNG
