"""Handler for ``synthesize_investigation``.

Takes the earlier tool envelopes and asks Gemini to produce a typed
``GeminiSynthesisResult``. Analysis stays deterministic; only the final narrative
uses the model.

When Gemini recommends customer confirmation and the charge is eligible, this
handler issues a short-lived one-time confirmation token. The model never mints
that token.
"""

import json

from ..app.container import Container
from ..app.execution import execute_tool
from ..app.presenters import to_confirmation_challenge
from ..app.validators import (
    validate_account_id,
    validate_investigation_findings,
    validate_transaction_id,
)
from ..config.settings import settings
from ..contracts.requests import SynthesizeInvestigationRequest
from ..contracts.responses import (
    ConfirmationChallengeData,
    GeminiSynthesisResult,
    SynthesisData,
    SynthesisResponse,
)
from ..domain.enums import AuditActorType, DisputeLifecycleEvent
from ..domain.exceptions import DisputeAlreadyExistsError, SynthesisUnavailableError
from ..llm.gemini_client import GeminiSynthesisClient
from ..resources.policies import drop_caller_policy_document, trusted_policy_json
from ..security.actor import current_host_actor

TOOL_NAME = "synthesize_investigation"
ELIGIBLE_CONFIRMATION_ACTION = "REQUEST_CUSTOMER_CONFIRMATION"


def synthesize_investigation(
    container: Container,
    request: SynthesizeInvestigationRequest,
) -> SynthesisResponse:
    """Synthesize gathered investigation findings into a customer-facing reply."""
    resolved_request_id = request.request_id or container.audit.new_request_id()
    actor_type, actor_id = current_host_actor()

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
        confirmation = _maybe_issue_confirmation(
            container,
            recommended_action=result.recommended_action,
            investigation_id=resolved_request_id,
            account_id=account_id,
            transaction_id=transaction_id,
            customer_response=result.customer_response,
            investigation_findings=untrusted_findings,
            actor_type=actor_type,
            actor_id=actor_id,
        )
        return SynthesisData(
            model_name=settings.gemini_model,
            customer_response=result.customer_response,
            recommended_action=result.recommended_action,
            investigation_id=resolved_request_id,
            confirmation=confirmation,
        )

    return execute_tool(
        response_type=SynthesisResponse,
        tool_name=TOOL_NAME,
        audit=container.audit,
        tracing=container.tracing,
        operation=operation,
        request_id=resolved_request_id,
        account_id=request.account_id,
    )


def _maybe_issue_confirmation(
    container: Container,
    *,
    recommended_action: str,
    investigation_id: str,
    account_id: str,
    transaction_id: str,
    customer_response: str,
    investigation_findings: str,
    actor_type: AuditActorType,
    actor_id: str,
) -> ConfirmationChallengeData | None:
    issued = None
    case_id = ""
    evidence_hash = None
    reason_code = None
    if recommended_action == ELIGIBLE_CONFIRMATION_ACTION:
        try:
            issued_confirmation = container.confirmations.issue(
                investigation_id=investigation_id,
                account_id=account_id,
                transaction_id=transaction_id,
                synthesis_summary=customer_response,
                investigation_findings=investigation_findings,
            )
        except DisputeAlreadyExistsError:
            issued_confirmation = None
        if issued_confirmation is not None:
            issued = to_confirmation_challenge(
                issued_confirmation.confirmation,
                confirmation_token=issued_confirmation.confirmation_token,
            )
            case_id = issued_confirmation.confirmation.case_id
            evidence_hash = issued_confirmation.confirmation.evidence_hash
            reason_code = issued_confirmation.confirmation.reason_code.value

    container.lifecycle.record(
        event_type=DisputeLifecycleEvent.INVESTIGATION_COMPLETED,
        case_id=case_id,
        investigation_id=investigation_id,
        correlation_id=investigation_id,
        actor_type=actor_type,
        actor_id=actor_id,
        previous_status=None,
        new_status=None,
        evidence_hash=evidence_hash,
        reason_code=reason_code,
    )
    if issued is not None:
        container.lifecycle.record(
            event_type=DisputeLifecycleEvent.CUSTOMER_CONFIRMATION_REQUESTED,
            case_id=case_id,
            investigation_id=investigation_id,
            correlation_id=investigation_id,
            actor_type=actor_type,
            actor_id=actor_id,
            previous_status=None,
            new_status=None,
            evidence_hash=evidence_hash,
            reason_code=reason_code,
        )
    return issued
