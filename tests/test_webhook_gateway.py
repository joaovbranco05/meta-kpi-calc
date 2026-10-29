"""Public-edge allowlist tests; upstream calls are always mocked."""

import httpx
import pytest
from fastapi.testclient import TestClient

from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.crm.webhook_gateway import create_webhook_gateway_app


@pytest.fixture
def gateway_transport():
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, text="accepted", headers={"X-Upstream-Secret": "must-not-forward"})

    return httpx.MockTransport(handler), calls


def test_gateway_only_forwards_exact_callback_and_get_post(gateway_transport):
    transport, calls = gateway_transport
    app = create_webhook_gateway_app(Settings(_env_file=None), transport=transport)
    with TestClient(app) as client:
        response = client.get("/webhooks/meta/lead-ads", params={
            "hub.mode": "subscribe", "hub.verify_token": "synthetic-verify", "hub.challenge": "42",
        })
        assert response.status_code == 200 and response.text == "accepted"
        assert calls[-1].url.path == "/webhooks/meta/lead-ads"
        assert calls[-1].url.params["hub.verify_token"] == "synthetic-verify"

        response = client.post("/webhooks/meta/lead-ads", content=b'{"object":"page"}', headers={
            "Content-Type": "application/json", "X-Hub-Signature-256": "sha256=signature",
            "Authorization": "Bearer do-not-forward", "Cookie": "private=cookie",
            "X-Forwarded-Host": "attacker.example",
        })
        assert response.status_code == 200
        assert calls[-1].headers["x-hub-signature-256"] == "sha256=signature"
        assert "authorization" not in calls[-1].headers
        assert "cookie" not in calls[-1].headers
        assert "x-forwarded-host" not in calls[-1].headers
        assert "x-upstream-secret" not in response.headers
        assert len(calls) == 2


@pytest.mark.parametrize("path", [
    "/", "/health", "/docs", "/openapi.json", "/redoc",
    "/api/crm/leads", "/api/meta/sync", "/api/dashboard/summary",
    "/webhooks/meta/lead-ads/", "/webhooks/meta/lead-ads/extra",
    "/webhooks/meta/%6cead-ads",
])
def test_gateway_denies_every_other_path_without_upstream_call(gateway_transport, path):
    transport, calls = gateway_transport
    app = create_webhook_gateway_app(Settings(_env_file=None), transport=transport)
    with TestClient(app) as client:
        assert client.get(path).status_code == 404
        assert client.post(path, content=b"ignored").status_code == 404
    assert calls == []


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
def test_gateway_rejects_other_methods_and_oversize_body(gateway_transport, method):
    transport, calls = gateway_transport
    settings = Settings(_env_file=None, lead_ads_body_max_bytes=1024)
    app = create_webhook_gateway_app(settings, transport=transport)
    with TestClient(app) as client:
        response = client.request(method, "/webhooks/meta/lead-ads", content=b"ignored")
        assert response.status_code == 405
        assert response.headers["allow"] == "GET, POST"
        assert client.post("/webhooks/meta/lead-ads", content=b"x" * 1025).status_code == 413
    assert calls == []


@pytest.mark.parametrize("url", [
    "https://127.0.0.1:8000", "http://example.com:8000", "http://127.0.0.1:9000",
    "http://user:pass@127.0.0.1:8000", "http://127.0.0.1:8000/private",
])
def test_gateway_refuses_unsafe_upstream(url):
    with pytest.raises(ValueError):
        create_webhook_gateway_app(Settings(_env_file=None), upstream_url=url)


def test_gateway_hides_upstream_transport_details(gateway_transport):
    async def unavailable(_request):
        raise httpx.ConnectError("synthetic-private-detail")

    app = create_webhook_gateway_app(
        Settings(_env_file=None), transport=httpx.MockTransport(unavailable)
    )
    with TestClient(app) as client:
        response = client.get("/webhooks/meta/lead-ads")
    assert response.status_code == 502
    assert "synthetic-private-detail" not in response.text
