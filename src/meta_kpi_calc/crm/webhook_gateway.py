"""Minimal edge gateway for exposing only the Meta Lead Ads callback.

Run separately from the CRM API and point any temporary tunnel at this app.
The CRM API itself must remain bound to loopback. This gateway has no docs,
health endpoint, static files, or configurable public upstream.
"""

import ipaddress
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.core.logging import configure_logging
from meta_kpi_calc.crm.webhook_logging import WebhookDiagnosticMiddleware

WEBHOOK_PATH = "/webhooks/meta/lead-ads"
ALLOWED_METHODS = ("GET", "POST")
DEFAULT_UPSTREAM = "http://127.0.0.1:8000"


def _validate_upstream(value: str) -> str:
    try:
        parsed = urlsplit(value)
        address = ipaddress.ip_address(parsed.hostname or "")
        valid = (parsed.scheme == "http" and address.is_loopback and
                 parsed.port in (None, 80, 8000) and
                 parsed.username is None and parsed.password is None and
                 parsed.path in ("", "/") and not parsed.query and not parsed.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Webhook gateway upstream must be a loopback HTTP URL.")
    return value.rstrip("/")


def create_webhook_gateway_app(
    settings: Settings | None = None,
    *,
    upstream_url: str = DEFAULT_UPSTREAM,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Create an allowlist proxy; only the exact callback path reaches upstream."""
    app_settings = settings or Settings()
    configure_logging(app_settings)
    upstream = _validate_upstream(upstream_url)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        async with httpx.AsyncClient(
            base_url=upstream,
            transport=transport,
            follow_redirects=False,
            timeout=httpx.Timeout(connect=2, read=15, write=5, pool=2),
        ) as client:
            application.state.upstream_client = client
            yield

    application = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    application.router.redirect_slashes = False
    if app_settings.lead_ads_diagnostic_log_path is not None:
        application.add_middleware(
            WebhookDiagnosticMiddleware, path=app_settings.lead_ads_diagnostic_log_path,
            webhook_only=False,
        )

    @application.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def gateway(request: Request, path: str) -> Response:
        raw_path = request.scope.get("raw_path", b"")
        if request.url.path != WEBHOOK_PATH or raw_path != WEBHOOK_PATH.encode():
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        if request.method not in ALLOWED_METHODS:
            return JSONResponse(
                status_code=405,
                content={"detail": "Method Not Allowed"},
                headers={"Allow": ", ".join(ALLOWED_METHODS)},
            )

        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > app_settings.lead_ads_body_max_bytes:
                return JSONResponse(status_code=413, content={"detail": "Payload Too Large"})
            body.extend(chunk)

        # Only protocol headers used by the webhook are forwarded. In particular,
        # cookies, authorization, host and caller-supplied forwarding headers are dropped.
        headers = {
            key: request.headers[key]
            for key in ("content-type", "accept", "x-hub-signature-256")
            if key in request.headers
        }
        try:
            upstream_response = await request.app.state.upstream_client.request(
                request.method,
                WEBHOOK_PATH,
                params=request.query_params,
                content=bytes(body) if request.method == "POST" else None,
                headers=headers,
            )
        except httpx.TransportError:
            return JSONResponse(status_code=502, content={"detail": "Webhook upstream unavailable"})

        response_headers = {}
        content_type = upstream_response.headers.get("content-type")
        if content_type:
            response_headers["content-type"] = content_type
        return Response(
            content=upstream_response.content,
            status_code=upstream_response.status_code,
            headers=response_headers,
        )

    return application


app = create_webhook_gateway_app()
