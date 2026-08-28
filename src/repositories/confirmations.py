"""Customer confirmation challenge data access.

Challenges are looked up by token digest, never by a caller-supplied
identifier, and are consumed in a single transaction so the same token cannot
open two cases.
"""

from datetime import datetime

from sqlalchemy import select

from ..domain.exceptions import ConfirmationAlreadyUsedError, ConfirmationNotFoundError
from ..domain.models import CustomerConfirmation
from ..domain.money import to_minor_units
from .mappers import to_customer_confirmation
from .models import ConfirmationChallengeRow
from .session import SessionFactory


class ConfirmationRepository:
    """Persists one-time customer confirmation challenges."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def insert(self, confirmation: CustomerConfirmation, *, token_hash: str) -> None:
        """Store a challenge. The raw token is never persisted."""
        row = ConfirmationChallengeRow(
            confirmation_id=confirmation.confirmation_id,
            token_hash=token_hash,
            investigation_id=confirmation.investigation_id,
            account_id=confirmation.account_id,
            transaction_id=confirmation.transaction_id,
            case_id=confirmation.case_id,
            customer_id=confirmation.customer_id,
            evidence_hash=confirmation.evidence_hash,
            reason=confirmation.reason,
            reason_code=confirmation.reason_code.value,
            snapshot=confirmation.snapshot,
            amount_minor=to_minor_units(confirmation.amount),
            currency=confirmation.currency,
            merchant_display_name=confirmation.merchant_display_name,
            created_at=confirmation.created_at,
            expires_at=confirmation.expires_at,
            consumed_at=None,
        )
        with self._session_factory() as session:
            session.add(row)
            session.commit()

    def get_by_token_hash(self, token_hash: str) -> CustomerConfirmation | None:
        """Load a challenge by token digest, or ``None`` when the token is unknown."""
        statement = select(ConfirmationChallengeRow).where(ConfirmationChallengeRow.token_hash == token_hash)
        with self._session_factory() as session:
            row = session.execute(statement).scalar_one_or_none()
        return None if row is None else to_customer_confirmation(row)

    def get(self, confirmation_id: str) -> CustomerConfirmation | None:
        """Load a challenge by its identifier."""
        statement = select(ConfirmationChallengeRow).where(ConfirmationChallengeRow.confirmation_id == confirmation_id)
        with self._session_factory() as session:
            row = session.execute(statement).scalar_one_or_none()
        return None if row is None else to_customer_confirmation(row)

    def consume(self, token_hash: str, *, consumed_at: datetime) -> CustomerConfirmation:
        """Mark a challenge used if it is still unused, in one transaction."""
        statement = select(ConfirmationChallengeRow).where(ConfirmationChallengeRow.token_hash == token_hash)
        with self._session_factory() as session:
            row = session.execute(statement).scalar_one_or_none()
            if row is None:
                raise ConfirmationNotFoundError(
                    "No pending customer confirmation matches this confirmation_token.",
                )
            if row.consumed_at is not None:
                raise ConfirmationAlreadyUsedError(
                    "This confirmation_token has already been used and cannot be reused.",
                )
            row.consumed_at = consumed_at
            session.commit()
            return to_customer_confirmation(row)
