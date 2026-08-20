"""Domain models.

Plain frozen dataclasses with no persistence concerns. The repository layer
maps SQLAlchemy rows onto them, and the domain services only ever see these
types.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from .enums import AccountStatus, AccountType, TransactionStatus


@dataclass(frozen=True, slots=True)
class Customer:
    """A fictional customer."""

    customer_id: str
    first_name: str
    last_name: str
    state: str


@dataclass(frozen=True, slots=True)
class Account:
    """A fictional card account."""

    account_id: str
    customer_id: str
    account_type: AccountType
    account_status: AccountStatus
    open_date: date
    card_last_four: str


@dataclass(frozen=True, slots=True)
class Merchant:
    """A fictional merchant and the descriptor fragments it bills under."""

    merchant_id: str
    display_name: str
    category: str
    country: str
    descriptor_patterns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Transaction:
    """A fictional card transaction."""

    transaction_id: str
    account_id: str
    merchant_id: str
    raw_descriptor: str
    amount: Decimal
    currency: str
    transaction_date: date
    posted_date: date | None
    status: TransactionStatus
    card_present: bool
    recurring: bool


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """A sanitized record of one tool invocation."""

    event_id: str
    tool_name: str
    request_id: str
    timestamp: datetime
    account_id_masked: str | None
    outcome: str
    duration_ms: int


@dataclass(frozen=True, slots=True)
class AccountWithCustomerState:
    """Read model joining an account to the minimum customer context needed."""

    account: Account
    customer_state: str


@dataclass(frozen=True, slots=True)
class TransactionWithMerchant:
    """Read model joining a transaction to its merchant."""

    transaction: Transaction
    merchant: Merchant
