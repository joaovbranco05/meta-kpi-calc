import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def run_alembic(project_root: Path, database: Path, command: str) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "DEMO_MODE": "true",
            "DATABASE_URL": f"sqlite:///{database.parent / 'real.db'}",
            "DEMO_DATABASE_URL": f"sqlite:///{database}",
        }
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", command, "head" if command == "upgrade" else "base"],
        cwd=project_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def test_alembic_domain_schema_is_persisted_and_reversible(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database = tmp_path / "alembic.db"

    run_alembic(project_root, database, "upgrade")
    with sqlite3.connect(database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert revision == ("0002_domain_models",)
    assert {
        "campaigns",
        "campaign_insights",
        "enrollment_records",
        "sync_runs",
    } <= tables

    run_alembic(project_root, database, "downgrade")
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
