"""Handler for ``submit_dispute_decision``.

Resumes the paused LangGraph workflow. A ``dispute_cases`` row is written
only when the human sets ``approved`` to true.
"""

from ..app.container import Container
from ..app.execution import execute_tool
from ..app.presenters import to_dispute_decision
from ..app.validators import (
    validate_account_id,
    validate_decision_note,
    validate_request_id,
    validate_transaction_id,
)
from ..contracts.requests import SubmitDisputeDecisionRequest
from ..contracts.responses import DisputeDecisionData, DisputeDecisionResponse
from ..domain.exceptions import InvalidInputError

TOOL_NAME = "submit_dispute_decision"


def submit_dispute_decision(
    container: Container,
    request: SubmitDisputeDecisionRequest,
) -> DisputeDecisionResponse:
    """Apply the human decision: register a case on approve, write nothing on decline."""

    def operation() -> DisputeDecisionData:
        if not request.request_id:
            raise InvalidInputError(
                "request_id is required so the paused dispute workflow can be resumed.",
            )
        account_id = validate_account_id(request.account_id)
        transaction_id = validate_transaction_id(request.transaction_id)
        request_id = validate_request_id(request.request_id)
        decision_note = validate_decision_note(request.decision_note)
        decision = container.dispute_workflow.decide(
            account_id=account_id,
            transaction_id=transaction_id,
            request_id=request_id,
            approved=request.approved,
            decision_note=decision_note,
        )
        return to_dispute_decision(decision)

    return execute_tool(
        response_type=DisputeDecisionResponse,
        tool_name=TOOL_NAME,
        audit=container.audit,
        tracing=container.tracing,
        operation=operation,
        request_id=request.request_id,
        account_id=request.account_id,
    )
