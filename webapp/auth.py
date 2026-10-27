"""Small PBKDF2 password helpers and signed-session authentication."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User, UserSession, utcnow
import secrets as _secrets


def _session_id(request: Request) -> str:
    """Stable server-side id for the signed cookie this browser is presenting.

    Starlette stores the decoded session payload in ``request.session``, but the
    revocation ledger needs to be bound to the exact signed cookie the browser
    sent, not to mutable session state. The cookie value is available on the raw
    cookie header; falling back to a fresh id only happens when the cookie is
    absent, which is the anonymous case anyway.
    """
    cookie_name = getattr(request.app.state if hasattr(request.app, "state") else None, "session_cookie", "arati_session")
    raw = None
    for name, value in request.cookies.items():
        if name == cookie_name:
            raw = value
            break
    if raw:
        return raw
    if request.session.get("user_id"):
        return _secrets.token_urlsafe(32)
    return ""


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
    """Resolve the signed-in user and reject stale or revoked credentials.

    The cookie is stateless, so a password change, a reset, a role change or a
    deactivation would otherwise leave already-issued cookies valid for their
    full 10 hours. ``session_version`` is bumped server-side on each of those
    events and compared here on every request.

    Session revocation is handled here too. If the server-side record for the
    presented cookie has been revoked, this request is treated like an expired
    session: the cookie is cleared and the user is bounced to the login page.
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

    session_id = _session_id(request)
    if session_id:
        record = db.execute(
            select(UserSession).where(
                UserSession.session_id == session_id,
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
            )
        ).scalar_one_or_none()
        if record is not None:
            request.session["_session_record_id"] = record.id
            request.session.modified = True
        elif db.scalar(
            select(UserSession.id).where(
                UserSession.session_id == session_id,
                UserSession.user_id == user_id,
            )
        ) is not None:
            request.session.clear()
            raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
        else:
            now = utcnow()
            record = UserSession(
                session_id=session_id,
                user_id=user_id,
                ip_address=request.client.host if request.client else "unknown",
                user_agent=(
                    (request.headers.get("user-agent") or "").strip()
                    [:512]
                ),
                created_at=now,
                last_seen_at=now,
            )
            db.add(record)
            db.flush()
            request.session["_session_record_id"] = record.id
            request.session.modified = True
        db.expunge(record)
    return user
