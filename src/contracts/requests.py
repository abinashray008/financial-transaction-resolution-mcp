"""Structured tool inputs.

The MCP layer exposes flat arguments so hosts get a readable JSON Schema; the
routers then assemble these contracts, which are what the handlers actually
consume. Semantic validation (ranges, identifier shapes) happens deeper, in
the domain criteria and the input validators, so that it is testable without
an MCP client.
"""

from datetime import date
from decimal import Decimal

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
