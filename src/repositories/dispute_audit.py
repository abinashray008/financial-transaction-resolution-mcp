"""Dispute lifecycle audit data access.

Append-only, and deliberately separate from ``audit_events``: tool telemetry
answers "which tools ran", while these events answer "who moved this case and
from which status to which". Actor identifiers arrive already masked.
"""

from sqlalchemy import select

from ..domain.enums import DisputeLifecycleEvent
from ..domain.models import DisputeLifecycleAuditEvent
from .mappers import to_dispute_lifecycle_event
from .models import DisputeLifecycleEventRow
from .session import SessionFactory


def lifecycle_event_row(event: DisputeLifecycleAuditEvent) -> DisputeLifecycleEventRow:
    """Build a row for one lifecycle event, for this or another repository's session."""
    return DisputeLifecycleEventRow(
        event_id=event.event_id,
        event_type=event.event_type.value,
        case_id=event.case_id,
        investigation_id=event.investigation_id,
        correlation_id=event.correlation_id,
        timestamp=event.timestamp,
        actor_type=event.actor_type.value,
        actor_id_masked=event.actor_id_masked,
        previous_status=None if event.previous_status is None else event.previous_status.value,
        new_status=None if event.new_status is None else event.new_status.value,
        evidence_hash=event.evidence_hash,
        reason_code=event.reason_code,
    )


class DisputeLifecycleAuditRepository:
    """Appends and reads dispute lifecycle events."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def append(self, event: DisputeLifecycleAuditEvent) -> None:
        """Persist one lifecycle event."""
        with self._session_factory() as session:
            session.add(lifecycle_event_row(event))
            session.commit()

    def append_once(self, event: DisputeLifecycleAuditEvent) -> bool:
        """Persist an event unless one of the same type exists for the case.

        Used for ``REVIEW_STARTED``, which a reviewer can trigger by reloading
        the page. Returns whether the event was written.
        """
        statement = select(DisputeLifecycleEventRow.event_id).where(
            DisputeLifecycleEventRow.case_id == event.case_id,
            DisputeLifecycleEventRow.event_type == event.event_type.value,
        )
        with self._session_factory() as session:
            if session.execute(statement).first() is not None:
                return False
            session.add(lifecycle_event_row(event))
            session.commit()
        return True

    def list_by_case_id(self, case_id: str) -> list[DisputeLifecycleAuditEvent]:
        """Every lifecycle event for one case, oldest first."""
        return self._list(DisputeLifecycleEventRow.case_id == case_id)

    def list_by_investigation_id(self, investigation_id: str) -> list[DisputeLifecycleAuditEvent]:
        """Every lifecycle event recorded under one investigation, oldest first."""
        return self._list(DisputeLifecycleEventRow.investigation_id == investigation_id)

    def count_of_type(self, case_id: str, event_type: DisputeLifecycleEvent) -> int:
        """How many events of one type exist for a case."""
        statement = select(DisputeLifecycleEventRow.event_id).where(
            DisputeLifecycleEventRow.case_id == case_id,
            DisputeLifecycleEventRow.event_type == event_type.value,
        )
        with self._session_factory() as session:
            return len(list(session.execute(statement).scalars()))

    def _list(self, condition: object) -> list[DisputeLifecycleAuditEvent]:
        statement = (
            select(DisputeLifecycleEventRow)
            .where(condition)  # type: ignore[arg-type]
            .order_by(DisputeLifecycleEventRow.timestamp.asc(), DisputeLifecycleEventRow.event_id.asc())
        )
        with self._session_factory() as session:
            rows = list(session.execute(statement).scalars())
        return [to_dispute_lifecycle_event(row) for row in rows]
