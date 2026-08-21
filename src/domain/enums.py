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

    AWAITING_APPROVAL = "awaiting_approval"
    REGISTERED = "registered"
    DECLINED = "declined"


class DisputeCaseStatus(StrEnum):
    """Lifecycle of a registered synthetic dispute case file."""

    REGISTERED = "registered"
