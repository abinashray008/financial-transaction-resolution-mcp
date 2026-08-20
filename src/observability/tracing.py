"""Opik-backed tracing for MCP tool calls and Gemini synthesis.

Spans record only sanitized fields: tool name, request_id, masked account id,
outcome, duration, and (for synthesis) model name plus token counts. Raw
descriptors, customer names and transaction payloads are never sent to Opik.

When Opik is not configured, every method is a no-op so tests and offline
evidence tools do not depend on the network.
"""

from __future__ import annotations

import atexit
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from ..config.settings import Settings, settings
from ..security.masking import mask_optional_account_id

logger = logging.getLogger(__name__)

_LLM_TOOL_NAME = "synthesize_investigation"
_configured = False
_current_span: ContextVar[_SpanState | None] = ContextVar("opik_tool_span", default=None)


def _env_disables_opik() -> bool:
    """Honor Opik's own kill switch so tests never export traces."""
    return os.environ.get("OPIK_TRACK_DISABLE", "").strip().lower() in {"1", "true", "yes"}


class TraceSink(Protocol):
    """Test double that records sanitized tool spans without calling Opik."""

    def record(self, event: ToolSpanEvent) -> None:
        """Store one completed tool span."""


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Prompt / completion token counts from a Gemini response."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ToolSpanEvent:
    """Sanitized observability payload for one MCP tool call."""

    tool_name: str
    request_id: str
    account_id_masked: str | None
    outcome: str
    status: str
    duration_ms: int
    model_name: str | None = None
    usage: TokenUsage | None = None


@dataclass(slots=True)
class _SpanState:
    """Mutable fields filled in after the tool operation finishes."""

    outcome: str = "INTERNAL_ERROR"
    status: str = "error"
    duration_ms: int = 0
    model_name: str | None = None
    usage: TokenUsage | None = None


class TracingService:
    """Records investigation traces. Safe to call when Opik is disabled."""

    def __init__(
        self,
        *,
        enabled: bool,
        project_name: str,
        sink: TraceSink | None = None,
    ) -> None:
        self._enabled = enabled
        self._project_name = project_name
        self._sink = sink

    @property
    def enabled(self) -> bool:
        """Whether Opik export is on (credentials plus not globally disabled)."""
        return self._enabled and not _env_disables_opik()

    @property
    def active(self) -> bool:
        """Whether spans will be recorded (Opik or an injected sink)."""
        return self.enabled or self._sink is not None

    def wrap_genai_client(self, client: Any) -> Any:
        """Wrap a ``google.genai.Client`` so Opik tracks LLM calls and cost."""
        if not self.enabled:
            return client
        try:
            from opik.integrations.genai import track_genai
        except Exception:
            logger.exception("Could not import Opik Gemini integration; LLM calls will not be traced")
            return client
        try:
            return track_genai(client, project_name=self._project_name)
        except TypeError:
            return track_genai(client)
        except Exception:
            logger.exception("Could not wrap the Gemini client with Opik; LLM calls will not be traced")
            return client

    def attach_llm_usage(self, *, model_name: str, usage: TokenUsage) -> None:
        """Attach Gemini token counts to the current tool span, if one is open."""
        state = _current_span.get()
        if state is None:
            return
        state.model_name = model_name
        state.usage = usage

    @contextmanager
    def tool_span(
        self,
        *,
        tool_name: str,
        request_id: str,
        account_id: str | None,
    ) -> Iterator[_SpanState]:
        """Open a span around one MCP tool call and record it when the call ends."""
        state = _SpanState()
        token = _current_span.set(state)
        account_id_masked = mask_optional_account_id(account_id)
        try:
            if self.enabled:
                with self._opik_span(
                    tool_name=tool_name,
                    request_id=request_id,
                    account_id_masked=account_id_masked,
                    state=state,
                ):
                    yield state
            else:
                yield state
        finally:
            event = ToolSpanEvent(
                tool_name=tool_name,
                request_id=request_id,
                account_id_masked=account_id_masked,
                outcome=state.outcome,
                status=state.status,
                duration_ms=state.duration_ms,
                model_name=state.model_name,
                usage=state.usage,
            )
            self._emit_sink(event)
            _current_span.reset(token)

    def _emit_sink(self, event: ToolSpanEvent) -> None:
        if self._sink is None:
            return
        try:
            self._sink.record(event)
        except Exception:
            logger.exception("Observability sink failed for %s", event.tool_name)

    @contextmanager
    def _opik_span(
        self,
        *,
        tool_name: str,
        request_id: str,
        account_id_masked: str | None,
        state: _SpanState,
    ) -> Iterator[None]:
        span_cm: Any = None
        span: Any = None
        try:
            import opik
            from opik import opik_context

            span_type: Literal["tool", "llm"] = "llm" if tool_name == _LLM_TOOL_NAME else "tool"
            span_cm = opik.start_as_current_span(
                name=tool_name,
                type=span_type,
                project_name=self._project_name,
                tags=["mcp", "investigation", tool_name],
                metadata=_span_metadata(
                    request_id=request_id,
                    account_id_masked=account_id_masked,
                    tool_name=tool_name,
                ),
            )
            span = span_cm.__enter__()
            span.input = {"tool_name": tool_name, "request_id": request_id}
            opik_context.update_current_trace(
                name="investigate_transaction",
                thread_id=request_id,
                tags=["mcp", "financial-transaction-resolution"],
                metadata={"request_id": request_id, "project": self._project_name},
            )
        except Exception:
            logger.exception("Opik could not open a span for %s", tool_name)
            span_cm = None
            span = None

        try:
            yield
        finally:
            if span is not None:
                try:
                    _apply_span_output(span, state)
                except Exception:
                    logger.exception("Opik could not attach output for %s", tool_name)
            if span_cm is not None:
                try:
                    span_cm.__exit__(None, None, None)
                except Exception:
                    logger.exception("Opik could not close the span for %s", tool_name)


