#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

BACKEND_PORT="${BACKEND_PORT:-8765}"
VITE_PORT="${VITE_PORT:-5173}"
NO_INSTALL=0
NO_LAUNCH=0
DOCKER_BACKEND=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --backend-port) BACKEND_PORT="$2"; shift 2 ;;
    --vite-port) VITE_PORT="$2"; shift 2 ;;
    --no-install) NO_INSTALL=1; shift ;;
    --no-launch) NO_LAUNCH=1; shift ;;
    --docker-backend) DOCKER_BACKEND=1; shift ;;
    --mock) export LOCAL_SCRIBE_PROVIDER=mock; shift ;;
    *) echo "[Local Scribe] Unknown option: $1"; exit 1 ;;
  esac
done

LOG_DIR="$ROOT/app-data/logs/launcher/$(date +%Y%m%d-%H%M%S)"
TMP_DIR="$ROOT/app-data/tmp/launcher"
mkdir -p "$LOG_DIR" "$TMP_DIR"
export TMPDIR="$TMP_DIR"
export LOCAL_SCRIBE_PROVIDER="${LOCAL_SCRIBE_PROVIDER:-mock}"

BACKEND_PID=""
VITE_PID=""

cleanup() {
  echo "[Local Scribe] App exited. Shutting down services..."
  if [ -n "$VITE_PID" ]; then kill "$VITE_PID" 2>/dev/null || true; fi
  if [ -n "$BACKEND_PID" ]; then kill "$BACKEND_PID" 2>/dev/null || true; fi
  if [ "$DOCKER_BACKEND" -eq 1 ]; then docker compose --profile mock stop backend >/dev/null 2>&1 || true; fi
  find "$TMP_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
}
trap cleanup EXIT INT TERM

need_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[Local Scribe] ERROR: $2"
    exit 1
  fi
}

wait_url() {
  url="$1"
  label="$2"
  limit="${3:-60}"
  i=0
  while [ "$i" -lt "$limit" ]; do
    if "$PYTHON" - "$url" <<'PY' >/dev/null 2>&1
import sys, urllib.request
urllib.request.urlopen(sys.argv[1], timeout=2).read()
PY
    then
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done
  echo "[Local Scribe] ERROR: $label did not become reachable at $url. See logs: $LOG_DIR"
  exit 1
}

echo "[Local Scribe] Checking Python..."
PYTHON="$(command -v python3 || command -v python || true)"
if [ -z "$PYTHON" ] && [ "$DOCKER_BACKEND" -eq 0 ]; then
  echo "[Local Scribe] ERROR: Python was not found. Install Python 3.12+ and rerun."
  exit 1
fi

echo "[Local Scribe] Checking Node/npm..."
need_command node "Node.js was not found. Install Node.js LTS and rerun."
need_command npm "npm was not found. Install Node.js LTS with npm enabled and rerun."

if [ "$DOCKER_BACKEND" -eq 1 ]; then
  echo "[Local Scribe] Checking Docker..."
  need_command docker "Docker was not found. Install Docker Desktop/Engine and rerun with --docker-backend."
  docker version >/dev/null
  echo "[Local Scribe] Starting Docker backend on http://127.0.0.1:$BACKEND_PORT..."
  docker compose --profile mock up -d --build backend >"$LOG_DIR/docker-backend.log" 2>&1
else
  if [ ! -x "$ROOT/.venv/bin/python" ]; then
    if [ "$NO_INSTALL" -eq 1 ]; then
      echo "[Local Scribe] ERROR: .venv is missing and --no-install was set."
      exit 1
    fi
    echo "[Local Scribe] Creating virtual environment..."
    "$PYTHON" -m venv "$ROOT/.venv" >"$LOG_DIR/venv-create.log" 2>&1
  fi
  PYTHON="$ROOT/.venv/bin/python"
  if [ "$NO_INSTALL" -eq 0 ]; then
    echo "[Local Scribe] Installing backend dependencies..."
    "$PYTHON" -m pip install -r backend/requirements.txt >"$LOG_DIR/pip-install.log" 2>&1
  fi
  echo "[Local Scribe] Starting backend on http://127.0.0.1:$BACKEND_PORT..."
  LOCAL_SCRIBE_HOST=127.0.0.1 LOCAL_SCRIBE_PORT="$BACKEND_PORT" "$PYTHON" -m uvicorn backend.app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" >"$LOG_DIR/backend.out.log" 2>"$LOG_DIR/backend.err.log" &
  BACKEND_PID="$!"
fi

echo "[Local Scribe] Waiting for backend health..."
wait_url "http://127.0.0.1:$BACKEND_PORT/api/health" "Backend"

if [ "$NO_INSTALL" -eq 0 ]; then
  echo "[Local Scribe] Installing desktop dependencies..."
  npm install >"$LOG_DIR/npm-install.log" 2>&1
fi

echo "[Local Scribe] Starting Vite dev server on http://127.0.0.1:$VITE_PORT..."
npm --workspace @localscribe/desktop run dev -- --host 127.0.0.1 --port "$VITE_PORT" >"$LOG_DIR/vite.out.log" 2>"$LOG_DIR/vite.err.log" &
VITE_PID="$!"

echo "[Local Scribe] Waiting for Vite..."
wait_url "http://127.0.0.1:$VITE_PORT" "Vite"

export VITE_DEV_SERVER_URL="http://127.0.0.1:$VITE_PORT"
export LOCAL_SCRIBE_API_BASE="http://127.0.0.1:$BACKEND_PORT/api"

if [ "$NO_LAUNCH" -eq 1 ]; then
  echo "[Local Scribe] Electron launch command verified: npm --workspace @localscribe/desktop run electron:dev"
  exit 0
fi

echo "[Local Scribe] Launching Local Scribe desktop app..."
npm --workspace @localscribe/desktop run electron:dev
