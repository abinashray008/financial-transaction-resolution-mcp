"""Structured tool inputs.

The MCP layer exposes flat arguments so hosts get a readable JSON Schema; the
routers then assemble these contracts, which are what the handlers actually
consume. Semantic validation (ranges, identifier shapes) happens deeper, in
the domain criteria and the input validators, so that it is testable without
an MCP client.
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..domain.criteria import DEFAULT_DATE_TOLERANCE_DAYS, DEFAULT_LIMIT
from ..domain.enums import TransactionStatus


class _Request(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str | None = Field(
        default=None,
        description="Caller-supplied correlation id. Generated when omitted.",
    )


class GetAccountSummaryRequest(_Request):
    """Input for ``get_account_summary``."""

    account_id: str


class SearchTransactionsRequest(_Request):
    """Input for ``search_transactions``."""

    account_id: str
    start_date: date | None = None
    end_date: date | None = None
    merchant_query: str | None = None
    minimum_amount: Decimal | None = None
    maximum_amount: Decimal | None = None
    status: TransactionStatus | None = None
    limit: int = DEFAULT_LIMIT


class GetTransactionDetailsRequest(_Request):
    """Input for ``get_transaction_details``."""

    account_id: str
    transaction_id: str


class ResolveMerchantRequest(_Request):
    """Input for ``resolve_merchant``."""

    raw_descriptor: str


class CheckDuplicateChargeRequest(_Request):
    """Input for ``check_duplicate_charge``."""

    account_id: str
    transaction_id: str
    date_tolerance_days: int = DEFAULT_DATE_TOLERANCE_DAYS
    amount_tolerance: Decimal = Decimal("0")


class GetAuditTraceRequest(BaseModel):
    """Input for ``get_audit_trace``."""

    model_config = ConfigDict(frozen=True)

    request_id: str


class SynthesizeInvestigationRequest(_Request):
    """Input for ``synthesize_investigation``."""

    account_id: str
    transaction_id: str
    investigation_findings: str = Field(
        description=(
            "JSON object collecting the earlier tool envelopes for this investigation "
            "(account summary, transaction details, merchant resolution, duplicate check, and "
            "optionally the audit trace)."
        ),
    )


class ConfirmUnrecognizedTransactionRequest(BaseModel):
    """Input for ``confirm_unrecognized_transaction``.

    Extra fields are forbidden so a caller cannot smuggle in its own evidence,
    reviewer identity, case status or approval flag. The only proof this tool
    accepts is the server-issued ``confirmation_token``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    investigation_id: str = Field(
        description="Correlation id of the investigation, returned by synthesize_investigation.",
    )
    account_id: str
    transaction_id: str
    confirmation_token: str = Field(
        description=(
            "One-time token issued by synthesize_investigation. Present it only after the "
            "policy's post_synthesis customer answer (merchant contact for a likely duplicate, "
            "or explicit non-recognition otherwise)."
        ),
    )
    idempotency_key: str = Field(
        description="Caller-chosen retry key. Repeating a confirmation with the same key returns the same case.",
    )


class ReviewDecisionRequest(BaseModel):
    """A back-office reviewer's decision on one pending dispute case.

    Used by the authenticated HTTP review application, not by an MCP tool.
    ``reviewer_id`` is deliberately absent: identity comes from the verified
    bearer token, never from the request body.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    expected_version: int = Field(
        description="Case version the reviewer loaded. A stale value is rejected instead of overwriting.",
    )
    decision: Literal["APPROVE", "REJECT"]
    reason_code: str = Field(description="Closed-vocabulary reason for this decision.")
    note: str | None = None
