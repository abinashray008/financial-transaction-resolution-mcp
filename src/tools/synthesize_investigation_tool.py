"""Handler for ``synthesize_investigation``.

Takes the earlier tool envelopes and asks Gemini to produce a typed
``GeminiSynthesisResult``. Analysis stays deterministic; only the final narrative
uses the model.

A policy document inside findings is dropped. If findings name a
``selected_policy_uri`` this server serves, that policy is loaded here and
passed to Gemini as trusted context.
"""

import json

from ..app.container import Container
from ..app.execution import execute_tool
from ..app.validators import (
    validate_account_id,
    validate_investigation_findings,
    validate_transaction_id,
)
from ..config.settings import settings
from ..contracts.requests import SynthesizeInvestigationRequest
from ..contracts.responses import GeminiSynthesisResult, SynthesisData, SynthesisResponse
from ..domain.exceptions import SynthesisUnavailableError
from ..llm.gemini_client import GeminiSynthesisClient
from ..resources.policies import drop_caller_policy_document, trusted_policy_json

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
        parsed = json.loads(findings)
        untrusted_findings = json.dumps(drop_caller_policy_document(parsed), ensure_ascii=False)
        policy = trusted_policy_json(parsed)

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

        result: GeminiSynthesisResult = client.synthesize(
            account_id=account_id,
            transaction_id=transaction_id,
            investigation_findings=untrusted_findings,
            trusted_policy=policy,
        )
        return SynthesisData(
            model_name=settings.gemini_model,
            customer_response=result.customer_response,
            recommended_action=result.recommended_action,
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
