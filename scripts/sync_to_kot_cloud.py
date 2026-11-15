#!/usr/bin/env python3
"""Push the local webapp rooms/menu (and optionally orders) to the KOT cloud.

Uses the same ``SyncEngine`` the webapp poller runs, so the phone app sees the
hotel room list as ``Room <number>`` tables plus the real menu. Idempotent:
existing cloud tables/dishes are updated in place, nothing is deleted.

Usage:
    python scripts/sync_to_kot_cloud.py            # rooms + menu
    python scripts/sync_to_kot_cloud.py --orders   # rooms + menu + local KOTs
    python scripts/sync_to_kot_cloud.py --dry-run  # show what would be sent
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


async def run(*, orders: bool, dry_run: bool) -> int:
    from webapp.integrations.kot.client import KotClient
    from webapp.integrations.kot.config import KotSyncSettings
    from webapp.integrations.kot.sync_engine import CycleResult, SyncEngine

    settings = KotSyncSettings.from_env()
    if not settings.enabled:
        print(f"KOT sync is not configured: {settings.disabled_reason}")
        return 2

    print(f"Cloud: {settings.base_url}")
    print(f"Account: {settings.username}")
    print(f"Push rooms={settings.push_rooms} menu={settings.push_menu} orders={orders}")
    if dry_run:
        print("Dry run: no requests are sent.")
        return 0

    result = CycleResult()
    async with KotClient(settings) as client:
        engine = SyncEngine(client, settings)
        await engine.push_rooms(result)
        await engine.push_menu(result)
        if orders:
            engine.enqueue_local_orders(result)
            await engine.flush_queue(result)

    print(
        "Pushed "
        f"{result.pushed_rooms} rooms, "
        f"{result.pushed_dishes} dishes, "
        f"{result.pushed_orders} orders "
        f"(queued {result.queued}, failed {result.failed})."
    )
    for error in result.errors:
        print(f"  ERROR: {error}")
    return 0 if not result.errors else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file", type=Path, default=ROOT / ".env", help="default: .env"
    )
    parser.add_argument(
        "--orders",
        action="store_true",
        help="also push local webapp KOTs that the cloud has not seen",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="validate config only"
    )
    args = parser.parse_args()
    load_env(args.env_file)
    return asyncio.run(run(orders=args.orders, dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
