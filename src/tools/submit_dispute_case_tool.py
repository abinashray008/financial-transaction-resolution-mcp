"""Handler for ``submit_dispute_case``.

Resumes the paused LangGraph workflow only after a minted, unused
``approval_id`` is verified. A boolean ``approved`` flag is not accepted.
"""

from ..app.container import Container
from ..app.execution import execute_tool
from ..app.presenters import to_dispute_decision
from ..app.validators import validate_approval_id, validate_request_id
from ..contracts.requests import SubmitDisputeCaseRequest
from ..contracts.responses import DisputeDecisionData, DisputeDecisionResponse

TOOL_NAME = "submit_dispute_case"


def submit_dispute_case(
    container: Container,
    request: SubmitDisputeCaseRequest,
) -> DisputeDecisionResponse:
    """Register a synthetic dispute case only after a verified approval record."""

    def operation() -> DisputeDecisionData:
        request_id = validate_request_id(request.request_id)
        approval_id = validate_approval_id(request.approval_id)
        proposal = container.dispute_workflow.get_pending(request_id)
        approval = container.approval_service.consume(
            approval_id=approval_id,
            request_id=request_id,
            expected_draft_hash=proposal.draft_hash,
        )
        decision = container.dispute_workflow.decide(
            request_id=request_id,
            approved=approval.is_approved,
            decision_note=approval.decision_note,
            approval_id=approval.approval_id,
        )
        return to_dispute_decision(decision)

    return execute_tool(
        response_type=DisputeDecisionResponse,
        tool_name=TOOL_NAME,
        audit=container.audit,
        tracing=container.tracing,
        operation=operation,
        request_id=request.request_id,
        account_id=None,
    )
