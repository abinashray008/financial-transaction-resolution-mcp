"""Transaction data access.

Every statement in this module is scoped to a single ``account_id``. There is
no code path that can return a transaction belonging to another account.
"""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import ColumnElement, Select, func, select

from ..domain.criteria import TransactionSearchCriteria
from ..domain.models import Transaction, TransactionWithMerchant
from ..domain.money import to_minor_units
from .mappers import to_merchant, to_transaction
from .models import MerchantRow, TransactionRow
from .session import SessionFactory

_LIKE_ESCAPE = "\\"


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards so a user query cannot widen the match."""
    escaped = value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
    return escaped.replace("%", f"{_LIKE_ESCAPE}%").replace("_", f"{_LIKE_ESCAPE}_")


class TransactionRepository:
    """Reads transactions, always within the boundary of one account."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def search(self, criteria: TransactionSearchCriteria) -> list[TransactionWithMerchant]:
        """Transactions on ``criteria.account_id`` matching every supplied filter."""
        statement = self._joined_select().where(TransactionRow.account_id == criteria.account_id)

        if criteria.start_date is not None:
            statement = statement.where(TransactionRow.transaction_date >= criteria.start_date)
        if criteria.end_date is not None:
            statement = statement.where(TransactionRow.transaction_date <= criteria.end_date)
        if criteria.minimum_amount is not None:
            statement = statement.where(TransactionRow.amount_minor >= to_minor_units(criteria.minimum_amount))
        if criteria.maximum_amount is not None:
            statement = statement.where(TransactionRow.amount_minor <= to_minor_units(criteria.maximum_amount))
        if criteria.status is not None:
            statement = statement.where(TransactionRow.status == criteria.status.value)
        if criteria.merchant_query is not None:
            statement = statement.where(self._merchant_query_filter(criteria.merchant_query))

        statement = statement.order_by(
            TransactionRow.transaction_date.desc(),
            TransactionRow.transaction_id.asc(),
        ).limit(criteria.limit)

        return self._execute_joined(statement)

    def get_for_account(self, account_id: str, transaction_id: str) -> TransactionWithMerchant | None:
        """A single transaction, only if it belongs to ``account_id``.

        A transaction that exists on a different account is indistinguishable
        from one that does not exist at all.
        """
        statement = self._joined_select().where(
            TransactionRow.account_id == account_id,
            TransactionRow.transaction_id == transaction_id,
        )
        results = self._execute_joined(statement)
        return results[0] if results else None

    def find_duplicate_candidates(
        self,
        *,
        subject: Transaction,
        date_tolerance_days: int,
        amount_tolerance: Decimal,
    ) -> list[Transaction]:
        """Other transactions on the same account and merchant near the subject."""
        tolerance_minor = to_minor_units(amount_tolerance)
        subject_minor = to_minor_units(subject.amount)

        statement = (
            select(TransactionRow)
            .where(
                TransactionRow.account_id == subject.account_id,
                TransactionRow.merchant_id == subject.merchant_id,
                TransactionRow.transaction_id != subject.transaction_id,
                TransactionRow.currency == subject.currency,
                TransactionRow.transaction_date >= subject.transaction_date - timedelta(days=date_tolerance_days),
                TransactionRow.transaction_date <= subject.transaction_date + timedelta(days=date_tolerance_days),
                TransactionRow.amount_minor >= subject_minor - tolerance_minor,
                TransactionRow.amount_minor <= subject_minor + tolerance_minor,
            )
            .order_by(TransactionRow.transaction_date.asc(), TransactionRow.transaction_id.asc())
        )

        with self._session_factory() as session:
            return [to_transaction(row) for row in session.execute(statement).scalars()]

    def count(self) -> int:
        """Total number of transactions in the dataset."""
        with self._session_factory() as session:
            return session.execute(select(func.count()).select_from(TransactionRow)).scalar_one()

    @staticmethod
    def _merchant_query_filter(merchant_query: str) -> ColumnElement[bool]:
        pattern = f"%{_escape_like(merchant_query.strip())}%"
        return MerchantRow.display_name.ilike(pattern, escape=_LIKE_ESCAPE) | TransactionRow.raw_descriptor.ilike(
            pattern, escape=_LIKE_ESCAPE
        )

    @staticmethod
    def _joined_select() -> Select[tuple[TransactionRow, MerchantRow]]:
        return select(TransactionRow, MerchantRow).join(
            MerchantRow, TransactionRow.merchant_id == MerchantRow.merchant_id
        )

    def _execute_joined(self, statement: Select[tuple[TransactionRow, MerchantRow]]) -> list[TransactionWithMerchant]:
        with self._session_factory() as session:
            rows = session.execute(statement).all()
        return [
            TransactionWithMerchant(transaction=to_transaction(transaction_row), merchant=to_merchant(merchant_row))
            for transaction_row, merchant_row in rows
        ]
