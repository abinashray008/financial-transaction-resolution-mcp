"""Dispute case data access.

A case is created at ``PENDING_REVIEW`` together with its immutable evidence
snapshot and creation audit events, all in one transaction, so a case can never
exist without the evidence a reviewer needs. Review decisions update the same
row under a version check.

Reads that serve an investigation are always scoped to a single ``account_id``:
a case on another account is indistinguishable from one that does not exist.
Reads that serve the back-office review application are scoped by ``case_id``,
because a reviewer is authenticated and not acting for one cardholder.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import Select, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError

from ..domain.enums import DisputeCaseStatus, ReviewReasonCode
from ..domain.exceptions import (
    ConfirmationAlreadyUsedError,
    ConfirmationExpiredError,
    ConfirmationNotFoundError,
    DisputeAlreadyExistsError,
    DisputeCaseNotFoundError,
    DisputeCaseVersionConflictError,
    DisputeReviewAlreadyRecordedError,
)
from ..domain.models import DisputeCase, DisputeEvidenceSnapshot, DisputeLifecycleAuditEvent
from ..domain.money import to_minor_units
from .dispute_audit import lifecycle_event_row
from .mappers import to_dispute_case, to_evidence_snapshot
from .models import ConfirmationChallengeRow, DisputeCaseRow, EvidenceSnapshotRow
from .session import SessionFactory


class DisputeRepository:
    """Persists internal synthetic dispute cases and their evidence snapshots."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def get_for_account(self, account_id: str, transaction_id: str) -> DisputeCase | None:
        """A case for one charge, only if it belongs to ``account_id``."""
        statement = select(DisputeCaseRow).where(
            DisputeCaseRow.account_id == account_id,
            DisputeCaseRow.transaction_id == transaction_id,
        )
        return self._one(statement)

    def get_by_case_id_for_account(self, account_id: str, case_id: str) -> DisputeCase | None:
        """A case by id, only if it belongs to ``account_id``."""
        statement = select(DisputeCaseRow).where(
            DisputeCaseRow.account_id == account_id,
            DisputeCaseRow.case_id == case_id,
        )
        return self._one(statement)

    def get(self, case_id: str) -> DisputeCase | None:
        """A case by id for the authenticated review application."""
        return self._one(select(DisputeCaseRow).where(DisputeCaseRow.case_id == case_id))

    def get_by_idempotency_key(self, idempotency_key: str) -> DisputeCase | None:
        """The case a previous confirmation with this key already created."""
        statement = select(DisputeCaseRow).where(DisputeCaseRow.idempotency_key == idempotency_key)
        return self._one(statement)

    def get_by_confirmation_id(self, confirmation_id: str) -> DisputeCase | None:
        """The case a specific confirmation challenge created."""
        statement = select(DisputeCaseRow).where(DisputeCaseRow.confirmation_id == confirmation_id)
        return self._one(statement)

    def get_snapshot(self, case_id: str) -> DisputeEvidenceSnapshot | None:
        """The immutable evidence snapshot captured when the case was created."""
        statement = select(EvidenceSnapshotRow).where(EvidenceSnapshotRow.case_id == case_id)
        with self._session_factory() as session:
            row = session.execute(statement).scalar_one_or_none()
        return None if row is None else to_evidence_snapshot(row)

    def consume_and_create_pending_case(
        self,
        *,
        token_hash: str,
        consumed_at: datetime,
        case: DisputeCase,
        snapshot: DisputeEvidenceSnapshot,
        events: Sequence[DisputeLifecycleAuditEvent],
    ) -> DisputeCase:
        """Consume a confirmation token and persist the case in one transaction."""
        if case.status is not DisputeCaseStatus.PENDING_REVIEW:
            raise ValueError("A dispute case must be created at PENDING_REVIEW.")
        case_row = self._case_row(case)
        snapshot_row = self._snapshot_row(snapshot)
        with self._session_factory() as session:
            challenge = session.execute(
                select(ConfirmationChallengeRow).where(ConfirmationChallengeRow.token_hash == token_hash)
            ).scalar_one_or_none()
            if challenge is None:
                raise ConfirmationNotFoundError(
                    "No pending customer confirmation matches this confirmation_token.",
                )
            if challenge.consumed_at is not None:
                raise ConfirmationAlreadyUsedError(
                    "This confirmation_token has already been used and cannot be reused.",
                )
            if consumed_at >= challenge.expires_at:
                raise ConfirmationExpiredError(
                    "This confirmation_token has expired. Re-run synthesize_investigation and ask again.",
                )
            challenge.consumed_at = consumed_at
            session.add(case_row)
            session.add(snapshot_row)
            for event in events:
                session.add(lifecycle_event_row(event))
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                existing = self.get_by_idempotency_key(case.idempotency_key)
                if existing is not None and existing.confirmation_id == case.confirmation_id:
                    return existing
                raise DisputeAlreadyExistsError(
                    "A dispute case already exists for this account and transaction.",
                ) from exc
            return to_dispute_case(case_row)

    def create_pending_case(
        self,
        *,
        case: DisputeCase,
        snapshot: DisputeEvidenceSnapshot,
        events: Sequence[DisputeLifecycleAuditEvent],
    ) -> DisputeCase:
        """Write a PENDING_REVIEW case, its evidence snapshot and its audit events."""
        if case.status is not DisputeCaseStatus.PENDING_REVIEW:
            raise ValueError("A dispute case must be created at PENDING_REVIEW.")
        case_row = self._case_row(case)
        snapshot_row = self._snapshot_row(snapshot)
        with self._session_factory() as session:
            session.add(case_row)
            session.add(snapshot_row)
            for event in events:
                session.add(lifecycle_event_row(event))
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise DisputeAlreadyExistsError(
                    "A dispute case already exists for this account and transaction.",
                ) from exc
            return to_dispute_case(case_row)

    def apply_review_decision(
        self,
        *,
        case_id: str,
        expected_version: int,
        new_status: DisputeCaseStatus,
        reviewer_id: str,
        review_reason_code: ReviewReasonCode,
        review_note: str | None,
        reviewed_at: datetime,
        event: DisputeLifecycleAuditEvent,
    ) -> DisputeCase:
        """Move a PENDING_REVIEW case to its decided status under a version check.

        The status and version predicates make a stale or replayed decision fail
        instead of overwriting a decision another reviewer already recorded.
        """
        lookup = select(DisputeCaseRow).where(DisputeCaseRow.case_id == case_id)
        with self._session_factory() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(DisputeCaseRow)
                    .where(
                        DisputeCaseRow.case_id == case_id,
                        DisputeCaseRow.version == expected_version,
                        DisputeCaseRow.status == DisputeCaseStatus.PENDING_REVIEW.value,
                    )
                    .values(
                        status=new_status.value,
                        version=expected_version + 1,
                        reviewer_id=reviewer_id,
                        review_reason_code=review_reason_code.value,
                        review_note=review_note,
                        reviewed_at=reviewed_at,
                        updated_at=reviewed_at,
                    )
                ),
            )
            if result.rowcount == 1:
                session.add(lifecycle_event_row(event))
                session.commit()
                updated_row = session.execute(lookup).scalar_one()
                return to_dispute_case(updated_row)

            current = session.execute(lookup).scalar_one_or_none()
            if current is None:
                raise DisputeCaseNotFoundError("No dispute case exists for this case_id.")
            if current.status != DisputeCaseStatus.PENDING_REVIEW.value:
                raise DisputeReviewAlreadyRecordedError(
                    f"This case is already {current.status} and cannot be reviewed again.",
                )
            raise DisputeCaseVersionConflictError(
                "This case changed since it was loaded. Reload it and record the decision again.",
            )

    @staticmethod
    def _case_row(case: DisputeCase) -> DisputeCaseRow:
        return DisputeCaseRow(
            case_id=case.case_id,
            customer_id=case.customer_id,
            account_id=case.account_id,
            transaction_id=case.transaction_id,
            investigation_id=case.investigation_id,
            confirmation_id=case.confirmation_id,
            idempotency_key=case.idempotency_key,
            reason=case.reason,
            reason_code=case.reason_code.value,
            status=case.status.value,
            version=case.version,
            evidence_hash=case.evidence_hash,
            amount_minor=to_minor_units(case.amount),
            currency=case.currency,
            merchant_display_name=case.merchant_display_name,
            created_at=case.created_at,
            updated_at=case.updated_at,
            externally_submitted=False,
            reviewer_id=None,
            review_reason_code=None,
            review_note=None,
            reviewed_at=None,
        )

    @staticmethod
    def _snapshot_row(snapshot: DisputeEvidenceSnapshot) -> EvidenceSnapshotRow:
        return EvidenceSnapshotRow(
            snapshot_id=snapshot.snapshot_id,
            case_id=snapshot.case_id,
            investigation_id=snapshot.investigation_id,
            account_id=snapshot.account_id,
            transaction_id=snapshot.transaction_id,
            evidence_hash=snapshot.evidence_hash,
            payload=snapshot.payload,
            created_at=snapshot.created_at,
        )

    def _one(self, statement: Select[Any]) -> DisputeCase | None:
        with self._session_factory() as session:
            row = session.execute(statement).scalar_one_or_none()
        return None if row is None else to_dispute_case(row)
