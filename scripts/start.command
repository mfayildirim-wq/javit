#!/usr/bin/env bash
# Doppelklick im Finder: startet Javit und öffnet die Oberfläche im Browser.
set -euo pipefail

JARVIS_DATEN="${JARVIS_HOME:-$HOME/.jarvis}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if [[ -x "$JARVIS_DATEN/venv/bin/jarvis" ]]; then
  JARVIS="$JARVIS_DATEN/venv/bin/jarvis"
elif command -v jarvis >/dev/null 2>&1; then
  JARVIS="$(command -v jarvis)"
else
  echo "Javit ist noch nicht installiert. Bitte im Terminal ausführen:"
  echo "  cd \"$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)\" && ./scripts/install.sh"
  read -r -p "Eingabetaste zum Schließen … " _
  exit 1
fi

echo "Javit startet … (dieses Fenster offen lassen; beenden mit Ctrl+C)"
exec "$JARVIS" start
