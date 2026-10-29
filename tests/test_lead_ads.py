"""Synthetic Lead Ads boundary, crash, fencing and pagination regressions."""

import asyncio
import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request

from meta_kpi_calc.api.app import create_app
from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.core.logging import configure_logging
from meta_kpi_calc.crm.inbox import EventInput, claim_event, complete_event, enqueue_events, fail_event
from meta_kpi_calc.crm.inbox_models import ReconciliationState, WebhookEvent
from meta_kpi_calc.crm.ingestion import change_lead_status
from meta_kpi_calc.crm.lead_ads_cli import main as cli_main
from meta_kpi_calc.crm.lead_ads_client import LeadAdsError, MetaLeadAdsClient
from meta_kpi_calc.crm.models import Lead, LeadActivity, LeadStatus
from meta_kpi_calc.crm.normalizer import normalize_lead
from meta_kpi_calc.crm.processing import process_events
from meta_kpi_calc.crm.reconciliation import reconcile_form
from meta_kpi_calc.crm.webhook import receive_webhook

NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
SECRET = "synthetic-app-secret"
TOKEN = "synthetic-graph-token"


def options(settings):
    return settings.model_copy(update=dict(demo_mode=False, lead_ads_enabled=True, lead_ads_app_secret=Settings(_env_file=None, lead_ads_app_secret=SECRET).lead_ads_app_secret,
        lead_ads_verify_token=Settings(_env_file=None, lead_ads_verify_token="synthetic-verify").lead_ads_verify_token,
        lead_ads_allowed_page_ids=["10"], lead_ads_authorized_sources={"20": "10"}, lead_ads_api_version="v26.0"))


def payload(lead="30"):
    return {"id": lead, "created_time": "2026-10-29T11:00:00+00:00", "form_id": "20", "ad_id": "40",
            "field_data": [{"name": "full_name", "values": ["Synthetic Candidate"]}]}


def notification(lead="30", page="10", field="leadgen"):
    return {"object": "page", "entry": [{"id": page, "changes": [{"field": field, "value": {
        "page_id": page, "leadgen_id": lead, "form_id": "20", "ad_id": "40"}}]}]}


def signed(value):
    raw = json.dumps(value).encode()
    digest = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return {"content": raw, "headers": {"X-Hub-Signature-256": "sha256=" + digest}}


def graph(handler, **kwargs):
    http = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return MetaLeadAdsClient(http, token=TOKEN, api_version="v26.0", **kwargs)


def enqueue(database, lead="30"):
    with database.session_factory.begin() as session:
        enqueue_events(session, [EventInput(lead, "10", "20", "40")])
        # Let deterministic clocks process an event received at an explicit timestamp.
        session.execute(update(WebhookEvent).values(next_attempt_at=NOW, received_at=NOW))


def test_settings_are_independent_fail_closed_and_validate_sources():
    settings = Settings(_env_file=None, meta_access_token="synthetic-ads-only")
    assert not settings.lead_ads_ingress_ready and not settings.lead_ads_graph_ready
    assert settings.lead_ads_api_version is None
    with pytest.raises(ValueError):
        Settings(_env_file=None, lead_ads_allowed_page_ids=["１２"])
    with pytest.raises(ValueError):
        Settings(_env_file=None, lead_ads_authorized_sources={"20": "10"})
    with pytest.raises(ValueError):
        Settings(_env_file=None, lead_ads_api_version="https://untrusted.test")


def test_webhook_handshake_disabled_valid_and_invalid(migrated_database):
    settings, database = migrated_database
    app = create_app(settings)
    app.state.database = database
    with TestClient(app) as client:
        assert client.get("/webhooks/meta/lead-ads").status_code == 503
        app.state.settings = options(settings)
        args = {"hub.mode": "subscribe", "hub.verify_token": "synthetic-verify", "hub.challenge": "12345"}
        response = client.get("/webhooks/meta/lead-ads", params=args)
        assert response.status_code == 200 and response.text == "12345"
        assert response.headers["content-type"].startswith("text/plain")
        args["hub.verify_token"] = "wrong"
        assert client.get("/webhooks/meta/lead-ads", params=args).status_code == 403
        args["hub.mode"] = "bad"
        assert client.get("/webhooks/meta/lead-ads", params=args).status_code == 400


