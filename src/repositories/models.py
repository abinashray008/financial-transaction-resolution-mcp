"""SQLAlchemy table definitions.

These rows never leave the repository layer; repositories map them onto the
frozen dataclasses in :mod:`src.domain.models`.
"""

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String
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
