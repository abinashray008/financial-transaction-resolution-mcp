"""Handler for ``get_audit_trace``."""

from ..app.container import Container
from ..app.execution import execute_tool
from ..app.presenters import to_audit_event_view
from ..app.validators import validate_request_id
from ..contracts.requests import GetAuditTraceRequest
from ..contracts.responses import AuditTraceData, AuditTraceResponse

TOOL_NAME = "get_audit_trace"


def get_audit_trace(container: Container, request: GetAuditTraceRequest) -> AuditTraceResponse:
    """Return the sanitized audit events recorded under a correlation id."""

    def operation() -> AuditTraceData:
        traced_request_id = validate_request_id(request.request_id)
        events = container.audit.trace(traced_request_id)
        return AuditTraceData(
            request_id=traced_request_id,
            event_count=len(events),
            events=[to_audit_event_view(event) for event in events],
        )

    # This call is audited under its own correlation id so that reading a trace
    # never appends to the trace being read.
    return execute_tool(
        response_type=AuditTraceResponse,
        tool_name=TOOL_NAME,
        audit=container.audit,
        tracing=container.tracing,
        operation=operation,
    )
