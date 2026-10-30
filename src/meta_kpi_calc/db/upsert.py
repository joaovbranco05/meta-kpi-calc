"""Select a supported dialect's conflict-aware INSERT implementation."""

from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session


def insert_for_session(session: Session, model):
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        return sqlite_insert(model)
    if dialect == "postgresql":
        return postgres_insert(model)
    raise ValueError("Unsupported database dialect")
