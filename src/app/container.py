"""Composition root.

Every dependency is assembled here and passed explicitly, so handlers and
services can be exercised in tests against an in-memory database without
starting an MCP client.
"""

from dataclasses import dataclass

from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy import Engine, inspect

from ..audit.lifecycle import DisputeLifecycleAuditService
from ..audit.service import AuditService
from ..config.settings import settings
from ..domain.services.duplicate_charge import DuplicateChargeService
from ..domain.services.merchant_resolver import MerchantResolverService
from ..llm.gemini_client import SynthesisClient
from ..observability.tracing import TracingService, build_tracing_service
from ..repositories.accounts import AccountRepository
from ..repositories.audit import AuditRepository
from ..repositories.confirmations import ConfirmationRepository
from ..repositories.dispute_audit import DisputeLifecycleAuditRepository
from ..repositories.disputes import DisputeRepository
from ..repositories.merchants import MerchantRepository
from ..repositories.schema import ensure_writable_schema
from ..repositories.session import SessionFactory, build_engine, build_session_factory
from ..repositories.transactions import TransactionRepository
from ..workflows.checkpointer import build_sqlite_checkpointer, checkpoint_path_for_engine
from ..workflows.dispute_case import DisputeWorkflowRunner
from .cases import CaseService
from .confirmations import ConfirmationService

_DATASET_TABLES = frozenset({"customers", "accounts", "merchants", "transactions"})


@dataclass(frozen=True, slots=True)
class Container:
    """Wired repositories and services."""

    engine: Engine
    session_factory: SessionFactory
    accounts: AccountRepository
    transactions: TransactionRepository
    merchants: MerchantRepository
    audit: AuditService
    lifecycle: DisputeLifecycleAuditService
    merchant_resolver: MerchantResolverService
    duplicates: DuplicateChargeService
    tracing: TracingService
    disputes: DisputeRepository
    confirmations: ConfirmationService
    dispute_workflow: DisputeWorkflowRunner
    cases: CaseService
    synthesis: SynthesisClient | None = None

    def dataset_ready(self) -> bool:
        """Whether the synthetic dataset has been generated."""
        return _DATASET_TABLES.issubset(set(inspect(self.engine).get_table_names()))


def build_container_from_engine(
    engine: Engine,
    *,
    synthesis: SynthesisClient | None = None,
    tracing: TracingService | None = None,
    checkpointer: BaseCheckpointSaver[str] | None = None,
    checkpoint_path: str | None = None,
) -> Container:
    """Assemble a container around an existing engine."""
    session_factory = build_session_factory(engine)
    ensure_writable_schema(engine)

    accounts = AccountRepository(session_factory)
    transactions = TransactionRepository(session_factory)
    disputes = DisputeRepository(session_factory)
    confirmation_repository = ConfirmationRepository(session_factory)
    lifecycle = DisputeLifecycleAuditService(DisputeLifecycleAuditRepository(session_factory))
    tracing_service = tracing or build_tracing_service()
    saver = checkpointer or build_sqlite_checkpointer(
        checkpoint_path if checkpoint_path is not None else checkpoint_path_for_engine(engine),
    )
    dispute_workflow = DisputeWorkflowRunner(
        disputes=disputes,
        checkpointer=saver,
        tracing=tracing_service,
    )
    confirmations = ConfirmationService(
        confirmations=confirmation_repository,
        accounts=accounts,
        transactions=transactions,
        disputes=disputes,
        ttl_seconds=settings.confirmation_ttl_seconds,
    )
    cases = CaseService(
        confirmations=confirmations,
        disputes=disputes,
        lifecycle=lifecycle,
        workflow=dispute_workflow,
    )
    return Container(
        engine=engine,
        session_factory=session_factory,
        accounts=accounts,
        transactions=transactions,
        merchants=MerchantRepository(session_factory),
        audit=AuditService(AuditRepository(session_factory)),
        lifecycle=lifecycle,
        merchant_resolver=MerchantResolverService(),
        duplicates=DuplicateChargeService(),
        tracing=tracing_service,
        disputes=disputes,
        confirmations=confirmations,
        dispute_workflow=dispute_workflow,
        cases=cases,
        synthesis=synthesis,
    )


def build_container(database_url: str | None = None) -> Container:
    """Assemble a container for the configured database."""
    return build_container_from_engine(
        build_engine(database_url or settings.database_url),
        checkpoint_path=settings.resolved_checkpoint_path,
    )
