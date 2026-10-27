#!/usr/bin/env bash
# Database initialization shortcut - seeds the database with demo data
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

echo "Initializing database..."
"$VENV/bin/python" -m webapp.seed
echo "Database initialized successfully!"