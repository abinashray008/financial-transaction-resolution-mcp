"""Merchant data access."""

from sqlalchemy import func, select

from ..domain.models import Merchant
from .mappers import to_merchant
from .models import MerchantRow
from .session import SessionFactory


class MerchantRepository:
    """Reads the merchant catalog."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def list_all(self) -> list[Merchant]:
        """Every merchant, ordered by identifier so matching is deterministic."""
        statement = select(MerchantRow).order_by(MerchantRow.merchant_id)
        with self._session_factory() as session:
            return [to_merchant(row) for row in session.execute(statement).scalars()]

    def get(self, merchant_id: str) -> Merchant | None:
        """A single merchant, or ``None`` if unknown."""
        statement = select(MerchantRow).where(MerchantRow.merchant_id == merchant_id)
        with self._session_factory() as session:
            row = session.execute(statement).scalar_one_or_none()
        return None if row is None else to_merchant(row)

    def count(self) -> int:
        """Number of merchants in the catalog."""
        with self._session_factory() as session:
            return session.execute(select(func.count()).select_from(MerchantRow)).scalar_one()
