"""Account data access."""

from sqlalchemy import select

from ..domain.models import AccountWithCustomerState
from .mappers import to_account
from .models import AccountRow, CustomerRow
from .session import SessionFactory


class AccountRepository:
    """Reads accounts and the minimum customer context a summary needs."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def get_with_customer_state(self, account_id: str) -> AccountWithCustomerState | None:
        """Return the account and its customer's state, or ``None`` if unknown."""
        statement = (
            select(AccountRow, CustomerRow.state)
            .join(CustomerRow, AccountRow.customer_id == CustomerRow.customer_id)
            .where(AccountRow.account_id == account_id)
        )
        with self._session_factory() as session:
            result = session.execute(statement).first()
        if result is None:
            return None
        account_row, customer_state = result
        return AccountWithCustomerState(account=to_account(account_row), customer_state=customer_state)

    def exists(self, account_id: str) -> bool:
        """Whether an account with this identifier exists."""
        statement = select(AccountRow.account_id).where(AccountRow.account_id == account_id)
        with self._session_factory() as session:
            return session.execute(statement).first() is not None
