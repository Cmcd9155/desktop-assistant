#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_URL="http://127.0.0.1:8787"
UI_URL="http://127.0.0.1:5173"
OPENCLAW_URL="http://127.0.0.1:18789"
BACKEND_LOG="/tmp/desktop-assistant-backend.log"
FRONTEND_LOG="/tmp/desktop-assistant-frontend.log"
NO_OPEN=0

for arg in "$@"; do
  case "$arg" in
    --no-open) NO_OPEN=1 ;;
  esac
done

is_port_open() {
  local port="$1"
  nc -z 127.0.0.1 "$port" >/dev/null 2>&1
}

spawn_detached() {
  if command -v setsid >/dev/null 2>&1; then
    setsid -f "$@" < /dev/null
    return 0
  fi
  nohup "$@" < /dev/null >/dev/null 2>&1 &
}

is_backend_running() {
  curl -fsS --max-time 1 "http://127.0.0.1:8787/health" >/dev/null 2>&1 || is_port_open 8787
}

is_frontend_running() {
  curl -fsS --max-time 1 "http://127.0.0.1:5173" >/dev/null 2>&1 || is_port_open 5173
}

is_openclaw_running() {
  curl -fsS --max-time 1 "http://127.0.0.1:18789/health" >/dev/null 2>&1 || is_port_open 18789
}

wait_for_check() {
  local check_fn="$1"
  local retries="${2:-40}"
  local delay="${3:-0.25}"
  local i
  for i in $(seq 1 "$retries"); do
    if "$check_fn"; then
      return 0
    fi
    sleep "$delay"
  done
  return 1
}

load_backend_env() {
  local env_file="$ROOT_DIR/config/secrets/backend.env"
  if [[ ! -f "$env_file" ]]; then
    return 0
  fi
  while IFS='=' read -r key value; do
    key="$(printf '%s' "$key" | tr -d '\r' | xargs)"
    value="$(printf '%s' "$value" | tr -d '\r')"
    [[ -z "$key" ]] && continue
    [[ "$key" =~ ^# ]] && continue
    export "$key=$value"
  done <"$env_file"
}

start_openclaw_if_needed() {
  if is_openclaw_running; then
    echo "OpenClaw: already running on 127.0.0.1:18789"
    return 0
  fi
  if systemctl --user cat openclaw-gateway.service >/dev/null 2>&1; then
    echo "OpenClaw: starting gateway service..."
    systemctl --user start openclaw-gateway.service >/tmp/openclaw-start.log 2>&1 || true
    if wait_for_check is_openclaw_running 60 0.25; then
      echo "OpenClaw: started"
    else
      echo "OpenClaw: service start timed out (see /tmp/openclaw-start.log)"
    fi
    return 0
  fi
  if [[ -x "$HOME/.openclaw/start-openclaw-comfyui-gemma.sh" ]]; then
    echo "OpenClaw: fallback startup script detected; launching in background..."
    nohup "$HOME/.openclaw/start-openclaw-comfyui-gemma.sh" >/tmp/openclaw-start.log 2>&1 < /dev/null &
    if wait_for_check is_openclaw_running 40 0.25; then
      echo "OpenClaw: started"
    else
      echo "OpenClaw: still starting or unavailable (see /tmp/openclaw-start.log)"
    fi
  else
    echo "OpenClaw: start script not found, skipping"
  fi
}

start_backend_if_needed() {
  if is_backend_running; then
    echo "Backend: already running on 127.0.0.1:8787"
    return 0
  fi
  echo "Backend: starting..."
  load_backend_env
  spawn_detached bash -lc "\"$ROOT_DIR/backend/.venv/bin/python\" -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --app-dir \"$ROOT_DIR/backend\" >\"$BACKEND_LOG\" 2>&1"
  if wait_for_check is_backend_running 80 0.25; then
    echo "Backend: started"
  else
    echo "Backend: failed to start (see $BACKEND_LOG)"
    return 1
  fi
}

start_frontend_if_needed() {
  if is_frontend_running; then
    echo "Frontend: already running on 127.0.0.1:5173"
    return 0
  fi
  echo "Frontend: starting..."
  spawn_detached bash -lc "cd '$ROOT_DIR/frontend' && npm run dev -- --host 127.0.0.1 --port 5173 >'$FRONTEND_LOG' 2>&1"
  if wait_for_check is_frontend_running 80 0.25; then
    echo "Frontend: started"
  else
    echo "Frontend: failed to start (see $FRONTEND_LOG)"
    return 1
  fi
}

open_app_window() {
  if command -v google-chrome >/dev/null 2>&1; then
    google-chrome --app="$UI_URL" >/dev/null 2>&1 &
  elif command -v chromium-browser >/dev/null 2>&1; then
    chromium-browser --app="$UI_URL" >/dev/null 2>&1 &
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$UI_URL" >/dev/null 2>&1 &
  fi
}

start_openclaw_if_needed
start_backend_if_needed
start_frontend_if_needed
if [[ "$NO_OPEN" != "1" ]]; then
  open_app_window
fi

echo
echo "Desktop Assistant status"
echo "Frontend: $UI_URL"
echo "Backend:  $API_URL"
echo "OpenClaw: $OPENCLAW_URL"
echo "Logs:"
echo "  Backend  -> $BACKEND_LOG"
echo "  Frontend -> $FRONTEND_LOG"
