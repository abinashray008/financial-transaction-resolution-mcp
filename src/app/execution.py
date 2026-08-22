"""The single place where tool calls are timed, audited and error-mapped.

Handlers stay thin because everything cross-cutting happens here: correlation
ids, duration measurement, translation of domain errors into the response
envelope, and the guarantee that an unexpected exception never reaches the
client as anything but a generic internal error.
"""

import logging
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from ..audit.service import AuditService
from ..contracts.common import ToolResponseBase
from ..domain.enums import AuditOutcome
from ..domain.exceptions import DataStoreUnavailableError, DomainError, ErrorCode
from ..observability.tracing import TracingService, build_tracing_service
from .validators import validate_request_id

logger = logging.getLogger(__name__)

_GENERIC_INTERNAL_MESSAGE = "The request could not be completed. Contact the server operator if this persists."


def execute_tool[R: ToolResponseBase](
    *,
    response_type: type[R],
    tool_name: str,
    audit: AuditService,
    operation: Callable[[], BaseModel],
    request_id: str | None = None,
    account_id: str | None = None,
    tracing: TracingService | None = None,
) -> R:
    """Run one tool operation, audit it, and wrap the outcome in an envelope."""
    started = time.perf_counter()
    correlation_id = audit.new_request_id()
    body: dict[str, Any]
    outcome: str
    tracer = tracing or build_tracing_service()

    try:
        if request_id is not None:
            correlation_id = validate_request_id(request_id)
    except DomainError as error:
        duration_ms = int((time.perf_counter() - started) * 1000)
        body = _error_body(correlation_id, error.code, error.safe_message)
        _record_audit(
            audit,
            tool_name=tool_name,
            request_id=correlation_id,
            account_id=account_id,
            outcome=error.code.value,
            duration_ms=duration_ms,
        )
        return response_type.model_validate(body)

    with tracer.tool_span(tool_name=tool_name, request_id=correlation_id, account_id=account_id) as span:
        try:
            body = {"status": "ok", "request_id": correlation_id, "data": operation()}
            outcome = AuditOutcome.SUCCESS.value
        except DomainError as error:
            body = _error_body(correlation_id, error.code, error.safe_message)
            outcome = error.code.value
        except SQLAlchemyError:
            # The real reason is logged to stderr only; it may name tables or files.
            logger.exception("Data access failed in %s", tool_name)
            fallback = DataStoreUnavailableError()
            body = _error_body(correlation_id, fallback.code, fallback.safe_message)
            outcome = fallback.code.value
        except Exception:
            logger.exception("Unhandled failure in %s", tool_name)
            body = _error_body(correlation_id, ErrorCode.INTERNAL_ERROR, _GENERIC_INTERNAL_MESSAGE)
            outcome = ErrorCode.INTERNAL_ERROR.value

        duration_ms = int((time.perf_counter() - started) * 1000)
        span.outcome = outcome
        span.status = str(body["status"])
        span.duration_ms = duration_ms
        _record_audit(
            audit,
            tool_name=tool_name,
            request_id=correlation_id,
            account_id=account_id,
            outcome=outcome,
            duration_ms=duration_ms,
        )
    return response_type.model_validate(body)


def _error_body(request_id: str, code: ErrorCode, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "request_id": request_id,
        "error": {"code": code, "message": message},
    }


def _record_audit(
    audit: AuditService,
    *,
    tool_name: str,
    request_id: str,
    account_id: str | None,
    outcome: str,
    duration_ms: int,
) -> None:
    """Audit failures must never turn a successful call into a failed one."""
    try:
        audit.record(
            tool_name=tool_name,
            request_id=request_id,
            account_id=account_id,
            outcome=outcome,
            duration_ms=duration_ms,
        )
    except Exception:
        logger.exception("Could not record audit event for %s", tool_name)
