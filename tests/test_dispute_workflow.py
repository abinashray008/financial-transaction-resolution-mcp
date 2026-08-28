"""Customer confirmation persists a PENDING_REVIEW case before LangGraph review."""

import json
import threading
from datetime import timedelta

import pytest
from pydantic import ValidationError

from src.app.container import build_container_from_engine
from src.app.presenters import CASE_CREATED_MESSAGE
from src.contracts.requests import (
    ConfirmUnrecognizedTransactionRequest,
    ReviewDecisionRequest,
    SynthesizeInvestigationRequest,
)
from src.domain.enums import (
    DisputeCaseStatus,
    DisputeLifecycleEvent,
    DisputeReasonCode,
    ReviewDecision,
    ReviewReasonCode,
)
from src.domain.exceptions import (
    DisputeCaseVersionConflictError,
    DisputeReviewAlreadyRecordedError,
    ErrorCode,
)
from src.domain.models import DisputeCase
from src.domain.services.dispute_evidence import DEFAULT_POLICY_URI, PROPOSED_ACTION
from src.tools.confirm_unrecognized_transaction_tool import confirm_unrecognized_transaction
from src.tools.synthesize_investigation_tool import synthesize_investigation
from tests.conftest import OTHER_ACCOUNT, SCENARIO_ACCOUNT, assert_error, assert_ok
from tests.test_synthesis import FakeSynthesisClient

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


def _issue(
    container,
    *,
    investigation_id: str,
    transaction_id: str = "TXN-SCN-DUP-A",
    findings: str = FINDINGS,
    account_id: str = SCENARIO_ACCOUNT,
):
    return container.confirmations.issue(
        investigation_id=investigation_id,
        account_id=account_id,
        transaction_id=transaction_id,
        synthesis_summary=SYNTHESIS,
        investigation_findings=findings,
    )


def _confirm(
    container,
    *,
    investigation_id: str,
    confirmation_token: str,
    idempotency_key: str,
    transaction_id: str = "TXN-SCN-DUP-A",
    account_id: str = SCENARIO_ACCOUNT,
):
    return confirm_unrecognized_transaction(
        container,
        ConfirmUnrecognizedTransactionRequest(
            investigation_id=investigation_id,
            account_id=account_id,
            transaction_id=transaction_id,
            confirmation_token=confirmation_token,
            idempotency_key=idempotency_key,
        ),
    )


def _open_case(container, *, investigation_id: str, findings: str = FINDINGS, transaction_id: str = "TXN-SCN-DUP-A"):
    issued = _issue(container, investigation_id=investigation_id, findings=findings, transaction_id=transaction_id)
    response = _confirm(
        container,
        investigation_id=investigation_id,
        confirmation_token=issued.confirmation_token,
        idempotency_key=f"idem-{investigation_id}",
        transaction_id=transaction_id,
    )
    assert_ok(response)
    assert response.data is not None
    return issued, response


def _draft(container, *, request_id: str, transaction_id: str = "TXN-SCN-DUP-A", findings: str = FINDINGS):
    """Compatibility helper: confirm a case and return the tool response."""
    _, response = _open_case(
        container,
        investigation_id=request_id,
        findings=findings,
        transaction_id=transaction_id,
    )
    return response


