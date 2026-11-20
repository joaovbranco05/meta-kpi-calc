"""PostgreSQL integration tests, only against the disposable local test cluster."""

import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
import test_authorization
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import URL, make_url

from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.db.session import Database
from meta_kpi_calc.db.migrate_sqlite import migrate_snapshot
from meta_kpi_calc.db.models import Campaign, CampaignInsight, EnrollmentRecord
from meta_kpi_calc.crm.inbox import EventInput, claim_event, enqueue_events
from meta_kpi_calc.crm.inbox_models import WebhookEvent
from meta_kpi_calc.crm.ingestion import LeadSubmission, change_lead_status, ingest_lead
from meta_kpi_calc.crm.models import Lead, LeadActivity, LeadStatus
from test_lead_ads import (
    test_webhook_batch_dedup_and_durable_ack_without_graph as webhook_dedup,
    test_webhook_commit_failure_rolls_back_and_lost_ack_replays_safely as webhook_commit,
    test_worker_two_claimers_have_one_winner as concurrent_claim,
    test_expired_worker_cannot_ingest_or_fail_and_restart_reclaims as expired_lease,
    test_completion_rollback_leaves_lease_recoverable as completion_rollback,
    test_worker_commits_claim_before_http_and_preserves_commercial_history as process_event,
    test_fetch_single_lead_reimport_is_idempotent_and_preserves_commercial_state as reimport,
    test_worker_retry_budget_eventually_terminal as retries,
)
from test_domain_models import (
    test_campaign_defaults_and_nullable_course as campaign_defaults,
    test_insight_preserves_decimal_and_json as insight_values,
    test_qualified_leads_is_nullable_and_rejects_negative_values as qualified_constraints,
    test_natural_keys_are_unique as unique_constraints,
    test_foreign_key_restricts_campaign_delete as foreign_keys,
)
from test_crm import (
    test_idempotent_ingestion_preserves_internal_status_and_records_source_corrections as crm_ingestion,
    test_crm_api_lists_and_updates_as_admin as crm_api,
)
from test_api_rest import (
    test_campaign_list_detail_filters_pagination_and_classification as campaign_api,
    test_enrollment_create_list_replace_conflicts_and_rollback as enrollment_api,
)

from test_continuous_worker import (
    test_worker_empty_then_new_event_and_restart as continuous_restart,
    test_worker_problem_event_does_not_block_next as continuous_problem,
    test_cycle_failure_backoff_and_safe_logs as continuous_backoff,
    test_expired_lease_recovered_by_continuous_worker as continuous_lease,
    test_two_workers_do_not_process_same_event as continuous_concurrent,
    test_stop_during_event_does_not_claim_next as continuous_stop,
    test_real_signal_stops_during_wait as continuous_signal,
)

SOCKET = os.environ.get("META_KPI_TEST_PG_SOCKET")
pytestmark = pytest.mark.skipif(not SOCKET, reason="PostgreSQL disposable test cluster not supplied")


