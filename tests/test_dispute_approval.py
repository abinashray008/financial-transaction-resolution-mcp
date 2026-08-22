"""Verifiable one-time approval records for dispute submission."""

import base64
import json
import re
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from src.app.approvals import ApprovalService
from src.contracts.requests import SubmitDisputeCaseRequest
from src.domain.enums import ApprovalDecision
from src.domain.exceptions import (
    DisputeApprovalAlreadyConsumedError,
    DisputeApprovalExpiredError,
    DisputeApprovalMismatchError,
    DisputeApprovalNotFoundError,
    DisputeWorkflowNotFoundError,
    ErrorCode,
)
from src.server import create_mcp_server
from tests.conftest import SCENARIO_ACCOUNT, assert_error
from tests.test_dispute_workflow import _draft, _mint, _submit


def test_record_decision_requires_a_paused_draft(container):
    try:
        container.approval_service.record_decision(
            request_id="inv-apr-missing",
            reviewer_id="rev-test-1",
            decision=ApprovalDecision.APPROVED,
        )
    except DisputeWorkflowNotFoundError:
        return
    raise AssertionError("expected DisputeWorkflowNotFoundError")


def test_expired_approval_cannot_submit(container):
    request_id = "inv-apr-expired"
    assert _draft(container, request_id=request_id).status == "ok"
    now = datetime(2026, 8, 21, 12, 0, 0)
    clock = {"now": now}

    service = ApprovalService(
        approvals=container.approvals,
        workflow=container.dispute_workflow,
        clock=lambda: clock["now"],
        ttl_seconds=60,
    )
    approval = service.record_decision(
        request_id=request_id,
        reviewer_id="rev-test-1",
        decision=ApprovalDecision.APPROVED,
        decision_note="Customer confirmed",
    )
    clock["now"] = now + timedelta(seconds=61)
    proposal = container.dispute_workflow.get_pending(request_id)

    try:
        service.consume(
            approval_id=approval.approval_id,
            request_id=request_id,
            expected_draft_hash=proposal.draft_hash,
        )
    except DisputeApprovalExpiredError:
        assert container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A") is None
        return
    raise AssertionError("expected DisputeApprovalExpiredError")


def test_hash_mismatch_is_rejected(container):
    request_id = "inv-apr-hash"
    assert _draft(container, request_id=request_id).status == "ok"
    approval = _mint(
        container,
        request_id,
        decision=ApprovalDecision.APPROVED,
        note="Customer confirmed",
    )

    try:
        container.approval_service.consume(
            approval_id=approval.approval_id,
            request_id=request_id,
            expected_draft_hash="0" * 64,
        )
    except DisputeApprovalMismatchError:
        return
    raise AssertionError("expected DisputeApprovalMismatchError")


def test_unknown_approval_id_is_not_found(container):
    request_id = "inv-apr-unknown"
    assert _draft(container, request_id=request_id).status == "ok"
    proposal = container.dispute_workflow.get_pending(request_id)

    try:
        container.approval_service.consume(
            approval_id="apr-unknown0001",
            request_id=request_id,
            expected_draft_hash=proposal.draft_hash,
        )
    except DisputeApprovalNotFoundError:
        return
    raise AssertionError("expected DisputeApprovalNotFoundError")


def test_consume_is_one_time(container):
    request_id = "inv-apr-once"
    assert _draft(container, request_id=request_id).status == "ok"
    approval = _mint(
        container,
        request_id,
        decision=ApprovalDecision.APPROVED,
        note="Customer confirmed",
    )
    first = _submit(container, request_id=request_id, approval_id=approval.approval_id)
    assert first.status == "ok"

    try:
        proposal_hash = approval.draft_hash
        container.approval_service.consume(
            approval_id=approval.approval_id,
            request_id=request_id,
            expected_draft_hash=proposal_hash,
        )
    except DisputeApprovalAlreadyConsumedError:
        return
    raise AssertionError("expected DisputeApprovalAlreadyConsumedError")


def test_http_review_mints_approval_id_from_reviewer_identity(container):
    request_id = "inv-apr-http"
    assert _draft(container, request_id=request_id).status == "ok"
    server = create_mcp_server(container)

    with TestClient(server.http_app()) as client:
        shown = client.get(f"/reviews/{request_id}", headers={"accept": "application/json"})
        minted = client.post(
            f"/reviews/{request_id}/decision",
            headers={"x-reviewer-id": "rev-http-1", "accept": "application/json"},
            json={"decision": "approved", "decision_note": "Reviewed in the app"},
        )

    assert shown.status_code == 200
    assert shown.json()["transaction_id"] == "TXN-SCN-DUP-A"
    assert shown.json()["draft_hash"]
    assert minted.status_code == 201
    body = minted.json()
    assert body["approval_id"].startswith("apr-")
    assert body["request_id"] == request_id
    assert body["reviewer_id"] == "rev-http-1"
    assert body["decision"] == "approved"
    assert body["consumed_at"] is None
    stored = container.approvals.get(body["approval_id"])
    assert stored is not None
    assert stored.draft_hash == shown.json()["draft_hash"]


