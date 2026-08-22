"""Handler for ``check_duplicate_charge``."""

from ..app.container import Container
from ..app.execution import execute_tool
from ..app.validators import validate_account_id, validate_transaction_id
from ..contracts.requests import CheckDuplicateChargeRequest
from ..contracts.responses import DuplicateCheckData, DuplicateCheckResponse
from ..domain.criteria import DuplicateCheckCriteria
from ..domain.exceptions import TransactionNotFoundError
from ..security.masking import mask_account_id

TOOL_NAME = "check_duplicate_charge"

_NOT_FOUND_MESSAGE = "No transaction with that transaction_id exists on the supplied account."


def check_duplicate_charge(container: Container, request: CheckDuplicateChargeRequest) -> DuplicateCheckResponse:
    """Check whether a transaction is likely a duplicate of another charge."""

    def operation() -> DuplicateCheckData:
        criteria = DuplicateCheckCriteria(
            account_id=validate_account_id(request.account_id),
            transaction_id=validate_transaction_id(request.transaction_id),
            date_tolerance_days=request.date_tolerance_days,
            amount_tolerance=request.amount_tolerance,
        )

        record = container.transactions.get_for_account(criteria.account_id, criteria.transaction_id)
        if record is None:
            raise TransactionNotFoundError(_NOT_FOUND_MESSAGE)

        candidates = container.transactions.find_duplicate_candidates(
            subject=record.transaction,
            date_tolerance_days=criteria.date_tolerance_days,
            amount_tolerance=criteria.amount_tolerance,
        )
        assessment = container.duplicates.assess(
            subject=record.transaction,
            candidates=candidates,
            date_tolerance_days=criteria.date_tolerance_days,
            amount_tolerance=criteria.amount_tolerance,
        )

        return DuplicateCheckData(
            masked_account_id=mask_account_id(criteria.account_id),
            transaction_id=criteria.transaction_id,
            duplicate_likely=assessment.duplicate_likely,
            confidence=assessment.confidence,
            candidate_transaction_ids=list(assessment.candidate_transaction_ids),
            reasons=list(assessment.reasons),
            date_tolerance_days=criteria.date_tolerance_days,
            amount_tolerance=criteria.amount_tolerance,
        )

    return execute_tool(
        response_type=DuplicateCheckResponse,
        tool_name=TOOL_NAME,
        audit=container.audit,
        tracing=container.tracing,
        operation=operation,
        request_id=request.request_id,
        account_id=request.account_id,
    )