def test_confirm_writes_pending_review_case_before_interrupt(container):
    issued, response = _open_case(container, investigation_id="inv-dsp-propose")

    assert response.data is not None
    assert response.data.status == "PENDING_REVIEW"
    assert response.data.transaction_id == "TXN-SCN-DUP-A"
    assert response.data.masked_account_id == "ACCT-****0001"
    assert "****" in response.data.masked_customer_id
    assert response.data.reason_code == DisputeReasonCode.NEEDS_SPECIALIST_REVIEW
    assert response.data.message == CASE_CREATED_MESSAGE
    assert response.data.review_required is True
    assert response.data.externally_submitted is False
    assert len(response.data.evidence_hash) == 64
    assert response.data.review_path == f"/reviews/{response.data.case_id}"
    assert response.data.version == 1
    stored = container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A")
    assert stored is not None
    assert stored.status is DisputeCaseStatus.PENDING_REVIEW
    assert stored.case_id == response.data.case_id
    assert stored.externally_submitted is False
    snapshot = container.disputes.get_snapshot(stored.case_id)
    assert snapshot is not None
    assert snapshot.evidence_hash == stored.evidence_hash
    assert DEFAULT_POLICY_URI in str(snapshot.payload.get("applied_policy"))
    assert snapshot.payload.get("proposed_action") == PROPOSED_ACTION
    assert container.dispute_workflow.get_pending(stored.case_id)["case_id"] == stored.case_id
    assert SCENARIO_ACCOUNT not in json.dumps(response.model_dump(mode="json"))
    assert "Lindholm" not in json.dumps(response.model_dump(mode="json"))
    assert issued.confirmation.case_id == stored.case_id


def test_complete_findings_set_likely_duplicate_reason_code(container):
    _, response = _open_case(container, investigation_id="inv-dsp-rich", findings=RICH_FINDINGS)

    assert response.data is not None
    assert response.data.reason_code == DisputeReasonCode.LIKELY_DUPLICATE


def test_confirm_is_idempotent_for_the_same_key_and_token(container):
    issued = _issue(container, investigation_id="inv-dsp-idem")
    first = _confirm(
        container,
        investigation_id="inv-dsp-idem",
        confirmation_token=issued.confirmation_token,
        idempotency_key="idem-same-key",
    )
    second = _confirm(
        container,
        investigation_id="inv-dsp-idem",
        confirmation_token=issued.confirmation_token,
        idempotency_key="idem-same-key",
    )

    assert_ok(first)
    assert_ok(second)
    assert first.data is not None
    assert second.data is not None
    assert first.data.case_id == second.data.case_id
    assert first.data.evidence_hash == second.data.evidence_hash


def test_token_replay_with_a_different_idempotency_key_is_rejected(container):
    issued = _issue(container, investigation_id="inv-dsp-replay")
    assert_ok(
        _confirm(
            container,
            investigation_id="inv-dsp-replay",
            confirmation_token=issued.confirmation_token,
            idempotency_key="idem-first",
        )
    )
    response = _confirm(
        container,
        investigation_id="inv-dsp-replay",
        confirmation_token=issued.confirmation_token,
        idempotency_key="idem-second",
    )
    assert_error(response, ErrorCode.CONFIRMATION_ALREADY_USED)


def test_token_bound_to_another_transaction_is_rejected(container):
    issued = _issue(container, investigation_id="inv-dsp-mismatch")
    response = _confirm(
        container,
        investigation_id="inv-dsp-mismatch",
        confirmation_token=issued.confirmation_token,
        idempotency_key="idem-mismatch",
        transaction_id="TXN-SCN-DUP-B",
    )
    assert_error(response, ErrorCode.CONFIRMATION_MISMATCH)
    assert container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A") is None


def test_expired_token_cannot_create_a_case(container):
    issued = _issue(container, investigation_id="inv-dsp-expired")
    stored = container.confirmations.peek(confirmation_token=issued.confirmation_token)
    container.confirmations._clock = lambda: stored.expires_at + timedelta(seconds=1)
    response = _confirm(
        container,
        investigation_id="inv-dsp-expired",
        confirmation_token=issued.confirmation_token,
        idempotency_key="idem-expired",
    )
    assert_error(response, ErrorCode.CONFIRMATION_EXPIRED)
    assert container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A") is None


def test_unknown_token_is_not_found(container):
    response = _confirm(
        container,
        investigation_id="inv-dsp-missing",
        confirmation_token="cnf_" + ("A" * 32),
        idempotency_key="idem-missing",
    )
    assert_error(response, ErrorCode.CONFIRMATION_NOT_FOUND)


