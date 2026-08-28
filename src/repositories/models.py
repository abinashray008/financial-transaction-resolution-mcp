"""SQLAlchemy table definitions.

These rows never leave the repository layer; repositories map them onto the
frozen dataclasses in :mod:`src.domain.models`.
"""

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for the synthetic dataset."""


class CustomerRow(Base):
    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    first_name: Mapped[str] = mapped_column(String(64))
    last_name: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(2))


class AccountRow(Base):
    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(32), ForeignKey("customers.customer_id"), index=True)
    account_type: Mapped[str] = mapped_column(String(32))
    account_status: Mapped[str] = mapped_column(String(16))
    open_date: Mapped[date] = mapped_column(Date)
    card_last_four: Mapped[str] = mapped_column(String(4))


class MerchantRow(Base):
    __tablename__ = "merchants"

    merchant_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(64))
    country: Mapped[str] = mapped_column(String(2))
    descriptor_patterns: Mapped[list[str]] = mapped_column(JSON)


class TransactionRow(Base):
    __tablename__ = "transactions"

    transaction_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(32), ForeignKey("accounts.account_id"), index=True)
    merchant_id: Mapped[str] = mapped_column(String(32), ForeignKey("merchants.merchant_id"), index=True)
    raw_descriptor: Mapped[str] = mapped_column(String(128))
    # Integer minor units keep amount comparisons exact in SQLite.
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    transaction_date: Mapped[date] = mapped_column(Date, index=True)
    posted_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(24))
    card_present: Mapped[bool] = mapped_column(Boolean)
    recurring: Mapped[bool] = mapped_column(Boolean)


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tool_name: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    account_id_masked: Mapped[str | None] = mapped_column(String(32), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32))
    duration_ms: Mapped[int] = mapped_column(Integer)


class DisputeCaseRow(Base):
    """Internal dispute case. Written at PENDING_REVIEW, then updated in place."""

    __tablename__ = "dispute_cases"
    __table_args__ = (
        UniqueConstraint("account_id", "transaction_id", name="uq_dispute_account_transaction"),
        UniqueConstraint("idempotency_key", name="uq_dispute_idempotency_key"),
        UniqueConstraint("confirmation_id", name="uq_dispute_confirmation"),
    )

    case_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(32), ForeignKey("customers.customer_id"), index=True)
    account_id: Mapped[str] = mapped_column(String(32), ForeignKey("accounts.account_id"), index=True)
    transaction_id: Mapped[str] = mapped_column(String(48), index=True)
    investigation_id: Mapped[str] = mapped_column(String(64), index=True)
    confirmation_id: Mapped[str] = mapped_column(String(48))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(String(2000))
    reason_code: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(24), index=True)
    # Bumped on every review update so a stale reviewer decision cannot win.
    version: Mapped[int] = mapped_column(Integer, default=1)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    merchant_display_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    externally_submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewer_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_reason_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EvidenceSnapshotRow(Base):
    """Append-only copy of the evidence a case was created from."""

    __tablename__ = "dispute_evidence_snapshots"
    __table_args__ = (UniqueConstraint("case_id", name="uq_snapshot_case"),)

    snapshot_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(32), index=True)
    investigation_id: Mapped[str] = mapped_column(String(64), index=True)
    account_id: Mapped[str] = mapped_column(String(32), index=True)
    transaction_id: Mapped[str] = mapped_column(String(48))
    evidence_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ConfirmationChallengeRow(Base):
    """One-time customer confirmation challenge. Only the token digest is stored."""

    __tablename__ = "confirmation_challenges"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_confirmation_token_hash"),)

    confirmation_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), index=True)
    investigation_id: Mapped[str] = mapped_column(String(64), index=True)
    account_id: Mapped[str] = mapped_column(String(32), index=True)
    transaction_id: Mapped[str] = mapped_column(String(48))
    case_id: Mapped[str] = mapped_column(String(32))
    customer_id: Mapped[str] = mapped_column(String(32))
    evidence_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(2000))
    reason_code: Mapped[str] = mapped_column(String(48))
    snapshot: Mapped[dict[str, object]] = mapped_column(JSON)
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    merchant_display_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DisputeLifecycleEventRow(Base):
    """Semantic dispute lifecycle events, separate from tool-call telemetry."""

    __tablename__ = "dispute_lifecycle_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    case_id: Mapped[str] = mapped_column(String(32), index=True)
    investigation_id: Mapped[str] = mapped_column(String(64), index=True)
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    actor_type: Mapped[str] = mapped_column(String(24))
    actor_id_masked: Mapped[str | None] = mapped_column(String(64), nullable=True)
    previous_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
