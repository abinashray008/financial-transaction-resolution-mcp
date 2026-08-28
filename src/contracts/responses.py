"""Structured tool outputs.

Amounts are ``Decimal`` and therefore serialize as JSON strings, which keeps
them exact. Account and card identifiers are always masked before they reach
these models.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..domain.enums import (
    AccountStatus,
    AccountType,
    AuditActorType,
    Confidence,
    DisputeCaseStatus,
    DisputeLifecycleEvent,
    DisputeReasonCode,
    ReviewReasonCode,
    TransactionStatus,
)
from .common import Money, ToolResponseBase


class _Payload(BaseModel):
    model_config = ConfigDict(frozen=True)


class AccountSummaryData(_Payload):
    """The minimum account context an investigation needs."""

    masked_account_id: str = Field(description="Account identifier with its body masked.")
    account_type: AccountType
    account_status: AccountStatus
    open_date: date
    masked_card: str = Field(description="Masked card identifier; only the last four digits are ever shown.")
    customer_state: str = Field(description="Two-letter state of the account holder. No name is returned.")


class TransactionSummary(_Payload):
    """One transaction as it appears in a search result."""

    transaction_id: str
    merchant_id: str
    merchant_display_name: str
    raw_descriptor: str = Field(description="Descriptor exactly as it appears on the statement.")
    amount: Money
    currency: str
    transaction_date: date
    posted_date: date | None
    status: TransactionStatus
    card_present: bool
    recurring: bool


class AppliedFilters(_Payload):
    """Echo of the filters the search actually applied."""

    start_date: date | None
    end_date: date | None
    merchant_query: str | None
    minimum_amount: Money | None
    maximum_amount: Money | None
    status: TransactionStatus | None
    limit: int


class TransactionSearchData(_Payload):
    """Result of ``search_transactions``."""

    masked_account_id: str
    applied_filters: AppliedFilters
    returned_count: int = Field(description="Number of transactions returned, never more than the limit.")
    truncated: bool = Field(description="True when the limit was reached and more may exist.")
    transactions: list[TransactionSummary]


class MerchantData(_Payload):
    """A merchant as returned alongside a transaction."""

    merchant_id: str
    display_name: str
    category: str
    country: str


class TransactionDetailsData(_Payload):
    """Result of ``get_transaction_details``."""

    masked_account_id: str
    transaction: TransactionSummary
    merchant: MerchantData


class MerchantResolutionData(_Payload):
    """Result of ``resolve_merchant``."""

    raw_descriptor: str
    normalized_descriptor: str
    matched: bool
    merchant_id: str | None
    display_name: str | None = Field(description="Normalized merchant display name, when a match was found.")
    category: str | None
    country: str | None
    match_confidence: Confidence
    match_score: float = Field(description="Deterministic score between 0 and 1.")
    match_rule: str = Field(description="Which fixed rule produced the match.")
    matched_pattern: str | None
    explanation: str


class DuplicateCheckData(_Payload):
    """Result of ``check_duplicate_charge``."""

    masked_account_id: str
    transaction_id: str
    duplicate_likely: bool
    confidence: Confidence
    candidate_transaction_ids: list[str]
    reasons: list[str]
    date_tolerance_days: int
    amount_tolerance: Money


class AuditEventView(_Payload):
    """One sanitized audit event."""

    event_id: str
    tool_name: str
    request_id: str
    timestamp: datetime
    account_id_masked: str | None
    outcome: str
    duration_ms: int


class AuditTraceData(_Payload):
    """Result of ``get_audit_trace``."""

    request_id: str
    event_count: int
    events: list[AuditEventView]


class AccountSummaryResponse(ToolResponseBase):
    """Envelope for ``get_account_summary``."""

    data: AccountSummaryData | None = None


class TransactionSearchResponse(ToolResponseBase):
    """Envelope for ``search_transactions``."""

    data: TransactionSearchData | None = None


class TransactionDetailsResponse(ToolResponseBase):
    """Envelope for ``get_transaction_details``."""

    data: TransactionDetailsData | None = None


class MerchantResolutionResponse(ToolResponseBase):
    """Envelope for ``resolve_merchant``."""

    data: MerchantResolutionData | None = None


class DuplicateCheckResponse(ToolResponseBase):
    """Envelope for ``check_duplicate_charge``."""

    data: DuplicateCheckData | None = None


class AuditTraceResponse(ToolResponseBase):
    """Envelope for ``get_audit_trace``."""

    data: AuditTraceData | None = None


class GeminiSynthesisResult(_Payload):
    """Structured Gemini output for ``synthesize_investigation``.

    The model chooses the narrative and one next action. It never issues the
    confirmation token, decides eligibility, or sees the case identifier.
    """

    customer_response: str = Field(
        min_length=1,
        description="Customer-facing synthesis of the investigation findings.",
    )
    recommended_action: Literal[
        "NO_ACTION",
        "REQUEST_MORE_INFORMATION",
        "REQUEST_CUSTOMER_CONFIRMATION",
    ] = Field(description="Exactly one next action after the customer-facing reply is shown.")


class ConfirmationChallengeData(_Payload):
    """The server-owned confirmation gate returned alongside an eligible synthesis."""

    confirmation_token: str = Field(
        description=(
            "One-time token to pass to confirm_unrecognized_transaction, and only after the "
            "customer explicitly confirms they do not recognize the charge."
        ),
    )
    expires_at: datetime = Field(description="After this instant the token is refused and synthesis must be re-run.")
    masked_account_id: str
    transaction_id: str
    next_tool: Literal["confirm_unrecognized_transaction"] = "confirm_unrecognized_transaction"
    message: str = Field(description="What the host agent must ask the customer before confirming.")


class SynthesisData(GeminiSynthesisResult):
    """Result of ``synthesize_investigation``."""

    model_name: str = Field(description="Gemini model that produced the reply.")
    investigation_id: str = Field(description="Correlation id to reuse when confirming.")
    confirmation: ConfirmationChallengeData | None = Field(
        default=None,
        description=(
            "Present only when this charge is eligible for a dispute case and no case exists yet. "
            "Absent means no confirmation can be taken for this investigation."
        ),
    )


class SynthesisResponse(ToolResponseBase):
    """Envelope for ``synthesize_investigation``."""

    data: SynthesisData | None = None


class DisputeCaseCreated(_Payload):
    """Result of ``confirm_unrecognized_transaction``.

    The case exists and is persisted at this point. It is queued for internal
    back-office review; nothing has been submitted to an issuer or network.
    """

    case_id: str
    status: Literal["PENDING_REVIEW"] = "PENDING_REVIEW"
    created_at: datetime
    review_required: Literal[True] = True
    externally_submitted: Literal[False] = False
    investigation_id: str
    masked_account_id: str
    masked_customer_id: str = Field(description="Masked customer identifier. The customer's name is never returned.")
    transaction_id: str
    reason_code: DisputeReasonCode
    version: int = Field(description="Optimistic-concurrency version a reviewer must echo back.")
    evidence_hash: str = Field(description="SHA-256 of the immutable evidence snapshot behind this case.")
    review_path: str = Field(description="HTTP path where an authenticated reviewer decides this case.")
    message: str = Field(description="What to tell the customer now that the case exists.")


class DisputeCaseCreatedResponse(ToolResponseBase):
    """Envelope for ``confirm_unrecognized_transaction``."""

    data: DisputeCaseCreated | None = None


class DisputeLifecycleEventView(_Payload):
    """One dispute lifecycle event, as shown to an authenticated reviewer."""

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


class DisputeCaseView(_Payload):
    """One dispute case and its immutable evidence, for the review application."""

    case_id: str
    status: DisputeCaseStatus
    version: int
    investigation_id: str
    masked_account_id: str
    masked_customer_id: str
    transaction_id: str
    merchant_display_name: str
    amount: Money
    currency: str
    reason: str
    reason_code: DisputeReasonCode
    verified_evidence: list[str]
    missing_evidence: list[str]
    applied_policy: str = Field(description="Server-owned policy URI applied to this case.")
    proposed_action: str
    evidence_hash: str
    created_at: datetime
    updated_at: datetime
    externally_submitted: Literal[False] = False
    reviewer_id: str | None = None
    review_reason_code: ReviewReasonCode | None = None
    review_note: str | None = None
    reviewed_at: datetime | None = None
    history: list[DisputeLifecycleEventView] = Field(default_factory=list)


class ReviewDecisionData(_Payload):
    """Result of an authenticated reviewer decision on a pending case."""

    case_id: str
    status: DisputeCaseStatus
    version: int
    reviewer_id: str = Field(description="Authenticated reviewer identity, derived from the bearer token.")
    reason_code: ReviewReasonCode
    note: str | None
    reviewed_at: datetime
    externally_submitted: Literal[False] = False
