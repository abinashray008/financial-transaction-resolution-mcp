"""Handler for ``get_transaction_details``."""

from ..app.container import Container
from ..app.execution import execute_tool
from ..app.presenters import to_merchant_data, to_transaction_summary
from ..app.validators import validate_account_id, validate_transaction_id
from ..contracts.requests import GetTransactionDetailsRequest
from ..contracts.responses import TransactionDetailsData, TransactionDetailsResponse
from ..domain.exceptions import TransactionNotFoundError
from ..security.masking import mask_account_id

TOOL_NAME = "get_transaction_details"

# One message for both "no such transaction" and "belongs to another account",
# so the response cannot be used to probe for transactions on other accounts.
_NOT_FOUND_MESSAGE = "No transaction with that transaction_id exists on the supplied account."


def get_transaction_details(
    container: Container,
    request: GetTransactionDetailsRequest,
) -> TransactionDetailsResponse:
    """Return one transaction, only if it belongs to the supplied account."""

    def operation() -> TransactionDetailsData:
        account_id = validate_account_id(request.account_id)
        transaction_id = validate_transaction_id(request.transaction_id)

        record = container.transactions.get_for_account(account_id, transaction_id)
        if record is None:
            raise TransactionNotFoundError(_NOT_FOUND_MESSAGE)

        return TransactionDetailsData(
            masked_account_id=mask_account_id(account_id),
            transaction=to_transaction_summary(record),
            merchant=to_merchant_data(record.merchant),
        )

    return execute_tool(
        response_type=TransactionDetailsResponse,
        tool_name=TOOL_NAME,
        audit=container.audit,
        tracing=container.tracing,
        operation=operation,
        request_id=request.request_id,
        account_id=request.account_id,
    )
