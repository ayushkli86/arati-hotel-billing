"""Role-based permissions, enforced in the data layer.

Hiding a button is a courtesy, not a control. Every operation that changes
money, room state or configuration asks this module first, so a staff
account cannot reach a privileged action even by calling the module
directly.

Two roles exist:

``admin``
    Full control, including financial adjustments, room rates, printer and
    hotel settings, report regeneration and staff management.
``staff``
    The front desk: raise invoices, take payments, print, check guests in
    and out, and look at the reports their role allows.
"""

from __future__ import annotations

# Every permission the app understands, mapped to the roles that hold it.
PERMISSIONS: dict[str, tuple[str, ...]] = {
    # --- billing -------------------------------------------------------
    "invoice.create": ("admin", "staff"),
    "invoice.void": ("admin",),
    "invoice.draft_delete": ("admin",),
    "invoice.print": ("admin", "staff"),
    "invoice.pdf": ("admin", "staff"),
    # --- cash ----------------------------------------------------------
    "payment.receive": ("admin", "staff"),
    "payment.refund": ("admin",),
    "payment.adjust": ("admin",),
    "payment.view": ("admin", "staff"),
    # --- rooms ---------------------------------------------------------
    "room.view": ("admin", "staff"),
    "room.reserve": ("admin", "staff"),
    "room.check_in": ("admin", "staff"),
    "room.check_out": ("admin", "staff"),
    "room.extend": ("admin", "staff"),
    "room.charge": ("admin", "staff"),
    "room.rate": ("admin",),
    "room.housekeeping": ("admin", "staff"),
    "room.maintenance": ("admin",),
    "room.inventory": ("admin",),
    # --- guests --------------------------------------------------------
    "customer.view": ("admin", "staff"),
    "customer.edit": ("admin", "staff"),
    "customer.deactivate": ("admin",),
    # --- reporting -----------------------------------------------------
    "report.view": ("admin", "staff"),
    "report.export": ("admin", "staff"),
    "report.regenerate": ("admin",),
    "analysis.view": ("admin",),
    # --- configuration -------------------------------------------------
    "settings.hotel": ("admin",),
    "settings.printer": ("admin",),
    "settings.closing": ("admin",),
    "staff.manage": ("admin",),
    "backup.manage": ("admin",),
    "audit.view": ("admin",),
}


class PermissionError_(PermissionError):
    """Raised when the signed-in role may not perform an operation."""


def can(user, permission: str) -> bool:
    """Whether ``user`` holds ``permission``.

    ``user`` may be a mapping with a ``role`` key or a plain role string.
    An unknown permission is denied, so a typo fails closed.
    """
    role = _role(user)
    if role is None:
        return False
    allowed = PERMISSIONS.get(permission)
    if allowed is None:
        return False
    return role in allowed


def require(user, permission: str, action: str = "") -> None:
    """Raise :class:`PermissionError_` unless ``user`` holds ``permission``."""
    if can(user, permission):
        return
    role = _role(user) or "unknown"
    label = action or permission
    raise PermissionError_(
        f"Your role ({role}) is not allowed to {label}. Ask an administrator."
    )


def _role(user) -> str | None:
    if user is None:
        return None
    if isinstance(user, str):
        return user
    if isinstance(user, dict):
        return user.get("role")
    try:
        return user["role"]
    except (KeyError, TypeError, IndexError):
        return getattr(user, "role", None)


def permissions_for(role: str) -> list[str]:
    """Every permission a role holds, for the settings screen."""
    return sorted(
        permission
        for permission, roles in PERMISSIONS.items()
        if role in roles
    )
