from pathlib import Path
from threading import Barrier, Thread

from sqlalchemy import func, select, text

from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.db.models import Campaign
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


def test_sqlite_allows_two_light_concurrent_writes(
    migrated_database: tuple[Settings, Database],
) -> None:
    _settings, database = migrated_database
    barrier = Barrier(2)
    errors: list[Exception] = []

    def write_campaign(meta_campaign_id: str) -> None:
        try:
            with database.session_factory.begin() as session:
                session.add(
                    Campaign(
                        meta_campaign_id=meta_campaign_id,
                        name=f"Campaign {meta_campaign_id}",
                    )
                )
                barrier.wait(timeout=5)
        except Exception as exc:  # pragma: no cover - assertion shows the error
            errors.append(exc)

    threads = [
        Thread(target=write_campaign, args=("concurrent-1",)),
        Thread(target=write_campaign, args=("concurrent-2",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    with database.session_factory() as session:
        assert session.scalar(select(func.count(Campaign.id))) == 2
