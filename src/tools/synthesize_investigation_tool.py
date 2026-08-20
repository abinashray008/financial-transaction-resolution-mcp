"""Handler for ``synthesize_investigation``.

Takes the earlier tool envelopes and asks Gemini to produce a customer-facing
reply. Analysis stays deterministic; only the final narrative uses the model.
"""

from ..app.container import Container
from ..app.execution import execute_tool
from ..app.validators import (
    validate_account_id,
    validate_investigation_findings,
    validate_transaction_id,
)
from ..config.settings import settings
from ..contracts.requests import SynthesizeInvestigationRequest
from ..contracts.responses import SynthesisData, SynthesisResponse
from ..domain.exceptions import SynthesisUnavailableError
from ..llm.gemini_client import GeminiSynthesisClient

TOOL_NAME = "synthesize_investigation"


def synthesize_investigation(
    container: Container,
    request: SynthesizeInvestigationRequest,
) -> SynthesisResponse:
    """Synthesize gathered investigation findings into a customer-facing reply."""

    def operation() -> SynthesisData:
        account_id = validate_account_id(request.account_id)
        transaction_id = validate_transaction_id(request.transaction_id)
        findings = validate_investigation_findings(request.investigation_findings)

        client = container.synthesis
        if client is None:
            if not settings.gemini_api_key.strip():
                raise SynthesisUnavailableError(
                    "GEMINI_API_KEY is not configured. Set it in the environment or a local .env file.",
                )
            client = GeminiSynthesisClient(
                api_key=settings.gemini_api_key,
                model=settings.gemini_model,
                tracing=container.tracing,
            )

        customer_response = client.synthesize(
            account_id=account_id,
            transaction_id=transaction_id,
            investigation_findings=findings,
        )
        return SynthesisData(
            model_name=settings.gemini_model,
            customer_response=customer_response,
        )

    return execute_tool(
        response_type=SynthesisResponse,
        tool_name=TOOL_NAME,
        audit=container.audit,
        tracing=container.tracing,
        operation=operation,
        request_id=request.request_id,
        account_id=request.account_id,
    )
