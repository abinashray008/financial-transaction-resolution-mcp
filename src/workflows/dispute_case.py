"""LangGraph human-in-the-loop workflow for internal dispute-case review.

The case and its immutable evidence snapshot are written before this graph
pauses. The interrupt holds a back-office review slot; resuming records the
authenticated decision against the existing row. Customer names never enter
graph state.

Paused threads are stored in a SQLite checkpointer so a process restart does
not drop ``PENDING_REVIEW`` cases. Production should use PostgreSQL.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, NotRequired, TypedDict, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from ..domain.enums import DisputeCaseStatus, ReviewDecision, ReviewReasonCode
from ..domain.exceptions import (
    DisputeCaseNotFoundError,
    DisputeNotAwaitingReviewError,
    DisputeWorkflowNotFoundError,
    InvalidInputError,
)
from ..domain.models import DisputeCase
from ..observability.tracing import TracingService, track_workflow, update_workflow_span
from ..repositories.disputes import DisputeRepository
from .checkpointer import build_sqlite_checkpointer

_REVIEW_MESSAGE = (
    "An authenticated back-office reviewer must approve or reject this internal case. "
    "Nothing has been submitted to an issuer or card network."
)


class DisputeWorkflowState(TypedDict):
    """Checkpointed graph state. Dates and amounts are strings so they serialize."""

    case_id: str
    investigation_id: str
    account_id: str
    transaction_id: str
    evidence_hash: str
    version: int
    status: str
    reason_code: NotRequired[str]
    decision: NotRequired[str]
    review_reason_code: NotRequired[str]
    review_note: NotRequired[str]
    reviewer_id: NotRequired[str]


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _thread_config(case_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": case_id}}


def _interrupt_payload(values: DisputeWorkflowState) -> dict[str, Any]:
    return {
        "message": _REVIEW_MESSAGE,
        "case_id": values["case_id"],
        "investigation_id": values["investigation_id"],
        "account_id": values["account_id"],
        "transaction_id": values["transaction_id"],
        "evidence_hash": values.get("evidence_hash", ""),
        "version": values.get("version", 1),
        "status": values.get("status", DisputeCaseStatus.PENDING_REVIEW.value),
    }


class DisputeWorkflowRunner:
    """Pauses a persisted PENDING_REVIEW case and resumes it after review."""

    def __init__(
        self,
        *,
        disputes: DisputeRepository,
        checkpointer: BaseCheckpointSaver[str] | None = None,
        clock: Callable[[], datetime] = _utc_now,
        tracing: TracingService | None = None,
    ) -> None:
        self._disputes = disputes
        self._clock = clock
        compiled = self._compile(checkpointer or build_sqlite_checkpointer(":memory:"))
        self._graph = tracing.wrap_langgraph(compiled) if tracing is not None else compiled

    @track_workflow("dispute_workflow.pause_for_review")
    def pause_for_review(self, case: DisputeCase) -> None:
        """Checkpoint the persisted case and pause for back-office review."""
        started = time.perf_counter()
        config = _thread_config(case.case_id)
        snapshot = self._graph.get_state(config)
        if snapshot.interrupts:
            _record_workflow_span(
                request_id=case.investigation_id,
                account_id=case.account_id,
                status=case.status.value,
                started=started,
            )
            return
        status = str((snapshot.values or {}).get("status") or "")
        if status in {DisputeCaseStatus.APPROVED.value, DisputeCaseStatus.REJECTED.value}:
            return
        result = self._graph.invoke(
            {
                "case_id": case.case_id,
                "investigation_id": case.investigation_id,
                "account_id": case.account_id,
                "transaction_id": case.transaction_id,
                "evidence_hash": case.evidence_hash,
                "version": case.version,
                "status": case.status.value,
                "reason_code": case.reason_code.value,
            },
            config,
        )
        if not result.get("__interrupt__"):
            raise DisputeNotAwaitingReviewError(
                "The dispute workflow did not pause for back-office review.",
            )
        _record_workflow_span(
            request_id=case.investigation_id,
            account_id=case.account_id,
            status=DisputeCaseStatus.PENDING_REVIEW.value,
            started=started,
        )

    def get_pending(self, case_id: str) -> DisputeWorkflowState:
        """Return checkpointed state for a case that is waiting on review."""
        config = _thread_config(case_id)
        snapshot = self._graph.get_state(config)
        if not snapshot.values:
            raise DisputeWorkflowNotFoundError(
                "No dispute case is awaiting review for this case_id.",
            )
        if not snapshot.interrupts:
            raise DisputeNotAwaitingReviewError(
                "The dispute workflow is not waiting for a human decision.",
            )
        return cast(DisputeWorkflowState, snapshot.values)

    @track_workflow("dispute_workflow.resume_review")
    def resume_review(
        self,
        *,
        case_id: str,
        decision: ReviewDecision,
        reason_code: ReviewReasonCode,
        note: str | None,
        reviewer_id: str,
        expected_version: int,
    ) -> None:
        """Resume a paused workflow after the case row has been updated."""
        started = time.perf_counter()
        config = _thread_config(case_id)
        snapshot = self._graph.get_state(config)
        if not snapshot.values:
            raise DisputeWorkflowNotFoundError(
                "No dispute case is awaiting review for this case_id.",
            )
        if not snapshot.interrupts:
            raise DisputeNotAwaitingReviewError(
                "The dispute workflow is not waiting for a human decision.",
            )
        self._graph.invoke(
            Command(
                resume={
                    "decision": decision.value,
                    "reason_code": reason_code.value,
                    "note": note or "",
                    "reviewer_id": reviewer_id,
                    "expected_version": expected_version,
                }
            ),
            config,
        )
        values = self._graph.get_state(config).values
        _record_workflow_span(
            request_id=str(values.get("investigation_id") or case_id),
            account_id=str(values.get("account_id") or ""),
            status=str(values.get("status") or ""),
            started=started,
        )

    def _compile(self, checkpointer: BaseCheckpointSaver[str]) -> Any:
        disputes = self._disputes

        def persist_pending(state: DisputeWorkflowState) -> dict[str, Any]:
            case = disputes.get(state["case_id"])
            if case is None:
                raise DisputeCaseNotFoundError("No dispute case exists for this case_id.")
            return {
                "case_id": case.case_id,
                "investigation_id": case.investigation_id,
                "account_id": case.account_id,
                "transaction_id": case.transaction_id,
                "evidence_hash": case.evidence_hash,
                "version": case.version,
                "status": case.status.value,
                "reason_code": case.reason_code.value,
            }

        def await_human_review(state: DisputeWorkflowState) -> dict[str, Any]:
            decision = interrupt(_interrupt_payload(state))
            if not isinstance(decision, dict):
                raise InvalidInputError("The human decision must be an object with decision APPROVE or REJECT.")
            raw_decision = decision.get("decision")
            try:
                parsed = ReviewDecision(str(raw_decision or "").strip().upper())
            except ValueError as error:
                raise InvalidInputError("decision must be 'APPROVE' or 'REJECT'.") from error
            reason = decision.get("reason_code", "")
            note = decision.get("note", "") or ""
            reviewer_id = decision.get("reviewer_id", "")
            if not isinstance(reason, str) or not isinstance(note, str) or not isinstance(reviewer_id, str):
                raise InvalidInputError("reason_code, note and reviewer identity must be strings.")
            return {
                "decision": parsed.value,
                "review_reason_code": reason.strip(),
                "review_note": note.strip(),
                "reviewer_id": reviewer_id.strip(),
                "status": parsed.resulting_status.value,
            }

        def apply_decision(state: DisputeWorkflowState) -> dict[str, Any]:
            case = disputes.get(state["case_id"])
            if case is None:
                raise DisputeCaseNotFoundError("No dispute case exists for this case_id.")
            return {
                "status": case.status.value,
                "version": case.version,
            }

        builder = StateGraph(DisputeWorkflowState)
        builder.add_node("persist_pending", persist_pending)
        builder.add_node("await_human_review", await_human_review)
        builder.add_node("apply_decision", apply_decision)
        builder.add_edge(START, "persist_pending")
        builder.add_edge("persist_pending", "await_human_review")
        builder.add_edge("await_human_review", "apply_decision")
        builder.add_edge("apply_decision", END)
        return builder.compile(checkpointer=checkpointer)


def _record_workflow_span(
    *,
    request_id: str,
    account_id: str,
    status: str,
    started: float,
) -> None:
    update_workflow_span(
        request_id=request_id,
        account_id=account_id,
        status=status,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
