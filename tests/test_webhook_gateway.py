"""Public ASGI boundary and administrative separation."""

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_lead_ads import graph, notification, options, payload, signed

from meta_kpi_calc.crm.inbox_models import WebhookEvent
from meta_kpi_calc.crm.processing import process_events
from meta_kpi_calc.crm.webhook_gateway import create_webhook_gateway_app

CALLBACK = "/webhooks/meta/lead-ads"


def test_public_router_only_mounts_meta_callback(migrated_database):
    settings, _ = migrated_database
    app = create_webhook_gateway_app(options(settings))
    paths = app.openapi()["paths"]
    assert set(paths) == {CALLBACK}
    assert set(paths[CALLBACK]) == {"get", "post"}
    with TestClient(app, follow_redirects=False) as client:
        for path in (
            "/",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/health",
            "/api/crm/leads",
            "/api/meta/sync",
            "/api/dashboard/summary",
            f"{CALLBACK}/",
            "/webhooks/meta/lead%2Dads",
        ):
            for method in ("GET", "POST", "PUT"):
                assert client.request(method, path).status_code == 404


@pytest.mark.parametrize(
    "method", ["HEAD", "OPTIONS", "PUT", "PATCH", "DELETE", "TRACE", "CONNECT"]
)
def test_callback_rejects_other_methods(migrated_database, method):
    settings, _ = migrated_database
    with TestClient(create_webhook_gateway_app(settings)) as client:
        response = client.request(method, CALLBACK)
    assert response.status_code == 405
    assert response.headers["allow"] == "GET, POST"


def test_admin_does_not_mount_callback(migrated_database):
    from meta_kpi_calc.api.app import create_app

    settings, _ = migrated_database
    with TestClient(create_app(settings), follow_redirects=False) as client:
        assert client.get(CALLBACK).status_code == 404
        assert client.post(CALLBACK, **signed(notification())).status_code == 404


def test_public_service_writes_to_worker_inbox_without_admin(migrated_database):
    settings, worker_database = migrated_database
    config = options(settings).model_copy(update={"database_url": settings.active_database_url})
    app = create_webhook_gateway_app(config)
    assert app.state.database.engine is not worker_database.engine
    with TestClient(app) as client:
        for _ in range(2):
            response = client.post(CALLBACK, **signed(notification()))
            assert response.status_code == 200
            with worker_database.session_factory() as session:
                assert session.scalar(select(func.count()).select_from(WebhookEvent)) == 1
                assert session.scalar(select(WebhookEvent.status)) == "PENDING"

    result = process_events(
        worker_database.session_factory,
        graph(lambda _: httpx.Response(200, json=payload())),
        config,
    )
    assert result["completed"] == 1
    with worker_database.session_factory() as session:
        assert session.scalar(select(WebhookEvent.status)) == "COMPLETED"
