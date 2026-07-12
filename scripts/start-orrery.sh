#!/usr/bin/env bash
# Idempotent Orrery launcher (macOS / Linux).
#
# Brings Docker and the bundled PostgreSQL up if they are not already, then starts Orrery.
# Safe to run as many times as you like — every step checks what is already running and skips
# it, so re-running never doubles anything up or crashes on "already running".
set -uo pipefail

CONTAINER="orrery-postgres"
IMAGE="pgvector/pgvector:pg17"

log() { printf '  %s\n' "$*"; }

# 1) Docker engine ----------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  log "Docker is not installed. Install Docker Desktop, then re-run:"
  log "  https://www.docker.com/products/docker-desktop/"
  exit 1
fi

if docker info >/dev/null 2>&1; then
  log "Docker is already running."
else
  log "Starting Docker..."
  case "$(uname -s)" in
    Darwin) open -a Docker >/dev/null 2>&1 || true ;;
    Linux)  (sudo systemctl start docker >/dev/null 2>&1 || systemctl --user start docker >/dev/null 2>&1) || true ;;
  esac
  for _ in $(seq 1 50); do docker info >/dev/null 2>&1 && break; sleep 3; done
  if ! docker info >/dev/null 2>&1; then
    log "Docker did not become ready in time. Start Docker Desktop, then re-run this script."
    exit 1
  fi
  log "Docker is running."
fi

# 2) Bundled database (idempotent) ------------------------------------------------
if [ -n "$(docker ps -q -f "name=^${CONTAINER}$" 2>/dev/null)" ]; then
  log "Database is already running."
elif [ -n "$(docker ps -aq -f "name=^${CONTAINER}$" 2>/dev/null)" ]; then
  log "Starting the existing database container..."
  docker start "$CONTAINER" >/dev/null
else
  log "Creating the bundled database (first run downloads the image, a few minutes)..."
  docker run -d --name "$CONTAINER" --restart unless-stopped \
    -e POSTGRES_USER=orrery -e POSTGRES_PASSWORD=orrery_dev_password -e POSTGRES_DB=orrery \
    -p 127.0.0.1:5432:5432 -v orrery_pgdata:/var/lib/postgresql/data "$IMAGE" >/dev/null
fi

log "Waiting for the database to accept connections..."
for _ in $(seq 1 60); do
  docker exec "$CONTAINER" pg_isready -U orrery -d orrery >/dev/null 2>&1 && break
  sleep 2
done
log "Database is ready."

# 3) Launch Orrery (skip if already open) -----------------------------------------
if pgrep -f "Orrery.app/Contents/MacOS/Orrery" >/dev/null 2>&1; then
  log "Orrery is already running — leaving it be."
  exit 0
fi

if [ -d "/Applications/Orrery.app" ]; then
  open -a Orrery
  log "Orrery launched."
elif [ -d "./Orrery.app" ]; then
  open "./Orrery.app"
  log "Orrery launched."
else
  log "Docker and the database are ready. Open Orrery from your Applications folder."
fi
