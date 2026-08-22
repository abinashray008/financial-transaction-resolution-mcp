"""Approval-record data access.

Minted by the human review application. Lookups are by ``approval_id``;
``request_id`` is checked at consume time so a token cannot be applied to a
different investigation.
"""

from datetime import datetime

from sqlalchemy import select

from ..domain.exceptions import DisputeApprovalAlreadyConsumedError, DisputeApprovalNotFoundError
from ..domain.models import DisputeApproval
from .mappers import to_dispute_approval
from .models import ApprovalRecordRow
from .session import SessionFactory


class ApprovalRepository:
    """Persists one-time human approval records."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def get(self, approval_id: str) -> DisputeApproval | None:
        """Load one approval record, or ``None`` if the id is unknown."""
        statement = select(ApprovalRecordRow).where(ApprovalRecordRow.approval_id == approval_id)
        with self._session_factory() as session:
            row = session.execute(statement).scalar_one_or_none()
        return None if row is None else to_dispute_approval(row)

    def insert(self, record: DisputeApproval) -> None:
        """Persist a newly minted approval. ``consumed_at`` is always null on insert."""
        row = ApprovalRecordRow(
            approval_id=record.approval_id,
            request_id=record.request_id,
            draft_hash=record.draft_hash,
            reviewer_id=record.reviewer_id,
            decision=record.decision.value,
            decision_note=record.decision_note,
            created_at=record.created_at,
            decided_at=record.decided_at,
            expires_at=record.expires_at,
            consumed_at=None,
        )
        with self._session_factory() as session:
            session.add(row)
            session.commit()

    def consume(self, approval_id: str, *, consumed_at: datetime) -> DisputeApproval:
        """Mark a record consumed if it is still unused. Raises if missing or already used."""
        statement = select(ApprovalRecordRow).where(ApprovalRecordRow.approval_id == approval_id)
        with self._session_factory() as session:
            row = session.execute(statement).scalar_one_or_none()
            if row is None:
                raise DisputeApprovalNotFoundError(
                    "No approval record matches the supplied approval_id and request_id.",
                )
            if row.consumed_at is not None:
                raise DisputeApprovalAlreadyConsumedError(
                    "This approval_id has already been used and cannot be reused.",
                )
            row.consumed_at = consumed_at
            session.commit()
            return to_dispute_approval(row)
