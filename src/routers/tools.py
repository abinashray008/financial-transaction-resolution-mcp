"""MCP tool registration.

These functions only translate MCP arguments into request contracts and hand
them to a handler. No business logic and no SQL lives here.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..app.container import Container
from ..contracts.requests import (
    CheckDuplicateChargeRequest,
    ConfirmUnrecognizedTransactionRequest,
    GetAccountSummaryRequest,
    GetAuditTraceRequest,
    GetTransactionDetailsRequest,
    ResolveMerchantRequest,
    SearchTransactionsRequest,
    SynthesizeInvestigationRequest,
)
from ..contracts.responses import (
    AccountSummaryResponse,
    AuditTraceResponse,
    DisputeCaseCreatedResponse,
    DuplicateCheckResponse,
    MerchantResolutionResponse,
    SynthesisResponse,
    TransactionDetailsResponse,
    TransactionSearchResponse,
)
from ..domain.criteria import (
    DEFAULT_DATE_TOLERANCE_DAYS,
    DEFAULT_LIMIT,
    MAX_DATE_TOLERANCE_DAYS,
    MAX_LIMIT,
)
from ..domain.enums import TransactionStatus
from ..tools.check_duplicate_charge_tool import check_duplicate_charge as check_duplicate_charge_handler
from ..tools.confirm_unrecognized_transaction_tool import (
    confirm_unrecognized_transaction as confirm_unrecognized_transaction_handler,
)
from ..tools.get_account_summary_tool import get_account_summary as get_account_summary_handler
from ..tools.get_audit_trace_tool import get_audit_trace as get_audit_trace_handler
from ..tools.get_transaction_details_tool import get_transaction_details as get_transaction_details_handler
from ..tools.resolve_merchant_tool import resolve_merchant as resolve_merchant_handler
from ..tools.search_transactions_tool import search_transactions as search_transactions_handler
from ..tools.synthesize_investigation_tool import (
    synthesize_investigation as synthesize_investigation_handler,
)

# Evidence tools read only from the local synthetic dataset. Synthesis calls Gemini.
# Confirmation writes an internal PENDING_REVIEW case after a server-issued token.
READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
SYNTHESIS = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
DISPUTE_CONFIRM = ToolAnnotations(
    readOnlyHint=False,
    idempotentHint=True,
    destructiveHint=False,
    openWorldHint=False,
)

AccountId = Annotated[str, Field(description="Account identifier, for example 'ACCT-0001'.")]
TransactionId = Annotated[str, Field(description="Transaction identifier, for example 'TXN-0001'.")]
RequestId = Annotated[
    str | None,
    Field(description="Optional correlation id reused across an investigation. Generated when omitted."),
]


def register_mcp_tools(mcp: FastMCP, container: Container) -> None:
    """Register every tool with the server instance."""

    @mcp.tool(annotations=READ_ONLY)
    def get_account_summary(account_id: AccountId, request_id: RequestId = None) -> AccountSummaryResponse:
        """Get the minimum context for an account: type, status, open date, masked card and the
        account holder's state. The account identifier and card are returned masked, and the
        customer's name is never returned.
        """
        return get_account_summary_handler(
            container,
            GetAccountSummaryRequest(account_id=account_id, request_id=request_id),
        )

    @mcp.tool(annotations=READ_ONLY)
    def search_transactions(
        account_id: AccountId,
        start_date: Annotated[date | None, Field(description="Earliest transaction date, inclusive.")] = None,
        end_date: Annotated[date | None, Field(description="Latest transaction date, inclusive.")] = None,
        merchant_query: Annotated[
            str | None,
            Field(description="Case-insensitive text matched against merchant name and statement descriptor."),
        ] = None,
        minimum_amount: Annotated[Decimal | None, Field(description="Smallest amount to include.")] = None,
        maximum_amount: Annotated[Decimal | None, Field(description="Largest amount to include.")] = None,
        status: Annotated[TransactionStatus | None, Field(description="Restrict to one status.")] = None,
        limit: Annotated[
            int,
            Field(ge=1, le=MAX_LIMIT, description=f"Maximum rows to return, 1 to {MAX_LIMIT}."),
        ] = DEFAULT_LIMIT,
        request_id: RequestId = None,
    ) -> TransactionSearchResponse:
        """Search the transactions on one account. Every filter is applied inside that account, so a
        result can never include another account's activity. Invalid date or amount ranges are
        rejected with a structured error rather than being silently ignored.
        """
        return search_transactions_handler(
            container,
            SearchTransactionsRequest(
                account_id=account_id,
                start_date=start_date,
                end_date=end_date,
                merchant_query=merchant_query,
                minimum_amount=minimum_amount,
                maximum_amount=maximum_amount,
                status=status,
                limit=limit,
                request_id=request_id,
            ),
        )

    @mcp.tool(annotations=READ_ONLY)
    def get_transaction_details(
        account_id: AccountId,
        transaction_id: TransactionId,
        request_id: RequestId = None,
    ) -> TransactionDetailsResponse:
        """Get one transaction in full, including its statement descriptor and merchant. Both
        identifiers are required, and the transaction is returned only if it belongs to the supplied
        account. A transaction on another account is reported exactly like one that does not exist.
        """
        return get_transaction_details_handler(
            container,
            GetTransactionDetailsRequest(
                account_id=account_id,
                transaction_id=transaction_id,
                request_id=request_id,
            ),
        )

    @mcp.tool(annotations=READ_ONLY)
    def resolve_merchant(
        raw_descriptor: Annotated[
            str,
            Field(description="Statement descriptor exactly as it appears on the transaction."),
        ],
        request_id: RequestId = None,
    ) -> MerchantResolutionResponse:
        """Resolve an unfamiliar statement descriptor to a merchant. Matching is deterministic and
        rule-based: the descriptor is normalized, then scored against the merchant catalog. The
        response explains which rule matched and how confident it is.
        """
        return resolve_merchant_handler(
            container,
            ResolveMerchantRequest(raw_descriptor=raw_descriptor, request_id=request_id),
        )

    @mcp.tool(annotations=READ_ONLY)
    def check_duplicate_charge(
        account_id: AccountId,
        transaction_id: TransactionId,
        date_tolerance_days: Annotated[
            int,
            Field(
                ge=0,
                le=MAX_DATE_TOLERANCE_DAYS,
                description=f"How many days apart two charges may be, 0 to {MAX_DATE_TOLERANCE_DAYS}.",
            ),
        ] = DEFAULT_DATE_TOLERANCE_DAYS,
        amount_tolerance: Annotated[
            Decimal,
            Field(ge=0, description="How far apart two amounts may be. Zero means an exact amount match."),
        ] = Decimal("0"),
        request_id: RequestId = None,
    ) -> DuplicateCheckResponse:
        """Check whether a transaction looks like a duplicate of another charge on the same account.
        Returns a LOW, MEDIUM or HIGH confidence category with the rule-based reasons behind it.
        Recurring subscriptions and authorization holds that later post are recognised and downgraded,
        because they are expected repeats rather than duplicates.
        """
        return check_duplicate_charge_handler(
            container,
            CheckDuplicateChargeRequest(
                account_id=account_id,
                transaction_id=transaction_id,
                date_tolerance_days=date_tolerance_days,
                amount_tolerance=amount_tolerance,
                request_id=request_id,
            ),
        )

    @mcp.tool(annotations=READ_ONLY)
    def get_audit_trace(
        request_id: Annotated[str, Field(description="Correlation id returned by an earlier tool call.")],
    ) -> AuditTraceResponse:
        """Get the sanitized audit events recorded under a correlation id. Events carry the tool name,
        timestamp, masked account identifier, outcome and duration only. Tool arguments, customer
        names, merchant descriptors and transaction payloads are never logged.
        """
        return get_audit_trace_handler(container, GetAuditTraceRequest(request_id=request_id))

    @mcp.tool(annotations=SYNTHESIS)
    def synthesize_investigation(
        account_id: AccountId,
        transaction_id: TransactionId,
        investigation_findings: Annotated[
            str,
            Field(
                description=(
                    "JSON object collecting the earlier tool envelopes for this investigation "
                    "(account summary, transaction details, merchant resolution, duplicate check, "
                    "and optionally the audit trace)."
                ),
            ),
        ],
        request_id: RequestId = None,
    ) -> SynthesisResponse:
        """Synthesize the gathered investigation tool responses into a typed customer-facing reply
        using Gemini. Call this only after the read-only evidence tools have been used. When the
        charge is eligible, the response includes a one-time confirmation_token. Does not file
        disputes or change any account data.
        """
        return synthesize_investigation_handler(
            container,
            SynthesizeInvestigationRequest(
                account_id=account_id,
                transaction_id=transaction_id,
                investigation_findings=investigation_findings,
                request_id=request_id,
            ),
        )

    @mcp.tool(annotations=DISPUTE_CONFIRM)
    def confirm_unrecognized_transaction(
        investigation_id: Annotated[
            str,
            Field(description="Correlation id of the investigation, returned by synthesize_investigation."),
        ],
        account_id: AccountId,
        transaction_id: TransactionId,
        confirmation_token: Annotated[
            str,
            Field(
                description=(
                    "One-time token issued by synthesize_investigation. Present it only after the "
                    "policy's post_synthesis customer answer (merchant contact for a likely duplicate, "
                    "or explicit non-recognition otherwise)."
                ),
            ),
        ],
        idempotency_key: Annotated[
            str,
            Field(
                description=(
                    "Caller-chosen retry key. Repeating a confirmation with the same key returns the same case."
                ),
            ),
        ],
    ) -> DisputeCaseCreatedResponse:
        """Create an internal PENDING_REVIEW dispute case after the policy's post_synthesis
        customer answer. The server verifies confirmation_token; it does not accept an LLM
        approval flag. Returns the case_id and a 10-business-day investigation message. The case is
        queued for authenticated back-office review and is not submitted to an issuer.
        """
        return confirm_unrecognized_transaction_handler(
            container,
            ConfirmUnrecognizedTransactionRequest(
                investigation_id=investigation_id,
                account_id=account_id,
                transaction_id=transaction_id,
                confirmation_token=confirmation_token,
                idempotency_key=idempotency_key,
            ),
        )
