#!/usr/bin/env bash
# Javit beim Anmelden automatisch starten (launchd):
#     ./scripts/autostart.sh an     # einrichten und sofort starten
#     ./scripts/autostart.sh aus    # entfernen und stoppen
#     ./scripts/autostart.sh status
set -euo pipefail

LABEL="de.jarvis.agent"  # bleibt (Kompatibilität mit bestehendem Autostart)
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
JARVIS_DATEN="${JARVIS_HOME:-$HOME/.jarvis}"
JARVIS_BIN="$JARVIS_DATEN/venv/bin/jarvis"
LOGS="$JARVIS_DATEN/logs"
DOMAENE="gui/$(id -u)"

hilfe() { echo "Verwendung: $0 an|aus|status"; }

entladen() {
  launchctl bootout "$DOMAENE/$LABEL" >/dev/null 2>&1 \
    || launchctl unload "$PLIST" >/dev/null 2>&1 \
    || true
}

case "${1:-}" in
  an)
    [[ -x "$JARVIS_BIN" ]] || { echo "Javit ist nicht installiert ($JARVIS_BIN fehlt). Bitte zuerst ./scripts/install.sh ausführen." >&2; exit 1; }
    mkdir -p "$HOME/Library/LaunchAgents" "$LOGS"
    cat >"$PLIST" <<PLIST_ENDE
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$JARVIS_BIN</string>
    <string>start</string>
    <string>--kein-browser</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin</string>
    <key>JARVIS_HOME</key>
    <string>$JARVIS_DATEN</string>
    <key>LANG</key>
    <string>de_DE.UTF-8</string>
  </dict>
  <key>WorkingDirectory</key>
  <string>$HOME</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>ProcessType</key>
  <string>Interactive</string>
  <key>StandardOutPath</key>
  <string>$LOGS/jarvis.log</string>
  <key>StandardErrorPath</key>
  <string>$LOGS/jarvis.log</string>
</dict>
</plist>
PLIST_ENDE
    plutil -lint "$PLIST" >/dev/null
    entladen
    launchctl bootstrap "$DOMAENE" "$PLIST" 2>/dev/null || launchctl load -w "$PLIST"
    echo "Autostart eingerichtet: Javit startet ab jetzt bei jeder Anmeldung (http://127.0.0.1:8765)."
    echo "Protokoll: $LOGS/jarvis.log"
    ;;
  aus)
    entladen
    rm -f "$PLIST"
    echo "Autostart entfernt; Javit wurde gestoppt."
    ;;
  status)
    if launchctl print "$DOMAENE/$LABEL" >/dev/null 2>&1; then
      echo "Autostart ist aktiv ($PLIST)."
    else
      echo "Autostart ist aus."
    fi
    ;;
  *)
    hilfe
    exit 2
    ;;
esac
