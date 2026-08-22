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
    ApprovalDecision,
    DisputeCaseStatus,
    DisputeReasonCode,
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
    """A human-approved synthetic dispute case file."""

    case_id: str
    customer_id: str
    account_id: str
    transaction_id: str
    request_id: str
    reason: str
    status: DisputeCaseStatus
    amount: Decimal
    currency: str
    merchant_display_name: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DisputeProposal:
    """A PENDING_REVIEW draft. Creating it does not register a case."""

    request_id: str
    account_id: str
    transaction_id: str
    customer_id: str
    merchant_display_name: str
    amount: Decimal
    currency: str
    transaction_date: date
    reason: str
    reason_code: DisputeReasonCode
    verified_evidence: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    applied_policy: str
    proposed_action: str
    draft_hash: str
    message: str


@dataclass(frozen=True, slots=True)
class DisputeDecision:
    """Result of resuming the dispute workflow after a verified approval."""

    request_id: str
    account_id: str
    transaction_id: str
    customer_id: str
    workflow_status: str
    case_id: str | None
    reason: str
    decision_note: str | None
    approval_id: str


@dataclass(frozen=True, slots=True)
class DisputeApproval:
    """One-time human approval record. Minted by the review app, not the LLM."""

    approval_id: str
    request_id: str
    draft_hash: str
    reviewer_id: str
    decision: ApprovalDecision
    decision_note: str | None
    created_at: datetime
    decided_at: datetime
    expires_at: datetime
    consumed_at: datetime | None

    @property
    def is_approved(self) -> bool:
        """Whether the reviewer approved registration."""
        return self.decision is ApprovalDecision.APPROVED
