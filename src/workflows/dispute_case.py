"""LangGraph human-in-the-loop workflow for dispute-case registration.

The graph loads account-scoped evidence, pauses for an explicit human
approval, and only then writes a row to ``dispute_cases``. Declining leaves
the database unchanged. Customer names never enter graph state.

Paused threads are stored in a SQLite checkpointer so a process restart does
not drop ``PENDING_REVIEW`` drafts. Production should use PostgreSQL.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, NotRequired, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from ..domain.enums import DisputeCaseStatus, DisputeReasonCode, DisputeWorkflowStatus
from ..domain.exceptions import (
    AccountNotFoundError,
    DisputeAlreadyExistsError,
    DisputeNotAwaitingApprovalError,
    DisputeWorkflowNotFoundError,
    InvalidInputError,
    TransactionNotFoundError,
)
from ..domain.models import DisputeCase, DisputeDecision, DisputeProposal
from ..domain.money import from_minor_units, to_minor_units
from ..domain.services.dispute_draft import build_dispute_draft
from ..observability.tracing import TracingService, track_workflow, update_workflow_span
from ..repositories.accounts import AccountRepository
from ..repositories.disputes import DisputeRepository
from ..repositories.transactions import TransactionRepository
from ..security.masking import mask_account_id
from .checkpointer import build_sqlite_checkpointer

_NOT_FOUND_MESSAGE = "No transaction with that transaction_id exists on the supplied account."
_APPROVAL_MESSAGE = (
    "A human reviewer must record a decision in the review application, which mints a "
    "one-time approval_id. submit_dispute_case accepts only request_id and approval_id; "
    "approved=true is not sufficient proof. This is a synthetic case file, not an issuer decision."
)
_MAX_REASON_LENGTH = 2000
_MAX_SYNTHESIS_IN_REASON = 1500


class DisputeWorkflowState(TypedDict):
    """Checkpointed graph state. Dates and amounts are strings so they serialize."""

    account_id: str
    transaction_id: str
    request_id: str
    synthesis_summary: str
    investigation_findings: str
    customer_id: NotRequired[str]
    merchant_display_name: NotRequired[str]
    amount: NotRequired[str]
    currency: NotRequired[str]
    transaction_date: NotRequired[str]
    reason: NotRequired[str]
    reason_code: NotRequired[str]
    verified_evidence: NotRequired[list[str]]
    missing_evidence: NotRequired[list[str]]
    applied_policy: NotRequired[str]
    proposed_action: NotRequired[str]
    draft_hash: NotRequired[str]
    approved: NotRequired[bool]
    decision_note: NotRequired[str]
    case_id: NotRequired[str]
    workflow_status: NotRequired[str]


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _case_id_factory() -> str:
    return f"DSP-{uuid.uuid4().hex[:8].upper()}"


def _thread_config(request_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": request_id}}


def build_proposed_reason(
    *,
    merchant_display_name: str,
    amount: str,
    currency: str,
    transaction_date: str,
    synthesis_summary: str,
) -> str:
    """Deterministic case reason from stored facts plus the synthesis narrative."""
    facts = f"Unrecognized charge at {merchant_display_name} for {amount} {currency} on {transaction_date}."
    summary = synthesis_summary.strip()
    if len(summary) > _MAX_SYNTHESIS_IN_REASON:
        summary = f"{summary[:_MAX_SYNTHESIS_IN_REASON]}…"
    reason = f"{facts} Synthesis: {summary}"
    if len(reason) > _MAX_REASON_LENGTH:
        return f"{reason[: _MAX_REASON_LENGTH - 1]}…"
    return reason


def _interrupt_payload(values: DisputeWorkflowState) -> dict[str, Any]:
    return {
        "message": _APPROVAL_MESSAGE,
        "account_id": values["account_id"],
        "transaction_id": values["transaction_id"],
        "merchant_display_name": values.get("merchant_display_name", ""),
        "amount": values.get("amount", ""),
        "currency": values.get("currency", ""),
        "transaction_date": values.get("transaction_date", ""),
        "reason": values.get("reason", ""),
        "reason_code": values.get("reason_code", ""),
        "verified_evidence": values.get("verified_evidence", []),
        "missing_evidence": values.get("missing_evidence", []),
        "applied_policy": values.get("applied_policy", ""),
        "proposed_action": values.get("proposed_action", ""),
        "draft_hash": values.get("draft_hash", ""),
        "status": DisputeWorkflowStatus.PENDING_REVIEW.value,
    }


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, list | tuple):
        return tuple(item for item in value if isinstance(item, str))
    return ()


def _reason_code_from_state(values: DisputeWorkflowState) -> DisputeReasonCode:
    raw = values.get("reason_code") or DisputeReasonCode.UNRECOGNIZED_TRANSACTION.value
    try:
        return DisputeReasonCode(raw)
    except ValueError:
        return DisputeReasonCode.UNRECOGNIZED_TRANSACTION


def _proposal_from_state(values: DisputeWorkflowState, request_id: str) -> DisputeProposal:
    return DisputeProposal(
        request_id=request_id,
        account_id=values["account_id"],
        transaction_id=values["transaction_id"],
        customer_id=values["customer_id"],
        merchant_display_name=values["merchant_display_name"],
        amount=Decimal(values["amount"]),
        currency=values["currency"],
        transaction_date=date.fromisoformat(values["transaction_date"]),
        reason=values["reason"],
        reason_code=_reason_code_from_state(values),
        verified_evidence=_string_tuple(values.get("verified_evidence")),
        missing_evidence=_string_tuple(values.get("missing_evidence")),
        applied_policy=str(values.get("applied_policy") or ""),
        proposed_action=str(values.get("proposed_action") or ""),
        draft_hash=str(values.get("draft_hash") or ""),
        message=_APPROVAL_MESSAGE,
    )


class DisputeWorkflowRunner:
    """Starts and resumes the LangGraph dispute-registration workflow."""

    def __init__(
        self,
        *,
        accounts: AccountRepository,
        transactions: TransactionRepository,
        disputes: DisputeRepository,
        checkpointer: BaseCheckpointSaver[str] | None = None,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], str] = _case_id_factory,
        tracing: TracingService | None = None,
    ) -> None:
        self._accounts = accounts
        self._transactions = transactions
        self._disputes = disputes
        self._clock = clock
        self._id_factory = id_factory
        compiled = self._compile(checkpointer or build_sqlite_checkpointer(":memory:"))
        self._graph = tracing.wrap_langgraph(compiled) if tracing is not None else compiled

    @track_workflow("dispute_workflow.propose")
    def propose(
        self,
        *,
        account_id: str,
        transaction_id: str,
        request_id: str,
        synthesis_summary: str,
        investigation_findings: str,
    ) -> DisputeProposal:
        """Build a PENDING_REVIEW draft and pause. Does not write a dispute case."""
        started = time.perf_counter()
        config = _thread_config(request_id)
        snapshot = self._graph.get_state(config)
        if snapshot.values:
            self._assert_same_subject(snapshot.values, account_id, transaction_id)
            if snapshot.interrupts:
                proposal = _proposal_from_state(snapshot.values, request_id)
                _record_workflow_span(
                    request_id=request_id,
                    account_id=account_id,
                    status=DisputeWorkflowStatus.PENDING_REVIEW.value,
                    started=started,
                )
                return proposal
            status = snapshot.values.get("workflow_status")
            if status == DisputeWorkflowStatus.REGISTERED.value or snapshot.values.get("case_id"):
                raise DisputeAlreadyExistsError(
                    "A dispute case is already registered for this account and transaction.",
                )

        result = self._graph.invoke(
            {
                "account_id": account_id,
                "transaction_id": transaction_id,
                "request_id": request_id,
                "synthesis_summary": synthesis_summary,
                "investigation_findings": investigation_findings,
            },
            config,
        )
        interrupts = result.get("__interrupt__")
        if not interrupts:
            raise DisputeNotAwaitingApprovalError(
                "The dispute workflow did not pause for human approval.",
            )
        values = self._graph.get_state(config).values
        proposal = _proposal_from_state(values, request_id)
        _record_workflow_span(
            request_id=request_id,
            account_id=account_id,
            status=DisputeWorkflowStatus.PENDING_REVIEW.value,
            started=started,
        )
        return proposal

    def get_pending(self, request_id: str) -> DisputeProposal:
        """Return the paused PENDING_REVIEW draft for ``request_id``."""
        config = _thread_config(request_id)
        snapshot = self._graph.get_state(config)
        if not snapshot.values:
            raise DisputeWorkflowNotFoundError(
                "No dispute proposal is awaiting approval for this request_id.",
            )
        if not snapshot.interrupts:
            raise DisputeNotAwaitingApprovalError(
                "The dispute workflow is not waiting for a human decision.",
            )
        return _proposal_from_state(snapshot.values, request_id)

    @track_workflow("dispute_workflow.decide")
    def decide(
        self,
        *,
        request_id: str,
        approved: bool,
        decision_note: str | None = None,
        approval_id: str,
    ) -> DisputeDecision:
        """Resume a paused workflow after a verified approval record."""
        started = time.perf_counter()
        config = _thread_config(request_id)
        snapshot = self._graph.get_state(config)
        if not snapshot.values:
            raise DisputeWorkflowNotFoundError(
                "No dispute proposal is awaiting approval for this request_id.",
            )
        if not snapshot.interrupts:
            raise DisputeNotAwaitingApprovalError(
                "The dispute workflow is not waiting for a human decision.",
            )

        result = self._graph.invoke(
            Command(resume={"approved": approved, "note": decision_note or ""}),
            config,
        )
        values = {**snapshot.values, **{key: value for key, value in result.items() if key != "__interrupt__"}}
        case_id = values.get("case_id") or None
        note = values.get("decision_note") or None
        workflow_status = str(values.get("workflow_status") or DisputeWorkflowStatus.DECLINED.value)
        _record_workflow_span(
            request_id=request_id,
            account_id=str(values.get("account_id") or ""),
            status=workflow_status,
            started=started,
        )
        return DisputeDecision(
            request_id=request_id,
            account_id=str(values["account_id"]),
            transaction_id=str(values["transaction_id"]),
            customer_id=values["customer_id"],
            workflow_status=workflow_status,
            case_id=case_id if case_id else None,
            reason=str(values.get("reason") or ""),
            decision_note=note if note else None,
            approval_id=approval_id,
        )

    @staticmethod
    def _assert_same_subject(values: dict[str, Any], account_id: str, transaction_id: str) -> None:
        stored_account = values.get("account_id")
        stored_transaction = values.get("transaction_id")
        if stored_account != account_id or stored_transaction != transaction_id:
            raise DisputeWorkflowNotFoundError(
                "No dispute proposal is awaiting approval for this request_id and account.",
            )

    def _compile(self, checkpointer: BaseCheckpointSaver[str]) -> Any:
        accounts = self._accounts
        transactions = self._transactions
        disputes = self._disputes
        clock = self._clock
        id_factory = self._id_factory

        def load_context(state: DisputeWorkflowState) -> dict[str, str]:
            record = accounts.get_with_customer_state(state["account_id"])
            if record is None:
                raise AccountNotFoundError("No account exists for the supplied account_id.")
            txn = transactions.get_for_account(state["account_id"], state["transaction_id"])
            if txn is None:
                raise TransactionNotFoundError(_NOT_FOUND_MESSAGE)
            existing = disputes.get_for_account(state["account_id"], state["transaction_id"])
            if existing is not None:
                raise DisputeAlreadyExistsError(
                    "A dispute case is already registered for this account and transaction.",
                )
            amount = str(txn.transaction.amount)
            return {
                "customer_id": record.account.customer_id,
                "merchant_display_name": txn.merchant.display_name,
                "amount": amount,
                "currency": txn.transaction.currency,
                "transaction_date": txn.transaction.transaction_date.isoformat(),
                "workflow_status": DisputeWorkflowStatus.PENDING_REVIEW.value,
            }

        def build_proposal(state: DisputeWorkflowState) -> dict[str, Any]:
            reason = build_proposed_reason(
                merchant_display_name=state["merchant_display_name"],
                amount=state["amount"],
                currency=state["currency"],
                transaction_date=state["transaction_date"],
                synthesis_summary=state["synthesis_summary"],
            )
            draft = build_dispute_draft(
                account_id=state["account_id"],
                masked_account_id=mask_account_id(state["account_id"]),
                transaction_id=state["transaction_id"],
                request_id=state["request_id"],
                merchant_display_name=state["merchant_display_name"],
                amount=state["amount"],
                currency=state["currency"],
                transaction_date=state["transaction_date"],
                synthesis_summary=state["synthesis_summary"],
                investigation_findings=state["investigation_findings"],
                proposed_reason=reason,
            )
            return {
                "reason": draft.reason,
                "reason_code": draft.reason_code.value,
                "verified_evidence": list(draft.verified_evidence),
                "missing_evidence": list(draft.missing_evidence),
                "applied_policy": draft.applied_policy,
                "proposed_action": draft.proposed_action,
                "draft_hash": draft.draft_hash,
                "workflow_status": DisputeWorkflowStatus.PENDING_REVIEW.value,
            }

        def await_human_approval(state: DisputeWorkflowState) -> dict[str, bool | str]:
            decision = interrupt(_interrupt_payload(state))
            if not isinstance(decision, dict):
                raise InvalidInputError("The human decision must be an object with approved true or false.")
            approved = decision.get("approved")
            if not isinstance(approved, bool):
                raise InvalidInputError("approved must be true or false.")
            note = decision.get("note", "")
            if note is None:
                note = ""
            if not isinstance(note, str):
                raise InvalidInputError("decision note must be a string.")
            return {"approved": approved, "decision_note": note.strip()}

        def persist_decision(state: DisputeWorkflowState) -> dict[str, str]:
            if not state.get("approved"):
                return {
                    "workflow_status": DisputeWorkflowStatus.DECLINED.value,
                    "case_id": "",
                }
            case = DisputeCase(
                case_id=id_factory(),
                customer_id=state["customer_id"],
                account_id=state["account_id"],
                transaction_id=state["transaction_id"],
                request_id=state["request_id"],
                reason=state["reason"],
                status=DisputeCaseStatus.REGISTERED,
                amount=from_minor_units(to_minor_units(Decimal(state["amount"]))),
                currency=state["currency"],
                merchant_display_name=state["merchant_display_name"],
                created_at=clock(),
            )
            disputes.insert(case)
            return {
                "workflow_status": DisputeWorkflowStatus.REGISTERED.value,
                "case_id": case.case_id,
            }

        builder = StateGraph(DisputeWorkflowState)
        builder.add_node("load_context", load_context)
        builder.add_node("build_proposal", build_proposal)
        builder.add_node("await_human_approval", await_human_approval)
        builder.add_node("persist_decision", persist_decision)
        builder.add_edge(START, "load_context")
        builder.add_edge("load_context", "build_proposal")
        builder.add_edge("build_proposal", "await_human_approval")
        builder.add_edge("await_human_approval", "persist_decision")
        builder.add_edge("persist_decision", END)
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
