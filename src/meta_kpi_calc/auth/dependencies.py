"""Authenticate an existing application session and resolve current permissions."""

import hashlib
import hmac
import re
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import or_, select, text, update
from sqlalchemy.orm import Session

from meta_kpi_calc.api.dependencies import get_session
from meta_kpi_calc.auth.models import AppSession, AppUser, BrowserContext

SessionDependency = Annotated[Session, Depends(get_session)]
SESSION_COOKIE = "__Host-rctec_session"
BROWSER_COOKIE = "__Host-rctec_browser"
READ_METHODS = {"GET", "HEAD", "OPTIONS"}


def lock_accounts(session: Session, *, shared: bool = False) -> None:
    """Order session changes and authorized writes before any domain locks."""
    if session.get_bind().dialect.name == "postgresql":
        if session.connection().get_isolation_level() != "READ COMMITTED":
            raise HTTPException(503, "Administrative transaction isolation unavailable")
        if shared:
            session.execute(text("SELECT pg_advisory_xact_lock_shared(718503120464)"))
        else:
            session.execute(text("SELECT pg_advisory_xact_lock(718503120464)"))
    else:
        # Acquire SQLite's writer lock before taking the authentication snapshot.
        session.execute(update(AppUser).where(AppUser.id.is_(None)).values(active=False))


def _lock_ordinary_write(session: SessionDependency) -> None:
    lock_accounts(session, shared=True)


def _lock_account_write(session: SessionDependency) -> None:
    lock_accounts(session)


def _lock_analytics_write(request: Request, session: SessionDependency) -> None:
    if request.method not in READ_METHODS:
        lock_accounts(session, shared=True)



def valid_cookie(value: str) -> bool:
    return re.fullmatch(r"[A-Za-z0-9_-]{43}", value) is not None


def session_binding(token: str) -> str:
    return hmac.new(token.encode(), b"rctec-streamlit-session-v1", hashlib.sha256).hexdigest()


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
    if valid_cookie(token):
        browser = request.cookies.get(BROWSER_COOKIE, "")
        now = datetime.now(UTC)
        user = session.scalar(
            select(AppUser)
            .join(AppSession, AppSession.user_id == AppUser.id)
            .outerjoin(BrowserContext, BrowserContext.digest == AppSession.browser_digest)
            .where(
                AppUser.active.is_(True),
                AppSession.token_digest == session_digest(token),
                AppSession.revoked_at.is_(None),
                AppSession.expires_at > now,
                or_(
                    AppSession.browser_digest.is_(None),
                    (BrowserContext.digest == session_digest(browser))
                    & (BrowserContext.expires_at > now),
                ),
            )
        )
        if user is not None:
            if request.method not in READ_METHODS:
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


# FastAPI resolves the guard before the identity. Both use the handler's
# cached SessionDependency, so the lock survives until commit or rollback.
def write_user(_guard: Annotated[None, Depends(_lock_ordinary_write)], user: CurrentUser) -> AppUser:
    return user


def account_writer(
    _guard: Annotated[None, Depends(_lock_account_write)], admin: CurrentAdmin,
) -> AppUser:
    return admin


def analytics_admin(
    _guard: Annotated[None, Depends(_lock_analytics_write)], admin: CurrentAdmin,
) -> AppUser:
    return admin


WriteUser = Annotated[AppUser, Depends(write_user)]
AccountWriter = Annotated[AppUser, Depends(account_writer)]
