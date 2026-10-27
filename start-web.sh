#!/usr/bin/env bash
# Web application startup shortcut - starts the web server and opens browser
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${ARATI_WEB_HOST:-127.0.0.1}"
PORT="${ARATI_WEB_PORT:-8000}"
URL="http://${HOST}:${PORT}/billing/create"
LOG_DIR="${ROOT}/.run"
LOG_FILE="${LOG_DIR}/web.log"

mkdir -p "$LOG_DIR"

is_up() {
    curl -fsS -o /dev/null --max-time 2 "http://${HOST}:${PORT}/login" 2>/dev/null
}

if ! is_up; then
    echo "Starting Arati Hotel Web Billing..."
    nohup "${ROOT}/run_web.sh" >>"$LOG_FILE" 2>&1 &
    for _ in $(seq 1 240); do
        if is_up; then
            break
        fi
        sleep 0.5
    done
fi

if ! is_up; then
    if command -v notify-send >/dev/null 2>&1; then
        notify-send "Arati Hotel Billing" "The web app did not start. See ${LOG_FILE}"
    fi
    echo "Failed to start web app. Check ${LOG_FILE}"
    exit 1
fi

echo "Arati Hotel Web Billing is ready at ${URL}"
if [ "${ARATI_WEB_NO_BROWSER:-0}" != "1" ]; then
    xdg-open "$URL" >/dev/null 2>&1 || gio open "$URL" >/dev/null 2>&1 || true
fi