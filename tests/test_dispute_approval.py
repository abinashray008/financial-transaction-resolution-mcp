"""HTTP back-office review of persisted PENDING_REVIEW cases."""

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from src.app.presenters import CASE_CREATED_MESSAGE
from src.contracts.requests import ConfirmUnrecognizedTransactionRequest
from src.domain.enums import DisputeCaseStatus, ReviewReasonCode
from src.domain.exceptions import ErrorCode
from src.security.reviewer import ReviewAuth
from src.server import create_mcp_server
from tests.conftest import assert_ok
from tests.test_dispute_workflow import _draft


def test_http_review_approves_existing_case_in_local_demo(container):
    response = _draft(container, request_id="inv-apr-http")
    assert_ok(response)
    assert response.data is not None
    case_id = response.data.case_id
    server = create_mcp_server(container, review_auth=ReviewAuth.local_demo())

    with TestClient(server.http_app()) as client:
        shown = client.get(
            f"/reviews/{case_id}",
            headers={"x-reviewer-id": "rev-http-1", "accept": "application/json"},
        )
        decided = client.post(
            f"/reviews/{case_id}/decision",
            headers={"x-reviewer-id": "rev-http-1", "accept": "application/json"},
            json={
                "case_id": case_id,
                "expected_version": shown.json()["version"],
                "decision": "APPROVE",
                "reason_code": ReviewReasonCode.EVIDENCE_SUPPORTS_DISPUTE.value,
                "note": "Customer confirmed",
            },
        )

    assert shown.status_code == 200
    assert shown.json()["status"] == DisputeCaseStatus.PENDING_REVIEW.value
    assert shown.json()["case_id"] == case_id
    assert decided.status_code == 200
    body = decided.json()
    assert body["reviewer_id"] == "rev-http-1"
    assert body["status"] == DisputeCaseStatus.APPROVED.value
    assert body["externally_submitted"] is False
    stored = container.disputes.get(case_id)
    assert stored is not None
    assert stored.status is DisputeCaseStatus.APPROVED
    assert stored.reviewer_id == "rev-http-1"


def test_http_review_json_cannot_spoof_reviewer_id(container):
    response = _draft(container, request_id="inv-apr-spoof")
    assert_ok(response)
    assert response.data is not None
    case_id = response.data.case_id
    server = create_mcp_server(container, review_auth=ReviewAuth.local_demo())

    with TestClient(server.http_app()) as client:
        decided = client.post(
            f"/reviews/{case_id}/decision",
            headers={"x-reviewer-id": "rev-real", "accept": "application/json"},
            json={
                "case_id": case_id,
                "expected_version": 1,
                "decision": "APPROVE",
                "reason_code": ReviewReasonCode.CUSTOMER_CONFIRMATION_CLEAR.value,
                "reviewer_id": "rev-spoof",
            },
        )

    assert decided.status_code == 400
    stored = container.disputes.get(case_id)
    assert stored is not None
    assert stored.status is DisputeCaseStatus.PENDING_REVIEW


def test_http_review_rejects_stale_version(container):
    response = _draft(container, request_id="inv-apr-stale")
    assert_ok(response)
    assert response.data is not None
    case_id = response.data.case_id
    server = create_mcp_server(container, review_auth=ReviewAuth.local_demo())

    with TestClient(server.http_app()) as client:
        decided = client.post(
            f"/reviews/{case_id}/decision",
            headers={"x-reviewer-id": "rev-http-1", "accept": "application/json"},
            json={
                "case_id": case_id,
                "expected_version": 9,
                "decision": "REJECT",
                "reason_code": ReviewReasonCode.EVIDENCE_INSUFFICIENT.value,
            },
        )

    assert decided.status_code == 409
    assert decided.json()["error"]["code"] == ErrorCode.DISPUTE_CASE_VERSION_CONFLICT.value


def test_http_review_html_local_demo_records_a_decision(container):
    response = _draft(container, request_id="inv-apr-html")
    assert_ok(response)
    assert response.data is not None
    case_id = response.data.case_id
    server = create_mcp_server(container, review_auth=ReviewAuth.local_demo())

    with TestClient(server.http_app()) as client:
        shown = client.get(f"/reviews/{case_id}", headers={"accept": "text/html"})
        decided = client.post(
            f"/reviews/{case_id}/decision",
            headers={"accept": "text/html", "content-type": "application/x-www-form-urlencoded"},
            data={
                "case_id": case_id,
                "expected_version": "1",
                "decision": "APPROVE",
                "reason_code": ReviewReasonCode.POLICY_CRITERIA_MET.value,
                "note": "Looks good",
                "reviewer_id": "local-reviewer",
            },
        )

    assert shown.status_code == 200
    assert "Reviewer id" in shown.text
    assert decided.status_code == 200
    assert "Decision recorded" in decided.text
    stored = container.disputes.get(case_id)
    assert stored is not None
    assert stored.reviewer_id == "local-reviewer"
    assert stored.status is DisputeCaseStatus.APPROVED


def test_unknown_case_is_not_found(container):
    server = create_mcp_server(container, review_auth=ReviewAuth.local_demo())
    with TestClient(server.http_app()) as client:
        shown = client.get(
            "/reviews/DSP-NOPE0001", headers={"x-reviewer-id": "rev-http-1", "accept": "application/json"}
        )
    assert shown.status_code == 404
    assert shown.json()["error"]["code"] == ErrorCode.DISPUTE_CASE_NOT_FOUND.value


def test_confirm_request_forbids_approval_flag():
    with pytest.raises(ValidationError):
        ConfirmUnrecognizedTransactionRequest.model_validate(
            {
                "investigation_id": "inv-001",
                "account_id": "ACCT-0001",
                "transaction_id": "TXN-SCN-DUP-A",
                "confirmation_token": "cnf_" + ("a" * 32),
                "idempotency_key": "idem-key-1",
                "approved": True,
            }
        )


def test_customer_message_is_the_required_sla(container):
    response = _draft(container, request_id="inv-apr-sla")
    assert_ok(response)
    assert response.data is not None
    assert response.data.message == CASE_CREATED_MESSAGE
