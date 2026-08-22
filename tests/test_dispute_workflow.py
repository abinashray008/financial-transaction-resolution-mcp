"""Human-in-the-loop dispute registration via LangGraph."""

import json

import pytest
from pydantic import ValidationError

from src.contracts.requests import CreateDisputeDraftRequest, SubmitDisputeCaseRequest
from src.domain.enums import ApprovalDecision, DisputeCaseStatus, DisputeReasonCode, DisputeWorkflowStatus
from src.domain.exceptions import ErrorCode
from src.domain.services.dispute_draft import DEFAULT_POLICY_URI, PROPOSED_ACTION
from src.tools.create_dispute_draft_tool import create_dispute_draft
from src.tools.submit_dispute_case_tool import submit_dispute_case
from tests.conftest import OTHER_ACCOUNT, SCENARIO_ACCOUNT, assert_error, assert_ok

FINDINGS = json.dumps(
    {
        "get_transaction_details": {
            "status": "ok",
            "request_id": "inv-dsp-1",
            "data": {"transaction": {"transaction_id": "TXN-SCN-DUP-A"}},
        }
    }
)
RICH_FINDINGS = json.dumps(
    {
        "selected_policy_uri": "policy://disputes/unrecognized-transaction",
        "get_account_summary": {
            "status": "ok",
            "data": {
                "account_type": "consumer_credit_card",
                "account_status": "active",
            },
        },
        "get_transaction_details": {
            "status": "ok",
            "data": {"transaction": {"transaction_id": "TXN-SCN-DUP-A"}},
        },
        "resolve_merchant": {
            "status": "ok",
            "data": {
                "matched": True,
                "display_name": "Halcyon Electronics",
                "match_confidence": "HIGH",
            },
        },
        "check_duplicate_charge": {
            "status": "ok",
            "data": {
                "duplicate_likely": True,
                "confidence": "HIGH",
                "candidate_transaction_ids": ["TXN-SCN-DUP-B"],
            },
        },
    }
)
SYNTHESIS = "The tools show a likely duplicate of TXN-SCN-DUP-A at Halcyon Electronics for 89.99 USD."
REVIEWER_ID = "rev-test-1"


def _draft(container, *, request_id: str, transaction_id: str = "TXN-SCN-DUP-A", findings: str = FINDINGS):
    return create_dispute_draft(
        container,
        CreateDisputeDraftRequest(
            account_id=SCENARIO_ACCOUNT,
            transaction_id=transaction_id,
            investigation_findings=findings,
            synthesis_summary=SYNTHESIS,
            request_id=request_id,
        ),
    )


def _mint(container, request_id: str, *, decision: ApprovalDecision, note: str):
    return container.approval_service.record_decision(
        request_id=request_id,
        reviewer_id=REVIEWER_ID,
        decision=decision,
        decision_note=note,
    )


def _submit(container, *, request_id: str, approval_id: str):
    return submit_dispute_case(
        container,
        SubmitDisputeCaseRequest(request_id=request_id, approval_id=approval_id),
    )


def test_create_draft_does_not_require_approval_and_does_not_write(container):
    response = _draft(container, request_id="inv-dsp-propose")

    assert_ok(response)
    assert response.data is not None
    assert response.data.status == DisputeWorkflowStatus.PENDING_REVIEW
    assert response.data.transaction_id == "TXN-SCN-DUP-A"
    assert response.data.merchant_display_name == "Halcyon Electronics"
    assert str(response.data.amount) == "89.99"
    assert response.data.masked_account_id == "ACCT-****0001"
    assert response.data.masked_customer_id.startswith("CUST-")
    assert "****" in response.data.masked_customer_id
    assert response.data.reason_code == DisputeReasonCode.NEEDS_SPECIALIST_REVIEW
    assert response.data.applied_policy == DEFAULT_POLICY_URI
    assert response.data.proposed_action == PROPOSED_ACTION
    assert len(response.data.draft_hash) == 64
    assert response.data.review_path == "/reviews/inv-dsp-propose"
    assert any("TXN-SCN-DUP-A" in item for item in response.data.verified_evidence)
    assert any("get_account_summary" in item for item in response.data.missing_evidence)
    assert any("resolve_merchant" in item for item in response.data.missing_evidence)
    assert any("check_duplicate_charge" in item for item in response.data.missing_evidence)
    assert SCENARIO_ACCOUNT not in json.dumps(response.model_dump(mode="json"))
    assert "Lindholm" not in json.dumps(response.model_dump(mode="json"))
    assert container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A") is None


def test_complete_findings_set_likely_duplicate_reason_code(container):
    response = _draft(container, request_id="inv-dsp-rich", findings=RICH_FINDINGS)

    assert_ok(response)
    assert response.data is not None
    assert response.data.status == DisputeWorkflowStatus.PENDING_REVIEW
    assert response.data.reason_code == DisputeReasonCode.LIKELY_DUPLICATE
    assert response.data.applied_policy == "policy://disputes/unrecognized-transaction"
    assert response.data.missing_evidence == []
    assert any("likely duplicate" in item for item in response.data.verified_evidence)
    assert container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A") is None


