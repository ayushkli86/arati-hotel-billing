#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if [ ! -d .venv ]; then
    echo "Creating virtualenv…"
    "$PYTHON" -m venv --system-site-packages .venv
fi

if ! .venv/bin/python -c "import reportlab" >/dev/null 2>&1; then
    echo "Installing reportlab…"
    .venv/bin/pip install -q -r requirements.txt
fi

exec .venv/bin/python app.py
