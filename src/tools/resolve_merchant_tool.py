"""Handler for ``resolve_merchant``."""

from ..app.container import Container
from ..app.execution import execute_tool
from ..app.validators import validate_raw_descriptor
from ..contracts.requests import ResolveMerchantRequest
from ..contracts.responses import MerchantResolutionData, MerchantResolutionResponse

TOOL_NAME = "resolve_merchant"


def resolve_merchant(container: Container, request: ResolveMerchantRequest) -> MerchantResolutionResponse:
    """Resolve a statement descriptor to a merchant using fixed rules."""

    def operation() -> MerchantResolutionData:
        descriptor = validate_raw_descriptor(request.raw_descriptor)
        match = container.merchant_resolver.resolve(descriptor, container.merchants.list_all())
        merchant = match.merchant

        return MerchantResolutionData(
            raw_descriptor=descriptor,
            normalized_descriptor=match.normalized_descriptor,
            matched=merchant is not None,
            merchant_id=merchant.merchant_id if merchant else None,
            display_name=merchant.display_name if merchant else None,
            category=merchant.category if merchant else None,
            country=merchant.country if merchant else None,
            match_confidence=match.confidence,
            match_score=match.score,
            match_rule=match.rule,
            matched_pattern=match.matched_pattern,
            explanation=match.explanation,
        )

    return execute_tool(
        response_type=MerchantResolutionResponse,
        tool_name=TOOL_NAME,
        audit=container.audit,
        tracing=container.tracing,
        operation=operation,
        request_id=request.request_id,
    )
