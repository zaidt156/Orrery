#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

APP="./Orrery.app"
BIN="$APP/Contents/MacOS/Orrery"

if [[ ! -d "$APP" || ! -x "$BIN" ]]; then
  echo "Missing Orrery.app or its executable. Extract the full Orrery-macOS.zip package and try again."
  read -r -p "Press return to close..."
  exit 1
fi

if [[ ! -f ".env" ]]; then
  echo "Orrery has not been configured in this extracted folder yet."
  echo "Opening setup..."
  echo
  exec ./setup-orrery.command
fi

"$BIN" --packaging-probe
"$BIN"