def test_webhook_batch_dedup_and_durable_ack_without_graph(migrated_database):
    settings, database = migrated_database
    app = create_app(options(settings)); app.state.database = database
    data = notification()
    data["entry"].append(notification("31")["entry"][0])
    with TestClient(app) as client:
        assert client.post("/webhooks/meta/lead-ads", **signed(data)).status_code == 200
        assert client.post("/webhooks/meta/lead-ads", **signed(data)).status_code == 200
    with database.session_factory() as session:
        rows = session.scalars(select(WebhookEvent)).all()
        assert len(rows) == 2
        assert all(row.status == "PENDING" and row.attempts == 0 for row in rows)
        assert session.scalar(select(func.count(Lead.id))) == 0


@pytest.mark.parametrize("signature", [None, "bad", "sha256=" + "0" * 64, "sha256=" + "z" * 64])
def test_webhook_rejects_signature_without_writes(migrated_database, signature):
    settings, database = migrated_database
    app = create_app(options(settings)); app.state.database = database
    headers = {"X-Hub-Signature-256": signature} if signature else {}
    with TestClient(app) as client:
        response = client.post("/webhooks/meta/lead-ads", content=b'{"private":"synthetic-private"}', headers=headers)
        assert response.status_code == 403
        assert "synthetic-private" not in response.text
    with database.session_factory() as session:
        assert session.scalar(select(func.count(WebhookEvent.id))) == 0


@pytest.mark.parametrize("case,expected", [("mixed_page", 403), ("bad_id", 400), ("bad_object", 400), ("mismatch", 400), ("unsupported", 200)])
def test_webhook_batch_atomic_validation(migrated_database, case, expected):
    settings, database = migrated_database
    app = create_app(options(settings)); app.state.database = database
    data = notification()
    if case == "mixed_page": data["entry"].append(notification("31", "99")["entry"][0])
    if case == "bad_id": data["entry"][0]["changes"].append({"field": "leadgen", "value": {"leadgen_id": "../private"}})
    if case == "bad_object": data["object"] = "user"
    if case == "mismatch": data["entry"][0]["changes"][0]["value"]["page_id"] = "99"
    if case == "unsupported": data["entry"][0]["changes"][0]["field"] = "feed"
    with TestClient(app) as client:
        assert client.post("/webhooks/meta/lead-ads", **signed(data)).status_code == expected
    with database.session_factory() as session:
        assert session.scalar(select(func.count(WebhookEvent.id))) == 0


def test_webhook_stream_size_limit_counts_chunks_before_parsing(migrated_database):
    settings, database = migrated_database
    settings = options(settings).model_copy(update={"lead_ads_body_max_bytes": 1024})
    app = create_app(settings); app.state.database = database
    chunks = iter([{"type": "http.request", "body": b"a" * 800, "more_body": True},
                   {"type": "http.request", "body": b"b" * 800, "more_body": True}])
    async def receive(): return next(chunks)
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": [], "app": app}, receive)
    with pytest.raises(HTTPException) as error:
        asyncio.run(receive_webhook(request))
    assert error.value.status_code == 413


def test_webhook_db_failure_never_acknowledges(migrated_database, monkeypatch):
    settings, database = migrated_database
    app = create_app(options(settings)); app.state.database = database
    def fail(*args): raise SQLAlchemyError("synthetic-private")
    monkeypatch.setattr("meta_kpi_calc.crm.webhook._persist", fail)
    with TestClient(app) as client:
        response = client.post("/webhooks/meta/lead-ads", **signed(notification()))
        assert response.status_code == 503
        assert "synthetic-private" not in response.text


