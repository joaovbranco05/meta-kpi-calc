"""Authenticate an existing application session and resolve current permissions."""

import hashlib
import re
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from meta_kpi_calc.api.dependencies import get_session
from meta_kpi_calc.auth.models import AppSession, AppUser

SessionDependency = Annotated[Session, Depends(get_session)]
SESSION_COOKIE = "rctec_session"


def authenticate_session(request: Request, session: SessionDependency) -> int:
    """Resolve a server-issued token; session issuance belongs to the OIDC phase."""
    token = request.cookies.get(SESSION_COOKIE, "")
    if re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        user_id = session.scalar(
            select(AppSession.user_id).where(
                AppSession.token_digest == hashlib.sha256(token.encode()).hexdigest(),
                AppSession.revoked_at.is_(None),
                AppSession.expires_at > datetime.now(UTC),
            )
        )
        if user_id is not None:
            return user_id
    raise HTTPException(401, "Authentication required")


def current_user(
    user_id: Annotated[int, Depends(authenticate_session)], session: SessionDependency
) -> AppUser:
    user = session.get(AppUser, user_id)
    if user is None or not user.active:
        raise HTTPException(401, "Authentication required")
    return user


CurrentUser = Annotated[AppUser, Depends(current_user)]


def require_admin(user: CurrentUser) -> AppUser:
    if user.role != "admin":
        raise HTTPException(403, "Administrator permission required")
    return user


CurrentAdmin = Annotated[AppUser, Depends(require_admin)]