def _apply_span_output(span: Any, state: _SpanState) -> None:
    output: dict[str, Any] = {
        "status": state.status,
        "outcome": state.outcome,
        "duration_ms": state.duration_ms,
    }
    if state.model_name:
        output["model_name"] = state.model_name
        span.provider = "google_ai"
        span.model = state.model_name
    if state.usage is not None:
        output["prompt_tokens"] = state.usage.prompt_tokens
        output["completion_tokens"] = state.usage.completion_tokens
        output["total_tokens"] = state.usage.total_tokens
        span.usage = {
            "prompt_tokens": state.usage.prompt_tokens or 0,
            "completion_tokens": state.usage.completion_tokens or 0,
            "total_tokens": state.usage.total_tokens or 0,
        }
    span.output = output


def _span_metadata(*, request_id: str, account_id_masked: str | None, tool_name: str) -> dict[str, str]:
    metadata = {"request_id": request_id, "tool_name": tool_name}
    if account_id_masked:
        metadata["account_id_masked"] = account_id_masked
    return metadata


def build_tracing_service(
    *,
    app_settings: Settings | None = None,
    sink: TraceSink | None = None,
) -> TracingService:
    """Build the tracing service used by the container."""
    resolved = app_settings or settings
    return TracingService(
        enabled=resolved.opik_tracing_enabled,
        project_name=resolved.opik_project_name,
        sink=sink,
    )


def configure_opik(app_settings: Settings | None = None) -> None:
    """Configure the Opik SDK once at process start. No-op when tracing is off."""
    global _configured
    resolved = app_settings or settings
    if _env_disables_opik() or not resolved.opik_tracing_enabled:
        return
    if _configured:
        return
    try:
        import opik
    except Exception:
        logger.exception("Opik is enabled but the package could not be imported")
        return

    try:
        kwargs: dict[str, Any] = {
            "project_name": resolved.opik_project_name,
            "force": True,
            "automatic_approvals": True,
        }
        if resolved.opik_use_local:
            kwargs["use_local"] = True
            if resolved.opik_url_override.strip():
                kwargs["url_override"] = resolved.opik_url_override.strip()
        else:
            if not resolved.opik_api_key.strip():
                logger.warning("Opik tracing is on but OPIK_API_KEY is empty; skipping configure")
                return
            kwargs["api_key"] = resolved.opik_api_key.strip()
            if resolved.opik_workspace.strip():
                kwargs["workspace"] = resolved.opik_workspace.strip()
            if resolved.opik_url_override.strip():
                kwargs["url_override"] = resolved.opik_url_override.strip()
        opik.configure(**kwargs)
        _configured = True
        atexit.register(_flush_opik)
        logger.info("Opik tracing enabled for project %s", resolved.opik_project_name)
    except Exception:
        logger.exception("Opik configure failed; agent traces will not be exported")


def _flush_opik() -> None:
    try:
        import opik

        client = opik.Opik()
        client.flush()
    except Exception:
        logger.exception("Opik flush failed")
