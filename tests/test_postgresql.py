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
    test_crm_api_lists_changes_status_and_rejects_nonlocal_peer as crm_api,
)
from test_api_rest import (
    test_campaign_list_detail_filters_pagination_and_classification as campaign_api,
    test_enrollment_create_list_replace_conflicts_and_rollback as enrollment_api,
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
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0006_lead_ads_inbox"
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
