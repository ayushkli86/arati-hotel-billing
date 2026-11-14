# Copyright 2026 AI Memory System. All rights reserved.
"""Cloud KOT integration for the Arati Hotel front office.

Importing this package registers the additive ``kot_*`` tables on the webapp
``Base`` (see ``models.py``) so the normal ``create_all`` startup path creates
them. Nothing else happens on import; the poller only starts from the FastAPI
lifespan and only when the environment is configured.
"""

from .config import KotSyncSettings
from .poller import build_poller, get_poller, start_poller, stop_poller
from .sync_engine import snapshot

__all__ = [
    "KotSyncSettings",
    "build_poller",
    "get_poller",
    "start_poller",
    "stop_poller",
    "snapshot",
]
