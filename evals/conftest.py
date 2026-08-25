"""Fixtures for synthesis evaluations.

Deterministic evals inject the same fake Gemini client used in unit tests, with a
reply that includes the facts the scorecard looks for. Live evals leave synthesis
unset so the handler builds ``GeminiSynthesisClient``.
"""

from __future__ import annotations

import json
import os

os.environ["OPIK_TRACK_DISABLE"] = "true"

import pytest
from sqlalchemy import Engine
from tests.conftest import engine as engine
from tests.test_synthesis import FakeSynthesisClient

from src.app.container import Container, build_container_from_engine


class ScorecardAwareFake(FakeSynthesisClient):
    """Call-recording fake whose canned reply can be graded by the scorecard.

    This does not exercise Gemini. It proves dataset loading, scoring, and the
    synthesize_investigation wiring still work.
    """

    def synthesize(
        self,
        *,
        account_id: str,
        transaction_id: str,
        investigation_findings: str,
        trusted_policy: str | None = None,
    ) -> str:
        super().synthesize(
            account_id=account_id,
            transaction_id=transaction_id,
            investigation_findings=investigation_findings,
            trusted_policy=trusted_policy,
        )
        parsed = json.loads(investigation_findings)
        transaction = parsed["get_transaction_details"]["data"]["transaction"]
        duplicate = parsed["check_duplicate_charge"]["data"]
        candidates = ", ".join(duplicate["candidate_transaction_ids"])
        return (
            f"Verified facts: {transaction['merchant']} charged {transaction['amount']} "
            f"{transaction['currency']} on {transaction['transaction_id']}. "
            f"This looks like a duplicate (confidence {duplicate['confidence']}); "
            f"candidate {candidates}.\n"
            "This is a dispute draft only. Human review and approval are required "
            "before any case is registered. No refund has been issued."
        )


@pytest.fixture
def container(engine: Engine) -> Container:
    """Seeded container with the deterministic synthesis client."""
    return build_container_from_engine(engine, synthesis=ScorecardAwareFake())


@pytest.fixture
def live_container(engine: Engine) -> Container:
    """Seeded container that calls Gemini when GEMINI_API_KEY is set."""
    return build_container_from_engine(engine)
