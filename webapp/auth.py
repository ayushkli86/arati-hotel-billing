"""Small PBKDF2 password helpers and signed-session authentication."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 240_000).hex()
    return f"pbkdf2_sha256$240000${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt, digest = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), int(rounds)
        ).hex()
        return hmac.compare_digest(candidate, digest)
    except (ValueError, TypeError):
        return False


def current_user(request: Request, db: Session) -> User:
    """Resolve the signed-in user and reject stale credentials.

    The cookie is stateless, so a password change, a reset, a role change or a
    deactivation would otherwise leave already-issued cookies valid for their
    full 10 hours. ``session_version`` is bumped server-side on each of those
    events and compared here on every request.
    """
    user_id = request.session.get("user_id")
    user = db.get(User, user_id) if user_id else None
    if (
        user is None
        or not user.active
        or request.session.get("sv", 0) != (user.session_version or 0)
    ):
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    return user
