"""Dispute lifecycle audit events.

``AuditService`` answers which tools ran; this service answers who moved a case
and between which statuses. Events are built here so every one of them carries
the same fields, and so actor identities are masked before they are stored.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from ..domain.enums import AuditActorType, DisputeCaseStatus, DisputeLifecycleEvent
from ..domain.models import DisputeLifecycleAuditEvent
from ..repositories.dispute_audit import DisputeLifecycleAuditRepository
from ..security.masking import mask_actor_id


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class DisputeLifecycleAuditService:
    """Builds and records the distinct events on a dispute's lifecycle."""

    def __init__(
        self,
        repository: DisputeLifecycleAuditRepository,
        *,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._id_factory = id_factory

    def build(
        self,
        *,
        event_type: DisputeLifecycleEvent,
        case_id: str,
        investigation_id: str,
        correlation_id: str,
        actor_type: AuditActorType,
        actor_id: str | None = None,
        previous_status: DisputeCaseStatus | None = None,
        new_status: DisputeCaseStatus | None = None,
        evidence_hash: str | None = None,
        reason_code: str | None = None,
    ) -> DisputeLifecycleAuditEvent:
        """Build an event without storing it, for callers that write it atomically."""
        return DisputeLifecycleAuditEvent(
            event_id=self._id_factory(),
            event_type=event_type,
            case_id=case_id,
            investigation_id=investigation_id,
            correlation_id=correlation_id,
            timestamp=self._clock(),
            actor_type=actor_type,
            actor_id_masked=mask_actor_id(actor_id),
            previous_status=previous_status,
            new_status=new_status,
            evidence_hash=evidence_hash,
            reason_code=reason_code,
        )

    def record(
        self,
        *,
        event_type: DisputeLifecycleEvent,
        case_id: str,
        investigation_id: str,
        correlation_id: str,
        actor_type: AuditActorType,
        actor_id: str | None = None,
        previous_status: DisputeCaseStatus | None = None,
        new_status: DisputeCaseStatus | None = None,
        evidence_hash: str | None = None,
        reason_code: str | None = None,
    ) -> DisputeLifecycleAuditEvent:
        """Build and persist one lifecycle event."""
        event = self.build(
            event_type=event_type,
            case_id=case_id,
            investigation_id=investigation_id,
            correlation_id=correlation_id,
            actor_type=actor_type,
            actor_id=actor_id,
            previous_status=previous_status,
            new_status=new_status,
            evidence_hash=evidence_hash,
            reason_code=reason_code,
        )
        self._repository.append(event)
        return event

    def record_once(
        self,
        *,
        event_type: DisputeLifecycleEvent,
        case_id: str,
        investigation_id: str,
        correlation_id: str,
        actor_type: AuditActorType,
        actor_id: str | None = None,
        previous_status: DisputeCaseStatus | None = None,
        new_status: DisputeCaseStatus | None = None,
        evidence_hash: str | None = None,
        reason_code: str | None = None,
    ) -> DisputeLifecycleAuditEvent:
        """Build and persist an event unless the case already has one of that type."""
        event = self.build(
            event_type=event_type,
            case_id=case_id,
            investigation_id=investigation_id,
            correlation_id=correlation_id,
            actor_type=actor_type,
            actor_id=actor_id,
            previous_status=previous_status,
            new_status=new_status,
            evidence_hash=evidence_hash,
            reason_code=reason_code,
        )
        self._repository.append_once(event)
        return event

    def case_history(self, case_id: str) -> list[DisputeLifecycleAuditEvent]:
        """Every lifecycle event for one case, oldest first."""
        return self._repository.list_by_case_id(case_id)

    def investigation_history(self, investigation_id: str) -> list[DisputeLifecycleAuditEvent]:
        """Every lifecycle event recorded under one investigation, oldest first."""
        return self._repository.list_by_investigation_id(investigation_id)