def test_graph_fixed_get_header_timeout_and_optional_normalization():
    def handler(request):
        assert request.method == "GET" and request.url.host == "graph.facebook.com"
        assert request.url.path == "/v26.0/30"
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        assert TOKEN not in str(request.url)
        assert request.extensions["timeout"] == {"connect": 5, "read": 10, "write": 10, "pool": 5}
        return httpx.Response(200, json=payload())
    normalized = normalize_lead(graph(handler).get_lead("30"), page_id="10", lead_id="30")
    assert normalized.submission.values["full_name"] == "Synthetic Candidate"
    assert "email" not in normalized.submission.values
    assert normalized.submission.values["meta_created_time"].tzinfo == timezone.utc
    assert normalized.submission.values["meta_page_id"] == "10"
    with pytest.raises(LeadAdsError): graph(handler).get_lead("../30")


@pytest.mark.parametrize("status,transient,code", [(429, True, "graph_temporary"), (500, True, "graph_temporary"), (401, False, "graph_access_denied"), (403, False, "graph_access_denied"), (404, False, "graph_not_found"), (302, False, "graph_rejected")])
def test_graph_errors_are_fixed_no_redirect_retry_or_pii(status, transient, code):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"Location": "https://untrusted.test", "Retry-After": "99999999"}, json={"error": {"message": TOKEN + " synthetic-private"}})
    with pytest.raises(LeadAdsError) as error:
        graph(handler).get_lead("30")
    assert error.value.code == code and error.value.transient == transient
    assert error.value.retry_after <= 3600
    assert len(calls) == 1 and TOKEN not in str(error.value) and "synthetic-private" not in str(error.value)


def test_graph_transport_malformed_and_id_mismatch():
    def timeout(request): raise httpx.ReadTimeout("synthetic-private", request=request)
    with pytest.raises(LeadAdsError) as error: graph(timeout).get_lead("30")
    assert error.value.code == "graph_transport" and error.value.transient
    for response in (httpx.Response(200, text="private-not-json"), httpx.Response(200, json=payload("99")), httpx.Response(200, json=[])):
        with pytest.raises(LeadAdsError) as error: graph(lambda request: response).get_lead("30")
        assert "private" not in str(error.value)


def test_graph_pagination_reconstructs_endpoint_and_traverses_all_pages():
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={"data": [payload()], "paging": {"next": "https://graph.facebook.com/v26.0/20/leads?after=ignored&access_token=do-not-follow", "cursors": {"after": "opaque-next"}}})
        assert request.url.path == "/v26.0/20/leads"
        assert request.url.params["after"] == "opaque-next" and "access_token" not in request.url.params
        return httpx.Response(200, json={"data": []})
    pages = list(graph(handler).iter_form_lead_pages("20"))
    assert len(pages) == 2 and len(calls) == 2


@pytest.mark.parametrize("next_url", ["http://graph.facebook.com/v26.0/20/leads", "https://untrusted.test/x", "https://u:p@graph.facebook.com/v26.0/20/leads", "https://graph.facebook.com/v26.0/99/leads"])
def test_graph_untrusted_pagination_rejected(next_url):
    with pytest.raises(LeadAdsError):
        list(graph(lambda request: httpx.Response(200, json={"data": [], "paging": {"next": next_url, "cursors": {"after": "x"}}})).iter_form_lead_pages("20"))


def test_graph_repeated_cursor_and_page_limit_fail_instead_of_truncating():
    def handler(request): return httpx.Response(200, json={"data": [payload()], "paging": {"next": "https://graph.facebook.com/v26.0/20/leads", "cursors": {"after": "same"}}})
    with pytest.raises(LeadAdsError) as error: list(graph(handler).iter_form_lead_pages("20"))
    assert error.value.code == "invalid_pagination"
    with pytest.raises(LeadAdsError) as error: list(graph(handler, max_pages=1).iter_form_lead_pages("20"))
    assert error.value.code == "page_limit"


