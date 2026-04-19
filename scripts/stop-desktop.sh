#!/usr/bin/env bash
set -euo pipefail

stop_port() {
  local port="$1"
  local pids
  pids="$(ss -lntp 2>/dev/null | awk -v p=":${port}" '$4 ~ p {print $NF}' | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | sort -u)"
  if [[ -n "$pids" ]]; then
    echo "$pids" | xargs -r kill >/dev/null 2>&1 || true
    sleep 0.2
    echo "$pids" | xargs -r kill -9 >/dev/null 2>&1 || true
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
ss -lntp | grep -E '(:5173|:8787|:18789)' || echo "No desktop-assistant ports are listening."

