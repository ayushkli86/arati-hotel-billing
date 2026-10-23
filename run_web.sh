#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
VENV=".venv-web"

if [ ! -x "$VENV/bin/python" ]; then
    echo "Creating web application virtual environment..."
    "$PYTHON" -m venv "$VENV"
fi

if ! "$VENV/bin/python" -c "import fastapi, sqlalchemy, jinja2, httpx, weasyprint" >/dev/null 2>&1; then
    echo "Installing web application dependencies..."
    "$VENV/bin/pip" install -r webapp/requirements.txt
fi

"$VENV/bin/python" -m webapp.seed
exec "$VENV/bin/python" -m uvicorn webapp.main:app --host "${ARATI_WEB_HOST:-127.0.0.1}" --port "${ARATI_WEB_PORT:-8000}"