def test_normalizer_unknown_fields_counted_known_conflicts_rejected_and_utc_strict():
    raw = payload(); raw["field_data"].append({"name": "synthetic_custom", "values": ["private-answer"]})
    result = normalize_lead(raw, page_id="10")
    assert result.unmapped_fields == 1 and "private-answer" not in repr(result)
    raw["field_data"].append({"name": "full_name", "values": ["conflict"]})
    with pytest.raises(LeadAdsError): normalize_lead(raw, page_id="10")
    raw = payload(); raw["created_time"] = "2026-10-29T12:00:00"
    with pytest.raises(LeadAdsError): normalize_lead(raw, page_id="10")
    raw = payload(); raw["field_data"] = [{"name": "phone_number", "values": ["one", "two"]}]
    with pytest.raises(LeadAdsError): normalize_lead(raw, page_id="10")


def test_worker_commits_claim_before_http_and_preserves_commercial_history(migrated_database):
    settings, database = migrated_database; settings = options(settings)
    enqueue(database)
    active = set()
    event.listen(database.engine, "begin", lambda connection: active.add(id(connection)))
    event.listen(database.engine, "commit", lambda connection: active.discard(id(connection)))
    event.listen(database.engine, "rollback", lambda connection: active.discard(id(connection)))
    def handler(request):
        assert not active
        with database.session_factory() as session:
            assert session.scalar(select(WebhookEvent.status)) == "PROCESSING"
        return httpx.Response(200, json=payload())
    client = graph(handler)
    result = process_events(database.session_factory, client, settings, clock=lambda: NOW)
    assert result["completed"] == 1
    with database.session_factory.begin() as session:
        row = session.scalar(select(Lead)); change_lead_status(session, row, LeadStatus.CONTACTED)
        assert row.meta_page_id == "10" and row.campaign_id is None
    with database.session_factory.begin() as session:
        enqueue_events(session, [EventInput("30", "10", "20", "40")])
    assert process_events(database.session_factory, client, settings, clock=lambda: NOW)["claimed"] == 0
    with database.session_factory() as session:
        assert session.scalar(select(Lead.commercial_status)) == LeadStatus.CONTACTED
        assert session.scalar(select(func.count(LeadActivity.id))) == 2
        assert session.scalar(select(WebhookEvent.status)) == "COMPLETED"


def test_worker_two_claimers_have_one_winner(migrated_database):
    settings, database = migrated_database; settings = options(settings); enqueue(database)
    barrier = Barrier(2)
    def worker(_):
        barrier.wait()
        with database.session_factory.begin() as session: return claim_event(session, settings, NOW)
    with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(worker, range(2)))
    assert sum(result is not None for result in results) == 1
    with database.session_factory() as session: assert session.scalar(select(WebhookEvent.attempts)) == 1


def test_expired_worker_cannot_ingest_or_fail_and_restart_reclaims(migrated_database):
    settings, database = migrated_database; settings = options(settings); enqueue(database)
    with database.session_factory.begin() as session: old = claim_event(session, settings, NOW)
    later = NOW + timedelta(seconds=121)
    with database.session_factory.begin() as session: new = claim_event(session, settings, later)
    assert old.token != new.token and new.attempts == 2
    normalized = normalize_lead(payload(), page_id="10")
    with database.session_factory.begin() as session:
        assert not complete_event(session, old, normalized, later)
        assert not fail_event(session, old, LeadAdsError("graph_rejected"), settings, later)
    with database.session_factory() as session: assert session.scalar(select(func.count(Lead.id))) == 0
    with database.session_factory.begin() as session: assert complete_event(session, new, normalized, later)
    with database.session_factory() as session: assert session.scalar(select(func.count(Lead.id))) == 1


def test_completion_rollback_leaves_lease_recoverable(migrated_database, monkeypatch):
    settings, database = migrated_database; settings = options(settings); enqueue(database)
    def fail(*args): raise SQLAlchemyError("synthetic-private")
    monkeypatch.setattr("meta_kpi_calc.crm.inbox.ingest_lead", fail)
    with pytest.raises(SQLAlchemyError):
        process_events(database.session_factory, graph(lambda request: httpx.Response(200, json=payload())), settings, clock=lambda: NOW)
    with database.session_factory() as session:
        assert session.scalar(select(WebhookEvent.status)) == "PROCESSING"
        assert session.scalar(select(func.count(Lead.id))) == 0