@pytest.fixture
def pg_database(tmp_path):
    import psycopg
    from psycopg import sql

    socket = Path(SOCKET or "").resolve()
    if socket.name != "socket" or not socket.parent.name.startswith("meta-kpi-pg-") or socket.parent.parent != Path("/tmp").resolve():
        pytest.fail("PostgreSQL test socket is not an isolated test cluster")
    port = int(os.environ["META_KPI_TEST_PG_PORT"])
    name = "mk_test_" + uuid4().hex
    connargs = dict(host=str(socket), port=port, user="mk_test", dbname="postgres", autocommit=True)
    with psycopg.connect(**connargs) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {} ").format(sql.Identifier(name)))
    url = URL.create("postgresql+psycopg", username="mk_test", host="localhost", database=name,
                     query={"host": str(socket), "port": str(port)}).render_as_string(hide_password=False)
    environment = os.environ.copy()
    environment.update(DEMO_MODE="true", DATABASE_URL=f"sqlite:///{tmp_path / 'unused.db'}", DEMO_DATABASE_URL=url)
    project = Path(__file__).resolve().parents[1]
    try:
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=project,
                       env=environment, check=True, capture_output=True, text=True)
        settings = Settings(_env_file=None, demo_mode=True, database_url=environment["DATABASE_URL"], demo_database_url=url)
        database = Database(settings)
        try:
            yield settings, database
        finally:
            database.engine.dispose()
    finally:
        with psycopg.connect(**connargs) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def test_schema_and_upgrade_idempotent(pg_database):
    settings, database = pg_database
    with database.engine.connect() as connection:
        assert int(connection.scalar(text("SHOW server_version_num"))) // 10000 == 17
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0009_browser_context"
    env = os.environ.copy()
    url = make_url(settings.demo_database_url).set(password="synthetic%:password")
    env.update(DEMO_MODE="true", DATABASE_URL=settings.database_url,
               DEMO_DATABASE_URL=url.render_as_string(hide_password=False))
    def upgrade(_):
        return subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                              cwd=Path(__file__).resolve().parents[1], env=env,
                              check=True, capture_output=True, text=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(list(pool.map(upgrade, range(2)))) == 2
    subprocess.run([sys.executable, "-m", "alembic", "check"], cwd=Path(__file__).resolve().parents[1],
                   env=env, check=True, capture_output=True, text=True)


@pytest.mark.parametrize("check", [webhook_dedup, concurrent_claim, expired_lease, process_event, reimport,
                                  retries, campaign_defaults, insight_values, qualified_constraints,
                                  unique_constraints, foreign_keys, crm_ingestion, crm_api,
                                  campaign_api, enrollment_api])
def test_shared_lead_ads_contracts(pg_database, check):
    check(pg_database)


@pytest.mark.parametrize("check", [webhook_commit, completion_rollback])
def test_transaction_failure_contracts(pg_database, monkeypatch, check):
    check(pg_database, monkeypatch)


def test_parallel_claims_get_distinct_events(pg_database):
    settings, database = pg_database
    now = datetime.now(timezone.utc)
    with database.session_factory.begin() as session:
        enqueue_events(session, [EventInput("101", "10", "20"), EventInput("102", "10", "20")])
        session.execute(update(WebhookEvent).values(next_attempt_at=now))
    barrier = Barrier(2)
    def worker(_):
        barrier.wait()
        with database.session_factory.begin() as session:
            return claim_event(session, settings, now)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, range(2)))
    assert all(results)
    assert len({result.id for result in results}) == 2


def test_parallel_imports_create_one_lead_and_history(pg_database):
    _, database = pg_database
    barrier = Barrier(2)
    def worker(_):
        barrier.wait()
        with database.session_factory.begin() as session:
            return ingest_lead(session, LeadSubmission("123", {"full_name": "Synthetic"})).created
    with ThreadPoolExecutor(max_workers=2) as pool:
        created = list(pool.map(worker, range(2)))
    assert sorted(created) == [False, True]
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Lead)) == 1
        assert session.scalar(select(func.count()).select_from(LeadActivity)) == 1


def test_constraints_reject_empty_id(pg_database):
    _, database = pg_database
    with pytest.raises(IntegrityError):
        with database.session_factory.begin() as session:
            session.add(Lead(meta_lead_id=""))
            session.flush()


