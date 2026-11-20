"""Authenticate an existing application session and resolve current permissions."""

import hashlib
import hmac
import re
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from meta_kpi_calc.api.dependencies import get_session
from meta_kpi_calc.auth.models import AppSession, AppUser

SessionDependency = Annotated[Session, Depends(get_session)]
SESSION_COOKIE = "__Host-rctec_session"


def session_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token(token: str) -> str:
    return hmac.new(token.encode(), b"rctec-crm-csrf-v1", hashlib.sha256).hexdigest()


def verify_csrf(request: Request, supplied: str, *, require_origin: bool = False) -> None:
    expected_origin = str(request.app.state.settings.oidc_public_origin).rstrip("/")
    origin = request.headers.get("origin")
    if (require_origin or origin is not None) and origin != expected_origin:
        raise HTTPException(403, "Invalid request origin")
    expected = csrf_token(request.cookies.get(SESSION_COOKIE, ""))
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(403, "Invalid CSRF token")


def authenticate_session(request: Request, session: SessionDependency) -> AppUser:
    """Resolve a server-issued token; session issuance belongs to the OIDC phase."""
    token = request.cookies.get(SESSION_COOKIE, "")
    if re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        user = session.scalar(
            select(AppUser)
            .join(AppSession, AppSession.user_id == AppUser.id)
            .where(
                AppUser.active.is_(True),
                AppSession.token_digest == session_digest(token),
                AppSession.revoked_at.is_(None),
                AppSession.expires_at > datetime.now(UTC),
            )
        )
        if user is not None:
            if (
                request.method not in {"GET", "HEAD", "OPTIONS"}
                and request.scope["path"] != "/auth/logout"
            ):
                verify_csrf(request, request.headers.get("x-csrf-token", ""))
            return user
    raise HTTPException(401, "Authentication required")


def current_user(user: Annotated[AppUser, Depends(authenticate_session)]) -> AppUser:
    return user


CurrentUser = Annotated[AppUser, Depends(current_user)]


def require_admin(user: CurrentUser) -> AppUser:
    if user.role != "admin":
        raise HTTPException(403, "Administrator permission required")
    return user


CurrentAdmin = Annotated[AppUser, Depends(require_admin)]
