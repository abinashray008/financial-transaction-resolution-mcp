"""Audit logging.

The service takes only the fields it is allowed to store. There is no code
path that accepts a tool's raw arguments, a customer name, a merchant
descriptor or a transaction payload, so none of those can reach the log.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from ..domain.enums import AuditOutcome
from ..domain.models import AuditEvent
from ..repositories.audit import AuditRepository
from ..security.masking import mask_optional_account_id


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AuditService:
    """Records one sanitized event per tool invocation."""

    def __init__(
        self,
        repository: AuditRepository,
        *,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._id_factory = id_factory

    def record(
        self,
        *,
        tool_name: str,
        request_id: str,
        account_id: str | None,
        outcome: AuditOutcome | str,
        duration_ms: int,
    ) -> AuditEvent:
        """Persist a sanitized audit event and return it."""
        event = AuditEvent(
            event_id=self._id_factory(),
            tool_name=tool_name,
            request_id=request_id,
            timestamp=self._clock(),
            account_id_masked=mask_optional_account_id(account_id),
            outcome=str(outcome),
            duration_ms=duration_ms,
        )
        self._repository.append(event)
        return event

    def trace(self, request_id: str) -> list[AuditEvent]:
        """Every sanitized event recorded under a request identifier."""
        return self._repository.list_by_request_id(request_id)

    def new_request_id(self) -> str:
        """Generate a correlation identifier for a caller that did not supply one."""
        return self._id_factory()