def test_migrate_synthetic_sqlite_snapshot(pg_database, migrated_database, tmp_path):
    _, target = pg_database
    sqlite_settings, sqlite_db = migrated_database
    with sqlite_db.session_factory.begin() as session:
        campaign = Campaign(meta_campaign_id="synthetic-campaign", name="Synthetic campaign")
        session.add(campaign)
        session.flush()
        session.add(CampaignInsight(campaign_id=campaign.id, date_start=date(2026, 1, 1), date_stop=date(2026, 1, 1),
                    spend=Decimal("123.45"), raw_actions=[{"value": "2"}]))
        session.add(EnrollmentRecord(campaign_id=campaign.id, reference_date=date(2026, 1, 1), course="Synthetic"))
        result = ingest_lead(session, LeadSubmission("123", {"full_name": "Synthetic", "is_organic": False,
                            "meta_created_time": datetime(2026, 1, 1, tzinfo=timezone.utc),
                            "meta_campaign_id": "synthetic-campaign"}))
        change_lead_status(session, result.lead, LeadStatus.CONTACTED)
        enqueue_events(session, [EventInput("123", "10", "20")])
    snapshot = tmp_path / "synthetic-snapshot.db"
    with sqlite3.connect(sqlite_settings.active_database_url.removeprefix("sqlite:///")) as source:
        with sqlite3.connect(snapshot) as destination:
            source.backup(destination)
    before = snapshot.read_bytes()
    preview = migrate_snapshot(snapshot, target.engine)
    assert preview["mode"] == "dry_run" and preview["counts"]["leads"] == 1
    assert snapshot.read_bytes() == before
    report = migrate_snapshot(snapshot, target.engine, execute=True)
    assert report["mode"] == "committed" and report["counts"]["lead_activities"] == 2
    assert snapshot.read_bytes() == before
    with target.session_factory.begin() as session:
        lead = session.scalar(select(Lead))
        assert lead.commercial_status == LeadStatus.CONTACTED
        assert session.scalar(select(func.count()).select_from(LeadActivity)) == 2
        assert session.scalar(select(WebhookEvent.status)) == "PENDING"
        assert ingest_lead(session, LeadSubmission("456", {})).lead.id > lead.id
    with pytest.raises(ValueError, match="empty"):
        migrate_snapshot(snapshot, target.engine, execute=True)


@pytest.mark.parametrize("check", [continuous_restart, continuous_problem, continuous_lease, continuous_concurrent, continuous_stop])
def test_continuous_worker_shared_contracts(pg_database, check):
    check(pg_database)


def test_continuous_worker_backoff(pg_database, monkeypatch, caplog):
    continuous_backoff(pg_database, monkeypatch, caplog)


@pytest.mark.parametrize("sig", [__import__("signal").SIGTERM, __import__("signal").SIGINT])
def test_continuous_worker_signals(pg_database, sig):
    continuous_signal(pg_database, sig)


def test_standalone_postgresql_ingress(pg_database):
    from test_webhook_gateway import test_public_service_writes_to_worker_inbox_without_admin

    test_public_service_writes_to_worker_inbox_without_admin(pg_database)


def test_standalone_postgresql_write_failure_returns_503(pg_database):
    from fastapi.testclient import TestClient
    from test_lead_ads import notification, options, signed

    from meta_kpi_calc.crm.webhook_gateway import create_webhook_gateway_app

    settings, database = pg_database
    config = options(settings).model_copy(update={"database_url": settings.active_database_url})
    with database.engine.begin() as connection:
        connection.execute(text("ALTER TABLE webhook_events RENAME TO unavailable_inbox"))
    with TestClient(create_webhook_gateway_app(config)) as client:
        response = client.post("/webhooks/meta/lead-ads", **signed(notification()))
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "database_unavailable"
    assert "webhook_events" not in response.text
    with database.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM unavailable_inbox")) == 0


@pytest.mark.parametrize("check", [
    test_authorization.test_permissions_and_audit,
    test_authorization.test_expired_and_inactive_sessions,
    test_authorization.test_concurrent_admin_deactivation_keeps_one_active,
])
def test_authorization_on_postgresql(pg_database, check):
    check(pg_database)


