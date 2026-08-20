"""Audit event data access."""

from sqlalchemy import select

from ..domain.models import AuditEvent
from .models import AuditEventRow
from .session import SessionFactory


class AuditRepository:
    """Appends and reads sanitized audit events."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def append(self, event: AuditEvent) -> None:
        """Persist one audit event."""
        row = AuditEventRow(
            event_id=event.event_id,
            tool_name=event.tool_name,
            request_id=event.request_id,
            timestamp=event.timestamp,
            account_id_masked=event.account_id_masked,
            outcome=event.outcome,
            duration_ms=event.duration_ms,
        )
        with self._session_factory() as session:
            session.add(row)
            session.commit()

    def list_by_request_id(self, request_id: str) -> list[AuditEvent]:
        """Every event recorded under a request identifier, oldest first."""
        statement = (
            select(AuditEventRow)
            .where(AuditEventRow.request_id == request_id)
            .order_by(AuditEventRow.timestamp.asc(), AuditEventRow.event_id.asc())
        )
        with self._session_factory() as session:
            rows = list(session.execute(statement).scalars())
        return [
            AuditEvent(
                event_id=row.event_id,
                tool_name=row.tool_name,
                request_id=row.request_id,
                timestamp=row.timestamp,
                account_id_masked=row.account_id_masked,
                outcome=row.outcome,
                duration_ms=row.duration_ms,
            )
            for row in rows
        ]
