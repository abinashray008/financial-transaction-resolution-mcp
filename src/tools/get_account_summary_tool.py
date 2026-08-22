"""Handler for ``get_account_summary``."""

from ..app.container import Container
from ..app.execution import execute_tool
from ..app.presenters import to_account_summary
from ..app.validators import validate_account_id
from ..contracts.requests import GetAccountSummaryRequest
from ..contracts.responses import AccountSummaryData, AccountSummaryResponse
from ..domain.exceptions import AccountNotFoundError

TOOL_NAME = "get_account_summary"


def get_account_summary(container: Container, request: GetAccountSummaryRequest) -> AccountSummaryResponse:
    """Return the minimum account context needed to start an investigation."""

    def operation() -> AccountSummaryData:
        account_id = validate_account_id(request.account_id)
        record = container.accounts.get_with_customer_state(account_id)
        if record is None:
            raise AccountNotFoundError("No account exists for the supplied account_id.")
        return to_account_summary(record)

    return execute_tool(
        response_type=AccountSummaryResponse,
        tool_name=TOOL_NAME,
        audit=container.audit,
        tracing=container.tracing,
        operation=operation,
        request_id=request.request_id,
        account_id=request.account_id,
    )