def test_authorization_migration_preserves_postgresql_history(pg_database, tmp_path):
    settings, database = pg_database
    env = os.environ.copy()
    env.update(
        DEMO_MODE="true",
        DATABASE_URL=f"sqlite:///{tmp_path / 'unused.db'}",
        DEMO_DATABASE_URL=settings.active_database_url,
    )

    def migrate(command, revision):
        subprocess.run(
            [sys.executable, "-m", "alembic", command, revision],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            check=True,
            capture_output=True,
        )

    migrate("downgrade", "0006_lead_ads_inbox")
    with database.engine.begin() as connection:
        lead_id = connection.scalar(text(
            "INSERT INTO leads (meta_lead_id, commercial_status) "
            "VALUES ('legacy-synthetic', 'CONTACTED') RETURNING id"
        ))
        connection.execute(text(
            "INSERT INTO lead_activities (lead_id, activity_type, actor_type, actor_id, note) "
            "VALUES (:lead_id, 'NOTE', 'LOCAL_OPERATOR', 'legacy-actor', 'Synthetic note')"
        ), {"lead_id": lead_id})
    migrate("upgrade", "head")
    with database.session_factory() as session:
        lead = session.get(Lead, lead_id)
        activity, = lead.activities
        assert lead.commercial_status == LeadStatus.CONTACTED
        assert lead.assigned_user_id is None
        assert (activity.actor_id, activity.actor_user_id, activity.note) == (
            "legacy-actor", None, "Synthetic note"
        )


@pytest.mark.parametrize("check", [
    test_authorization.test_profile_changes_revoke_all_existing_sessions,
    test_authorization.test_administrative_audit_failure_rolls_back,
])
def test_authorization_hardening_on_postgresql(pg_database, check):
    check(pg_database)


@pytest.mark.parametrize("operation", ["history", "status", "note"])
def test_reassignment_commits_before_scoped_operation(pg_database, operation):
    from threading import Event

    from fastapi.testclient import TestClient
    from sqlalchemy import event

    from meta_kpi_calc.api.app import create_app

    settings, database = pg_database
    app = create_app(settings)
    with database.session_factory.begin() as session:
        admin = test_authorization._account(session, "admin", "admin")
        operator = test_authorization._account(session, "usuario", "operator")
        other = test_authorization._account(session, "usuario", "other")
        lead = ingest_lead(session, LeadSubmission("123", {})).lead
        lead.assigned_user_id = operator[0]
        path = f"/api/crm/leads/{lead.id}"
    waiting, resume = Event(), Event()

    def pause_before_statement(_conn, _cursor, sql, *_args):
        sql = sql.lower()
        scoped = "left outer join lead_activities" in sql if operation == "history" else sql.startswith("update leads")
        if scoped:
            waiting.set()
            assert resume.wait(10)

    event.listen(app.state.database.engine, "before_cursor_execute", pause_before_statement)
    try:
        with TestClient(app) as caller, TestClient(create_app(settings)) as administrator:
            test_authorization._login(caller, operator)
            test_authorization._login(administrator, admin)
            calls = {
                "history": ("GET", "/activities", {}),
                "status": ("PATCH", "/status", {"json": {"commercial_status": "LOST"}}),
                "note": ("POST", "/activities", {"json": {"activity_type": "NOTE", "note": "Synthetic"}}),
            }
            method, suffix, kwargs = calls[operation]
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(caller.request, method, path + suffix, **kwargs)
                try:
                    assert waiting.wait(10)
                    assert administrator.patch(path + "/assignment", json={"assigned_user_id": other[0]}).status_code == 200
                finally:
                    resume.set()
                response = future.result(timeout=10)
            assert response.status_code == 404
    finally:
        app.state.database.engine.dispose()
    with database.session_factory() as session:
        assert session.scalar(select(Lead.commercial_status)) == LeadStatus.NEW
        assert session.scalar(select(func.count()).select_from(LeadActivity)) == 1


def test_admin_rejects_unsupported_transaction_isolation(pg_database):
    from fastapi.testclient import TestClient

    from meta_kpi_calc.api.app import create_app

    settings, database = pg_database
    with database.engine.connect() as connection:
        assert connection.get_isolation_level() == "READ COMMITTED"
    with database.session_factory.begin() as session:
        admin = test_authorization._account(session, "admin", "admin")
    app = create_app(settings)
    app.state.database.engine.update_execution_options(isolation_level="REPEATABLE READ")
    try:
        with TestClient(app) as client:
            test_authorization._login(client, admin)
            response = client.put(f"/api/admin/users/{admin[0]}", json={"role": "usuario", "active": True})
            assert response.status_code == 503
    finally:
        app.state.database.engine.dispose()


