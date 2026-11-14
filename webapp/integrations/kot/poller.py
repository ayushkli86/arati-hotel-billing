# Copyright 2026 AI Memory System. All rights reserved.
"""The single background poller.

Exactly one task per process performs sync cycles: a second task would double
the outbound traffic and race the cursor. It is created in the FastAPI lifespan
and stopped on shutdown. The task never dies on an error — a failed cycle is
recorded and retried after the normal interval with the same cursor, which is
what gives the offline behaviour its resume-after-restart guarantee.

Run uvicorn with a single worker (the provided run script does): with several
workers each would start its own poller.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from .client import KotApiError, KotClient
from .config import KotSyncSettings
from .sync_engine import CycleResult, SyncEngine

_log = logging.getLogger("webapp.kot_sync")


class KotPoller:
    """Owns the cloud client, the engine and the sleep/wake loop."""

    def __init__(self, settings: KotSyncSettings, *, client: KotClient | None = None) -> None:
        self.settings = settings
        self.client = client or KotClient(settings)
        self.engine = SyncEngine(self.client, settings)
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._stop = asyncio.Event()
        self._run_lock = asyncio.Lock()
        self.last_result: CycleResult | None = None
        self.last_finished_at: datetime | None = None
        self.cycles = 0

    # ---------------------------------------------------------------- lifecycle
    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="kot-sync-poller")
        _log.info("kot sync: poller started (every %ss)", self.settings.poll_seconds)

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        try:
            await self.client.aclose()
        except Exception:  # noqa: BLE001
            _log.debug("kot sync: client close failed", exc_info=True)
        _log.info("kot sync: poller stopped")

    # -------------------------------------------------------------------- loop
    async def _loop(self) -> None:
        # Let startup finish (migrations, seeding) before the first network call.
        await asyncio.sleep(3)
        while not self._stop.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.settings.poll_seconds)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def run_once(self) -> CycleResult:
        """Run one cycle; overlapping calls collapse into the running one."""
        if self._run_lock.locked():
            _log.info("kot sync: cycle already running")
            return self.last_result or CycleResult()
        async with self._run_lock:
            self.cycles += 1
            started = datetime.now(timezone.utc)
            try:
                result = await self.engine.run_cycle()
            except Exception as exc:  # noqa: BLE001 - the loop must survive
                _log.exception("kot sync: unexpected cycle error")
                result = CycleResult(errors=[f"{type(exc).__name__}: {exc}"])
            self.last_result = result
            self.last_finished_at = datetime.now(timezone.utc)
            elapsed = (self.last_finished_at - started).total_seconds()
            level = logging.INFO if result.ok else logging.WARNING
            _log.log(
                level,
                "kot sync: pulled=%s refreshed=%s queued=%s orders=%s dishes=%s failed=%s %.1fs",
                result.pulled, result.refreshed, result.queued,
                result.pushed_orders, result.pushed_dishes, result.failed, elapsed,
            )
            return result

    def request_sync(self) -> bool:
        """Wake the loop now (manual "Sync now" from the dashboard)."""
        if not self.running:
            return False
        self._wake.set()
        return True

    def status(self) -> dict:
        result = self.last_result
        return {
            "running": self.running,
            "cycles": self.cycles,
            "last_finished": self.last_finished_at.isoformat(timespec="seconds")
            if self.last_finished_at else "",
            "last_result": {
                "pulled": result.pulled,
                "refreshed": result.refreshed,
                "queued": result.queued,
                "pushed_orders": result.pushed_orders,
                "pushed_dishes": result.pushed_dishes,
                "failed": result.failed,
                "errors": result.errors[:5],
            } if result else None,
        }


# The module-level singleton: the app only ever has one.
_poller: KotPoller | None = None


def get_poller() -> KotPoller | None:
    return _poller


def build_poller(settings: KotSyncSettings) -> KotPoller:
    global _poller
    _poller = KotPoller(settings)
    return _poller


async def start_poller(settings: KotSyncSettings) -> KotPoller | None:
    """Start the poller when configured; returning None keeps the app untouched."""
    global _poller
    if not settings.enabled:
        _log.info("kot sync: disabled — %s", settings.disabled_reason)
        _poller = None
        return None
    try:
        poller = build_poller(settings)
        poller.start()
        return poller
    except KotApiError as exc:
        _log.warning("kot sync: cannot start — %s", exc)
        _poller = None
        return None


async def stop_poller() -> None:
    global _poller
    poller = _poller
    _poller = None
    if poller is not None:
        await poller.stop()
