"""Central logging configuration with defensive secret redaction."""

import json
import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

from meta_kpi_calc.core.config import Settings

REDACTED = "[REDACTED]"
SENSITIVE_KEYS = {
    "access_token",
    "authorization",
    "api_key",
    "secret",
    "password",
    "cookie",
}


def redact_text(value: str, secrets: Sequence[str] = ()) -> str:
    redacted = re.sub(
        r"(?i)\bBearer\s+[^\s,;]+", f"Bearer {REDACTED}", value
    )
    redacted = re.sub(
        r"(?i)(access_token(?:=|\s*:\s*)[\"']?)[^\s&;,\"']+",
        rf"\1{REDACTED}",
        redacted,
    )
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, REDACTED)
    return redacted


def redact_data(value: Any, secrets: Sequence[str] = ()) -> Any:
    if isinstance(value, Mapping):
        return {
            key: (
                REDACTED
                if str(key).lower() in SENSITIVE_KEYS
                else redact_data(item, secrets)
            )
            for key, item in value.items()
        }
    if isinstance(value, str):
        return redact_text(value, secrets)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return type(value)(redact_data(item, secrets) for item in value)
    return value


class RedactingFormatter(logging.Formatter):
    def __init__(self, *args: Any, secrets: Sequence[str] = (), **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._secrets = tuple(secrets)

    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record), self._secrets)


class RedactingFilter(logging.Filter):
    """Redact a record before any existing handler has a chance to emit it."""

    def __init__(self, secrets: Sequence[str] = ()) -> None:
        super().__init__()
        self._secrets = tuple(secrets)

    def filter(self, record: logging.LogRecord) -> bool:
        # Render once before redaction. Redacting the format template itself can
        # remove a ``%s`` placeholder and leave logging with unmatched args.
        record.msg = redact_text(record.getMessage(), self._secrets)
        record.args = ()
        if record.exc_info:
            exception_text = logging.Formatter().formatException(record.exc_info)
            record.exc_text = redact_text(exception_text, self._secrets)
            # Prevent a pre-existing formatter from rebuilding an unsafe
            # traceback after this filter has sanitized it.
            record.exc_info = None
        if record.exc_text:
            record.exc_text = redact_text(record.exc_text, self._secrets)
        return True


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger()
    token = (
        settings.meta_access_token.get_secret_value()
        if settings.meta_access_token
        else ""
    )

    for handler in list(root.handlers):
        if getattr(handler, "_meta_kpi_handler", False):
            root.removeHandler(handler)

    redacting_filter = RedactingFilter((token,))
    for existing_handler in root.handlers:
        for existing_filter in list(existing_handler.filters):
            if isinstance(existing_filter, RedactingFilter):
                existing_handler.removeFilter(existing_filter)
        existing_handler.addFilter(redacting_filter)

    handler = logging.StreamHandler()
    handler._meta_kpi_handler = True  # type: ignore[attr-defined]
    handler.addFilter(redacting_filter)
    handler.setFormatter(
        RedactingFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            secrets=(token,),
        )
    )
    root.addHandler(handler)
    root.setLevel(settings.log_level)


def safe_json(value: Any, secrets: Sequence[str] = ()) -> str:
    return json.dumps(redact_data(value, secrets), ensure_ascii=False, default=str)
