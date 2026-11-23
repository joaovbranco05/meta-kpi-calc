"""Browser login boundary and private session inspection."""

import base64
import hashlib
import hmac
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
    BROWSER_COOKIE,
    SESSION_COOKIE,
    CurrentUser,
    SessionDependency,
    csrf_token,
    session_binding,
    session_digest,
    valid_cookie,
)
from meta_kpi_calc.auth.models import AppSession, AppUser, BrowserContext, OIDCFlow
from meta_kpi_calc.auth.oidc import AUTHORIZE, exchange_identity
from meta_kpi_calc.auth.presentation import ENTRY_CSP, entry_page

router = APIRouter(prefix="/auth")
BROWSER_SECONDS = 86400
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
    state, verifier, nonce = (secrets.token_urlsafe(32) for _ in range(3))
    lock_accounts(session)
    now = account_clock(session)
    cookie, context = load_browser(request, session, now)
    if context is None:
        cookie = secrets.token_urlsafe(32)
        context = BrowserContext(
            digest=session_digest(cookie),
            generation=0,
            expires_at=now + timedelta(seconds=BROWSER_SECONDS),
        )
        session.add(context)
    context.generation += 1
    session.execute(delete(OIDCFlow).where(OIDCFlow.browser_digest == context.digest))
    session.execute(delete(OIDCFlow).where(OIDCFlow.expires_at <= now))
    session.add(
        OIDCFlow(
            state_digest=session_digest(state),
            browser_digest=context.digest,
            generation=context.generation,
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
        BROWSER_COOKIE,
        cookie,
        expires=utc(context.expires_at),
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return result


def verify_callback(request: Request, session: SessionDependency, *, expected_email=None):
    config, origin = config_for(request)
    query = request.query_params
    state, code = query.get("state", ""), query.get("code", "")
    browser = request.cookies.get(BROWSER_COOKIE, "")
    if len(query.getlist("state")) != 1 or not valid_cookie(state) or not valid_cookie(browser):
        raise HTTPException(400, "Invalid login transaction")
    flow = session.execute(
        delete(OIDCFlow)
        .where(
            OIDCFlow.state_digest == session_digest(state),
            OIDCFlow.browser_digest == session_digest(browser),
            OIDCFlow.expires_at > account_clock(session),
        )
        .returning(OIDCFlow.verifier, OIDCFlow.nonce, OIDCFlow.expires_at, OIDCFlow.generation)
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
                expected_email=expected_email,
            )
    except (httpx.HTTPError, jwt.PyJWTError, ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(401, "Corporate identity could not be verified") from None

    lock_accounts(session)
    _, context = load_browser(request, session, account_clock(session))
    if context is None or context.generation != flow.generation:
        raise HTTPException(400, "Invalid login transaction")
    now = account_clock(session)
    if min(utc(flow.expires_at), utc(context.expires_at)) <= now:
        raise HTTPException(400, "Invalid login transaction")
    return config, issuer, subject, flow, context


@router.get("/callback")
def callback(request: Request, session: SessionDependency):
    config, issuer, subject, flow, context = verify_callback(request, session)
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
    if min(utc(flow.expires_at), utc(context.expires_at)) <= now:
        raise HTTPException(400, "Invalid login transaction")
    revoke_context_sessions(session, context, now)
    token = secrets.token_urlsafe(32)
    lifetime = min(timedelta(minutes=config.oidc_session_minutes), utc(context.expires_at) - now)
    session.add(
        AppSession(
            user_id=user.id,
            token_digest=session_digest(token),
            expires_at=now + lifetime,
            browser_digest=context.digest,
        )
    )
    session.commit()

    result = RedirectResponse("/", headers=PRIVATE_HEADERS, status_code=303)
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
    token = request.cookies[SESSION_COOKIE]
    return {
        "id": user.id,
        "role": user.role,
        "csrf": csrf_token(token),
        "binding": session_binding(token),
    }


@router.get("/logout", response_class=HTMLResponse)
def logout_form(request: Request, session: SessionDependency):
    config_for(request)
    cookie, context = load_browser(request, session, account_clock(session))
    if context is None:
        return RedirectResponse("/", status_code=303)
    token = csrf_token(cookie)
    return HTMLResponse(
        entry_page(logout_token=token),
        headers={
            **PRIVATE_HEADERS,
            "Referrer-Policy": "same-origin",
            "Content-Security-Policy": ENTRY_CSP,
        },
    )


@router.post("/logout")
async def logout(request: Request, session: SessionDependency):
    _, origin = config_for(request)
    if request.headers.get("origin") != origin:
        raise HTTPException(403, "Invalid request origin")
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
    supplied = values[0] if len(values) == 1 else ""
    return await run_in_threadpool(revoke_browser_session, request, session, supplied)


def load_browser(request, session, now):
    cookie = request.cookies.get(BROWSER_COOKIE, "")
    context = session.get(BrowserContext, session_digest(cookie)) if valid_cookie(cookie) else None
    if context is not None and utc(context.expires_at) <= now:
        context = None
    return cookie, context


def revoke_context_sessions(session, context, now):
    session.execute(
        update(AppSession)
        .where(
            AppSession.browser_digest == context.digest,
            AppSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )


def revoke_browser_session(request, session, supplied):
    lock_accounts(session)
    now = account_clock(session)
    cookie, context = load_browser(request, session, now)
    if context is None or not hmac.compare_digest(supplied.encode(), csrf_token(cookie).encode()):
        raise HTTPException(403, "Invalid CSRF token")
    context.generation += 1
    session.execute(delete(OIDCFlow).where(OIDCFlow.browser_digest == context.digest))
    revoke_context_sessions(session, context, now)
    session.commit()
    result = RedirectResponse("/", headers=PRIVATE_HEADERS, status_code=303)
    result.delete_cookie(SESSION_COOKIE, secure=True, httponly=True, samesite="lax")
    return result


@router.get("/edge-entry")
def edge_entry(request: Request, session: SessionDependency):
    from meta_kpi_calc.auth.dependencies import authenticate_session

    try:
        authenticate_session(request, session)
    except HTTPException as error:
        if error.status_code != 401:
            raise
        return HTMLResponse(
            entry_page(),
            status_code=401,
            headers={**PRIVATE_HEADERS, "Content-Security-Policy": ENTRY_CSP},
        )
    return HTMLResponse("", status_code=204, headers=PRIVATE_HEADERS)


@router.get("/edge-session")
def edge_session(request: Request, _user: CurrentUser):
    from fastapi import Response

    return Response(
        status_code=204,
        headers={
            "X-RCTEC-Session": session_binding(request.cookies[SESSION_COOKIE]),
            **PRIVATE_HEADERS,
        },
    )


def require_download_binding(request: Request, binding: str = "") -> None:
    token = request.cookies.get(SESSION_COOKIE, "")
    if not hmac.compare_digest(binding.encode(), session_binding(token).encode()):
        raise HTTPException(403, "Download does not belong to this session")