@pytest.mark.parametrize("status,expected", [(429, "RETRY"), (503, "RETRY"), (401, "FAILED")])
def test_worker_durable_retry_bounded_and_no_sleeps(migrated_database, status, expected):
    settings, database = migrated_database; settings = options(settings); enqueue(database)
    client = graph(lambda request: httpx.Response(status, headers={"Retry-After": "999999"}))
    result = process_events(database.session_factory, client, settings, max_events=100, clock=lambda: NOW)
    assert result["claimed"] == 1 and result["failed_or_retry"] == 1
    with database.session_factory() as session:
        row = session.scalar(select(WebhookEvent))
        assert row.status == expected and row.attempts == 1 and row.lease_token is None
        assert row.next_attempt_at <= (NOW + timedelta(seconds=3600)).replace(tzinfo=None)


def test_exhausted_stale_processing_terminal_without_http(migrated_database):
    settings, database = migrated_database; settings = options(settings); enqueue(database)
    settings = settings.model_copy(update={"lead_ads_max_attempts": 1})
    with database.session_factory.begin() as session: assert claim_event(session, settings, NOW)
    client = graph(lambda request: pytest.fail("exhausted event must not call Graph"))
    assert process_events(database.session_factory, client, settings, clock=lambda: NOW + timedelta(seconds=121))["claimed"] == 0
    with database.session_factory() as session:
        row = session.scalar(select(WebhookEvent))
        assert row.status == "FAILED" and row.error_code == "attempts_exhausted"


def test_reconciliation_checkpoint_only_complete_replay_overlap_and_webhook_dedup(migrated_database):
    settings, database = migrated_database; settings = options(settings)
    calls = []
    def failing(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={"data": [payload()], "paging": {"next": "https://graph.facebook.com/v26.0/20/leads", "cursors": {"after": "next"}}})
        return httpx.Response(503)
    start = NOW - timedelta(days=1)
    with pytest.raises(LeadAdsError): reconcile_form(database.session_factory, graph(failing), settings, form_id="20", start=start, clock=lambda: NOW)
    with database.session_factory.begin() as session:
        state = session.scalar(select(ReconciliationState))
        assert state.completed_until is None and state.last_result == "FAILED"
        assert session.scalar(select(func.count(Lead.id))) == 1
        change_lead_status(session, session.scalar(select(Lead)), LeadStatus.LOST)
    good = graph(lambda request: httpx.Response(200, json={"data": [payload()]}))
    result = reconcile_form(database.session_factory, good, settings, form_id="20", start=start, clock=lambda: NOW)
    assert result["processed"] == 1 and result["created"] == 0
    with database.session_factory() as session:
        state = session.scalar(select(ReconciliationState))
        assert state.completed_until == NOW.replace(tzinfo=None) and state.last_result == "COMPLETED"
        assert session.scalar(select(Lead.commercial_status)) == LeadStatus.LOST
        assert session.scalar(select(func.count(LeadActivity.id))) == 2
    enqueue(database)
    assert process_events(database.session_factory, graph(lambda request: httpx.Response(200, json=payload())), settings, clock=lambda: NOW)["completed"] == 1
    with database.session_factory() as session: assert session.scalar(select(func.count(LeadActivity.id))) == 2
    # A second scan starts at checkpoint-overlap and still sees a lead 2 minutes before checkpoint.
    recent = payload("31"); recent["created_time"] = (NOW - timedelta(seconds=120)).isoformat()
    result = reconcile_form(database.session_factory, graph(lambda request: httpx.Response(200, json={"data": [recent]})), settings, form_id="20", clock=lambda: NOW + timedelta(seconds=60))
    assert result["created"] == 1