def test_service_roles_with_minimum_grants(pg_database, tmp_path):
    import httpx
    from fastapi.testclient import TestClient
    from sqlalchemy.exc import ProgrammingError
    from test_lead_ads import graph, notification, options, payload, signed

    from meta_kpi_calc.api.app import create_app
    from meta_kpi_calc.crm.ingestion import SOURCE_FIELDS
    from meta_kpi_calc.crm.processing import process_events
    from meta_kpi_calc.crm.webhook_gateway import create_webhook_gateway_app

    settings, database = pg_database
    suffix = uuid4().hex
    owner, api, hook, worker = (f"test_{name}_{suffix}" for name in ("ddl", "api", "hook", "worker"))

    def as_role(role):
        url = make_url(settings.active_database_url)
        url = url.update_query_dict({"options": f"-c role={role}"})
        return settings.model_copy(update={"demo_database_url": url.render_as_string(hide_password=False)})

    def migrate(config, command, revision):
        env = dict(os.environ, DEMO_MODE="true",
                   DATABASE_URL=f"sqlite:///{tmp_path / 'unused.db'}",
                   DEMO_DATABASE_URL=config.active_database_url)
        subprocess.run([sys.executable, "-m", "alembic", command, revision],
                       cwd=Path(__file__).resolve().parents[1], env=env, check=True, capture_output=True)

    migrate(settings, "downgrade", "base")
    with database.engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
        for role in (owner, api, hook, worker):
            connection.execute(text(f"CREATE ROLE {role} NOLOGIN"))
        connection.execute(text(f"GRANT USAGE, CREATE ON SCHEMA public TO {owner}"))
        connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {api}, {hook}, {worker}"))

    migrate(as_role(owner), "upgrade", "head")
    with database.engine.begin() as connection:
        grants = (
            f"GRANT SELECT, INSERT, UPDATE ON app_users TO {api}",
            f"GRANT SELECT ON app_sessions, browser_contexts TO {api}",
            f"GRANT UPDATE (revoked_at) ON app_sessions TO {api}",
            f"GRANT INSERT ON admin_audit TO {api}",
            f"GRANT SELECT (id, created_at) ON admin_audit TO {api}",
            f"GRANT SELECT ON leads, lead_activities, campaigns, campaign_insights, enrollment_records, commercial_closures, sync_runs TO {api}",
            f"GRANT INSERT, UPDATE ON campaigns, campaign_insights, enrollment_records, commercial_closures, sync_runs TO {api}",
            f"GRANT UPDATE (commercial_status, last_contact_at, assigned_user_id, updated_at) ON leads TO {api}",
            f"GRANT INSERT ON lead_activities TO {api}",
            f"GRANT USAGE ON SEQUENCE app_users_id_seq, admin_audit_id_seq, lead_activities_id_seq, campaigns_id_seq, campaign_insights_id_seq, enrollment_records_id_seq, commercial_closures_id_seq, sync_runs_id_seq TO {api}",
            f"GRANT INSERT (dedup_key, meta_lead_id, meta_page_id, meta_form_id, meta_ad_id) ON webhook_events TO {hook}",
            f"GRANT SELECT (dedup_key) ON webhook_events TO {hook}",
            f"GRANT USAGE ON SEQUENCE webhook_events_id_seq TO {hook}",
            f"GRANT SELECT ON webhook_events TO {worker}",
            f"GRANT UPDATE (status, attempts, lease_token, lease_expires_at, updated_at, error_code, completed_at, unmapped_fields, next_attempt_at) ON webhook_events TO {worker}",
            f"GRANT SELECT ON leads, campaigns TO {worker}",
            f"GRANT INSERT ({', '.join((*SOURCE_FIELDS, 'campaign_id', 'meta_lead_id', 'commercial_status'))}) ON leads TO {worker}",
            f"GRANT UPDATE ({', '.join((*SOURCE_FIELDS, 'campaign_id', 'updated_at'))}) ON leads TO {worker}",
            f"GRANT INSERT ON lead_activities TO {worker}",
            f"GRANT SELECT (id, created_at) ON lead_activities TO {worker}",
            f"GRANT USAGE ON SEQUENCE leads_id_seq, lead_activities_id_seq TO {worker}",
        )
        for grant in grants:
            connection.execute(text(grant))

    with database.session_factory.begin() as session:
        admin = test_authorization._account(session, "admin", "admin")

    def ingress_config(role):
        role_settings = as_role(role)
        return options(role_settings).model_copy(update={"database_url": role_settings.active_database_url})

    with TestClient(create_webhook_gateway_app(ingress_config(hook))) as client:
        for _ in range(2):
            assert client.post("/webhooks/meta/lead-ads", **signed(notification())).status_code == 200

    worker_config = ingress_config(worker)
    worker_db = Database(worker_config)
    try:
        result = process_events(worker_db.session_factory,
                                graph(lambda _: httpx.Response(200, json=payload())), worker_config)
        assert result["completed"] == 1
    finally:
        worker_db.engine.dispose()
    with TestClient(create_app(as_role(api))) as client:
        test_authorization._login(client, admin)
        leads = client.get("/api/crm/leads").json()
        assert leads["total"] == 1
        assert client.patch(f"/api/crm/leads/{leads['items'][0]['id']}/assignment",
                            json={"assigned_user_id": admin[0]}).status_code == 200
        created = client.post("/api/admin/users", json={"issuer": "test", "subject": "new", "role": "usuario"})
        assert created.status_code == 201
        endpoint = f"/api/admin/users/{created.json()['id']}"
        assert client.put(endpoint, json={"active": True, "role": "admin"}).status_code == 200


    for role, sql in (
        (api, "DELETE FROM admin_audit"), (api, "SELECT * FROM webhook_events"),
        (hook, "SELECT * FROM leads"), (hook, "UPDATE webhook_events SET status = 'PENDING'"),
        (worker, "SELECT * FROM app_sessions"), (worker, "UPDATE leads SET assigned_user_id = NULL"),
        (worker, "UPDATE leads SET commercial_status = 'LOST'"),
        (worker, "UPDATE webhook_events SET meta_lead_id = '123'"),
        (worker, "INSERT INTO leads (meta_lead_id, assigned_user_id) VALUES ('456', NULL)"),
        (api, "CREATE TABLE forbidden (id int)"), (hook, "CREATE TABLE forbidden (id int)"),
        (worker, "CREATE TABLE forbidden (id int)"),
    ):
        restricted = Database(as_role(role))
        try:
            with pytest.raises(ProgrammingError) as denied, restricted.engine.begin() as connection:
                assert connection.scalar(text("SELECT current_user")) == role
                connection.execute(text(sql))
            assert denied.value.orig.sqlstate == "42501"
        finally:
            restricted.engine.dispose()


@pytest.mark.parametrize("active", [True, False])
def test_oidc_account_change_concurrency_on_postgresql(pg_database, active):
    from test_oidc import test_session_issuance_races_account_change

    test_session_issuance_races_account_change(pg_database, active)


def test_oidc_callback_and_logout_on_postgresql(pg_database):
    from test_oidc import test_login_csrf_expiry_logout_and_replay

    test_login_csrf_expiry_logout_and_replay(pg_database)


@pytest.mark.parametrize("logout_first", [True, False])
def test_oidc_logout_callback_race_on_postgresql(pg_database, logout_first):
    from test_oidc import test_logout_fences_callback_in_both_commit_orders

    test_logout_fences_callback_in_both_commit_orders(pg_database, logout_first)
