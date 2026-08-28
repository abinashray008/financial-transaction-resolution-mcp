"""Row-to-domain mapping."""

from ..domain.enums import (
    AccountStatus,
    AccountType,
    AuditActorType,
    DisputeCaseStatus,
    DisputeLifecycleEvent,
    DisputeReasonCode,
    ReviewReasonCode,
    TransactionStatus,
)
from ..domain.models import (
    Account,
    Customer,
    CustomerConfirmation,
    DisputeCase,
    DisputeEvidenceSnapshot,
    DisputeLifecycleAuditEvent,
    Merchant,
    Transaction,
)
from ..domain.money import from_minor_units
from .models import (
    AccountRow,
    ConfirmationChallengeRow,
    CustomerRow,
    DisputeCaseRow,
    DisputeLifecycleEventRow,
    EvidenceSnapshotRow,
    MerchantRow,
    TransactionRow,
)


def to_customer(row: CustomerRow) -> Customer:
    return Customer(
        customer_id=row.customer_id,
        first_name=row.first_name,
        last_name=row.last_name,
        state=row.state,
    )


def to_account(row: AccountRow) -> Account:
    return Account(
        account_id=row.account_id,
        customer_id=row.customer_id,
        account_type=AccountType(row.account_type),
        account_status=AccountStatus(row.account_status),
        open_date=row.open_date,
        card_last_four=row.card_last_four,
    )


def to_merchant(row: MerchantRow) -> Merchant:
    return Merchant(
        merchant_id=row.merchant_id,
        display_name=row.display_name,
        category=row.category,
        country=row.country,
        descriptor_patterns=tuple(row.descriptor_patterns),
    )


def to_transaction(row: TransactionRow) -> Transaction:
    return Transaction(
        transaction_id=row.transaction_id,
        account_id=row.account_id,
        merchant_id=row.merchant_id,
        raw_descriptor=row.raw_descriptor,
        amount=from_minor_units(row.amount_minor),
        currency=row.currency,
        transaction_date=row.transaction_date,
        posted_date=row.posted_date,
        status=TransactionStatus(row.status),
        card_present=row.card_present,
        recurring=row.recurring,
    )


def to_dispute_case(row: DisputeCaseRow) -> DisputeCase:
    return DisputeCase(
        case_id=row.case_id,
        customer_id=row.customer_id,
        account_id=row.account_id,
        transaction_id=row.transaction_id,
        investigation_id=row.investigation_id,
        confirmation_id=row.confirmation_id,
        idempotency_key=row.idempotency_key,
        reason=row.reason,
        reason_code=DisputeReasonCode(row.reason_code),
        status=DisputeCaseStatus(row.status),
        version=row.version,
        evidence_hash=row.evidence_hash,
        amount=from_minor_units(row.amount_minor),
        currency=row.currency,
        merchant_display_name=row.merchant_display_name,
        created_at=row.created_at,
        updated_at=row.updated_at,
        externally_submitted=row.externally_submitted,
        reviewer_id=row.reviewer_id,
        review_reason_code=(None if row.review_reason_code is None else ReviewReasonCode(row.review_reason_code)),
        review_note=row.review_note,
        reviewed_at=row.reviewed_at,
    )


def to_evidence_snapshot(row: EvidenceSnapshotRow) -> DisputeEvidenceSnapshot:
    return DisputeEvidenceSnapshot(
        snapshot_id=row.snapshot_id,
        case_id=row.case_id,
        investigation_id=row.investigation_id,
        account_id=row.account_id,
        transaction_id=row.transaction_id,
        evidence_hash=row.evidence_hash,
        payload=dict(row.payload),
        created_at=row.created_at,
    )


def to_customer_confirmation(row: ConfirmationChallengeRow) -> CustomerConfirmation:
    return CustomerConfirmation(
        confirmation_id=row.confirmation_id,
        investigation_id=row.investigation_id,
        account_id=row.account_id,
        transaction_id=row.transaction_id,
        case_id=row.case_id,
        customer_id=row.customer_id,
        evidence_hash=row.evidence_hash,
        reason=row.reason,
        reason_code=DisputeReasonCode(row.reason_code),
        snapshot=dict(row.snapshot),
        amount=from_minor_units(row.amount_minor),
        currency=row.currency,
        merchant_display_name=row.merchant_display_name,
        created_at=row.created_at,
        expires_at=row.expires_at,
        consumed_at=row.consumed_at,
    )


def to_dispute_lifecycle_event(row: DisputeLifecycleEventRow) -> DisputeLifecycleAuditEvent:
    return DisputeLifecycleAuditEvent(
        event_id=row.event_id,
        event_type=DisputeLifecycleEvent(row.event_type),
        case_id=row.case_id,
        investigation_id=row.investigation_id,
        correlation_id=row.correlation_id,
        timestamp=row.timestamp,
        actor_type=AuditActorType(row.actor_type),
        actor_id_masked=row.actor_id_masked,
        previous_status=(None if row.previous_status is None else DisputeCaseStatus(row.previous_status)),
        new_status=(None if row.new_status is None else DisputeCaseStatus(row.new_status)),
        evidence_hash=row.evidence_hash,
        reason_code=row.reason_code,
    )
