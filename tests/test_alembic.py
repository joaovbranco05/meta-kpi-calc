import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def run_alembic(
    project_root: Path, database: Path, command: str, target: str
) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "DEMO_MODE": "true",
            "DATABASE_URL": f"sqlite:///{database.parent / 'real.db'}",
            "DEMO_DATABASE_URL": f"sqlite:///{database}",
        }
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", command, target],
        cwd=project_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def test_alembic_domain_schema_is_persisted_and_reversible(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database = tmp_path / "alembic.db"

    run_alembic(project_root, database, "upgrade", "head")
    with sqlite3.connect(database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(campaign_insights)")
        }
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert revision == ("0006_lead_ads_inbox",)
    assert "qualified_leads" in columns
    assert {
        "campaigns",
        "campaign_insights",
        "enrollment_records",
        "commercial_closures",
        "leads",
        "lead_activities",
        "sync_runs",
    } <= tables

    run_alembic(project_root, database, "downgrade", "0004_commercial_closures")
    with sqlite3.connect(database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert revision == ("0004_commercial_closures",)
    assert "commercial_closures" in tables

    run_alembic(project_root, database, "upgrade", "head")
    run_alembic(project_root, database, "downgrade", "0003_qualified_leads")
    with sqlite3.connect(database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert revision == ("0003_qualified_leads",)
    assert "commercial_closures" not in tables

    run_alembic(project_root, database, "downgrade", "0002_domain_models")
    with sqlite3.connect(database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(campaign_insights)")
        }
    assert revision == ("0002_domain_models",)
    assert "qualified_leads" not in columns

    run_alembic(project_root, database, "downgrade", "base")
    with sqlite3.connect(database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert revision is None
    assert "campaigns" not in tables


def test_qualified_leads_migration_preserves_existing_rows_as_unknown(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database = tmp_path / "existing.db"
    run_alembic(project_root, database, "upgrade", "0002_domain_models")

    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO campaigns (meta_campaign_id, name, brand) "
            "VALUES ('existing', 'Existing campaign', 'RCTEC')"
        )
        connection.execute(
            "INSERT INTO campaign_insights (campaign_id, date_start, date_stop) "
            "VALUES (1, '2026-09-01', '2026-09-01')"
        )
        connection.commit()

    run_alembic(project_root, database, "upgrade", "head")
    with sqlite3.connect(database) as connection:
        value = connection.execute(
            "SELECT qualified_leads FROM campaign_insights WHERE id = 1"
        ).fetchone()

    assert value == (None,)


def test_lead_ads_migration_preserves_phase_one_rows_and_matches_metadata(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database = tmp_path / "lead-ads-upgrade.db"
    run_alembic(project_root, database, "upgrade", "0005_crm_leads")
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO leads (meta_lead_id, commercial_status) VALUES ('synthetic-migration-id', 'CONTACTED')")
        connection.execute("INSERT INTO lead_activities (lead_id, activity_type, actor_type, note) VALUES (1, 'NOTE', 'LOCAL_OPERATOR', 'Synthetic note')")
    run_alembic(project_root, database, "upgrade", "head")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT meta_lead_id, commercial_status, meta_page_id FROM leads").fetchone() == ("synthetic-migration-id", "CONTACTED", None)
        assert connection.execute("SELECT note FROM lead_activities").fetchone() == ("Synthetic note",)
        assert {"webhook_events", "lead_reconciliation_states"} <= {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    # A clean metadata comparison is a separate guarantee from successful DDL.
    environment = os.environ.copy()
    environment.update(DEMO_MODE="true", DATABASE_URL=f"sqlite:///{tmp_path / 'real.db'}", DEMO_DATABASE_URL=f"sqlite:///{database}")
    subprocess.run([sys.executable, "-m", "alembic", "check"], cwd=project_root,
                   env=environment, check=True, capture_output=True, text=True)
    run_alembic(project_root, database, "downgrade", "0005_crm_leads")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT meta_lead_id, commercial_status FROM leads").fetchone() == ("synthetic-migration-id", "CONTACTED")
        assert "meta_page_id" not in {row[1] for row in connection.execute("PRAGMA table_info(leads)")}
    run_alembic(project_root, database, "upgrade", "head")
