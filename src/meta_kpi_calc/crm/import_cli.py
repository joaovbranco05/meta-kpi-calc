"""Local, dry-run-by-default Meta lead export importer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from meta_kpi_calc.crm.import_files import ImportFileError, parse_meta_export
from meta_kpi_calc.crm.ingestion import ingest_lead
from meta_kpi_calc.crm.models import Lead
from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.db.session import create_database_engine


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import a Meta lead export into a migrated database.")
    parser.add_argument("file", type=Path)
    parser.add_argument("--database-url", required=True, help="Explicit database URL; Alembic migrations must already be applied.")
    parser.add_argument("--commit", action="store_true", help="Persist rows; default is a read-only dry run.")
    args = parser.parse_args(argv)
    try:
        url = make_url(args.database_url)
        if url.drivername not in {"sqlite", "postgresql", "postgresql+psycopg"} or not url.database:
            parser.error("--database-url must identify a SQLite or PostgreSQL database.")
        if url.drivername == "sqlite":
            database_path = Path(url.database)
            if url.database == ":memory:" or not database_path.is_file():
                parser.error("--database-url must identify an existing migrated SQLite file.")
        with args.file.open("rb") as stream:
            submissions, report = parse_meta_export(stream, args.file.name)
    except (OSError, ImportFileError) as exc:
        code = exc.code if isinstance(exc, ImportFileError) else "file_unavailable"
        print(json.dumps({"error": code}, sort_keys=True))
        return 2

    settings = Settings(
        _env_file=None,
        demo_mode=False,
        database_url=args.database_url,
        demo_database_url="sqlite:///:memory:",
    )
    engine = create_database_engine(settings) if args.commit else create_engine(settings.active_database_url, hide_parameters=True)
    try:
        with Session(engine, expire_on_commit=False) as session:
            if args.commit:
                try:
                    for submission in submissions:
                        result = ingest_lead(session, submission)
                        if result.created:
                            report.inserted += 1
                        else:
                            report.existing += 1
                    session.commit()
                except Exception:
                    session.rollback()
                    print(json.dumps({"error": "import_failed"}, sort_keys=True))
                    return 2
            else:
                ids = [item.meta_lead_id for item in submissions]
                existing = set(session.scalars(select(Lead.meta_lead_id).where(Lead.meta_lead_id.in_(ids))).all()) if ids else set()
                seen: set[str] = set()
                for value in ids:
                    if value in existing or value in seen:
                        report.existing += 1
                    else:
                        report.inserted += 1
                    seen.add(value)
            payload = report.as_dict()
            payload["mode"] = "committed" if args.commit else "dry_run"
            print(json.dumps(payload, sort_keys=True))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
