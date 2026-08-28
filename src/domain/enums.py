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


class DisputeReasonCode(StrEnum):
    """Deterministic reason assigned to a dispute case from investigation findings."""

    UNRECOGNIZED_TRANSACTION = "UNRECOGNIZED_TRANSACTION"
    LIKELY_DUPLICATE = "LIKELY_DUPLICATE"
    NEEDS_SPECIALIST_REVIEW = "NEEDS_SPECIALIST_REVIEW"
    FOREIGN_TRANSACTION_FEE = "FOREIGN_TRANSACTION_FEE"
    LATE_PAYMENT_FEE = "LATE_PAYMENT_FEE"


class DisputeCaseStatus(StrEnum):
    """Lifecycle of an internal synthetic dispute case file."""

    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReviewDecision(StrEnum):
    """What an authenticated back-office reviewer decided about a pending case."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"

    @property
    def resulting_status(self) -> DisputeCaseStatus:
        """Case status this decision moves a PENDING_REVIEW case to."""
        if self is ReviewDecision.APPROVE:
            return DisputeCaseStatus.APPROVED
        return DisputeCaseStatus.REJECTED


class ReviewReasonCode(StrEnum):
    """Closed vocabulary a reviewer must pick from when recording a decision."""

    CUSTOMER_CONFIRMATION_CLEAR = "CUSTOMER_CONFIRMATION_CLEAR"
    EVIDENCE_SUPPORTS_DISPUTE = "EVIDENCE_SUPPORTS_DISPUTE"
    POLICY_CRITERIA_MET = "POLICY_CRITERIA_MET"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    MERCHANT_RECOGNIZED_ON_REVIEW = "MERCHANT_RECOGNIZED_ON_REVIEW"
    POLICY_CRITERIA_NOT_MET = "POLICY_CRITERIA_NOT_MET"
    DUPLICATE_CASE_REQUEST = "DUPLICATE_CASE_REQUEST"


APPROVE_REASON_CODES = frozenset(
    {
        ReviewReasonCode.CUSTOMER_CONFIRMATION_CLEAR,
        ReviewReasonCode.EVIDENCE_SUPPORTS_DISPUTE,
        ReviewReasonCode.POLICY_CRITERIA_MET,
    }
)
REJECT_REASON_CODES = frozenset(
    {
        ReviewReasonCode.EVIDENCE_INSUFFICIENT,
        ReviewReasonCode.MERCHANT_RECOGNIZED_ON_REVIEW,
        ReviewReasonCode.POLICY_CRITERIA_NOT_MET,
        ReviewReasonCode.DUPLICATE_CASE_REQUEST,
    }
)


class AuditActorType(StrEnum):
    """Who caused a dispute lifecycle event, established by authentication."""

    HOST_AGENT = "host_agent"
    CUSTOMER = "customer"
    REVIEWER = "reviewer"


class DisputeLifecycleEvent(StrEnum):
    """Distinct, semantically named events on the dispute lifecycle."""

    INVESTIGATION_COMPLETED = "INVESTIGATION_COMPLETED"
    CUSTOMER_CONFIRMATION_REQUESTED = "CUSTOMER_CONFIRMATION_REQUESTED"
    CUSTOMER_CONFIRMED_UNRECOGNIZED = "CUSTOMER_CONFIRMED_UNRECOGNIZED"
    DISPUTE_CASE_CREATED = "DISPUTE_CASE_CREATED"
    REVIEW_STARTED = "REVIEW_STARTED"
    REVIEW_APPROVED = "REVIEW_APPROVED"
    REVIEW_REJECTED = "REVIEW_REJECTED"
