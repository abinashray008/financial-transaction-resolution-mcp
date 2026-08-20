"""Validated value objects describing a query against the dataset.

Range validation lives here rather than in the MCP layer so it can be tested
without a client and reused by any future transport.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .enums import TransactionStatus
from .exceptions import InvalidAmountRangeError, InvalidDateRangeError, InvalidInputError

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
DEFAULT_DATE_TOLERANCE_DAYS = 3
MAX_DATE_TOLERANCE_DAYS = 30


@dataclass(frozen=True, slots=True)
class TransactionSearchCriteria:
    """Filters for a transaction search, always scoped to a single account."""

    account_id: str
    start_date: date | None = None
    end_date: date | None = None
    merchant_query: str | None = None
    minimum_amount: Decimal | None = None
    maximum_amount: Decimal | None = None
    status: TransactionStatus | None = None
    limit: int = DEFAULT_LIMIT

    def __post_init__(self) -> None:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise InvalidDateRangeError("start_date must not be after end_date.")

        for label, amount in (("minimum_amount", self.minimum_amount), ("maximum_amount", self.maximum_amount)):
            if amount is not None and amount < 0:
                raise InvalidAmountRangeError(f"{label} must not be negative.")

        if (
            self.minimum_amount is not None
            and self.maximum_amount is not None
            and self.minimum_amount > self.maximum_amount
        ):
            raise InvalidAmountRangeError("minimum_amount must not be greater than maximum_amount.")

        if self.merchant_query is not None and not self.merchant_query.strip():
            raise InvalidInputError("merchant_query must not be blank when provided.")

        if not 1 <= self.limit <= MAX_LIMIT:
            raise InvalidInputError(f"limit must be between 1 and {MAX_LIMIT}.")


@dataclass(frozen=True, slots=True)
class DuplicateCheckCriteria:
    """Tolerances used when looking for a duplicate of a known transaction."""

    account_id: str
    transaction_id: str
    date_tolerance_days: int = DEFAULT_DATE_TOLERANCE_DAYS
    amount_tolerance: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not 0 <= self.date_tolerance_days <= MAX_DATE_TOLERANCE_DAYS:
            raise InvalidInputError(f"date_tolerance_days must be between 0 and {MAX_DATE_TOLERANCE_DAYS}.")
        if self.amount_tolerance < 0:
            raise InvalidAmountRangeError("amount_tolerance must not be negative.")
