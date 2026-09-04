from pathlib import Path

from sqlalchemy import text

from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.db.session import Database


def test_sqlite_connection_invariants(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'real.db'}",
        demo_database_url=f"sqlite:///{tmp_path / 'demo.db'}",
        sqlite_busy_timeout_ms=4321,
    )
    database = Database(settings)

    with database.engine.connect() as connection:
        foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
        busy_timeout = connection.execute(text("PRAGMA busy_timeout")).scalar_one()
        journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()

    database.engine.dispose()
    assert foreign_keys == 1
    assert busy_timeout == 4321
    assert journal_mode.lower() == "wal"


def test_session_generator_always_closes_session(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'real.db'}",
        demo_database_url=f"sqlite:///{tmp_path / 'demo.db'}",
    )
    database = Database(settings)
    class FakeSession:
        closed = False

        def close(self) -> None:
            self.closed = True

    fake_session = FakeSession()
    database.session_factory = lambda: fake_session  # type: ignore[assignment]
    generator = database.session()
    assert next(generator) is fake_session

    generator.close()

    assert fake_session.closed is True
    database.engine.dispose()