def test_second_case_for_the_same_charge_is_rejected(container):
    _open_case(container, investigation_id="inv-dsp-dup-1")
    issued = _issue(container, investigation_id="inv-dsp-dup-2", transaction_id="TXN-SCN-DUP-B")
    # First charge already has a case; issuing for DUP-A should fail inside confirm if we reuse it.
    second_issue = container.confirmations.issue(
        investigation_id="inv-dsp-dup-2b",
        account_id=SCENARIO_ACCOUNT,
        transaction_id="TXN-SCN-DUP-B",
        synthesis_summary=SYNTHESIS,
        investigation_findings=FINDINGS,
    )
    assert_ok(
        _confirm(
            container,
            investigation_id="inv-dsp-dup-2b",
            confirmation_token=second_issue.confirmation_token,
            idempotency_key="idem-other-txn",
            transaction_id="TXN-SCN-DUP-B",
        )
    )
    del issued


def test_review_approve_updates_the_existing_case(container):
    _, created = _open_case(container, investigation_id="inv-dsp-approve", findings=RICH_FINDINGS)
    assert created.data is not None
    case_id = created.data.case_id
    updated = container.cases.record_review(
        case_id=case_id,
        expected_version=1,
        decision=ReviewDecision.APPROVE,
        reason_code=ReviewReasonCode.EVIDENCE_SUPPORTS_DISPUTE,
        note="Customer confirmed the duplicate posting.",
        reviewer_id=REVIEWER_ID,
        correlation_id=case_id,
    )

    assert updated.status is DisputeCaseStatus.APPROVED
    assert updated.version == 2
    assert updated.reviewer_id == REVIEWER_ID
    assert updated.externally_submitted is False
    stored = container.disputes.get(case_id)
    assert stored is not None
    assert stored.status is DisputeCaseStatus.APPROVED
    snapshot = container.disputes.get_snapshot(case_id)
    assert snapshot is not None
    assert snapshot.evidence_hash == stored.evidence_hash


def test_review_reject_updates_the_existing_case(container):
    _, created = _open_case(container, investigation_id="inv-dsp-reject")
    assert created.data is not None
    updated = container.cases.record_review(
        case_id=created.data.case_id,
        expected_version=1,
        decision=ReviewDecision.REJECT,
        reason_code=ReviewReasonCode.MERCHANT_RECOGNIZED_ON_REVIEW,
        note="Merchant is the customer's usual electronics store.",
        reviewer_id=REVIEWER_ID,
        correlation_id=created.data.case_id,
    )

    assert updated.status is DisputeCaseStatus.REJECTED
    assert updated.version == 2
    history = container.lifecycle.case_history(created.data.case_id)
    assert DisputeLifecycleEvent.REVIEW_REJECTED in [event.event_type for event in history]


def test_stale_expected_version_is_rejected(container):
    _, created = _open_case(container, investigation_id="inv-dsp-version")
    assert created.data is not None
    try:
        container.cases.record_review(
            case_id=created.data.case_id,
            expected_version=99,
            decision=ReviewDecision.APPROVE,
            reason_code=ReviewReasonCode.POLICY_CRITERIA_MET,
            note=None,
            reviewer_id=REVIEWER_ID,
            correlation_id=created.data.case_id,
        )
    except Exception as error:
        assert isinstance(error, DisputeCaseVersionConflictError)
    else:
        raise AssertionError("expected DisputeCaseVersionConflictError")
    stored = container.disputes.get(created.data.case_id)
    assert stored is not None
    assert stored.status is DisputeCaseStatus.PENDING_REVIEW
    assert stored.version == 1


