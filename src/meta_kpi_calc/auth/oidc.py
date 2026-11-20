"""Google OIDC over fixed provider endpoints and verified RS256 tokens."""

import hmac

import httpx
import jwt

ISSUER = "https://accounts.google.com"
AUTHORIZE = ISSUER + "/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"


class InvalidIdentity(ValueError):
    pass


def exchange_identity(http: httpx.Client, config, *, code, verifier, nonce, redirect_uri):
    response = http.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": config.oidc_client_id,
            "client_secret": config.oidc_client_secret.get_secret_value(),
            "redirect_uri": redirect_uri,
        },
    )
    response.raise_for_status()
    token = response.json()["id_token"]
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid or header.get("alg") != "RS256":
        raise InvalidIdentity
    response = http.get(JWKS_URL)
    response.raise_for_status()
    candidates = [
        key
        for key in response.json()["keys"]
        if key.get("kid") == kid and key.get("kty") == "RSA" and key.get("use", "sig") == "sig"
    ]
    if len(candidates) != 1:
        raise InvalidIdentity
    claims = jwt.decode(
        token,
        jwt.PyJWK.from_dict(candidates[0], algorithm="RS256").key,
        algorithms=["RS256"],
        audience=config.oidc_client_id,
        issuer=[ISSUER, "accounts.google.com"],
        options={"require": ["iss", "aud", "exp", "sub", "nonce", "hd"], "strict_aud": True},
    )
    if (
        not isinstance(claims["nonce"], str)
        or not hmac.compare_digest(claims["nonce"].encode(), nonce.encode())
        or claims["hd"] != config.oidc_workspace_domain
        or claims.get("azp", config.oidc_client_id) != config.oidc_client_id
        or claims.get("email_verified") is not True
        or not isinstance(claims["sub"], str)
        or not 1 <= len(claims["sub"]) <= 255
    ):
        raise InvalidIdentity
    return ISSUER, claims["sub"]
