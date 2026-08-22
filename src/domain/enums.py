"""Closed vocabularies shared by the domain, the contracts and the seed data."""

from enum import StrEnum


class AccountType(StrEnum):
    """Product family a fictional account belongs to."""

    CONSUMER_CREDIT_CARD = "consumer_credit_card"
    BUSINESS_CREDIT_CARD = "business_credit_card"
    CONSUMER_CHARGE_CARD = "consumer_charge_card"


class AccountStatus(StrEnum):
    """Lifecycle state of a fictional account."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class TransactionStatus(StrEnum):
    """Lifecycle state of a fictional transaction."""

    PENDING = "pending"
    POSTED = "posted"
    AUTHORIZATION_HOLD = "authorization_hold"
    REVERSED = "reversed"


class Confidence(StrEnum):
    """Confidence category returned by the deterministic analysis services."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AuditOutcome(StrEnum):
    """Coarse outcome recorded for every tool invocation."""

    SUCCESS = "success"
    ERROR = "error"


class DisputeWorkflowStatus(StrEnum):
    """Where a human-in-the-loop dispute registration graph currently sits."""

    PENDING_REVIEW = "pending_review"
    REGISTERED = "registered"
    DECLINED = "declined"


class DisputeReasonCode(StrEnum):
    """Deterministic reason assigned to a dispute draft from investigation findings."""

    UNRECOGNIZED_TRANSACTION = "UNRECOGNIZED_TRANSACTION"
    LIKELY_DUPLICATE = "LIKELY_DUPLICATE"
    NEEDS_SPECIALIST_REVIEW = "NEEDS_SPECIALIST_REVIEW"
    FOREIGN_TRANSACTION_FEE = "FOREIGN_TRANSACTION_FEE"
    LATE_PAYMENT_FEE = "LATE_PAYMENT_FEE"


class DisputeCaseStatus(StrEnum):
    """Lifecycle of a registered synthetic dispute case file."""

    REGISTERED = "registered"


class ApprovalDecision(StrEnum):
    """Human decision stored on a minted approval record."""

    APPROVED = "approved"
    DECLINED = "declined"