def test_second_review_is_rejected(container):
    _, created = _open_case(container, investigation_id="inv-dsp-second-review")
    assert created.data is not None
    container.cases.record_review(
        case_id=created.data.case_id,
        expected_version=1,
        decision=ReviewDecision.APPROVE,
        reason_code=ReviewReasonCode.CUSTOMER_CONFIRMATION_CLEAR,
        note=None,
        reviewer_id=REVIEWER_ID,
        correlation_id=created.data.case_id,
    )
    try:
        container.cases.record_review(
            case_id=created.data.case_id,
            expected_version=2,
            decision=ReviewDecision.REJECT,
            reason_code=ReviewReasonCode.EVIDENCE_INSUFFICIENT,
            note=None,
            reviewer_id="rev-other",
            correlation_id=created.data.case_id,
        )
    except Exception as error:
        assert isinstance(error, DisputeReviewAlreadyRecordedError)
    else:
        raise AssertionError("expected DisputeReviewAlreadyRecordedError")


def test_paused_case_survives_process_restart(engine, tmp_path):
    checkpoints = tmp_path / "paused.db"
    first = build_container_from_engine(engine, checkpoint_path=str(checkpoints))
    _, created = _open_case(first, investigation_id="inv-dsp-restart")
    assert created.data is not None
    case_id = created.data.case_id

    restarted = build_container_from_engine(engine, checkpoint_path=str(checkpoints))
    pending = restarted.dispute_workflow.get_pending(case_id)
    assert pending["case_id"] == case_id
    stored = restarted.disputes.get(case_id)
    assert stored is not None
    assert stored.status is DisputeCaseStatus.PENDING_REVIEW
    updated = restarted.cases.record_review(
        case_id=case_id,
        expected_version=1,
        decision=ReviewDecision.APPROVE,
        reason_code=ReviewReasonCode.EVIDENCE_SUPPORTS_DISPUTE,
        note="Restarted reviewer",
        reviewer_id=REVIEWER_ID,
        correlation_id=case_id,
    )
    assert updated.status is DisputeCaseStatus.APPROVED


def test_lifecycle_events_cover_confirmation_and_review(engine):
    container = build_container_from_engine(engine, synthesis=FakeSynthesisClient())
    synthesis = synthesize_investigation(
        container,
        SynthesizeInvestigationRequest(
            account_id=SCENARIO_ACCOUNT,
            transaction_id="TXN-SCN-DUP-A",
            investigation_findings=RICH_FINDINGS,
            request_id="inv-dsp-audit",
        ),
    )
    assert_ok(synthesis)
    assert synthesis.data is not None
    assert synthesis.data.confirmation is not None
    created = _confirm(
        container,
        investigation_id="inv-dsp-audit",
        confirmation_token=synthesis.data.confirmation.confirmation_token,
        idempotency_key="idem-dsp-audit",
    )
    assert_ok(created)
    assert created.data is not None
    container.cases.get_for_review(created.data.case_id, reviewer_id=REVIEWER_ID, correlation_id=created.data.case_id)
    container.cases.record_review(
        case_id=created.data.case_id,
        expected_version=1,
        decision=ReviewDecision.APPROVE,
        reason_code=ReviewReasonCode.EVIDENCE_SUPPORTS_DISPUTE,
        note="ok",
        reviewer_id=REVIEWER_ID,
        correlation_id=created.data.case_id,
    )
    history = container.lifecycle.investigation_history("inv-dsp-audit")
    types = [event.event_type for event in history]
    for expected in DisputeLifecycleEvent:
        if expected is DisputeLifecycleEvent.REVIEW_REJECTED:
            continue
        assert expected in types
    for event in history:
        assert event.investigation_id == "inv-dsp-audit"
        assert event.correlation_id
        assert event.timestamp
        assert event.actor_type
        assert event.actor_id_masked != REVIEWER_ID
        if event.event_type is not DisputeLifecycleEvent.INVESTIGATION_COMPLETED:
            assert event.case_id == created.data.case_id
            assert event.evidence_hash == created.data.evidence_hash