def test_reconciliation_no_checkpoint_on_page_cap_or_bad_old_timestamp(migrated_database):
    settings, database = migrated_database; settings = options(settings)
    def pages(request): return httpx.Response(200, json={"data": [payload()], "paging": {"next": "https://graph.facebook.com/v26.0/20/leads", "cursors": {"after": "next"}}})
    with pytest.raises(LeadAdsError): reconcile_form(database.session_factory, graph(pages, max_pages=1), settings, form_id="20", start=NOW - timedelta(days=1), clock=lambda: NOW)
    old = payload(); old["created_time"] = "not-an-offset-time"
    with pytest.raises(LeadAdsError): reconcile_form(database.session_factory, graph(lambda request: httpx.Response(200, json={"data": [old]})), settings, form_id="20", start=NOW - timedelta(days=1), clock=lambda: NOW)
    with database.session_factory() as session: assert session.scalar(select(ReconciliationState.completed_until)) is None


def test_reconciliation_lease_prevents_concurrent_scan_and_fences_stale_page(migrated_database):
    settings, database = migrated_database; settings = options(settings)
    def handler(request):
        with pytest.raises(LeadAdsError) as error:
            reconcile_form(database.session_factory, graph(lambda _: pytest.fail("no concurrent scan")), settings, form_id="20", start=NOW-timedelta(days=1), clock=lambda: NOW)
        assert error.value.code == "reconciliation_in_progress"
        with database.session_factory.begin() as session:
            session.execute(update(ReconciliationState).values(lease_token="new-owner"))
        return httpx.Response(200, json={"data": [payload()]})
    with pytest.raises(LeadAdsError) as error:
        reconcile_form(database.session_factory, graph(handler), settings, form_id="20", start=NOW-timedelta(days=1), clock=lambda: NOW)
    assert error.value.code == "lease_lost"
    with database.session_factory() as session:
        assert session.scalar(select(ReconciliationState.completed_until)) is None
        assert session.scalar(select(func.count(Lead.id))) == 0


