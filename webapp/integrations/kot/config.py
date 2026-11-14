# Copyright 2026 AI Memory System. All rights reserved.
"""Cloud KOT integration: configuration.

The local webapp owns billing and the admin menu. The cloud KOT service owns
kitchen status. This package mirrors cloud tickets into the local database and
pushes local orders/menu changes out, over plain outbound HTTPS.

Everything is off unless configured: with no ``KOT_CLOUD_URL`` (or no service
account) the webapp behaves exactly as it did before.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_TRUE = {"1", "true", "yes", "on"}


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in _TRUE


def _int(name: str, default: int, *, low: int, high: int) -> int:
    try:
        value = int(str(os.getenv(name, "")).strip() or default)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def _float(name: str, default: float, *, low: float, high: float) -> float:
    try:
        value = float(str(os.getenv(name, "")).strip() or default)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


@dataclass(frozen=True)
class KotSyncSettings:
    """Resolved sync configuration (immutable, safe to share across tasks)."""

    base_url: str = ""
    username: str = ""
    password: str = ""
    poll_seconds: int = 60
    page_size: int = 100
    request_timeout: float = 30.0
    open_refresh_limit: int = 25
    push_menu: bool = True
    push_orders: bool = True
    push_rooms: bool = True
    # A local order is only pushed once it has been cut (the kitchen has it).
    push_order_statuses: tuple[str, ...] = ("new", "preparing", "ready", "served")

    @property
    def enabled(self) -> bool:
        """True only when a URL and a service account are both present."""
        return bool(self.base_url and self.username and self.password)

    @property
    def disabled_reason(self) -> str:
        if self.enabled:
            return ""
        missing = [
            name
            for name, value in (
                ("KOT_CLOUD_URL", self.base_url),
                ("KOT_CLOUD_USERNAME", self.username),
                ("KOT_CLOUD_PASSWORD", self.password),
            )
            if not value
        ]
        return "Not configured: set " + ", ".join(missing)

    @classmethod
    def from_env(cls) -> "KotSyncSettings":
        base_url = os.getenv("KOT_CLOUD_URL", "").strip().rstrip("/")
        username = os.getenv("KOT_CLOUD_USERNAME", "").strip()
        password = os.getenv("KOT_CLOUD_PASSWORD", "").strip()
        statuses = tuple(
            part.strip().lower()
            for part in os.getenv(
                "KOT_PUSH_ORDER_STATUSES", "new,preparing,ready,served"
            ).split(",")
            if part.strip()
        )
        return cls(
            base_url=base_url,
            username=username,
            password=password,
            poll_seconds=_int("KOT_POLL_SECONDS", 60, low=15, high=3600),
            page_size=_int("KOT_SYNC_PAGE_SIZE", 100, low=10, high=500),
            request_timeout=_float("KOT_SYNC_TIMEOUT", 30.0, low=3.0, high=120.0),
            open_refresh_limit=_int("KOT_OPEN_REFRESH_LIMIT", 25, low=0, high=200),
            push_menu=_flag("KOT_PUSH_MENU", True),
            push_orders=_flag("KOT_PUSH_ORDERS", True),
            push_rooms=_flag("KOT_PUSH_ROOMS", True),
            push_order_statuses=statuses or ("new", "preparing", "ready", "served"),
        )

    def public_summary(self) -> dict:
        """Everything the dashboard may show — never the password."""
        return {
            "enabled": self.enabled,
            "base_url": self.base_url or "—",
            "username": self.username or "—",
            "poll_seconds": self.poll_seconds,
            "push_menu": self.push_menu,
            "push_orders": self.push_orders,
            "push_rooms": self.push_rooms,
            "disabled_reason": self.disabled_reason,
        }
