#!/usr/bin/env bash
# Javit beim Anmelden automatisch starten (Linux, systemd-Benutzerdienst):
#     ./scripts/autostart-linux.sh an      # einrichten und sofort starten
#     ./scripts/autostart-linux.sh aus     # entfernen und stoppen
#     ./scripts/autostart-linux.sh status
# Deutsche Anführungszeichen („…“) sind gewollt:
# shellcheck disable=SC1111
set -euo pipefail

DIENST="jarvis.service"
UNIT_ORDNER="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_ORDNER/$DIENST"
JARVIS_DATEN="${JARVIS_HOME:-$HOME/.jarvis}"
JARVIS_BIN="$JARVIS_DATEN/venv/bin/jarvis"
LOGS="$JARVIS_DATEN/logs"

hilfe() { echo "Verwendung: $0 an|aus|status"; }

command -v systemctl >/dev/null 2>&1 || {
  echo "systemctl fehlt – diese Distribution nutzt kein systemd. Alternative: Javit über die Autostart-Einstellungen"
  echo "der Desktop-Umgebung mit dem Befehl „$JARVIS_BIN start --kein-browser“ starten."
  exit 1
}

# Werte für die Unit-Datei: % → %% (systemd-Platzhalter), in "…" zusätzlich \ und " maskiert –
# Benutzerordner mit Leerzeichen funktionieren so (geprüft mit systemd-analyze verify).
unit_wert() { printf '%s' "${1//%/%%}"; }
unit_quote() { local w; w="$(unit_wert "$1")"; w="${w//\\/\\\\}"; printf '"%s"' "${w//\"/\\\"}"; }

case "${1:-}" in
  an)
    [[ -x "$JARVIS_BIN" ]] || { echo "Javit ist nicht installiert ($JARVIS_BIN fehlt). Bitte zuerst ./scripts/install-linux.sh ausführen." >&2; exit 1; }
    mkdir -p "$UNIT_ORDNER" "$LOGS"
    cat >"$UNIT" <<UNIT_ENDE
[Unit]
Description=Javit – persönlicher KI-Assistent (http://127.0.0.1:8765)
After=graphical-session.target pipewire.service pulseaudio.service
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=$(unit_quote "$JARVIS_BIN") start --kein-browser
WorkingDirectory=%h
Environment=$(unit_quote "JARVIS_HOME=$JARVIS_DATEN")
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=LANG=de_DE.UTF-8
Restart=on-failure
RestartSec=10
StandardOutput=append:$(unit_wert "$LOGS/jarvis.log")
StandardError=append:$(unit_wert "$LOGS/jarvis.log")

[Install]
WantedBy=graphical-session.target
UNIT_ENDE
    # Sitzungsvariablen (DISPLAY, WAYLAND_DISPLAY, DBUS …) an den Benutzerdienst weitergeben,
    # damit Mitteilungen, Zwischenablage und Musiksteuerung funktionieren
    systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XDG_SESSION_TYPE XDG_CURRENT_DESKTOP \
      DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR 2>/dev/null || true
    systemctl --user daemon-reload
    systemctl --user enable "$DIENST" >/dev/null
    systemctl --user restart "$DIENST"
    echo "Autostart eingerichtet: Javit startet ab jetzt bei jeder Anmeldung (http://127.0.0.1:8765)."
    echo "Protokoll: $LOGS/jarvis.log   ·   Status: systemctl --user status $DIENST"
    ;;
  aus)
    systemctl --user disable --now "$DIENST" >/dev/null 2>&1 || true
    rm -f "$UNIT"
    systemctl --user daemon-reload 2>/dev/null || true
    echo "Autostart entfernt; Javit wurde gestoppt."
    ;;
  status)
    if systemctl --user is-enabled "$DIENST" >/dev/null 2>&1; then
      zustand="$(systemctl --user is-active "$DIENST" 2>/dev/null || true)"
      echo "Autostart ist aktiv ($UNIT), Dienst: ${zustand:-unbekannt}."
    else
      echo "Autostart ist aus."
    fi
    ;;
  *)
    hilfe
    exit 2
    ;;
esac
