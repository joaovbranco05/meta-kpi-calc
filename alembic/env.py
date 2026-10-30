"""Alembic environment using the same validated settings as the API."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from meta_kpi_calc.core.config import get_settings
from meta_kpi_calc.db.base import Base
from meta_kpi_calc.db import models  # noqa: F401  # Register model metadata.
from meta_kpi_calc.crm import models as crm_models  # noqa: F401
from meta_kpi_calc.crm import inbox_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().active_database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        is_postgresql = connection.dialect.name == "postgresql"
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
        elif is_postgresql:
            # Session-level lock survives Alembic's transaction boundaries.
            connection.exec_driver_sql("SELECT pg_advisory_lock(718503120463)")
            connection.commit()
        try:
            context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
            with context.begin_transaction():
                context.run_migrations()
        finally:
            if is_postgresql:
                connection.rollback()
                connection.exec_driver_sql("SELECT pg_advisory_unlock(718503120463)")
                connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
