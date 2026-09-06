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
    assert revision == ("0003_qualified_leads",)
    assert "qualified_leads" in columns
    assert {
        "campaigns",
        "campaign_insights",
        "enrollment_records",
        "sync_runs",
    } <= tables

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