def test_cli_network_optin_and_status_counts_only(migrated_database, capsys):
    settings, database = migrated_database
    enqueue(database)
    assert cli_main(["status", "--database-url", settings.demo_database_url]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["events"] == {"PENDING": 1} and "meta_lead_id" not in str(result)
    assert cli_main(["process", "--database-url", settings.demo_database_url]) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "network_not_authorized"


def test_all_new_secrets_redacted_by_existing_logging(caplog):
    import logging
    settings = Settings(_env_file=None, lead_ads_access_token=TOKEN,
                        lead_ads_app_secret=SECRET, lead_ads_verify_token="synthetic-verify")
    configure_logging(settings)
    logging.getLogger("lead-ads-test").warning("%s %s %s", TOKEN, SECRET, "synthetic-verify")
    assert TOKEN not in caplog.text and SECRET not in caplog.text and "synthetic-verify" not in caplog.text


def test_graph_urls_and_cursors_are_redacted_in_httpx_logs(caplog):
    configure_logging(Settings(_env_file=None))
    with caplog.at_level("INFO", logger="httpx"):
        graph(lambda request: httpx.Response(200, json=payload())).get_lead("30")
    assert "graph.facebook.com" not in caplog.text
    assert "/v26.0/30" not in caplog.text
    assert "REDACTED_META_URL" in caplog.text


def test_webhook_signed_malformed_json_and_tampered_bytes_rejected(migrated_database):
    settings, database = migrated_database
    app = create_app(options(settings)); app.state.database = database
    raw = b'{"synthetic":'
    signature = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    with TestClient(app) as client:
        assert client.post("/webhooks/meta/lead-ads", content=raw, headers={"X-Hub-Signature-256": "sha256="+signature}).status_code == 400
        data = signed(notification()); data["content"] += b" "
        assert client.post("/webhooks/meta/lead-ads", **data).status_code == 403


def test_webhook_commit_failure_rolls_back_and_lost_ack_replays_safely(migrated_database, monkeypatch):
    from meta_kpi_calc.crm import webhook
    settings, database = migrated_database
    app = create_app(options(settings)); app.state.database = database
    def commit_failure(connection): raise SQLAlchemyError("synthetic-private")
    event.listen(database.engine, "commit", commit_failure)
    with TestClient(app) as client:
        assert client.post("/webhooks/meta/lead-ads", **signed(notification())).status_code == 503
    event.remove(database.engine, "commit", commit_failure)
    with database.session_factory() as session:
        assert session.scalar(select(func.count(WebhookEvent.id))) == 0
    original = webhook._persist
    def lost_ack(factory, events):
        original(factory, events)
        raise OSError("synthetic-failure-after-commit")
    monkeypatch.setattr(webhook, "_persist", lost_ack)
    with TestClient(app) as client:
        assert client.post("/webhooks/meta/lead-ads", **signed(notification())).status_code == 503
    monkeypatch.setattr(webhook, "_persist", original)
    with TestClient(app) as client:
        assert client.post("/webhooks/meta/lead-ads", **signed(notification())).status_code == 200
    with database.session_factory() as session:
        assert session.scalar(select(func.count(WebhookEvent.id))) == 1


def test_worker_retry_budget_eventually_terminal(migrated_database):
    settings, database = migrated_database; settings = options(settings); enqueue(database)
    settings = settings.model_copy(update={"lead_ads_max_attempts": 2})
    client = graph(lambda request: httpx.Response(500))
    process_events(database.session_factory, client, settings, clock=lambda: NOW)
    process_events(database.session_factory, client, settings, clock=lambda: NOW + timedelta(seconds=31))
    with database.session_factory() as session:
        row = session.scalar(select(WebhookEvent))
        assert row.status == "FAILED" and row.attempts == 2 and row.lease_token is None


def test_reconciliation_restart_after_expiry_traverses_old_and_new_pages(migrated_database):
    settings, database = migrated_database; settings = options(settings)
    with database.session_factory.begin() as session:
        session.add(ReconciliationState(meta_page_id="10", meta_form_id="20", last_result="PROCESSING",
                    lease_token="dead-process", lease_expires_at=NOW - timedelta(seconds=1)))
    calls = []
    active = set()
    event.listen(database.engine, "begin", lambda connection: active.add(id(connection)))
    event.listen(database.engine, "commit", lambda connection: active.discard(id(connection)))
    event.listen(database.engine, "rollback", lambda connection: active.discard(id(connection)))
    def handler(request):
        assert not active
        calls.append(request)
        if len(calls) == 1:
            old = payload("29"); old["created_time"] = "2020-01-01T00:00:00Z"
            return httpx.Response(200, json={"data": [old], "paging": {"next": "https://graph.facebook.com/v26.0/20/leads", "cursors": {"after": "opaque-cursor-sentinel"}}})
        return httpx.Response(200, json={"data": [payload()]})
    result = reconcile_form(database.session_factory, graph(handler), settings, form_id="20", start=NOW - timedelta(days=1), clock=lambda: NOW)
    assert result["pages"] == 2 and result["processed"] == 1
    with database.session_factory() as session:
        assert session.scalar(select(func.count(Lead.id))) == 1
        state = session.scalar(select(ReconciliationState))
        assert state.lease_token is None and state.completed_until == NOW.replace(tzinfo=None)


def test_reconciliation_expired_page_cannot_write_or_checkpoint(migrated_database):
    settings, database = migrated_database; settings = options(settings)
    clock_calls = []
    def clock():
        clock_calls.append(1)
        return NOW if len(clock_calls) == 1 else NOW + timedelta(seconds=121)
    with pytest.raises(LeadAdsError) as error:
        reconcile_form(database.session_factory, graph(lambda request: httpx.Response(200, json={"data": [payload()]})), settings, form_id="20", start=NOW-timedelta(days=1), clock=clock)
    assert error.value.code == "lease_lost"
    with database.session_factory() as session:
        assert session.scalar(select(func.count(Lead.id))) == 0
        assert session.scalar(select(ReconciliationState.completed_until)) is None


def test_logging_hides_graph_cursor_id_and_tokens_without_hiding_other_messages(caplog):
    import logging
    configure_logging(Settings(_env_file=None, lead_ads_access_token=TOKEN))
    logging.getLogger("httpx").warning('GET https://graph.facebook.com/v26.0/987654321123456?after=opaque-cursor-sentinel %s', TOKEN)
    logging.getLogger("test-app").warning("safe-event-completed")
    assert all(value not in caplog.text for value in ("987654321123456", "opaque-cursor-sentinel", TOKEN))
    assert "safe-event-completed" in caplog.text


def test_cli_resolves_relative_database_once_before_settings(migrated_database, monkeypatch, capsys):
    settings, database = migrated_database
    enqueue(database)
    from pathlib import Path
    path = Path(database.engine.url.database)
    monkeypatch.chdir(path.parent)
    assert cli_main(["status", "--database-url", "sqlite:///" + path.name]) == 0
    assert json.loads(capsys.readouterr().out)["events"] == {"PENDING": 1}


def test_webhook_cannot_ingest_into_demo_database_even_when_configured(migrated_database):
    settings, database = migrated_database
    configured = options(settings).model_copy(update={"demo_mode": True})
    assert not configured.lead_ads_ingress_ready
    app = create_app(configured); app.state.database = database
    with TestClient(app) as client:
        assert client.post("/webhooks/meta/lead-ads", **signed(notification())).status_code == 503
    with database.session_factory() as session:
        assert session.scalar(select(func.count(WebhookEvent.id))) == 0


def test_uvicorn_access_handler_redacts_verify_query_with_propagation_off():
    import logging
    from io import StringIO
    configure_logging(Settings(_env_file=None))
    logger = logging.getLogger("uvicorn.access")
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    old_propagate, old_level = logger.propagate, logger.level
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        logger.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1", "GET",
                    "/webhooks/meta/lead-ads?hub.verify_token=synthetic-unconfigured-secret&hub.challenge=123", "1.1", 200)
    finally:
        logger.removeHandler(handler)
        logger.propagate, logger.level = old_propagate, old_level
    assert "synthetic-unconfigured-secret" not in stream.getvalue()
    assert "hub.verify_token=[REDACTED]&hub.challenge=123" in stream.getvalue()
    assert "GET" in stream.getvalue()


