#!/usr/bin/env python3
"""Back up the billing database and generated invoices.

Usage:
    python3 scripts/backup.py [--out DIR] [--keep N]

The database is copied through SQLite's online backup API, so it is safe to run
while the till is open. A manifest with SHA-256 hashes is written next to it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
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
    parser = argparse.ArgumentParser(description="Back up Arati Hotel billing data")
    parser.add_argument("--out", default=str(ROOT / "backups"), help="destination root")
    parser.add_argument("--keep", type=int, default=14, help="number of backups to keep")
    args = parser.parse_args()

    db_path = Path(db.DB_PATH)
    if not db_path.exists():
        print(f"error: database not found at {db_path}", file=sys.stderr)
        return 2

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = Path(args.out) / f"arati-backup-{stamp}"
    target.mkdir(parents=True, exist_ok=False)

    # Online backup: consistent even while bills are being written.
    source = sqlite3.connect(str(db_path))
    destination = sqlite3.connect(str(target / "arati.db"))
    try:
        with destination:
            source.backup(destination)
        bills = destination.execute(
            "SELECT COUNT(*), COALESCE(MAX(bill_no), '') FROM bills"
        ).fetchone()
        integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        destination.close()
        source.close()

    if INVOICE_DIR.exists():
        shutil.copytree(INVOICE_DIR, target / "invoices", dirs_exist_ok=True)

    files = []
    for path in sorted(target.rglob("*")):
        if path.is_file() and path.name != "MANIFEST.json":
            files.append({
                "path": str(path.relative_to(target)),
                "size": path.stat().st_size,
                "sha256": sha256(path),
            })

    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_db": str(db_path),
        "bills": bills[0],
        "last_bill_no": bills[1],
        "integrity_check": integrity,
        "files": files,
    }
    (target / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    print(f"backup: {target}")
    print(f"bills: {bills[0]} (last {bills[1] or '—'}) · integrity: {integrity}")

    backups = sorted(Path(args.out).glob("arati-backup-*"))
    for old in backups[: max(0, len(backups) - args.keep)]:
        shutil.rmtree(old, ignore_errors=True)
        print(f"pruned old backup: {old.name}")
    return 0 if integrity == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
