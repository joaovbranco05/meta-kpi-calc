"""Opt-in webhook diagnostics with an explicit, four-field output allowlist."""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from starlette.types import ASGIApp, Message, Receive, Scope, Send

WEBHOOK_PATH = "/webhooks/meta/lead-ads"
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE", "CONNECT"}
CODES = {
    "lead_ads_disabled", "invalid_verification", "body_too_large",
    "invalid_signature", "invalid_payload", "page_not_allowed",
    "source_mismatch", "source_not_allowed", "validation_error",
    "database_unavailable", "internal_error",
}


def response_code(status: int, method: str, body: bytes) -> str:
    """Never copy arbitrary response content into a diagnostic record."""
    if status < 400:
        return "verified" if method == "GET" else "accepted"
    try:
        payload = json.loads(body)
        detail = payload.get("detail") if isinstance(payload, dict) else None
        code = detail.get("code") if isinstance(detail, dict) else None
        if isinstance(code, str) and code in CODES:
            return code
    except (ValueError, UnicodeError, RecursionError):
        pass
    return {
        404: "not_found", 405: "method_not_allowed", 413: "body_too_large",
        500: "internal_error", 502: "upstream_unavailable",
    }.get(status, "rejected_unknown")


class WebhookDiagnosticMiddleware:
    """Observe responses without reading requests or changing validation/ACKs."""

    def __init__(self, app: ASGIApp, *, path: Path, webhook_only: bool = True):
        self.app = app
        self.path = Path(path)
        self.webhook_only = webhook_only
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
        # Fail startup if the private destination cannot be opened safely.
        os.close(self._open())

    def _open(self) -> int:
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(fd, 0o600)
        except BaseException:
            os.close(fd)
            raise
        return fd

    def _write(self, method: str, status: int, code: str) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "method": method if method in METHODS else "OTHER",
            "status": status,
            "code": code,
        }
        try:
            fd = self._open()
            with os.fdopen(fd, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, separators=(",", ":")) + "\n")
        except OSError:
            # Logging failures must not change the webhook response or expose exceptions.
            record["code"] = "diagnostic_log_unavailable"
            sys.stderr.write(json.dumps(record, separators=(",", ":")) + "\n")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or (self.webhook_only and scope.get("path") != WEBHOOK_PATH):
            await self.app(scope, receive, send)
            return
        status = 500
        body = bytearray()
        overflow = False

        async def observe(message: Message) -> None:
            nonlocal status, overflow
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body" and status >= 400:
                chunk = message.get("body", b"")
                if len(body) + len(chunk) <= 4096 and not overflow:
                    body.extend(chunk)
                else:
                    body.clear()
                    overflow = True
            await send(message)

        try:
            await self.app(scope, receive, observe)
        finally:
            method = scope.get("method", "OTHER")
            self._write(method, status, response_code(status, method, bytes(body)))
