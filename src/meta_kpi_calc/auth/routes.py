"""Browser login boundary and private session inspection."""

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, select, update

from meta_kpi_calc.auth.admin import account_clock, lock_accounts
from meta_kpi_calc.auth.dependencies import (
    SESSION_COOKIE,
    CurrentUser,
    SessionDependency,
    csrf_token,
    session_digest,
    verify_csrf,
)
from meta_kpi_calc.auth.models import AppSession, AppUser, OIDCFlow
from meta_kpi_calc.auth.oidc import AUTHORIZE, exchange_identity

router = APIRouter(prefix="/auth")
FLOW_COOKIE = "__Host-rctec_oidc"
FLOW_SECONDS = 600
PRIVATE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def config_for(request):
    config = request.app.state.settings
    if not config.oidc_public_origin or config.demo_mode:
        raise HTTPException(404, "Authentication unavailable")
    return config, str(config.oidc_public_origin).rstrip("/")


@router.get("/login")
def login(request: Request, session: SessionDependency):
    config, origin = config_for(request)
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site not in (None, "none", "same-origin"):
        raise HTTPException(403, "Login must start on this site")
    state, browser, verifier, nonce = (secrets.token_urlsafe(32) for _ in range(4))
    now = account_clock(session)
    session.execute(delete(OIDCFlow).where(OIDCFlow.expires_at <= now))
    session.add(
        OIDCFlow(
            state_digest=session_digest(state),
            browser_digest=session_digest(browser),
            verifier=verifier,
            nonce=nonce,
            expires_at=now + timedelta(seconds=FLOW_SECONDS),
        )
    )
    session.commit()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    query = urlencode(
        {
            "client_id": config.oidc_client_id,
            "response_type": "code",
            "redirect_uri": origin + "/auth/callback",
            "scope": "openid email",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "hd": config.oidc_workspace_domain,
            "prompt": "select_account",
        }
    )
    result = RedirectResponse(f"{AUTHORIZE}?{query}", headers=PRIVATE_HEADERS, status_code=303)
    result.set_cookie(
        FLOW_COOKIE, browser, max_age=FLOW_SECONDS, secure=True, httponly=True, samesite="lax"
    )
    return result


@router.get("/callback")
def callback(request: Request, session: SessionDependency):
    config, origin = config_for(request)
    query = request.query_params
    state, code = query.get("state", ""), query.get("code", "")
    browser = request.cookies.get(FLOW_COOKIE, "")
    if len(query.getlist("state")) != 1 or len(state) != 43 or len(browser) != 43:
        raise HTTPException(400, "Invalid login transaction")
    flow = session.execute(
        delete(OIDCFlow)
        .where(
            OIDCFlow.state_digest == session_digest(state),
            OIDCFlow.browser_digest == session_digest(browser),
            OIDCFlow.expires_at > account_clock(session),
        )
        .returning(OIDCFlow.verifier, OIDCFlow.nonce, OIDCFlow.expires_at)
    ).one_or_none()
    session.commit()
    if (
        flow is None
        or "error" in query
        or len(query.getlist("code")) != 1
        or not 1 <= len(code) <= 4096
    ):
        raise HTTPException(400, "Invalid login transaction")
    try:
        # Only tests inject a transport. Network destinations are fixed in oidc.py.
        with httpx.Client(
            timeout=10,
            follow_redirects=False,
            trust_env=False,
            transport=request.app.state.oidc_transport,
        ) as http:
            issuer, subject = exchange_identity(
                http,
                config,
                code=code,
                verifier=flow.verifier,
                nonce=flow.nonce,
                redirect_uri=origin + "/auth/callback",
            )
    except (httpx.HTTPError, jwt.PyJWTError, ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(401, "Corporate identity could not be verified") from None

    lock_accounts(session)
    user = session.scalar(
        select(AppUser).where(
            AppUser.issuer == issuer,
            AppUser.subject == subject,
            AppUser.active.is_(True),
        )
    )
    if user is None:
        raise HTTPException(403, "Corporate identity is not authorized")
    if user.auth_changed_at is not None and (
        utc(user.auth_changed_at) >= utc(flow.expires_at) - timedelta(seconds=FLOW_SECONDS)
    ):
        raise HTTPException(403, "Account changed; start a new login")
    now = account_clock(session)
    if utc(flow.expires_at) <= now:
        raise HTTPException(400, "Invalid login transaction")
    old = request.cookies.get(SESSION_COOKIE, "")
    if len(old) == 43:
        session.execute(
            update(AppSession)
            .where(
                AppSession.token_digest == session_digest(old),
                AppSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
    token = secrets.token_urlsafe(32)
    lifetime = timedelta(minutes=config.oidc_session_minutes)
    session.add(
        AppSession(user_id=user.id, token_digest=session_digest(token), expires_at=now + lifetime)
    )
    session.commit()

    result = RedirectResponse("/", headers=PRIVATE_HEADERS, status_code=303)
    result.delete_cookie(FLOW_COOKIE, secure=True, httponly=True, samesite="lax")
    result.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(lifetime.total_seconds()),
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return result


@router.get("/session")
def session_view(request: Request, user: CurrentUser):
    return {"id": user.id, "role": user.role, "csrf": csrf_token(request.cookies[SESSION_COOKIE])}


@router.get("/logout", response_class=HTMLResponse)
def logout_form(request: Request, _user: CurrentUser):
    config_for(request)
    token = csrf_token(request.cookies[SESSION_COOKIE])
    return HTMLResponse(
        '<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Sair do CRM</title>'
        '<form method="post" action="/auth/logout">'
        f'<input type="hidden" name="csrf" value="{token}">'
        '<button type="submit">Confirmar saída</button></form></html>',
        headers={
            **PRIVATE_HEADERS,
            "Referrer-Policy": "same-origin",
            "Content-Security-Policy": "default-src 'none'; form-action 'self'; frame-ancestors 'none'",
        },
    )


@router.post("/logout")
async def logout(request: Request, session: SessionDependency, _user: CurrentUser):
    config_for(request)
    from starlette.concurrency import run_in_threadpool

    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 1024:
            raise HTTPException(400, "Invalid logout request")
    try:
        fields = parse_qs(data.decode("ascii"), max_num_fields=2)
    except ValueError:
        raise HTTPException(400, "Invalid logout request") from None
    values = fields.get("csrf", [])
    verify_csrf(request, values[0] if len(values) == 1 else "", require_origin=True)
    return await run_in_threadpool(revoke_browser_session, request, session)


def revoke_browser_session(request, session):
    session.execute(
        update(AppSession)
        .where(AppSession.token_digest == session_digest(request.cookies[SESSION_COOKIE]))
        .values(revoked_at=account_clock(session))
    )
    session.commit()
    result = RedirectResponse("/", headers=PRIVATE_HEADERS, status_code=303)
    result.delete_cookie(SESSION_COOKIE, secure=True, httponly=True, samesite="lax")
    result.delete_cookie(FLOW_COOKIE, secure=True, httponly=True, samesite="lax")
    return result
