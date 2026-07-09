#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

APP="./Orrery.app"
BIN="$APP/Contents/MacOS/Orrery"
DEFAULT_DB_URL="postgresql+psycopg://orrery:orrery_dev_password@127.0.0.1:5432/orrery"
DOCKER_URL="https://www.docker.com/products/docker-desktop/"
OLLAMA_URL="https://ollama.com/download"

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

check_prerequisites() {
  clear
  echo "Orrery - checking prerequisites"
  echo "==============================="
  echo
  if command -v docker >/dev/null 2>&1; then
    if docker info >/dev/null 2>&1; then
      echo "  [ OK ]     Docker Desktop is installed and running."
    else
      echo "  [ WAIT ]   Docker Desktop is installed but NOT running - start it for the bundled database and file sandbox."
    fi
  else
    echo "  [ NEEDED ] Docker Desktop is not installed."
    echo "             It powers the included PostgreSQL database and the file-generation sandbox."
    echo "             Download: $DOCKER_URL"
  fi
  if command -v ollama >/dev/null 2>&1; then
    echo "  [ OK ]     Ollama is installed (optional, for local models)."
  else
    echo "  [ OPT ]    Ollama not found (optional) - only needed to run local models. $OLLAMA_URL"
  fi
  echo
  echo "  You can still continue: choosing \"your own PostgreSQL database\" (option 2) does not need Docker."
  echo
  if ! command -v docker >/dev/null 2>&1; then
    read -r -p "Open the Docker Desktop download page now? [y/N]: " open_docker
    case "$open_docker" in y|Y) open "$DOCKER_URL" ;; esac
  fi
  echo
  read -r -p "Press return to continue..."
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo
    echo "Docker was not found."
    echo "Install Docker Desktop, or go back and choose option 2 to use your own PostgreSQL server."
    echo "Download: $DOCKER_URL"
    read -r -p "Open the Docker download page now? [y/N]: " open_docker
    case "$open_docker" in y|Y) open "$DOCKER_URL" ;; esac
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
check_prerequisites

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
