"""Handler for ``search_transactions``."""

from ..app.container import Container
from ..app.execution import execute_tool
from ..app.presenters import to_transaction_summary
from ..app.validators import validate_account_id, validate_merchant_query
from ..contracts.requests import SearchTransactionsRequest
from ..contracts.responses import AppliedFilters, TransactionSearchData, TransactionSearchResponse
from ..domain.criteria import TransactionSearchCriteria
from ..domain.exceptions import AccountNotFoundError
from ..security.masking import mask_account_id

TOOL_NAME = "search_transactions"


def search_transactions(container: Container, request: SearchTransactionsRequest) -> TransactionSearchResponse:
    """Search one account's transactions. Results can never span accounts."""

    def operation() -> TransactionSearchData:
        account_id = validate_account_id(request.account_id)
        criteria = TransactionSearchCriteria(
            account_id=account_id,
            start_date=request.start_date,
            end_date=request.end_date,
            merchant_query=validate_merchant_query(request.merchant_query),
            minimum_amount=request.minimum_amount,
            maximum_amount=request.maximum_amount,
            status=request.status,
            limit=request.limit,
        )
        if not container.accounts.exists(account_id):
            raise AccountNotFoundError("No account exists for the supplied account_id.")

        records = container.transactions.search(criteria)
        return TransactionSearchData(
            masked_account_id=mask_account_id(account_id),
            applied_filters=AppliedFilters(
                start_date=criteria.start_date,
                end_date=criteria.end_date,
                merchant_query=criteria.merchant_query,
                minimum_amount=criteria.minimum_amount,
                maximum_amount=criteria.maximum_amount,
                status=criteria.status,
                limit=criteria.limit,
            ),
            returned_count=len(records),
            truncated=len(records) == criteria.limit,
            transactions=[to_transaction_summary(record) for record in records],
        )

    return execute_tool(
        response_type=TransactionSearchResponse,
        tool_name=TOOL_NAME,
        audit=container.audit,
        tracing=container.tracing,
        operation=operation,
        request_id=request.request_id,
        account_id=request.account_id,
    )
