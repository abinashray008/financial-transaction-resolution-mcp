"""Handler for ``propose_dispute_case``.

Starts the LangGraph dispute workflow and pauses at the human-approval
interrupt. No ``dispute_cases`` row is written here.
"""

from ..app.container import Container
from ..app.execution import execute_tool
from ..app.presenters import to_dispute_proposal
from ..app.validators import (
    validate_account_id,
    validate_investigation_findings,
    validate_synthesis_summary,
    validate_transaction_id,
)
from ..contracts.requests import ProposeDisputeCaseRequest
from ..contracts.responses import DisputeProposalData, DisputeProposalResponse

TOOL_NAME = "propose_dispute_case"


def propose_dispute_case(
    container: Container,
    request: ProposeDisputeCaseRequest,
) -> DisputeProposalResponse:
    """Pause the dispute workflow until a human approves or declines."""
    resolved_request_id = request.request_id or container.audit.new_request_id()

    def operation() -> DisputeProposalData:
        account_id = validate_account_id(request.account_id)
        transaction_id = validate_transaction_id(request.transaction_id)
        validate_investigation_findings(request.investigation_findings)
        synthesis_summary = validate_synthesis_summary(request.synthesis_summary)
        proposal = container.dispute_workflow.propose(
            account_id=account_id,
            transaction_id=transaction_id,
            request_id=resolved_request_id,
            synthesis_summary=synthesis_summary,
        )
        return to_dispute_proposal(proposal)

    return execute_tool(
        response_type=DisputeProposalResponse,
        tool_name=TOOL_NAME,
        audit=container.audit,
        tracing=container.tracing,
        operation=operation,
        request_id=resolved_request_id,
        account_id=request.account_id,
    )
