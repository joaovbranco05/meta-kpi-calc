"""Diagnostic privacy and rejection regression; persistence is forbidden."""

import hashlib
import hmac
import json
import stat
from datetime import datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from meta_kpi_calc.api.app import create_app
from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.crm.webhook_gateway import create_webhook_gateway_app
from meta_kpi_calc.crm.webhook_logging import WebhookDiagnosticMiddleware

SECRET = "synthetic-app-secret"
PRIVATE = "synthetic-private-value"


def settings(tmp_path):
    return Settings(
        _env_file=None, demo_mode=False, scheduler_enabled=False,
        database_url=f"sqlite:///{tmp_path / 'unused.db'}",
        lead_ads_enabled=True, lead_ads_app_secret=SECRET,
        lead_ads_verify_token=PRIVATE, lead_ads_allowed_page_ids=["10"],
        lead_ads_authorized_sources={"20": "10"},
        lead_ads_diagnostic_log_path=tmp_path / ".logs" / "diagnostic.jsonl",
        log_level="WARNING",
    )


def read_records(config):
    path = config.lead_ads_diagnostic_log_path
    records = [json.loads(line) for line in path.read_text().splitlines()]
    for record in records:
        assert set(record) == {"timestamp", "method", "status", "code"}
        assert datetime.fromisoformat(record["timestamp"]).tzinfo is not None
    assert PRIVATE not in path.read_text() and SECRET not in path.read_text()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    return records


@pytest.mark.parametrize("case,status,code", [
    ("missing_signature", 403, "invalid_signature"),
    ("malformed_signature", 403, "invalid_signature"),
    ("wrong_signature", 403, "invalid_signature"),
    ("page", 403, "page_not_allowed"),
    ("form", 403, "source_not_allowed"),
    ("mismatch", 400, "source_mismatch"),
    ("json", 400, "invalid_payload"),
    ("id", 400, "invalid_payload"),
])
def test_api_rejection_logs_only_approved_fields_without_persistence(tmp_path, case, status, code):
    config = settings(tmp_path)
    app = create_app(config)

    def forbidden(*args, **kwargs):
        pytest.fail("Rejected notifications must never reach persistence")

    app.state.database.session_factory = forbidden
    value = {"page_id": "10", "form_id": "20", "leadgen_id": "30", "private": PRIVATE}
    data = {"object": "page", "entry": [{"id": "10", "changes": [{"field": "leadgen", "value": value}]}]}
    if case == "page":
        data["entry"][0]["id"] = value["page_id"] = "99"
    if case == "form":
        value["form_id"] = "99"
    if case == "mismatch":
        value["page_id"] = "99"
    if case == "id":
        value["leadgen_id"] = 30
    raw = b'{"private":' if case == "json" else json.dumps(data).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    if case == "malformed_signature":
        signature = PRIVATE
    if case == "wrong_signature":
        signature = "sha256=" + "0" * 64
    headers = {} if case == "missing_signature" else {"x-hub-signature-256": signature}
    with TestClient(app) as client:
        response = client.post("/webhooks/meta/lead-ads", content=raw, headers=headers)
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    records = read_records(config)
    assert len(records) == 1
    assert records[0] | {"timestamp": None} == {"timestamp": None, "method": "POST", "status": status, "code": code}
    assert signature not in config.lead_ads_diagnostic_log_path.read_text()
    assert not (tmp_path / "unused.db").exists()


def test_verification_challenge_and_query_are_not_logged(tmp_path):
    config = settings(tmp_path)
    with TestClient(create_app(config)) as client:
        response = client.get("/webhooks/meta/lead-ads", params={
            "hub.mode": "subscribe", "hub.verify_token": PRIVATE, "hub.challenge": PRIVATE,
        })
    assert response.status_code == 200 and response.text == PRIVATE
    assert read_records(config)[0]["code"] == "verified"


def test_gateway_logs_upstream_rejection_and_local_blocks_without_details(tmp_path):
    config = settings(tmp_path)
    seen = []

    async def upstream(request):
        seen.append(request)
        return httpx.Response(403, json={"detail": {"code": "page_not_allowed", "private": PRIVATE}})

    app = create_webhook_gateway_app(config, transport=httpx.MockTransport(upstream))
    with TestClient(app) as client:
        assert client.post("/webhooks/meta/lead-ads", content=PRIVATE).status_code == 403
        assert client.get("/docs", params={"private": PRIVATE}).status_code == 404
        assert client.put("/webhooks/meta/lead-ads").status_code == 405
    assert len(seen) == 1 and seen[0].content == PRIVATE.encode()
    assert [(r["status"], r["code"]) for r in read_records(config)] == [
        (403, "page_not_allowed"), (404, "not_found"), (405, "method_not_allowed"),
    ]


@pytest.mark.parametrize("code", [PRIVATE, [PRIVATE], {"secret": PRIVATE}])
def test_untrusted_upstream_codes_cannot_enter_logs(tmp_path, code):
    config = settings(tmp_path)
    transport = httpx.MockTransport(lambda request: httpx.Response(403, json={"detail": {"code": code}}))
    with TestClient(create_webhook_gateway_app(config, transport=transport)) as client:
        assert client.post("/webhooks/meta/lead-ads").status_code == 403
    assert read_records(config)[0]["code"] == "rejected_unknown"


def test_log_write_failure_keeps_response_and_hides_exception(tmp_path, monkeypatch, capsys):
    config = settings(tmp_path)
    with TestClient(create_app(config)) as client:
        def unavailable(self):
            raise OSError(PRIVATE)
        monkeypatch.setattr(WebhookDiagnosticMiddleware, "_open", unavailable)
        response = client.post("/webhooks/meta/lead-ads")
    assert response.status_code == 403
    captured = capsys.readouterr().err
    assert PRIVATE not in captured
    record = json.loads(captured)
    assert set(record) == {"timestamp", "method", "status", "code"}
    assert record["code"] == "diagnostic_log_unavailable"


def test_diagnostic_file_cannot_follow_symlink(tmp_path):
    target = tmp_path / "private.txt"
    target.write_text(PRIVATE)
    directory = tmp_path / ".logs"
    directory.mkdir()
    link = directory / "diagnostic.jsonl"
    link.symlink_to(target)

    async def unused(scope, receive, send):
        pytest.fail("No request should run with an unsafe log destination")

    with pytest.raises(OSError):
        WebhookDiagnosticMiddleware(unused, path=link)
    assert target.read_text() == PRIVATE
