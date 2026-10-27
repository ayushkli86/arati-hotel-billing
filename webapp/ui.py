"""Small UI-facing helpers shared by the web routes.

Keeping the toast vocabulary in one place means a redirect, an HTMX trigger,
and a rendered page all describe feedback the same way. That removes the
hand-written ``?created=1`` / ``?saved=1`` checks scattered through the routes
and gives the frontend a single event contract to render.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import Request

TOAST_KINDS = frozenset({"success", "error", "warning", "info"})
MAX_TOAST_LENGTH = 500


def toast_event(message: str, kind: str = "success") -> dict[str, str]:
    """A payload for an HTMX ``showToast`` trigger."""
    return {
        "message": str(message)[:MAX_TOAST_LENGTH],
        "type": kind if kind in TOAST_KINDS else "success",
    }


def toast_url(url: str, message: str, kind: str = "success") -> str:
    """Append flash-style toast parameters to a redirect target."""
    params = urlencode(toast_event(message, kind))
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{params}"


def toast_from_request(request: Request) -> dict[str, str] | None:
    """Read a toast left by a redirect, if there is one."""
    message = (request.query_params.get("toast") or "").strip()
    if not message:
        return None
    kind = (request.query_params.get("toast_type") or "success").strip().lower()
    return toast_event(message, kind)