def test_verified_approval_registers_a_case_for_the_same_customer(container):
    request_id = "inv-dsp-approve"
    proposed = _draft(container, request_id=request_id)
    assert_ok(proposed)
    approval = _mint(
        container,
        request_id,
        decision=ApprovalDecision.APPROVED,
        note="Customer confirmed",
    )

    decided = _submit(container, request_id=request_id, approval_id=approval.approval_id)

    assert_ok(decided)
    assert decided.data is not None
    assert decided.data.registered is True
    assert decided.data.workflow_status == DisputeWorkflowStatus.REGISTERED
    assert decided.data.case_id is not None
    assert decided.data.case_id.startswith("DSP-")
    assert decided.data.approval_id == approval.approval_id
    assert decided.data.decision_note == "Customer confirmed"

    stored = container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A")
    account = container.accounts.get_with_customer_state(SCENARIO_ACCOUNT)
    consumed = container.approvals.get(approval.approval_id)
    assert stored is not None
    assert account is not None
    assert stored.customer_id == account.account.customer_id
    assert stored.account_id == SCENARIO_ACCOUNT
    assert stored.transaction_id == "TXN-SCN-DUP-A"
    assert stored.status == DisputeCaseStatus.REGISTERED
    assert stored.request_id == request_id
    assert "Halcyon Electronics" in stored.reason
    assert "89.99" in stored.reason
    assert consumed is not None
    assert consumed.consumed_at is not None
    assert consumed.reviewer_id == REVIEWER_ID


def test_declined_approval_does_not_register_a_case(container):
    request_id = "inv-dsp-decline"
    assert_ok(_draft(container, request_id=request_id))
    approval = _mint(
        container,
        request_id,
        decision=ApprovalDecision.DECLINED,
        note="Customer declined",
    )

    decided = _submit(container, request_id=request_id, approval_id=approval.approval_id)

    assert_ok(decided)
    assert decided.data is not None
    assert decided.data.registered is False
    assert decided.data.workflow_status == DisputeWorkflowStatus.DECLINED
    assert decided.data.case_id is None
    assert decided.data.approval_id == approval.approval_id
    assert container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A") is None


def test_create_draft_is_idempotent_while_pending_review(container):
    first = _draft(container, request_id="inv-dsp-again")
    second = _draft(container, request_id="inv-dsp-again")

    assert_ok(first)
    assert_ok(second)
    assert first.data is not None
    assert second.data is not None
    assert first.data.reason == second.data.reason
    assert first.data.draft_hash == second.data.draft_hash
    assert container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A") is None


def test_cannot_register_a_second_case_for_the_same_charge(container):
    assert_ok(_draft(container, request_id="inv-dsp-dup-1"))
    approval = _mint(
        container,
        "inv-dsp-dup-1",
        decision=ApprovalDecision.APPROVED,
        note="Customer confirmed",
    )
    assert_ok(_submit(container, request_id="inv-dsp-dup-1", approval_id=approval.approval_id))

    response = _draft(container, request_id="inv-dsp-dup-2")

    assert_error(response, ErrorCode.DISPUTE_ALREADY_EXISTS)
    assert container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A") is not None


def test_submit_without_a_minted_approval_is_not_found(container):
    assert_ok(_draft(container, request_id="inv-dsp-missing"))

    response = _submit(container, request_id="inv-dsp-missing", approval_id="apr-doesnotexist")

    assert_error(response, ErrorCode.DISPUTE_APPROVAL_NOT_FOUND)
    assert container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A") is None


def test_submit_without_a_draft_is_not_found(container):
    response = _submit(container, request_id="inv-dsp-nodraft", approval_id="apr-orphan001")

    assert_error(response, ErrorCode.DISPUTE_WORKFLOW_NOT_FOUND)
    assert container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A") is None


def test_consumed_approval_cannot_be_reused(container):
    request_id = "inv-dsp-finished"
    assert_ok(_draft(container, request_id=request_id))
    approval = _mint(
        container,
        request_id,
        decision=ApprovalDecision.DECLINED,
        note="Customer declined",
    )
    assert_ok(_submit(container, request_id=request_id, approval_id=approval.approval_id))

    response = _submit(container, request_id=request_id, approval_id=approval.approval_id)

    assert_error(response, ErrorCode.DISPUTE_NOT_AWAITING_APPROVAL)
    assert container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A") is None


def test_approval_for_a_different_request_is_rejected(container):
    assert_ok(_draft(container, request_id="inv-dsp-isolation-a"))
    assert_ok(_draft(container, request_id="inv-dsp-isolation-b", transaction_id="TXN-SCN-DUP-B"))
    approval = _mint(
        container,
        "inv-dsp-isolation-a",
        decision=ApprovalDecision.APPROVED,
        note="Customer confirmed",
    )

    response = _submit(container, request_id="inv-dsp-isolation-b", approval_id=approval.approval_id)

    assert_error(response, ErrorCode.DISPUTE_APPROVAL_NOT_FOUND)
    assert container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A") is None


def test_submit_request_rejects_approved_boolean():
    with pytest.raises(ValidationError):
        SubmitDisputeCaseRequest(
            request_id="inv-001",
            approval_id="apr-901",
            approved=True,
        )


def test_create_draft_rejects_a_transaction_on_another_account(container):
    response = create_dispute_draft(
        container,
        CreateDisputeDraftRequest(
            account_id=OTHER_ACCOUNT,
            transaction_id="TXN-SCN-DUP-A",
            investigation_findings=FINDINGS,
            synthesis_summary=SYNTHESIS,
            request_id="inv-dsp-other",
        ),
    )

    assert_error(response, ErrorCode.TRANSACTION_NOT_FOUND)


def test_blank_synthesis_summary_is_rejected(container):
    response = create_dispute_draft(
        container,
        CreateDisputeDraftRequest(
            account_id=SCENARIO_ACCOUNT,
            transaction_id="TXN-SCN-DUP-A",
            investigation_findings=FINDINGS,
            synthesis_summary="  ",
            request_id="inv-dsp-blank",
        ),
    )

    assert_error(response, ErrorCode.INVALID_INPUT)
