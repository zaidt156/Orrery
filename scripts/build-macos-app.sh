#!/usr/bin/env bash
set -euo pipefail

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

remove_in_repo() {
  local relative="$1"
  local target="$REPO_ROOT/$relative"
  if [[ ! -e "$target" ]]; then
    return
  fi
  local resolved
  resolved="$(cd "$(dirname "$target")" && pwd -P)/$(basename "$target")"
  case "$resolved" in
    "$REPO_ROOT"/*) rm -rf "$resolved" ;;
    *) echo "Refusing to remove path outside repository: $resolved" >&2; exit 1 ;;
  esac
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
    echo "macOS release builds require Python $REQUIRED_PYTHON_MINOR.x. Found $version." >&2
    exit 1
  fi
}

build_icon() {
  local source_png="assets/desktop/orrery.png"
  local iconset="build/orrery.iconset"
  local icon_file="build/orrery.icns"
  if ! command -v sips >/dev/null 2>&1 || ! command -v iconutil >/dev/null 2>&1; then
    echo ""
    return
  fi
  mkdir -p "$iconset"
  sips -z 16 16 "$source_png" --out "$iconset/icon_16x16.png" >/dev/null
  sips -z 32 32 "$source_png" --out "$iconset/icon_16x16@2x.png" >/dev/null
  sips -z 32 32 "$source_png" --out "$iconset/icon_32x32.png" >/dev/null
  sips -z 64 64 "$source_png" --out "$iconset/icon_32x32@2x.png" >/dev/null
  sips -z 128 128 "$source_png" --out "$iconset/icon_128x128.png" >/dev/null
  sips -z 256 256 "$source_png" --out "$iconset/icon_128x128@2x.png" >/dev/null
  sips -z 256 256 "$source_png" --out "$iconset/icon_256x256.png" >/dev/null
  sips -z 512 512 "$source_png" --out "$iconset/icon_256x256@2x.png" >/dev/null
  sips -z 512 512 "$source_png" --out "$iconset/icon_512x512.png" >/dev/null
  sips -z 1024 1024 "$source_png" --out "$iconset/icon_512x512@2x.png" >/dev/null
  iconutil -c icns "$iconset" -o "$icon_file"
  echo "$icon_file"
}

echo "Cleaning old build output..."
remove_in_repo "build"
remove_in_repo "dist"
remove_in_repo "release"

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
run "$PY" -m pip install -r requirements.txt
run "$PY" -m pip install pyinstaller

ICON_FILE="$(build_icon)"
PYINSTALLER_ARGS=(
  --noconfirm
  --clean
  --windowed
  --onedir
  --name Orrery
  --add-data "assets:assets"
  --add-data "ui/dist:ui/dist"
  --add-data "skills:skills"
  --add-data "sandbox:sandbox"
  --add-data "backend/providers/model_manifest.json:backend/providers"
  --collect-all litellm
  --collect-all tiktoken
  --collect-submodules tiktoken_ext
  --collect-all fastembed
  --collect-all webview
  --collect-data procrastinate
  --copy-metadata procrastinate
  --copy-metadata pywebview
  --collect-submodules keyring.backends
)
if [[ -n "$ICON_FILE" ]]; then
  PYINSTALLER_ARGS+=(--icon "$ICON_FILE")
fi

echo "Building PyInstaller macOS app..."
run "$PY" -m PyInstaller "${PYINSTALLER_ARGS[@]}" app.py

DIST_APP="dist/Orrery.app"
DIST_BIN="$DIST_APP/Contents/MacOS/Orrery"
RELEASE_ROOT="release/Orrery-macOS"

echo "Validating PyInstaller output..."
assert_exists "$DIST_APP" "PyInstaller app bundle was not created"
assert_exists "$DIST_BIN" "PyInstaller app executable was not created"
assert_exists "$DIST_APP/Contents/Info.plist" "PyInstaller Info.plist is missing"
run "$DIST_BIN" --packaging-probe

echo "Creating release folder..."
mkdir -p "$RELEASE_ROOT/sandbox"
cp -R "$DIST_APP" "$RELEASE_ROOT/Orrery.app"
cp docker-compose.yml "$RELEASE_ROOT/docker-compose.yml"
cp .env.example "$RELEASE_ROOT/.env.example"
cp sandbox/Dockerfile "$RELEASE_ROOT/sandbox/Dockerfile"
cp scripts/macos/setup-orrery.command "$RELEASE_ROOT/setup-orrery.command"
cp scripts/macos/run-orrery.command "$RELEASE_ROOT/run-orrery.command"
cp scripts/macos/README-MACOS.txt "$RELEASE_ROOT/README-MACOS.txt"
chmod +x "$RELEASE_ROOT/setup-orrery.command" "$RELEASE_ROOT/run-orrery.command"

echo "Validating release folder..."
assert_exists "$RELEASE_ROOT/Orrery.app" "Release app bundle is missing"
assert_exists "$RELEASE_ROOT/Orrery.app/Contents/MacOS/Orrery" "Release app executable is missing"
assert_exists "$RELEASE_ROOT/docker-compose.yml" "Release docker-compose.yml is missing"
assert_exists "$RELEASE_ROOT/.env.example" "Release .env.example is missing"
assert_exists "$RELEASE_ROOT/sandbox/Dockerfile" "Release sandbox Dockerfile is missing"
assert_exists "$RELEASE_ROOT/setup-orrery.command" "Release setup launcher is missing"
assert_exists "$RELEASE_ROOT/run-orrery.command" "Release launcher is missing"
assert_exists "$RELEASE_ROOT/README-MACOS.txt" "Release notes are missing"
run "$RELEASE_ROOT/Orrery.app/Contents/MacOS/Orrery" --packaging-probe

echo "Creating release zip..."
mkdir -p release
ditto -c -k --sequesterRsrc --keepParent "$RELEASE_ROOT" "release/Orrery-macOS.zip"
assert_exists "release/Orrery-macOS.zip" "Release zip was not created"

echo ""
echo "Built release/Orrery-macOS.zip"
echo "Publish this zip as the macOS release asset after CI verifies it."
