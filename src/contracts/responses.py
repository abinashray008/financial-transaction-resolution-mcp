"""Structured tool outputs.

Amounts are ``Decimal`` and therefore serialize as JSON strings, which keeps
them exact. Account and card identifiers are always masked before they reach
these models.
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from ..domain.enums import AccountStatus, AccountType, Confidence, TransactionStatus
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


class SynthesisData(_Payload):
    """Result of ``synthesize_investigation``."""

    model_name: str = Field(description="Gemini model that produced the reply.")
    customer_response: str = Field(description="Customer-facing synthesis of the investigation findings.")


class SynthesisResponse(ToolResponseBase):
    """Envelope for ``synthesize_investigation``."""

    data: SynthesisData | None = None