def test_review_decision_request_forbids_reviewer_id_and_approved_flag():
    with pytest.raises(ValidationError):
        ReviewDecisionRequest.model_validate(
            {
                "case_id": "DSP-ABCD1234",
                "expected_version": 1,
                "decision": "APPROVE",
                "reason_code": "EVIDENCE_SUPPORTS_DISPUTE",
                "reviewer_id": "rev-spoof",
            }
        )
    with pytest.raises(ValidationError):
        ReviewDecisionRequest.model_validate(
            {
                "case_id": "DSP-ABCD1234",
                "expected_version": 1,
                "decision": "APPROVE",
                "reason_code": "EVIDENCE_SUPPORTS_DISPUTE",
                "approved": True,
            }
        )
    with pytest.raises(ValidationError):
        ReviewDecisionRequest.model_validate(
            {
                "case_id": "DSP-ABCD1234",
                "decision": "APPROVE",
                "reason_code": "EVIDENCE_SUPPORTS_DISPUTE",
            }
        )


def test_token_bound_to_another_investigation_is_rejected(container):
    issued = _issue(container, investigation_id="inv-dsp-bound-a")
    response = _confirm(
        container,
        investigation_id="inv-dsp-bound-b",
        confirmation_token=issued.confirmation_token,
        idempotency_key="idem-bound",
    )
    assert_error(response, ErrorCode.CONFIRMATION_MISMATCH)
    assert container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A") is None


def test_evidence_snapshot_is_unchanged_after_review(container):
    _, created = _open_case(container, investigation_id="inv-dsp-snapshot", findings=RICH_FINDINGS)
    assert created.data is not None
    before = container.disputes.get_snapshot(created.data.case_id)
    assert before is not None
    container.cases.record_review(
        case_id=created.data.case_id,
        expected_version=1,
        decision=ReviewDecision.APPROVE,
        reason_code=ReviewReasonCode.EVIDENCE_SUPPORTS_DISPUTE,
        note="ok",
        reviewer_id=REVIEWER_ID,
        correlation_id=created.data.case_id,
    )
    after = container.disputes.get_snapshot(created.data.case_id)
    assert after is not None
    assert after.evidence_hash == before.evidence_hash == created.data.evidence_hash
    assert after.payload == before.payload
    stored = container.disputes.get(created.data.case_id)
    assert stored is not None
    assert stored.evidence_hash == before.evidence_hash


def test_concurrent_reviews_only_one_succeeds(container):
    _, created = _open_case(container, investigation_id="inv-dsp-concurrent", findings=RICH_FINDINGS)
    assert created.data is not None
    case_id = created.data.case_id
    barrier = threading.Barrier(2)
    outcomes: list[DisputeCase | Exception] = []
    lock = threading.Lock()

    def attempt(reviewer_id: str) -> None:
        barrier.wait()
        try:
            updated = container.cases.record_review(
                case_id=case_id,
                expected_version=1,
                decision=ReviewDecision.APPROVE,
                reason_code=ReviewReasonCode.EVIDENCE_SUPPORTS_DISPUTE,
                note="ok",
                reviewer_id=reviewer_id,
                correlation_id=case_id,
            )
            with lock:
                outcomes.append(updated)
        except (DisputeCaseVersionConflictError, DisputeReviewAlreadyRecordedError) as error:
            with lock:
                outcomes.append(error)

    threads = [
        threading.Thread(target=attempt, args=("rev-conc-a",)),
        threading.Thread(target=attempt, args=("rev-conc-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    successes = [item for item in outcomes if isinstance(item, DisputeCase)]
    failures = [item for item in outcomes if isinstance(item, Exception)]
    assert len(successes) == 1
    assert len(failures) == 1
    stored = container.disputes.get(case_id)
    assert stored is not None
    assert stored.status is DisputeCaseStatus.APPROVED
    assert stored.version == 2
    assert stored.reviewer_id in {"rev-conc-a", "rev-conc-b"}


def test_cross_account_confirmation_is_rejected(container):
    issued = _issue(container, investigation_id="inv-dsp-isolation")
    response = _confirm(
        container,
        investigation_id="inv-dsp-isolation",
        confirmation_token=issued.confirmation_token,
        idempotency_key="idem-isolation",
        account_id=OTHER_ACCOUNT,
    )
    assert_error(response, ErrorCode.CONFIRMATION_MISMATCH)
    assert container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A") is None
