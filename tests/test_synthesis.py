"""Unit tests for Gemini synthesis wiring."""

import json

import pytest

from src.app.container import Container, build_container_from_engine
from src.contracts.requests import SynthesizeInvestigationRequest
from src.domain.exceptions import ErrorCode
from src.tools.synthesize_investigation_tool import synthesize_investigation
from tests.conftest import SCENARIO_ACCOUNT, assert_error, assert_ok


class FakeSynthesisClient:
    """Deterministic stand-in for Gemini."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def synthesize(
        self,
        *,
        account_id: str,
        transaction_id: str,
        investigation_findings: str,
    ) -> str:
        self.calls.append(
            {
                "account_id": account_id,
                "transaction_id": transaction_id,
                "investigation_findings": investigation_findings,
            }
        )
        return (
            "Verified facts: the tools show a likely duplicate of TXN-SCN-DUP-A.\n"
            "Inferences: the charge may have posted twice.\n"
            "Next step: a specialist should review the audit trail."
        )


@pytest.fixture
def synthesis_container(engine) -> tuple[Container, FakeSynthesisClient]:
    fake = FakeSynthesisClient()
    return build_container_from_engine(engine, synthesis=fake), fake


def test_synthesize_investigation_uses_injected_client(synthesis_container):
    container, fake = synthesis_container
    findings = json.dumps(
        {
            "get_transaction_details": {
                "status": "ok",
                "request_id": "inv-1",
                "data": {"transaction": {"transaction_id": "TXN-SCN-DUP-A"}},
            }
        }
    )

    response = synthesize_investigation(
        container,
        SynthesizeInvestigationRequest(
            account_id=SCENARIO_ACCOUNT,
            transaction_id="TXN-SCN-DUP-A",
            investigation_findings=findings,
            request_id="inv-1",
        ),
    )

    assert_ok(response)
    assert response.data is not None
    assert "likely duplicate" in response.data.customer_response
    assert response.data.model_name == "gemini-2.5-pro"
    assert len(fake.calls) == 1
    assert fake.calls[0]["account_id"] == SCENARIO_ACCOUNT
    assert fake.calls[0]["transaction_id"] == "TXN-SCN-DUP-A"


def test_synthesize_investigation_rejects_invalid_json(synthesis_container):
    container, _fake = synthesis_container

    response = synthesize_investigation(
        container,
        SynthesizeInvestigationRequest(
            account_id=SCENARIO_ACCOUNT,
            transaction_id="TXN-SCN-DUP-A",
            investigation_findings="not-json",
        ),
    )

    assert_error(response, ErrorCode.INVALID_INPUT)


def test_synthesize_investigation_requires_api_key_without_client(engine):
    container = build_container_from_engine(engine, synthesis=None)
    findings = json.dumps({"get_account_summary": {"status": "ok"}})

    response = synthesize_investigation(
        container,
        SynthesizeInvestigationRequest(
            account_id=SCENARIO_ACCOUNT,
            transaction_id="TXN-SCN-DUP-A",
            investigation_findings=findings,
        ),
    )

    assert_error(response, ErrorCode.SYNTHESIS_UNAVAILABLE)
