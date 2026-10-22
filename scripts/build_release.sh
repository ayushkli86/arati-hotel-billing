#!/usr/bin/env bash
# Build a clean, versioned release archive (no database, invoices or virtualenv).
set -euo pipefail

cd "$(dirname "$0")/.."

VERSION="${1:-$(python3 -c "import re;print(re.search(r'__version__ = \"([^\"]+)\"', open('arati/__init__.py').read()).group(1))")}"
NAME="arati-billing-${VERSION}"

rm -rf "dist/${NAME}" "dist/${NAME}.tar.gz" "dist/${NAME}.tar.gz.sha256"
mkdir -p "dist/${NAME}"

tar -cf - \
    --exclude='.venv' \
    --exclude='arati.db*' \
    --exclude='invoices' \
    --exclude='backups' \
    --exclude='dist' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    . | tar -xf - -C "dist/${NAME}"

tar -czf "dist/${NAME}.tar.gz" -C dist "${NAME}"
sha256sum "dist/${NAME}.tar.gz" | tee "dist/${NAME}.tar.gz.sha256"

echo "release: dist/${NAME}.tar.gz"
echo "verify:  sha256sum -c dist/${NAME}.tar.gz.sha256"
