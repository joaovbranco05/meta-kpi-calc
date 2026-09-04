import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.db.session import Database


@pytest.fixture
def migrated_database(tmp_path: Path) -> Iterator[tuple[Settings, Database]]:
    project_root = Path(__file__).resolve().parents[1]
    demo_database = tmp_path / "demo.db"
    settings = Settings(
        _env_file=None,
        demo_mode=True,
        database_url=f"sqlite:///{tmp_path / 'real.db'}",
        demo_database_url=f"sqlite:///{demo_database}",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "DEMO_MODE": "true",
            "DATABASE_URL": settings.database_url,
            "DEMO_DATABASE_URL": settings.demo_database_url,
        }
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=project_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    database = Database(settings)
    try:
        yield settings, database
    finally:
        database.engine.dispose()