def test_http_review_requires_reviewer_identity(container):
    request_id = "inv-apr-norev"
    assert _draft(container, request_id=request_id).status == "ok"
    server = create_mcp_server(container)

    with TestClient(server.http_app()) as client:
        response = client.post(
            f"/reviews/{request_id}/decision",
            headers={"accept": "application/json"},
            json={"decision": "approved"},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUT"


def test_http_review_with_descope_requires_bearer(container):
    from src.config.settings import Settings
    from src.security.descope import build_descope_provider

    request_id = "inv-apr-auth"
    assert _draft(container, request_id=request_id).status == "ok"
    settings = Settings(
        _env_file=None,
        descope_config_url=(
            "https://api.descope.com/v1/apps/agentic/P2TESTPROJECTID/M2TESTMCPID/.well-known/openid-configuration"
        ),
        base_url="http://127.0.0.1:8000",
    )
    server = create_mcp_server(container, auth=build_descope_provider(settings))

    with TestClient(server.http_app()) as client:
        response = client.post(
            f"/reviews/{request_id}/decision",
            headers={"x-reviewer-id": "rev-http-1", "accept": "application/json"},
            json={"decision": "approved"},
        )

    assert response.status_code == 401


def test_http_review_html_form_mints_without_bearer_when_descope_enabled(container):
    from src.config.settings import Settings
    from src.security.descope import build_descope_provider

    request_id = "inv-html-form"
    assert _draft(container, request_id=request_id).status == "ok"
    settings = Settings(
        _env_file=None,
        descope_config_url=(
            "https://api.descope.com/v1/apps/agentic/P2TESTPROJECTID/M2TESTMCPID/.well-known/openid-configuration"
        ),
        base_url="http://127.0.0.1:8000",
    )
    server = create_mcp_server(container, auth=build_descope_provider(settings))

    with TestClient(server.http_app()) as client:
        shown = client.get(f"/reviews/{request_id}", headers={"accept": "text/html"})
        minted = client.post(
            f"/reviews/{request_id}/decision",
            data={
                "decision": "approved",
                "decision_note": "Reviewed in the browser form",
                "reviewer_id": "rev-form-1",
            },
        )

    assert shown.status_code == 200
    assert "Reviewer id" in shown.text
    assert minted.status_code == 201
    match = re.search(r"apr-[A-Za-z0-9]+", minted.text)
    assert match is not None
    stored = container.approvals.get(match.group())
    assert stored is not None
    assert stored.reviewer_id == "rev-form-1"
    assert stored.decision == ApprovalDecision.APPROVED


def test_http_review_reads_reviewer_from_jwt_sub(container):
    request_id = "inv-apr-jwt"
    assert _draft(container, request_id=request_id).status == "ok"
    server = create_mcp_server(container)
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"sub": "rev-jwt-1"}).encode()).rstrip(b"=").decode()
    token = f"{header}.{payload}.x"

    with TestClient(server.http_app()) as client:
        minted = client.post(
            f"/reviews/{request_id}/decision",
            headers={"authorization": f"Bearer {token}", "accept": "application/json"},
            json={"decision": "declined", "decision_note": "No case"},
        )

    assert minted.status_code == 201
    assert minted.json()["reviewer_id"] == "rev-jwt-1"
    assert minted.json()["decision"] == "declined"


def test_submit_contract_rejects_approved_boolean():
    with pytest.raises(ValidationError):
        SubmitDisputeCaseRequest(request_id="inv-001", approval_id="apr-901", approved=True)


def test_forged_approval_id_does_not_register(container):
    request_id = "inv-apr-bool"
    assert _draft(container, request_id=request_id).status == "ok"

    response = _submit(container, request_id=request_id, approval_id="apr-forgedtrue")

    assert_error(response, ErrorCode.DISPUTE_APPROVAL_NOT_FOUND)
    assert container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A") is None


def test_http_review_missing_draft_is_not_found(container):
    server = create_mcp_server(container)

    with TestClient(server.http_app()) as client:
        response = client.get("/reviews/inv-apr-absent", headers={"accept": "application/json"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DISPUTE_WORKFLOW_NOT_FOUND"


def test_approval_record_fields_are_complete(container):
    request_id = "inv-apr-fields"
    drafted = _draft(container, request_id=request_id)
    assert drafted.data is not None
    before = datetime.now(UTC).replace(tzinfo=None)
    approval = _mint(
        container,
        request_id,
        decision=ApprovalDecision.APPROVED,
        note="Looks correct",
    )
    after = datetime.now(UTC).replace(tzinfo=None)

    assert approval.approval_id.startswith("apr-")
    assert approval.request_id == request_id
    assert approval.draft_hash == drafted.data.draft_hash
    assert approval.reviewer_id == "rev-test-1"
    assert approval.decision is ApprovalDecision.APPROVED
    assert approval.decision_note == "Looks correct"
    assert before <= approval.created_at <= after
    assert approval.created_at == approval.decided_at
    assert approval.expires_at > approval.created_at
    assert approval.consumed_at is None
