"""Composition root.

Every dependency is assembled here and passed explicitly, so handlers and
services can be exercised in tests against an in-memory database without
starting an MCP client.
"""

from dataclasses import dataclass

from sqlalchemy import Engine, inspect

from ..audit.service import AuditService
from ..config.settings import settings
from ..domain.services.duplicate_charge import DuplicateChargeService
from ..domain.services.merchant_resolver import MerchantResolverService
from ..llm.gemini_client import SynthesisClient
from ..observability.tracing import TracingService, build_tracing_service
from ..repositories.accounts import AccountRepository
from ..repositories.audit import AuditRepository
from ..repositories.disputes import DisputeRepository
from ..repositories.merchants import MerchantRepository
from ..repositories.models import Base
from ..repositories.session import SessionFactory, build_engine, build_session_factory
from ..repositories.transactions import TransactionRepository
from ..workflows.dispute_case import DisputeWorkflowRunner

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
    merchant_resolver: MerchantResolverService
    duplicates: DuplicateChargeService
    tracing: TracingService
    disputes: DisputeRepository
    dispute_workflow: DisputeWorkflowRunner
    synthesis: SynthesisClient | None = None

    def dataset_ready(self) -> bool:
        """Whether the synthetic dataset has been generated."""
        return _DATASET_TABLES.issubset(set(inspect(self.engine).get_table_names()))


def build_container_from_engine(
    engine: Engine,
    *,
    synthesis: SynthesisClient | None = None,
    tracing: TracingService | None = None,
) -> Container:
    """Assemble a container around an existing engine."""
    session_factory = build_session_factory(engine)
    # Audit events and registered dispute cases are the only tables the server writes;
    # they are created on demand. The read-only catalog comes from the data generator.
    Base.metadata.tables["audit_events"].create(bind=engine, checkfirst=True)
    Base.metadata.tables["dispute_cases"].create(bind=engine, checkfirst=True)

    accounts = AccountRepository(session_factory)
    transactions = TransactionRepository(session_factory)
    disputes = DisputeRepository(session_factory)
    return Container(
        engine=engine,
        session_factory=session_factory,
        accounts=accounts,
        transactions=transactions,
        merchants=MerchantRepository(session_factory),
        audit=AuditService(AuditRepository(session_factory)),
        merchant_resolver=MerchantResolverService(),
        duplicates=DuplicateChargeService(),
        tracing=tracing or build_tracing_service(),
        disputes=disputes,
        dispute_workflow=DisputeWorkflowRunner(
            accounts=accounts,
            transactions=transactions,
            disputes=disputes,
        ),
        synthesis=synthesis,
    )


def build_container(database_url: str | None = None) -> Container:
    """Assemble a container for the configured database."""
    return build_container_from_engine(build_engine(database_url or settings.database_url))
