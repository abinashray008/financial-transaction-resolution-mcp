"""Durable LangGraph checkpointer for the demo HITL dispute workflow.

``InMemorySaver`` loses paused threads when the process restarts, even if
approval records in SQLite survive. This module opens a file-backed
``SqliteSaver`` so ``PENDING_REVIEW`` drafts remain resumable.

The SQLite saver is appropriate for a local demo. A production deployment
should use ``PostgresSaver`` from ``langgraph-checkpoint-postgres``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy import Engine

from ..config.settings import IN_MEMORY_DATABASE


def build_sqlite_checkpointer(path: str) -> SqliteSaver:
    """Open a SQLite checkpointer, creating parent directories and tables."""
    if path != IN_MEMORY_DATABASE:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    # LangGraph documents check_same_thread=False; SqliteSaver serializes access.
    conn = sqlite3.connect(path, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def checkpoint_path_for_engine(engine: Engine) -> str:
    """Isolate checkpoints next to a dataset file so tests do not share state.

    ``:memory:`` engines keep an in-memory checkpointer. File engines use
    ``{stem}.checkpoints{suffix}`` beside the dataset, so a rebuilt container
    on the same file can resume paused threads.
    """
    database = engine.url.database
    if not database or database == IN_MEMORY_DATABASE:
        return IN_MEMORY_DATABASE
    path = Path(database)
    suffix = path.suffix or ".db"
    return str(path.with_name(f"{path.stem}.checkpoints{suffix}"))
