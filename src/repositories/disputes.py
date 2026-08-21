"""Dispute case data access.

Inserts and lookups are always scoped to a single ``account_id``. A case on
another account is indistinguishable from one that does not exist.
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..domain.exceptions import DisputeAlreadyExistsError
from ..domain.models import DisputeCase
from ..domain.money import to_minor_units
from .mappers import to_dispute_case
from .models import DisputeCaseRow
from .session import SessionFactory


class DisputeRepository:
    """Persists human-approved synthetic dispute cases."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def get_for_account(self, account_id: str, transaction_id: str) -> DisputeCase | None:
        """A registered case, only if it belongs to ``account_id``."""
        statement = select(DisputeCaseRow).where(
            DisputeCaseRow.account_id == account_id,
            DisputeCaseRow.transaction_id == transaction_id,
        )
        with self._session_factory() as session:
            row = session.execute(statement).scalar_one_or_none()
        return None if row is None else to_dispute_case(row)

    def get_by_case_id_for_account(self, account_id: str, case_id: str) -> DisputeCase | None:
        """A registered case by id, only if it belongs to ``account_id``."""
        statement = select(DisputeCaseRow).where(
            DisputeCaseRow.account_id == account_id,
            DisputeCaseRow.case_id == case_id,
        )
        with self._session_factory() as session:
            row = session.execute(statement).scalar_one_or_none()
        return None if row is None else to_dispute_case(row)

    def insert(self, case: DisputeCase) -> None:
        """Persist one registered case. Duplicate account/transaction pairs are rejected."""
        row = DisputeCaseRow(
            case_id=case.case_id,
            customer_id=case.customer_id,
            account_id=case.account_id,
            transaction_id=case.transaction_id,
            request_id=case.request_id,
            reason=case.reason,
            status=case.status.value,
            amount_minor=to_minor_units(case.amount),
            currency=case.currency,
            merchant_display_name=case.merchant_display_name,
            created_at=case.created_at,
        )
        with self._session_factory() as session:
            session.add(row)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise DisputeAlreadyExistsError(
                    "A dispute case is already registered for this account and transaction.",
                ) from exc
