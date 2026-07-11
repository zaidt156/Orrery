#!/usr/bin/env bash
set -euo pipefail

# Builds the installable macOS app: a PyInstaller backend-only bundle (OrreryBackend) wrapped by
# the Electron shell, packaged with electron-builder into a DMG (drag to Applications; in-app
# updates via electron-updater). Runs on macOS only — locally on a Mac or in the GitHub Action.
#
# Output: desktop/electron/dist/Orrery-<version>-mac-<arch>.dmg
#
# The plain .app zip (build-macos-app.sh) remains the no-Electron option.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

REQUIRED_PYTHON_MINOR="3.12"
VENV_DIR=".venv-macos"

run() {
  echo "+ $*"
  "$@"
}

assert_exists() {
  local path="$1"
  local message="${2:-Required path is missing}"
  if [[ ! -e "$path" ]]; then
    echo "$message: $path" >&2
    exit 1
  fi
}

python_cmd() {
  if command -v python3.12 >/dev/null 2>&1; then
    command -v python3.12
  else
    command -v python3
  fi
}

assert_python_version() {
  local py="$1"
  local version
  version="$("$py" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")"
  if [[ "$version" != "$REQUIRED_PYTHON_MINOR" ]]; then
    echo "macOS installer builds require Python $REQUIRED_PYTHON_MINOR.x. Found $version." >&2
    exit 1
  fi
}

echo "Building frontend..."
pushd ui >/dev/null
if [[ -d node_modules ]]; then
  run npm install
else
  run npm ci
fi
run npm run build
popd >/dev/null

PYTHON_BIN="$(python_cmd)"
assert_python_version "$PYTHON_BIN"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "Creating $VENV_DIR..."
  run "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
PY="$VENV_DIR/bin/python"
assert_python_version "$PY"

echo "Installing Python dependencies..."
run "$PY" -m pip install --upgrade pip
if [[ -f requirements.lock.txt ]]; then
  run "$PY" -m pip install -r requirements.lock.txt
else
  run "$PY" -m pip install -r requirements.txt
fi
run "$PY" -m pip install pyinstaller

echo "Building PyInstaller backend-only bundle (OrreryBackend)..."
rm -rf dist/OrreryBackend
PYINSTALLER_ARGS=(
  --noconfirm
  --clean
  --onedir
  --name OrreryBackend
  --add-data "assets:assets"
  --add-data "ui/dist:ui/dist"
  --add-data "skills:skills"
  --add-data "sandbox:sandbox"
  --add-data "backend/providers/model_manifest.json:backend/providers"
  --add-data "LIFE.md:."
  --collect-all litellm
  --collect-all tiktoken
  --collect-submodules tiktoken_ext
  --collect-all fastembed
  --collect-all pptx
  --collect-data procrastinate
  --copy-metadata procrastinate
  --copy-metadata pywebview
  --copy-metadata python-pptx
  --exclude-module webview.platforms.cocoa
  --exclude-module webview.platforms.qt
  --exclude-module webview.platforms.gtk
  --exclude-module webview.platforms.winforms
  --exclude-module webview.platforms.edgechromium
  --exclude-module webview.platforms.mshtml
  --exclude-module webview.platforms.android
  --exclude-module webview.platforms.cef
  --exclude-module PySide6
  --exclude-module qtpy
  --collect-submodules keyring.backends
)
run "$PY" -m PyInstaller "${PYINSTALLER_ARGS[@]}" app.py

assert_exists "dist/OrreryBackend/OrreryBackend" "Backend executable was not created"
assert_exists "dist/OrreryBackend/_internal/ui/dist" "Bundled frontend build is missing"
assert_exists "dist/OrreryBackend/_internal/procrastinate/sql/queries.sql" "Bundled Procrastinate SQL is missing"

echo "Running backend packaging probe..."
run "dist/OrreryBackend/OrreryBackend" --packaging-probe --backend-only

echo "Building Electron DMG..."
pushd "desktop/electron" >/dev/null
if [[ -d node_modules ]]; then
  run npm install
else
  run npm ci
fi
# No signing identity on CI/dev machines — build unsigned rather than failing.
CSC_IDENTITY_AUTO_DISCOVERY=false run npx electron-builder --mac dmg --publish never
popd >/dev/null

DMG="$(ls desktop/electron/dist/Orrery-*-mac-*.dmg 2>/dev/null | head -1 || true)"
if [[ -z "$DMG" ]]; then
  # electron-builder's artifactName ${os} is "mac"; fall back to any dmg it produced
  DMG="$(ls desktop/electron/dist/*.dmg 2>/dev/null | head -1 || true)"
fi
if [[ -z "$DMG" ]]; then
  echo "electron-builder did not produce a DMG in desktop/electron/dist" >&2
  exit 1
fi

echo ""
echo "Built installer: $DMG"
echo "Users open the DMG and drag Orrery to Applications."
