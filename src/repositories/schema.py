"""Create and upgrade the tables this server writes.

``create(checkfirst=True)`` will not add columns to an existing local
``dispute_cases`` table from an earlier schema, so this module also applies a
small additive SQLite upgrade.
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from .models import Base

_WRITABLE_TABLES = (
    "audit_events",
    "dispute_cases",
    "dispute_evidence_snapshots",
    "confirmation_challenges",
    "dispute_lifecycle_events",
)

_DISPUTE_CASE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("investigation_id", "VARCHAR(64) DEFAULT ''"),
    ("confirmation_id", "VARCHAR(48) DEFAULT ''"),
    ("idempotency_key", "VARCHAR(128) DEFAULT ''"),
    ("reason_code", "VARCHAR(48) DEFAULT 'UNRECOGNIZED_TRANSACTION'"),
    ("version", "INTEGER DEFAULT 1"),
    ("evidence_hash", "VARCHAR(64) DEFAULT ''"),
    ("updated_at", "DATETIME"),
    ("externally_submitted", "BOOLEAN DEFAULT 0"),
    ("reviewer_id", "VARCHAR(128)"),
    ("review_reason_code", "VARCHAR(48)"),
    ("review_note", "VARCHAR(500)"),
    ("reviewed_at", "DATETIME"),
)


def ensure_writable_schema(engine: Engine) -> None:
    """Create writable tables and add any missing ``dispute_cases`` columns."""
    for name in _WRITABLE_TABLES:
        Base.metadata.tables[name].create(bind=engine, checkfirst=True)
    _upgrade_dispute_cases(engine)


def _upgrade_dispute_cases(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("dispute_cases"):
        return
    existing = {column["name"] for column in inspector.get_columns("dispute_cases")}
    statements: list[str] = []
    for name, ddl in _DISPUTE_CASE_COLUMNS:
        if name not in existing:
            statements.append(f"ALTER TABLE dispute_cases ADD COLUMN {name} {ddl}")
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        if "request_id" in existing:
            connection.execute(
                text(
                    "UPDATE dispute_cases SET investigation_id = request_id "
                    "WHERE investigation_id IS NULL OR investigation_id = ''"
                )
            )
        connection.execute(text("UPDATE dispute_cases SET updated_at = created_at WHERE updated_at IS NULL"))
        _create_unique_index_if_possible(
            connection,
            "ix_dispute_cases_idempotency_key",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_dispute_cases_idempotency_key ON dispute_cases (idempotency_key)",
        )
        _create_unique_index_if_possible(
            connection,
            "ix_dispute_cases_confirmation_id",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_dispute_cases_confirmation_id ON dispute_cases (confirmation_id)",
        )


def _create_unique_index_if_possible(connection: Connection, _name: str, statement: str) -> None:
    """Skip a unique index when existing local rows would collide."""
    try:
        connection.execute(text(statement))
    except Exception:
        return
