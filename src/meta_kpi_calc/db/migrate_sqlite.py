"""Copy a SQLite snapshot to an empty, migrated PostgreSQL database.

The source is opened read-only. Never run against a live SQLite database: create
a consistent snapshot separately and verify the destination before executing.
"""

import argparse
import hashlib
import json
import os
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

from meta_kpi_calc.db.base import Base
from meta_kpi_calc.db import models  # noqa: F401
from meta_kpi_calc.crm import models as crm_models  # noqa: F401
from meta_kpi_calc.crm import inbox_models  # noqa: F401

REVISION = "0006_lead_ads_inbox"


def _normalized(value):
    if isinstance(value, datetime):
        return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value.normalize())
    raise TypeError("Unsupported migration value")


def _digest(connection, table):
    digest = hashlib.sha256()
    query = select(table).order_by(*table.primary_key.columns)
    for row in connection.execute(query).mappings():
        data = json.dumps(dict(row), sort_keys=True, default=_normalized, separators=(",", ":"), ensure_ascii=False)
        digest.update(data.encode("utf-8"))
        digest.update(b"\n")
    return digest.digest()


def migrate_snapshot(source: Path, target_engine, *, execute: bool = False) -> dict:
    source = source.resolve(strict=True)
    if not source.is_file() or target_engine.dialect.name != "postgresql":
        raise ValueError("A SQLite snapshot and PostgreSQL destination are required")
    source_uri = source.as_uri() + "?mode=ro"
    source_engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(source_uri, uri=True))
    try:
        with source_engine.connect() as src, target_engine.begin() as dst:
            if src.scalar(text("SELECT version_num FROM alembic_version")) != REVISION:
                raise ValueError("Source schema revision is not supported")
            if dst.scalar(text("SELECT version_num FROM alembic_version")) != REVISION:
                raise ValueError("Destination schema revision is not supported")
            tables = Base.metadata.sorted_tables
            counts = {}
            for table in tables:
                if dst.scalar(select(func.count()).select_from(table)):
                    raise ValueError("Destination must be empty")
                counts[table.name] = src.scalar(select(func.count()).select_from(table))
            if not execute:
                return {"mode": "dry_run", "counts": counts}
            for table in tables:
                rows = src.execute(select(table).order_by(*table.primary_key.columns)).mappings()
                batch = []
                for row in rows:
                    item = dict(row)
                    for column in table.columns:
                        value = item[column.name]
                        if isinstance(value, datetime) and value.tzinfo is None and getattr(column.type, "timezone", False):
                            item[column.name] = value.replace(tzinfo=timezone.utc)
                    batch.append(item)
                    if len(batch) == 500:
                        dst.execute(table.insert(), batch)
                        batch.clear()
                if batch:
                    dst.execute(table.insert(), batch)
                if _digest(src, table) != _digest(dst, table):
                    raise ValueError("Data verification failed")
            for table in tables:
                if "id" not in table.c:
                    continue
                sequence = dst.scalar(text("SELECT pg_get_serial_sequence(:table_name, 'id')"), {"table_name": table.name})
                if sequence:
                    maximum = dst.scalar(select(func.max(table.c.id)))
                    dst.execute(text("SELECT setval(CAST(:sequence AS regclass), :value, :called)"),
                                {"sequence": sequence, "value": maximum or 1, "called": maximum is not None})
            return {"mode": "committed", "counts": counts}
    finally:
        source_engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy a read-only SQLite snapshot into an empty PostgreSQL database.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--confirm-target", required=True, help="Expected destination database name")
    parser.add_argument("--execute", action="store_true", help="Commit the copy; default is dry-run")
    args = parser.parse_args()
    engine = None
    try:
        url = make_url(os.environ["MIGRATION_TARGET_URL"])
        if url.drivername not in {"postgresql", "postgresql+psycopg"} or not url.host or url.database != args.confirm_target:
            raise ValueError("Destination confirmation failed")
        engine = create_engine(url.set(drivername="postgresql+psycopg"), pool_pre_ping=True, hide_parameters=True)
        print(json.dumps(migrate_snapshot(args.source, engine, execute=args.execute), sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({"error": "migration_failed"}))
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
