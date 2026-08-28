"""Domain models.

Plain frozen dataclasses with no persistence concerns. The repository layer
maps SQLAlchemy rows onto them, and the domain services only ever see these
types.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from .enums import (
    AccountStatus,
    AccountType,
    AuditActorType,
    DisputeCaseStatus,
    DisputeLifecycleEvent,
    DisputeReasonCode,
    ReviewReasonCode,
    TransactionStatus,
)


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


@dataclass(frozen=True, slots=True)
class DisputeCase:
    """An internal synthetic dispute case file, created on customer confirmation.

    A case is written at ``PENDING_REVIEW`` before any human looks at it, and is
    only ever updated in place afterwards. ``externally_submitted`` is always
    false: nothing here is sent to a card network.
    """

    case_id: str
    customer_id: str
    account_id: str
    transaction_id: str
    investigation_id: str
    confirmation_id: str
    idempotency_key: str
    reason: str
    reason_code: DisputeReasonCode
    status: DisputeCaseStatus
    version: int
    evidence_hash: str
    amount: Decimal
    currency: str
    merchant_display_name: str
    created_at: datetime
    updated_at: datetime
    externally_submitted: bool = False
    reviewer_id: str | None = None
    review_reason_code: ReviewReasonCode | None = None
    review_note: str | None = None
    reviewed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DisputeEvidenceSnapshot:
    """Immutable copy of the evidence a case was created from.

    Written in the same transaction as the case and never updated, so a
    reviewer always sees exactly what the customer confirmed.
    """

    snapshot_id: str
    case_id: str
    investigation_id: str
    account_id: str
    transaction_id: str
    evidence_hash: str
    payload: dict[str, object]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CustomerConfirmation:
    """A server-issued challenge that proves the customer confirmed the charge.

    The token itself is never stored; only its digest is, so a leaked database
    row cannot be replayed as a confirmation.
    """

    confirmation_id: str
    investigation_id: str
    account_id: str
    transaction_id: str
    case_id: str
    customer_id: str
    evidence_hash: str
    reason: str
    reason_code: DisputeReasonCode
    snapshot: dict[str, object]
    amount: Decimal
    currency: str
    merchant_display_name: str
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class IssuedConfirmation:
    """A freshly issued challenge plus the one-time token, returned once."""

    confirmation: CustomerConfirmation
    confirmation_token: str


@dataclass(frozen=True, slots=True)
class DisputeLifecycleAuditEvent:
    """One sanitized dispute lifecycle event.

    Distinct from :class:`AuditEvent`, which records tool invocations. Actor
    identifiers are masked before they reach this model.
    """

    event_id: str
    event_type: DisputeLifecycleEvent
    case_id: str
    investigation_id: str
    correlation_id: str
    timestamp: datetime
    actor_type: AuditActorType
    actor_id_masked: str | None
    previous_status: DisputeCaseStatus | None
    new_status: DisputeCaseStatus | None
    evidence_hash: str | None
    reason_code: str | None
