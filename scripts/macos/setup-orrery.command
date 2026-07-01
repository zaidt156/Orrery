#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

APP="./Orrery.app"
BIN="$APP/Contents/MacOS/Orrery"
DEFAULT_DB_URL="postgresql+psycopg://orrery:orrery_dev_password@127.0.0.1:5432/orrery"

check_package() {
  if [[ ! -d "$APP" || ! -x "$BIN" ]]; then
    echo "Missing Orrery.app or its executable. Extract the full Orrery-macOS.zip package and try again."
    read -r -p "Press return to close..."
    exit 1
  fi
}

ensure_env() {
  if [[ ! -f ".env" ]]; then
    if [[ -f ".env.example" ]]; then
      cp ".env.example" ".env"
    else
      printf "ORRERY_DEV=0\n" > ".env"
    fi
  fi
}

write_database_url() {
  local url="$1"
  {
    echo "# Orrery macOS package settings"
    echo "DATABASE_URL=$url"
    echo "ORRERY_DEV=0"
  } > ".env"
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo
    echo "Docker was not found."
    echo "Install/start Docker Desktop, or choose option 2 and use your own PostgreSQL server."
    read -r -p "Press return to continue..."
    return 1
  fi
  if ! docker info >/dev/null 2>&1; then
    echo
    echo "Docker Desktop is installed but not running."
    echo "Start Docker Desktop and run setup-orrery.command again."
    read -r -p "Press return to continue..."
    return 1
  fi
}

start_postgres() {
  echo
  echo "Starting included PostgreSQL database..."
  docker compose up -d

  echo "Checking PostgreSQL readiness..."
  local ready=0
  for _ in $(seq 1 45); do
    if docker exec orrery-postgres pg_isready -U orrery -d orrery >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 2
  done
  if [[ "$ready" != "1" ]]; then
    echo "PostgreSQL did not become ready in time."
    return 1
  fi
}

build_sandbox() {
  echo
  echo "Building file-generation sandbox image..."
  docker build -t orrery-sandbox:latest sandbox
}

start_orrery() {
  echo
  echo "Checking packaged desktop runtime..."
  "$BIN" --packaging-probe

  echo
  echo "Starting Orrery..."
  echo
  "$BIN"
}

check_package
ensure_env

while true; do
  clear
  cat <<'MENU'
Orrery macOS Setup
==================

Choose how this Mac should run Orrery:

  1. Use the included Docker PostgreSQL database, build sandbox, then start Orrery
  2. Use my own PostgreSQL database URL, then start Orrery
  3. Build or refresh the file-generation sandbox image only
  4. Start Orrery only
  5. Quit

MENU
  read -r -p "Select 1-5: " choice

  case "$choice" in
    1)
      write_database_url "$DEFAULT_DB_URL"
      require_docker && start_postgres && build_sandbox && start_orrery
      exit $?
      ;;
    2)
      echo
      echo "Paste your PostgreSQL URL."
      echo "Example:"
      echo "  postgresql+psycopg://user:password@host:5432/database"
      echo
      read -r -p "Database URL: " custom_db_url
      if [[ -z "$custom_db_url" ]]; then
        echo "No database URL entered."
        read -r -p "Press return to continue..."
        continue
      fi
      write_database_url "$custom_db_url"
      echo
      echo "Saved DATABASE_URL to .env for this extracted Orrery folder."
      read -r -p "Build the local file-generation sandbox now? [Y/n]: " build_sandbox_answer
      case "$build_sandbox_answer" in
        n|N) ;;
        *) require_docker && build_sandbox ;;
      esac
      start_orrery
      exit $?
      ;;
    3)
      require_docker && build_sandbox
      echo
      echo "Sandbox image is ready."
      read -r -p "Press return to continue..."
      ;;
    4)
      start_orrery
      exit $?
      ;;
    5)
      exit 0
      ;;
    *)
      echo "Choose 1, 2, 3, 4, or 5."
      sleep 1
      ;;
  esac
done
