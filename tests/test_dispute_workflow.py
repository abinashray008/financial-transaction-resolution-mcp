"""Human-in-the-loop dispute registration via LangGraph."""

import json

from src.contracts.requests import ProposeDisputeCaseRequest, SubmitDisputeDecisionRequest
from src.domain.enums import DisputeCaseStatus, DisputeWorkflowStatus
from src.domain.exceptions import ErrorCode
from src.tools.propose_dispute_case_tool import propose_dispute_case
from src.tools.submit_dispute_decision_tool import submit_dispute_decision
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
SYNTHESIS = "The tools show a likely duplicate of TXN-SCN-DUP-A at Halcyon Electronics for 89.99 USD."


def _propose(container, *, request_id: str, transaction_id: str = "TXN-SCN-DUP-A"):
    return propose_dispute_case(
        container,
        ProposeDisputeCaseRequest(
            account_id=SCENARIO_ACCOUNT,
            transaction_id=transaction_id,
            investigation_findings=FINDINGS,
            synthesis_summary=SYNTHESIS,
            request_id=request_id,
        ),
    )


def _decide(container, *, request_id: str, approved: bool, transaction_id: str = "TXN-SCN-DUP-A"):
    return submit_dispute_decision(
        container,
        SubmitDisputeDecisionRequest(
            account_id=SCENARIO_ACCOUNT,
            transaction_id=transaction_id,
            approved=approved,
            request_id=request_id,
            decision_note="Customer confirmed" if approved else "Customer declined",
        ),
    )


def test_propose_pauses_for_human_approval_and_does_not_write(container):
    response = _propose(container, request_id="inv-dsp-propose")

    assert_ok(response)
    assert response.data is not None
    assert response.data.workflow_status == DisputeWorkflowStatus.AWAITING_APPROVAL
    assert response.data.transaction_id == "TXN-SCN-DUP-A"
    assert response.data.merchant_display_name == "Halcyon Electronics"
    assert str(response.data.amount) == "89.99"
    assert response.data.masked_account_id == "ACCT-****0001"
    assert response.data.masked_customer_id.startswith("CUST-")
    assert "****" in response.data.masked_customer_id
    assert "Lindholm" not in json.dumps(response.model_dump(mode="json"))
    assert container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A") is None


def test_approval_registers_a_case_for_the_same_customer(container):
    request_id = "inv-dsp-approve"
    proposed = _propose(container, request_id=request_id)
    assert_ok(proposed)

    decided = _decide(container, request_id=request_id, approved=True)

    assert_ok(decided)
    assert decided.data is not None
    assert decided.data.registered is True
    assert decided.data.workflow_status == DisputeWorkflowStatus.REGISTERED
    assert decided.data.case_id is not None
    assert decided.data.case_id.startswith("DSP-")
    assert decided.data.decision_note == "Customer confirmed"

    stored = container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A")
    account = container.accounts.get_with_customer_state(SCENARIO_ACCOUNT)
    assert stored is not None
    assert account is not None
    assert stored.customer_id == account.account.customer_id
    assert stored.account_id == SCENARIO_ACCOUNT
    assert stored.transaction_id == "TXN-SCN-DUP-A"
    assert stored.status == DisputeCaseStatus.REGISTERED
    assert stored.request_id == request_id
    assert "Halcyon Electronics" in stored.reason
    assert "89.99" in stored.reason


def test_decline_does_not_register_a_case(container):
    request_id = "inv-dsp-decline"
    assert_ok(_propose(container, request_id=request_id))

    decided = _decide(container, request_id=request_id, approved=False)

    assert_ok(decided)
    assert decided.data is not None
    assert decided.data.registered is False
    assert decided.data.workflow_status == DisputeWorkflowStatus.DECLINED
    assert decided.data.case_id is None
    assert container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A") is None


def test_propose_is_idempotent_while_awaiting_approval(container):
    first = _propose(container, request_id="inv-dsp-again")
    second = _propose(container, request_id="inv-dsp-again")

    assert_ok(first)
    assert_ok(second)
    assert first.data is not None
    assert second.data is not None
    assert first.data.reason == second.data.reason
    assert container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A") is None


def test_cannot_register_a_second_case_for_the_same_charge(container):
    assert_ok(_propose(container, request_id="inv-dsp-dup-1"))
    assert_ok(_decide(container, request_id="inv-dsp-dup-1", approved=True))

    response = _propose(container, request_id="inv-dsp-dup-2")

    assert_error(response, ErrorCode.DISPUTE_ALREADY_EXISTS)
    assert container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A") is not None


def test_submit_without_a_proposal_is_not_found(container):
    response = _decide(container, request_id="inv-dsp-missing", approved=True)

    assert_error(response, ErrorCode.DISPUTE_WORKFLOW_NOT_FOUND)
    assert container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A") is None


def test_second_decision_is_rejected_once_the_graph_has_finished(container):
    request_id = "inv-dsp-finished"
    assert_ok(_propose(container, request_id=request_id))
    assert_ok(_decide(container, request_id=request_id, approved=False))

    response = _decide(container, request_id=request_id, approved=True)

    assert_error(response, ErrorCode.DISPUTE_NOT_AWAITING_APPROVAL)
    assert container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A") is None


def test_submit_requires_the_investigation_request_id(container):
    response = submit_dispute_decision(
        container,
        SubmitDisputeDecisionRequest(
            account_id=SCENARIO_ACCOUNT,
            transaction_id="TXN-SCN-DUP-A",
            approved=True,
            request_id=None,
        ),
    )

    assert_error(response, ErrorCode.INVALID_INPUT)


def test_submit_for_a_different_account_does_not_leak_the_workflow(container):
    assert_ok(_propose(container, request_id="inv-dsp-isolation"))

    response = submit_dispute_decision(
        container,
        SubmitDisputeDecisionRequest(
            account_id=OTHER_ACCOUNT,
            transaction_id="TXN-SCN-DUP-A",
            approved=True,
            request_id="inv-dsp-isolation",
        ),
    )

    assert_error(response, ErrorCode.DISPUTE_WORKFLOW_NOT_FOUND)
    assert container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A") is None


def test_propose_rejects_a_transaction_on_another_account(container):
    response = propose_dispute_case(
        container,
        ProposeDisputeCaseRequest(
            account_id=OTHER_ACCOUNT,
            transaction_id="TXN-SCN-DUP-A",
            investigation_findings=FINDINGS,
            synthesis_summary=SYNTHESIS,
            request_id="inv-dsp-other",
        ),
    )

    assert_error(response, ErrorCode.TRANSACTION_NOT_FOUND)


def test_blank_synthesis_summary_is_rejected(container):
    response = propose_dispute_case(
        container,
        ProposeDisputeCaseRequest(
            account_id=SCENARIO_ACCOUNT,
            transaction_id="TXN-SCN-DUP-A",
            investigation_findings=FINDINGS,
            synthesis_summary="  ",
            request_id="inv-dsp-blank",
        ),
    )

    assert_error(response, ErrorCode.INVALID_INPUT)
