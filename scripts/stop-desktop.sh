#!/usr/bin/env bash
set -euo pipefail

stop_port() {
  local port="$1"
  local pids
  if command -v ss >/dev/null 2>&1; then
    pids="$(ss -lntp 2>/dev/null | awk -v p=":${port}" '$4 ~ p {print $NF}' | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | sort -u)"
  else
    pids="$(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null | sort -u)"
  fi
  if [[ -n "$pids" ]]; then
    echo "$pids" | xargs kill >/dev/null 2>&1 || true
    sleep 0.2
    echo "$pids" | xargs kill -9 >/dev/null 2>&1 || true
  fi
}

echo "Stopping Desktop Assistant processes..."

# Frontend + backend local ports.
stop_port 5173
stop_port 8787

# Fallback process patterns for detached launches.
pkill -f "uvicorn app.main:app --host 127.0.0.1 --port 8787" >/dev/null 2>&1 || true
pkill -f "npm run dev -- --host 127.0.0.1 --port 5173" >/dev/null 2>&1 || true
pkill -f "vite --host 127.0.0.1 --port 5173" >/dev/null 2>&1 || true

# OpenClaw gateway service (if managed by systemd user unit).
systemctl --user stop openclaw-gateway.service >/dev/null 2>&1 || true

echo "Stopped. Current listening ports:"
if command -v ss >/dev/null 2>&1; then
  ss -lntp | grep -E '(:5173|:8787|:18789)' || echo "No desktop-assistant ports are listening."
else
  lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | grep -E ':(5173|8787|18789)\b' || echo "No desktop-assistant ports are listening."
fi
