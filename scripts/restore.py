#!/usr/bin/env python3
"""Restore a backup made by scripts/backup.py.

Usage:
    python3 scripts/restore.py BACKUP_DIR --yes

The current database and invoices are moved aside (not deleted) before the
backup is copied in, so an unsuccessful restore can be undone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from arati import db

INVOICE_DIR = Path(os.environ.get("ARATI_INVOICE_DIR") or (ROOT / "invoices"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 256), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore an Arati Hotel backup")
    parser.add_argument("backup", help="backup directory containing arati.db")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args()

    backup = Path(args.backup).expanduser().resolve()
    source_db = backup / "arati.db"
    if not source_db.exists():
        print(f"error: no arati.db in {backup}", file=sys.stderr)
        return 2

    manifest_path = backup / "MANIFEST.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        for entry in manifest.get("files", []):
            path = backup / entry["path"]
            if not path.exists() or sha256(path) != entry["sha256"]:
                print(f"error: checksum mismatch for {entry['path']}", file=sys.stderr)
                return 3
        print(f"manifest verified: {manifest.get('bills', '?')} bills, "
              f"created {manifest.get('created_at', '?')}")

    if not args.yes:
        answer = input(f"Restore {backup} over {db.DB_PATH}? Type 'restore': ")
        if answer.strip() != "restore":
            print("aborted")
            return 1

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    db_path = Path(db.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if db_path.exists():
        keeper = db_path.with_suffix(f".pre-restore-{stamp}")
        shutil.copy2(db_path, keeper)
        print(f"current database saved as {keeper.name}")
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(db_path) + suffix)
            if sidecar.exists():
                sidecar.unlink()

    shutil.copy2(source_db, db_path)
    os.chmod(db_path, 0o600)

    backup_invoices = backup / "invoices"
    if backup_invoices.exists():
        if INVOICE_DIR.exists():
            shutil.move(str(INVOICE_DIR), str(INVOICE_DIR.with_name(
                f"invoices.pre-restore-{stamp}")))
        shutil.copytree(backup_invoices, INVOICE_DIR)

    print(f"restored database: {db_path}")
    print(f"restored invoices: {INVOICE_DIR}")
    print("Rollback: copy the *.pre-restore-* files back if this restore was wrong.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
