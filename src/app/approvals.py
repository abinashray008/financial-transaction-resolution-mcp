"""Mint and consume one-time dispute approval records.

The human review application is the only caller of ``record_decision``. It
stores the authenticated reviewer identity and returns an ``approval_id``.
``submit_dispute_case`` then calls ``consume``, which is the only proof the
write path accepts — a boolean ``approved`` flag is not enough.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from ..domain.enums import ApprovalDecision
from ..domain.exceptions import (
    DisputeApprovalExpiredError,
    DisputeApprovalMismatchError,
    DisputeApprovalNotFoundError,
)
from ..domain.models import DisputeApproval
from ..repositories.approvals import ApprovalRepository
from ..workflows.dispute_case import DisputeWorkflowRunner

DEFAULT_APPROVAL_TTL_SECONDS = 900


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _approval_id_factory() -> str:
    return f"apr-{uuid.uuid4().hex[:12]}"


class ApprovalService:
    """Create and verify one-time approval records for a paused dispute draft."""

    def __init__(
        self,
        *,
        approvals: ApprovalRepository,
        workflow: DisputeWorkflowRunner,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], str] = _approval_id_factory,
        ttl_seconds: int = DEFAULT_APPROVAL_TTL_SECONDS,
    ) -> None:
        self._approvals = approvals
        self._workflow = workflow
        self._clock = clock
        self._id_factory = id_factory
        self._ttl_seconds = ttl_seconds

    def record_decision(
        self,
        *,
        request_id: str,
        reviewer_id: str,
        decision: ApprovalDecision,
        decision_note: str | None = None,
    ) -> DisputeApproval:
        """Store a human decision against the paused draft and mint ``approval_id``."""
        proposal = self._workflow.get_pending(request_id)
        now = self._clock()
        record = DisputeApproval(
            approval_id=self._id_factory(),
            request_id=request_id,
            draft_hash=proposal.draft_hash,
            reviewer_id=reviewer_id,
            decision=decision,
            decision_note=decision_note,
            created_at=now,
            decided_at=now,
            expires_at=now + timedelta(seconds=self._ttl_seconds),
            consumed_at=None,
        )
        self._approvals.insert(record)
        return record

    def consume(
        self,
        *,
        approval_id: str,
        request_id: str,
        expected_draft_hash: str,
    ) -> DisputeApproval:
        """Verify a minted token against the paused draft, then mark it used."""
        stored = self._approvals.get(approval_id)
        if stored is None or stored.request_id != request_id:
            raise DisputeApprovalNotFoundError(
                "No approval record matches the supplied approval_id and request_id.",
            )
        now = self._clock()
        if now >= stored.expires_at:
            raise DisputeApprovalExpiredError(
                "This approval_id has expired. The reviewer must record a new decision.",
            )
        if stored.draft_hash != expected_draft_hash:
            raise DisputeApprovalMismatchError(
                "This approval_id does not match the paused dispute draft.",
            )
        return self._approvals.consume(approval_id, consumed_at=now)
