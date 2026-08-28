"""Handler for ``confirm_unrecognized_transaction``.

Validates the server-issued customer confirmation token, writes a
``PENDING_REVIEW`` case with an immutable evidence snapshot, then pauses the
LangGraph workflow for authenticated back-office review.
"""

from ..app.container import Container
from ..app.execution import execute_tool
from ..app.presenters import to_dispute_case_created
from ..app.validators import (
    validate_account_id,
    validate_confirmation_token,
    validate_idempotency_key,
    validate_request_id,
    validate_transaction_id,
)
from ..contracts.requests import ConfirmUnrecognizedTransactionRequest
from ..contracts.responses import DisputeCaseCreated, DisputeCaseCreatedResponse
from ..security.actor import current_host_actor

TOOL_NAME = "confirm_unrecognized_transaction"


def confirm_unrecognized_transaction(
    container: Container,
    request: ConfirmUnrecognizedTransactionRequest,
) -> DisputeCaseCreatedResponse:
    """Create an internal PENDING_REVIEW case after a verified customer confirmation."""
    investigation_id = validate_request_id(request.investigation_id)
    _, host_actor_id = current_host_actor()

    def operation() -> DisputeCaseCreated:
        account_id = validate_account_id(request.account_id)
        transaction_id = validate_transaction_id(request.transaction_id)
        confirmation_token = validate_confirmation_token(request.confirmation_token)
        idempotency_key = validate_idempotency_key(request.idempotency_key)
        case = container.cases.confirm_unrecognized(
            investigation_id=investigation_id,
            account_id=account_id,
            transaction_id=transaction_id,
            confirmation_token=confirmation_token,
            idempotency_key=idempotency_key,
            host_actor_id=host_actor_id,
            correlation_id=investigation_id,
        )
        return to_dispute_case_created(case)

    return execute_tool(
        response_type=DisputeCaseCreatedResponse,
        tool_name=TOOL_NAME,
        audit=container.audit,
        tracing=container.tracing,
        operation=operation,
        request_id=investigation_id,
        account_id=request.account_id,
    )
