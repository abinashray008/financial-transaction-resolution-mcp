"""Engine and session construction."""

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

SessionFactory = sessionmaker[Session]

_SQLITE_PREFIX = "sqlite+pysqlite:///"


def build_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create an engine for the synthetic dataset, creating its folder if needed."""
    options: dict[str, Any] = {"echo": echo, "future": True}
    if database_url.startswith(_SQLITE_PREFIX):
        file_part = database_url[len(_SQLITE_PREFIX) :]
        if file_part and file_part != ":memory:":
            Path(file_part).parent.mkdir(parents=True, exist_ok=True)
        options["connect_args"] = {"check_same_thread": False}
    return create_engine(database_url, **options)


def build_session_factory(engine: Engine) -> SessionFactory:
    """Create a session factory bound to the given engine."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
