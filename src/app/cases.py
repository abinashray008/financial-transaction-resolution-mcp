"""Orchestrate confirmation, case persistence, and authenticated review.

Customer confirmation writes the ``PENDING_REVIEW`` case and its immutable
evidence snapshot before LangGraph pauses for back-office review. The reviewer
decision updates that same row; nothing is submitted to a card network.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime

from ..audit.lifecycle import DisputeLifecycleAuditService
from ..domain.enums import (
    AuditActorType,
    DisputeCaseStatus,
    DisputeLifecycleEvent,
    ReviewDecision,
    ReviewReasonCode,
)
from ..domain.exceptions import (
    ConfirmationAlreadyUsedError,
    ConfirmationExpiredError,
    ConfirmationMismatchError,
    ConfirmationNotFoundError,
    DisputeAlreadyExistsError,
    DisputeCaseNotFoundError,
    DisputeNotAwaitingReviewError,
    DisputeReviewAlreadyRecordedError,
    DisputeWorkflowNotFoundError,
)
from ..domain.models import CustomerConfirmation, DisputeCase, DisputeEvidenceSnapshot
from ..repositories.disputes import DisputeRepository
from ..workflows.dispute_case import DisputeWorkflowRunner
from .confirmations import ConfirmationService, hash_confirmation_token
from .presenters import review_path


class CaseService:
    """Creates pending cases from confirmed investigations and records reviews."""

    def __init__(
        self,
        *,
        confirmations: ConfirmationService,
        disputes: DisputeRepository,
        lifecycle: DisputeLifecycleAuditService,
        workflow: DisputeWorkflowRunner,
    ) -> None:
        self._confirmations = confirmations
        self._disputes = disputes
        self._lifecycle = lifecycle
        self._workflow = workflow

    def confirm_unrecognized(
        self,
        *,
        investigation_id: str,
        account_id: str,
        transaction_id: str,
        confirmation_token: str,
        idempotency_key: str,
        host_actor_id: str,
        correlation_id: str,
    ) -> DisputeCase:
        """Validate the customer confirmation, persist the case, then pause for review."""
        existing = self._disputes.get_by_idempotency_key(idempotency_key)
        stored = self._peek_or_none(confirmation_token)
        if existing is not None:
            if stored is None or stored.confirmation_id != existing.confirmation_id:
                raise ConfirmationMismatchError(
                    "This confirmation_token was not issued for this investigation, account and transaction.",
                )
            self._confirmations.assert_same_subject(
                stored,
                investigation_id=investigation_id,
                account_id=account_id,
                transaction_id=transaction_id,
            )
            self._workflow.pause_for_review(existing)
            return existing

        if stored is None:
            raise ConfirmationNotFoundError(
                "No pending customer confirmation matches this confirmation_token.",
            )
        self._confirmations.assert_same_subject(
            stored,
            investigation_id=investigation_id,
            account_id=account_id,
            transaction_id=transaction_id,
        )
        if stored.consumed_at is not None:
            raise ConfirmationAlreadyUsedError(
                "This confirmation_token has already been used and cannot be reused.",
            )
        now = self._confirmations.now()
        if now >= stored.expires_at:
            raise ConfirmationExpiredError(
                "This confirmation_token has expired. Re-run synthesize_investigation and ask again.",
            )
        if self._disputes.get_for_account(account_id, transaction_id) is not None:
            raise DisputeAlreadyExistsError(
                "A dispute case already exists for this account and transaction.",
            )

        case = self._pending_case(stored, idempotency_key=idempotency_key, created_at=now)
        snapshot = DisputeEvidenceSnapshot(
            snapshot_id=self._confirmations.new_snapshot_id(),
            case_id=stored.case_id,
            investigation_id=stored.investigation_id,
            account_id=stored.account_id,
            transaction_id=stored.transaction_id,
            evidence_hash=stored.evidence_hash,
            payload=dict(stored.snapshot),
            created_at=now,
        )
        events = [
            self._lifecycle.build(
                event_type=DisputeLifecycleEvent.CUSTOMER_CONFIRMED_UNRECOGNIZED,
                case_id=case.case_id,
                investigation_id=case.investigation_id,
                correlation_id=correlation_id,
                actor_type=AuditActorType.CUSTOMER,
                actor_id=stored.customer_id,
                previous_status=None,
                new_status=DisputeCaseStatus.PENDING_REVIEW,
                evidence_hash=case.evidence_hash,
                reason_code=case.reason_code.value,
            ),
            self._lifecycle.build(
                event_type=DisputeLifecycleEvent.DISPUTE_CASE_CREATED,
                case_id=case.case_id,
                investigation_id=case.investigation_id,
                correlation_id=correlation_id,
                actor_type=AuditActorType.HOST_AGENT,
                actor_id=host_actor_id,
                previous_status=None,
                new_status=DisputeCaseStatus.PENDING_REVIEW,
                evidence_hash=case.evidence_hash,
                reason_code=case.reason_code.value,
            ),
        ]
        created = self._disputes.consume_and_create_pending_case(
            token_hash=hash_confirmation_token(confirmation_token),
            consumed_at=now,
            case=case,
            snapshot=snapshot,
            events=events,
        )
        self._workflow.pause_for_review(created)
        return created

    def get_for_review(self, case_id: str, *, reviewer_id: str | None, correlation_id: str) -> DisputeCase:
        """Load a case for the review application and record REVIEW_STARTED once."""
        case = self._disputes.get(case_id)
        if case is None:
            raise DisputeCaseNotFoundError("No dispute case exists for this case_id.")
        self._lifecycle.record_once(
            event_type=DisputeLifecycleEvent.REVIEW_STARTED,
            case_id=case.case_id,
            investigation_id=case.investigation_id,
            correlation_id=correlation_id,
            actor_type=AuditActorType.REVIEWER,
            actor_id=reviewer_id,
            previous_status=case.status,
            new_status=case.status,
            evidence_hash=case.evidence_hash,
            reason_code=case.reason_code.value,
        )
        return case

    def record_review(
        self,
        *,
        case_id: str,
        expected_version: int,
        decision: ReviewDecision,
        reason_code: ReviewReasonCode,
        note: str | None,
        reviewer_id: str,
        correlation_id: str,
    ) -> DisputeCase:
        """Update the existing PENDING_REVIEW case with an authenticated decision."""
        current = self._disputes.get(case_id)
        if current is None:
            raise DisputeCaseNotFoundError("No dispute case exists for this case_id.")
        if current.status is not DisputeCaseStatus.PENDING_REVIEW:
            raise DisputeReviewAlreadyRecordedError(
                f"This case is already {current.status.value} and cannot be reviewed again.",
            )
        now = self._confirmations.now()
        new_status = decision.resulting_status
        event_type = (
            DisputeLifecycleEvent.REVIEW_APPROVED
            if decision is ReviewDecision.APPROVE
            else DisputeLifecycleEvent.REVIEW_REJECTED
        )
        event = self._lifecycle.build(
            event_type=event_type,
            case_id=current.case_id,
            investigation_id=current.investigation_id,
            correlation_id=correlation_id,
            actor_type=AuditActorType.REVIEWER,
            actor_id=reviewer_id,
            previous_status=DisputeCaseStatus.PENDING_REVIEW,
            new_status=new_status,
            evidence_hash=current.evidence_hash,
            reason_code=reason_code.value,
        )
        updated = self._disputes.apply_review_decision(
            case_id=case_id,
            expected_version=expected_version,
            new_status=new_status,
            reviewer_id=reviewer_id,
            review_reason_code=reason_code,
            review_note=note,
            reviewed_at=now,
            event=event,
        )
        with suppress(DisputeNotAwaitingReviewError, DisputeWorkflowNotFoundError):
            self._workflow.resume_review(
                case_id=case_id,
                decision=decision,
                reason_code=reason_code,
                note=note,
                reviewer_id=reviewer_id,
                expected_version=expected_version,
            )
        return updated

    def review_path_for(self, case_id: str) -> str:
        """HTTP path where an authenticated reviewer decides this case."""
        return review_path(case_id)

    def _peek_or_none(self, confirmation_token: str) -> CustomerConfirmation | None:
        try:
            return self._confirmations.peek(confirmation_token=confirmation_token)
        except ConfirmationNotFoundError:
            return None

    @staticmethod
    def _pending_case(
        stored: CustomerConfirmation,
        *,
        idempotency_key: str,
        created_at: datetime,
    ) -> DisputeCase:
        return DisputeCase(
            case_id=stored.case_id,
            customer_id=stored.customer_id,
            account_id=stored.account_id,
            transaction_id=stored.transaction_id,
            investigation_id=stored.investigation_id,
            confirmation_id=stored.confirmation_id,
            idempotency_key=idempotency_key,
            reason=stored.reason,
            reason_code=stored.reason_code,
            status=DisputeCaseStatus.PENDING_REVIEW,
            version=1,
            evidence_hash=stored.evidence_hash,
            amount=stored.amount,
            currency=stored.currency,
            merchant_display_name=stored.merchant_display_name,
            created_at=created_at,
            updated_at=created_at,
            externally_submitted=False,
        )
