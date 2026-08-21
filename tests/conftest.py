"""Shared fixtures.

Each test gets its own seeded SQLite file, so tests can assert on audit
contents without interfering with one another.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

os.environ["OPIK_TRACK_DISABLE"] = "true"

import pytest
from sqlalchemy import Engine

from src.app.container import Container, build_container_from_engine
from src.app.data_seed import DEFAULT_SEED, seed_database
from src.contracts.common import ToolResponseBase
from src.domain.exceptions import ErrorCode
from src.repositories.session import build_engine

SCENARIO_ACCOUNT = "ACCT-0001"
OTHER_ACCOUNT = "ACCT-0002"


@pytest.fixture
def engine(tmp_path) -> Iterator[Engine]:
    """A freshly seeded database, isolated per test."""
    created = build_engine(f"sqlite+pysqlite:///{tmp_path / 'test.db'}")
    seed_database(created, seed=DEFAULT_SEED)
    yield created
    created.dispose()


@pytest.fixture
def container(engine: Engine) -> Container:
    """Repositories and services wired over the seeded database."""
    return build_container_from_engine(engine)


def assert_ok(response: ToolResponseBase) -> None:
    """Assert a tool call succeeded, showing the error if it did not."""
    assert response.status == "ok", f"expected success, got {response.error}"
    assert response.error is None


def assert_error(response: ToolResponseBase, code: ErrorCode) -> None:
    """Assert a tool call failed with a specific stable code."""
    assert response.status == "error", "expected an error response"
    assert response.error is not None
    assert response.error.code == code
    assert getattr(response, "data", None) is None