def test_reconciliation_rejects_explicit_start_gap_without_advancing_checkpoint(migrated_database):
    settings, database = migrated_database; settings = options(settings)
    with database.session_factory.begin() as session:
        session.add(ReconciliationState(meta_page_id="10", meta_form_id="20", completed_until=NOW,
                                       last_result="COMPLETED", last_success_at=NOW))
    client = graph(lambda request: pytest.fail("gap must fail before Graph"))
    with pytest.raises(LeadAdsError) as error:
        reconcile_form(database.session_factory, client, settings, form_id="20",
                       start=NOW + timedelta(seconds=301), end=NOW + timedelta(seconds=900),
                       clock=lambda: NOW + timedelta(seconds=900))
    assert error.value.code == "invalid_window"
    with database.session_factory() as session:
        state = session.scalar(select(ReconciliationState))
        assert state.completed_until == NOW.replace(tzinfo=None)
        assert state.last_result == "COMPLETED" and state.lease_token is None
    # At the overlap boundary, the effective lower bound is exactly the checkpoint.
    valid = graph(lambda request: httpx.Response(200, json={"data": []}))
    assert reconcile_form(database.session_factory, valid, settings, form_id="20",
                          start=NOW + timedelta(seconds=300), end=NOW + timedelta(seconds=900),
                          clock=lambda: NOW + timedelta(seconds=900))["pages"] == 1


def test_cli_status_aggregates_attempts_and_reconciliation_results(migrated_database, capsys):
    settings, database = migrated_database; enqueue(database)
    with database.session_factory.begin() as session:
        session.execute(update(WebhookEvent).values(attempts=3))
        session.add(ReconciliationState(meta_page_id="10", meta_form_id="20", last_result="FAILED", error_code="graph_temporary"))
    assert cli_main(["status", "--database-url", settings.demo_database_url]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["attempts_total"] == 3 and summary["reconciliation_results"] == {"FAILED": 1}
    assert "meta_page_id" not in str(summary) and "meta_form_id" not in str(summary)
