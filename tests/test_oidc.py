"""OIDC with a synthetic signed provider and disposable application databases."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from test_authorization import _account, _login

from meta_kpi_calc.api.app import create_app
from meta_kpi_calc.auth.dependencies import SESSION_COOKIE
from meta_kpi_calc.auth.models import AppSession, AppUser
from meta_kpi_calc.auth.oidc import ISSUER, JWKS_URL, TOKEN_URL

ORIGIN = "https://crm.invalid"


class Provider:
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        self.jwk["kid"] = "test"
        self.codes = {}
        self.exchange_started = None
        self.resume = None

    def __call__(self, request):
        if str(request.url) == JWKS_URL:
            return httpx.Response(200, json={"keys": [self.jwk]})
        assert str(request.url) == TOKEN_URL
        form = parse_qs(request.content.decode())
        code = form["code"][0]
        claims, challenge, key = self.codes.pop(code, (None, None, None))
        if claims is None:
            return httpx.Response(400, json={"error": "invalid_grant"})
        import base64
        import hashlib

        verifier = form["code_verifier"][0]
        actual = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        assert actual == challenge
        assert form["redirect_uri"] == [ORIGIN + "/auth/callback"]
        if self.exchange_started is not None:
            self.exchange_started.set()
            assert self.resume.wait(10)
        return httpx.Response(
            200,
            json={
                "id_token": jwt.encode(
                    claims, key or self.key, algorithm="RS256", headers={"kid": "test"}
                )
            },
        )


def build(database, provider):
    settings, db = database
    config = settings.model_copy(
        update={
            "demo_mode": False,
            "database_url": settings.active_database_url,
            "oidc_public_origin": ORIGIN,
            "oidc_client_id": "test-client",
            "oidc_client_secret": SecretStr("test-client-secret"),
            "oidc_workspace_domain": "workspace.invalid",
        }
    )
    return create_app(config, oidc_transport=httpx.MockTransport(provider)), db


def begin(client, provider, code, *, key=None, **overrides):
    response = client.get("/auth/login", params={"next": "https://outside.invalid"})
    assert response.status_code == 303
    assert response.headers["cache-control"] == "no-store"
    assert "HttpOnly" in response.headers["set-cookie"]
    params = {k: v[0] for k, v in parse_qs(urlsplit(response.headers["location"]).query).items()}
    assert params["code_challenge_method"] == "S256"
    assert params["redirect_uri"] == ORIGIN + "/auth/callback"
    claims = {
        "iss": "accounts.google.com",
        "sub": "subject",
        "aud": "test-client",
        "exp": datetime.now(UTC) + timedelta(minutes=1),
        "nonce": params["nonce"],
        "hd": "workspace.invalid",
        "email_verified": True,
    }
    provider.codes[code] = (claims | overrides, params["code_challenge"], key)
    return {"state": params["state"], "code": code}


def test_login_csrf_expiry_logout_and_replay(migrated_database):
    provider = Provider()
    app, db = build(migrated_database, provider)
    with db.session_factory.begin() as session:
        session.add(AppUser(issuer=ISSUER, subject="subject", role="usuario", active=True))
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as client:
        params = begin(client, provider, "first")
        with TestClient(app, base_url=ORIGIN, follow_redirects=False) as other:
            assert other.get("/auth/callback", params=params).status_code == 400
        response = client.get("/auth/callback", params=params)
        assert response.status_code == 303 and response.headers["location"] == "/"
        assert (
            "Secure" in response.headers["set-cookie"]
            and "HttpOnly" in response.headers["set-cookie"]
        )
        old_cookie = client.cookies[SESSION_COOKIE]
        assert client.get("/auth/callback", params=params).status_code == 400
        replay = begin(client, provider, "unused")
        replay["code"] = "first"
        assert client.get("/auth/callback", params=replay).status_code == 401
        assert client.get("/api/campaigns").status_code == 403
        assert client.get("/api/crm/leads").status_code == 200
        assert client.post("/api/crm/leads/1/activities", json={}).status_code == 403
        identity = client.get("/auth/session").json()
        assert (
            client.post(
                "/api/crm/leads/1/activities",
                json={},
                headers={"Origin": "https://wrong.invalid", "X-CSRF-Token": identity["csrf"]},
            ).status_code
            == 403
        )
        form = client.get("/auth/logout")
        assert form.status_code == 200
        assert form.headers["referrer-policy"] == "same-origin"
        assert client.get("/auth/session").status_code == 200
        assert client.post("/auth/logout", data={"csrf": identity["csrf"]}).status_code == 403
        assert (
            client.post(
                "/auth/logout", headers={"Origin": ORIGIN}, data={"csrf": identity["csrf"]}
            ).status_code
            == 303
        )
        assert (
            client.get(
                "/auth/session", headers={"Cookie": f"{SESSION_COOKIE}={old_cookie}"}
            ).status_code
            == 401
        )

        assert (
            client.get("/auth/callback", params=begin(client, provider, "fresh")).status_code == 303
        )
        with db.session_factory.begin() as session:
            for row in session.scalars(select(AppSession)):
                row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        assert client.get("/auth/session").status_code == 401


@pytest.mark.parametrize(
    ("claims", "expected"),
    [
        ({"iss": "https://wrong.invalid"}, 401),
        ({"aud": "other-app"}, 401),
        ({"exp": 1}, 401),
        ({"nonce": "replayed"}, 401),
        ({"hd": "wrong.invalid"}, 401),
        ({"sub": "unknown"}, 403),
        ({"sub": "inactive"}, 403),
        ({"email_verified": False}, 401),
    ],
)
def test_invalid_identity(migrated_database, claims, expected):
    provider = Provider()
    app, db = build(migrated_database, provider)
    with db.session_factory.begin() as session:
        session.add_all(
            [
                AppUser(issuer=ISSUER, subject="subject", role="usuario", active=True),
                AppUser(issuer=ISSUER, subject="inactive", role="admin", active=False),
            ]
        )
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as client:
        assert (
            client.get(
                "/auth/callback", params=begin(client, provider, "bad", **claims)
            ).status_code
            == expected
        )
        assert SESSION_COOKIE not in client.cookies
        params = begin(
            client,
            provider,
            "wrong-signature",
            key=rsa.generate_private_key(public_exponent=65537, key_size=2048),
        )
        assert client.get("/auth/callback", params=params).status_code == 401


@pytest.mark.parametrize("active", [True, False])
def test_session_issuance_races_account_change(migrated_database, active):
    provider = Provider()
    provider.exchange_started, provider.resume = Event(), Event()
    app, db = build(migrated_database, provider)
    with db.session_factory.begin() as session:
        admin = _account(session, "admin", "admin")
        user = AppUser(issuer=ISSUER, subject="subject", role="usuario", active=True)
        session.add(user)
        session.flush()
        user_id = user.id
    with (
        TestClient(app, base_url=ORIGIN, follow_redirects=False) as caller,
        TestClient(app, base_url=ORIGIN, follow_redirects=False) as operator,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        _login(operator, admin)
        params = begin(caller, provider, "concurrent")
        attempt = pool.submit(caller.get, "/auth/callback", params=params)
        try:
            assert provider.exchange_started.wait(10)
            assert (
                operator.put(
                    f"/api/admin/users/{user_id}", json={"role": "admin", "active": active}
                ).status_code
                == 200
            )
        finally:
            provider.resume.set()
        assert attempt.result(timeout=10).status_code == 403
        assert SESSION_COOKIE not in caller.cookies
    with db.session_factory() as session:
        assert session.scalar(select(AppSession).where(AppSession.user_id == user_id)) is None


def test_switch_account_revokes_previous_cookie(migrated_database):
    provider = Provider()
    app, db = build(migrated_database, provider)
    with db.session_factory.begin() as session:
        session.add_all(
            [
                AppUser(issuer=ISSUER, subject="subject", role="usuario", active=True),
                AppUser(issuer=ISSUER, subject="administrator", role="admin", active=True),
            ]
        )
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as client:
        assert (
            client.get("/auth/callback", params=begin(client, provider, "operator")).status_code
            == 303
        )
        previous = client.cookies[SESSION_COOKIE]
        params = begin(client, provider, "admin", sub="administrator")
        assert client.get("/auth/callback", params=params).status_code == 303
        assert client.cookies[SESSION_COOKIE] != previous
        assert client.get("/api/campaigns").status_code == 200
        with TestClient(app, base_url=ORIGIN) as old_tab:
            old_tab.cookies.set(SESSION_COOKIE, previous)
            assert old_tab.get("/auth/session").status_code == 401


def test_oidc_log_redaction():
    from meta_kpi_calc.core.logging import redact_text

    raw = (
        "GET /auth/callback?code=synthetic-code&state=synthetic-state "
        "Cookie: __Host-rctec_session=synthetic-session; __Host-rctec_oidc=synthetic-flow"
    )
    assert "synthetic-" not in redact_text(raw)
