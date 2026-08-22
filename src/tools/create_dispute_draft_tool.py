"""Handler for ``create_dispute_draft``.

Builds a PENDING_REVIEW proposal from investigation findings. This does not
require approval and does not write a ``dispute_cases`` row.
"""

from ..app.container import Container
from ..app.execution import execute_tool
from ..app.presenters import to_dispute_draft
from ..app.validators import (
    validate_account_id,
    validate_investigation_findings,
    validate_synthesis_summary,
    validate_transaction_id,
)
from ..contracts.requests import CreateDisputeDraftRequest
from ..contracts.responses import DisputeDraftData, DisputeDraftResponse

TOOL_NAME = "create_dispute_draft"


def create_dispute_draft(
    container: Container,
    request: CreateDisputeDraftRequest,
) -> DisputeDraftResponse:
    """Create a reviewable dispute draft. Approval is required only to submit it."""
    resolved_request_id = request.request_id or container.audit.new_request_id()

    def operation() -> DisputeDraftData:
        account_id = validate_account_id(request.account_id)
        transaction_id = validate_transaction_id(request.transaction_id)
        findings = validate_investigation_findings(request.investigation_findings)
        synthesis_summary = validate_synthesis_summary(request.synthesis_summary)
        proposal = container.dispute_workflow.propose(
            account_id=account_id,
            transaction_id=transaction_id,
            request_id=resolved_request_id,
            synthesis_summary=synthesis_summary,
            investigation_findings=findings,
        )
        return to_dispute_draft(proposal)

    return execute_tool(
        response_type=DisputeDraftResponse,
        tool_name=TOOL_NAME,
        audit=container.audit,
        tracing=container.tracing,
        operation=operation,
        request_id=resolved_request_id,
        account_id=request.account_id,
    )
