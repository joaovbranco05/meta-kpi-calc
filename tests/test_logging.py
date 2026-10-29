import io
import logging

from pydantic import SecretStr
from uvicorn.logging import AccessFormatter

from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.core.logging import REDACTED, RedactingFilter, configure_logging, redact_data


def test_redact_data_handles_nested_sensitive_values() -> None:
    payload = {
        "Authorization": "Bearer abc",
        "nested": [{"access_token": "abc"}, "access_token=abc&other=1"],
    }

    redacted = redact_data(payload)

    assert redacted["Authorization"] == REDACTED
    assert redacted["nested"][0]["access_token"] == REDACTED
    assert "abc" not in redacted["nested"][1]


def test_redact_data_removes_explicit_secret_from_mapping_keys() -> None:
    sentinel = "mapping-key-secret"

    redacted = redact_data({sentinel: {"value": 1}}, (sentinel,))

    assert sentinel not in repr(redacted)
    assert redacted == {REDACTED: {"value": 1}}


def test_configured_formatter_never_emits_concrete_token(
    tmp_path, capsys
) -> None:
    sentinel = "super-secret-token-123"
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'real.db'}",
        demo_database_url=f"sqlite:///{tmp_path / 'demo.db'}",
        meta_access_token=SecretStr(sentinel),
    )
    configure_logging(settings)

    logging.getLogger("security-test").error(
        "authorization=Bearer %s access_token=%s", sentinel, sentinel
    )

    captured = capsys.readouterr()
    assert sentinel not in captured.err
    assert REDACTED in captured.err


def test_configure_logging_protects_preexisting_handlers(tmp_path) -> None:
    sentinel = "super-secret-token-123"
    stream = io.StringIO()
    existing_handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    root.addHandler(existing_handler)
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'real.db'}",
        demo_database_url=f"sqlite:///{tmp_path / 'demo.db'}",
        meta_access_token=SecretStr(sentinel),
    )

    try:
        configure_logging(settings)
        logging.getLogger("preexisting-handler-test").error("token=%s", sentinel)
    finally:
        root.removeHandler(existing_handler)

    assert sentinel not in stream.getvalue()
    assert REDACTED in stream.getvalue()


def test_preexisting_handler_cannot_leak_token_from_traceback(tmp_path) -> None:
    sentinel = "qa-traceback-secret"
    stream = io.StringIO()
    existing_handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    root.addHandler(existing_handler)
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'real.db'}",
        demo_database_url=f"sqlite:///{tmp_path / 'demo.db'}",
        meta_access_token=SecretStr(sentinel),
    )

    try:
        configure_logging(settings)
        try:
            raise RuntimeError(sentinel)
        except RuntimeError:
            logging.getLogger("traceback-test").exception("request failed")
    finally:
        root.removeHandler(existing_handler)

    assert sentinel not in stream.getvalue()
    assert REDACTED in stream.getvalue()


def test_uvicorn_access_filter_preserves_formatter_arguments_and_redacts_secrets() -> None:
    secrets = ("synthetic-verify", "synthetic-app-secret", "synthetic-page-token")
    path = (
        "/webhooks/meta/lead-ads?hub.verify_token=synthetic-verify"
        "&app_secret=synthetic-app-secret&access_token=synthetic-page-token"
    )
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:12345", "GET", path, "1.1", 200),
        None,
    )

    assert RedactingFilter(secrets).filter(record)
    formatted = AccessFormatter().format(record)

    assert len(record.args) == 5
    assert all(secret not in formatted for secret in secrets)
    assert REDACTED in formatted
