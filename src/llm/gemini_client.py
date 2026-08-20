"""Gemini client used to turn investigation tool outputs into a customer reply.

Deterministic analysis stays in ``domain/``. This module is the only place that
calls a model, so tests can inject a fake client without touching Gemini.
"""

from __future__ import annotations

import logging
from typing import Protocol

from google import genai
from google.genai import types

from ..domain.exceptions import SynthesisUnavailableError
from ..observability.tracing import TokenUsage, TracingService

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTIONS = """You are a careful card-transaction investigation assistant working over a
fictional, synthetic dataset. You never file disputes, approve refunds, waive fees, or claim any
write action was taken.

The investigation_findings JSON includes a selected policy resource. You MUST apply that policy when
drafting the reply: follow its eligibility, required investigation steps, outcome guidance, and
prohibited_actions. Cite the policy by title or policy_id when explaining what applies.

Write a clear response for the end user that:
1. Addresses the customer's concern (from customer_concern when present) in plain language.
2. States which synthetic policy was applied and why it matches their concern.
3. Separates verified facts (from the tool payloads) from inferences (your interpretation).
4. Names every relevant transaction id and the investigation request_id when present.
5. Explains merchant resolution, duplicate findings, or fee rules using the tool evidence and the
   selected policy — do not invent scores, rates, or rules.
6. Lists what is still unknown and recommends exactly one concrete next investigative step, saying
   who would perform it, consistent with the policy.
7. Never claims a dispute was filed, submitted, approved, or resolved, and never waives a fee.
8. Never invents amounts, dates, merchants, or account details that are absent from the findings.
9. Reminds the reader briefly that the data and policies are synthetic/fictional when it helps set
   expectations.

If a tool returned status "error", say so with its error code and continue with what remains.
Keep the reply concise and satisfactory for a support-style conversation.
"""


class SynthesisClient(Protocol):
    """Anything that can turn investigation findings into customer-facing prose."""

    def synthesize(
        self,
        *,
        account_id: str,
        transaction_id: str,
        investigation_findings: str,
    ) -> str:
        """Return the synthesized customer response."""


class GeminiSynthesisClient:
    """Calls Gemini to synthesize a customer-facing investigation reply."""

    def __init__(self, *, api_key: str, model: str, tracing: TracingService | None = None) -> None:
        if not api_key.strip():
            raise SynthesisUnavailableError(
                "GEMINI_API_KEY is not configured. Set it in the environment or a local .env file.",
            )
        self._model = model
        self._tracing = tracing
        client = genai.Client(api_key=api_key.strip())
        self._client = tracing.wrap_genai_client(client) if tracing is not None else client

    def synthesize(
        self,
        *,
        account_id: str,
        transaction_id: str,
        investigation_findings: str,
    ) -> str:
        """Ask Gemini to synthesize the gathered tool payloads into one reply."""
        user_prompt = (
            f"Account under investigation: {account_id}\n"
            f"Transaction under investigation: {transaction_id}\n\n"
            f"Investigation findings from read-only MCP tools and the selected policy (JSON):\n"
            f"{investigation_findings}\n\n"
            "Apply the selected policy when answering the customer."
        )
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTIONS,
                    temperature=0.2,
                ),
            )
        except Exception as error:
            logger.exception("Gemini synthesis failed")
            raise SynthesisUnavailableError(
                "The synthesis model could not complete the request. Retry later or check the API key.",
            ) from error

        self._record_usage(response)
        text = (getattr(response, "text", None) or "").strip()
        if not text:
            raise SynthesisUnavailableError(
                "The synthesis model returned an empty response. Retry the investigation.",
            )
        return text

    def _record_usage(self, response: object) -> None:
        if self._tracing is None:
            return
        usage = _token_usage_from_response(response)
        if usage is None:
            return
        self._tracing.attach_llm_usage(model_name=self._model, usage=usage)


def _token_usage_from_response(response: object) -> TokenUsage | None:
    metadata = getattr(response, "usage_metadata", None)
    if metadata is None:
        return None
    prompt_tokens = getattr(metadata, "prompt_token_count", None)
    completion_tokens = getattr(metadata, "candidates_token_count", None)
    total_tokens = getattr(metadata, "total_token_count", None)
    if prompt_tokens is None and completion_tokens is None and total_tokens is None:
        return None
    return TokenUsage(
        prompt_tokens=_as_optional_int(prompt_tokens),
        completion_tokens=_as_optional_int(completion_tokens),
        total_tokens=_as_optional_int(total_tokens),
    )


def _as_optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value
