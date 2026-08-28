"""Domain-to-contract mapping.

Masking happens here, on the boundary, so no handler can accidentally return
an unmasked identifier.
"""

from ..contracts.responses import (
    AccountSummaryData,
    AuditEventView,
    ConfirmationChallengeData,
    DisputeCaseCreated,
    DisputeCaseView,
    DisputeLifecycleEventView,
    MerchantData,
    ReviewDecisionData,
    TransactionSummary,
)
from ..domain.models import (
    AccountWithCustomerState,
    AuditEvent,
    CustomerConfirmation,
    DisputeCase,
    DisputeEvidenceSnapshot,
    DisputeLifecycleAuditEvent,
    Merchant,
    TransactionWithMerchant,
)
from ..security.masking import mask_account_id, mask_card, mask_customer_id

CASE_CREATED_MESSAGE = "We will investigate the case and get back in 10 business days."
CONFIRMATION_PROMPT_MESSAGE = (
    "Show the customer-facing reply, then ask the customer to confirm in their own words that they "
    "do not recognize this charge. Only if they confirm, call confirm_unrecognized_transaction with "
    "this confirmation_token. Do not confirm on the customer's behalf."
)


def review_path(case_id: str) -> str:
    """HTTP path where an authenticated reviewer decides one case."""
    return f"/reviews/{case_id}"


def to_account_summary(record: AccountWithCustomerState) -> AccountSummaryData:
    """Present an account without the customer's name."""
    account = record.account
    return AccountSummaryData(
        masked_account_id=mask_account_id(account.account_id),
        account_type=account.account_type,
        account_status=account.account_status,
        open_date=account.open_date,
        masked_card=mask_card(account.card_last_four),
        customer_state=record.customer_state,
    )


def to_transaction_summary(record: TransactionWithMerchant) -> TransactionSummary:
    """Present a transaction together with its merchant's display name."""
    transaction = record.transaction
    return TransactionSummary(
        transaction_id=transaction.transaction_id,
        merchant_id=transaction.merchant_id,
        merchant_display_name=record.merchant.display_name,
        raw_descriptor=transaction.raw_descriptor,
        amount=transaction.amount,
        currency=transaction.currency,
        transaction_date=transaction.transaction_date,
        posted_date=transaction.posted_date,
        status=transaction.status,
        card_present=transaction.card_present,
        recurring=transaction.recurring,
    )


def to_merchant_data(merchant: Merchant) -> MerchantData:
    """Present a merchant without its internal descriptor patterns."""
    return MerchantData(
        merchant_id=merchant.merchant_id,
        display_name=merchant.display_name,
        category=merchant.category,
        country=merchant.country,
    )


def to_audit_event_view(event: AuditEvent) -> AuditEventView:
    """Present an already-sanitized audit event."""
    return AuditEventView(
        event_id=event.event_id,
        tool_name=event.tool_name,
        request_id=event.request_id,
        timestamp=event.timestamp,
        account_id_masked=event.account_id_masked,
        outcome=event.outcome,
        duration_ms=event.duration_ms,
    )


def to_confirmation_challenge(
    confirmation: CustomerConfirmation,
    *,
    confirmation_token: str,
) -> ConfirmationChallengeData:
    """Present the one-time confirmation gate issued after eligible synthesis."""
    return ConfirmationChallengeData(
        confirmation_token=confirmation_token,
        expires_at=confirmation.expires_at,
        masked_account_id=mask_account_id(confirmation.account_id),
        transaction_id=confirmation.transaction_id,
        message=CONFIRMATION_PROMPT_MESSAGE,
    )


def to_dispute_case_created(case: DisputeCase) -> DisputeCaseCreated:
    """Present a newly persisted PENDING_REVIEW case to the host agent."""
    return DisputeCaseCreated(
        case_id=case.case_id,
        status="PENDING_REVIEW",
        created_at=case.created_at,
        investigation_id=case.investigation_id,
        masked_account_id=mask_account_id(case.account_id),
        masked_customer_id=mask_customer_id(case.customer_id),
        transaction_id=case.transaction_id,
        reason_code=case.reason_code,
        version=case.version,
        evidence_hash=case.evidence_hash,
        review_path=review_path(case.case_id),
        message=CASE_CREATED_MESSAGE,
    )


def to_lifecycle_event_view(event: DisputeLifecycleAuditEvent) -> DisputeLifecycleEventView:
    """Present one already-sanitized lifecycle event."""
    return DisputeLifecycleEventView(
        event_id=event.event_id,
        event_type=event.event_type,
        case_id=event.case_id,
        investigation_id=event.investigation_id,
        correlation_id=event.correlation_id,
        timestamp=event.timestamp,
        actor_type=event.actor_type,
        actor_id_masked=event.actor_id_masked,
        previous_status=event.previous_status,
        new_status=event.new_status,
        evidence_hash=event.evidence_hash,
        reason_code=event.reason_code,
    )


def to_dispute_case_view(
    case: DisputeCase,
    snapshot: DisputeEvidenceSnapshot | None,
    history: list[DisputeLifecycleAuditEvent],
) -> DisputeCaseView:
    """Present a case and its frozen evidence to an authenticated reviewer."""
    payload = snapshot.payload if snapshot is not None else {}
    verified = payload.get("verified_evidence")
    missing = payload.get("missing_evidence")
    return DisputeCaseView(
        case_id=case.case_id,
        status=case.status,
        version=case.version,
        investigation_id=case.investigation_id,
        masked_account_id=mask_account_id(case.account_id),
        masked_customer_id=mask_customer_id(case.customer_id),
        transaction_id=case.transaction_id,
        merchant_display_name=case.merchant_display_name,
        amount=case.amount,
        currency=case.currency,
        reason=case.reason,
        reason_code=case.reason_code,
        verified_evidence=[item for item in verified if isinstance(item, str)] if isinstance(verified, list) else [],
        missing_evidence=[item for item in missing if isinstance(item, str)] if isinstance(missing, list) else [],
        applied_policy=str(payload.get("applied_policy") or ""),
        proposed_action=str(payload.get("proposed_action") or ""),
        evidence_hash=case.evidence_hash,
        created_at=case.created_at,
        updated_at=case.updated_at,
        reviewer_id=case.reviewer_id,
        review_reason_code=case.review_reason_code,
        review_note=case.review_note,
        reviewed_at=case.reviewed_at,
        history=[to_lifecycle_event_view(event) for event in history],
    )


def to_review_decision(case: DisputeCase) -> ReviewDecisionData:
    """Present the outcome of an authenticated reviewer decision."""
    if case.reviewer_id is None or case.review_reason_code is None or case.reviewed_at is None:
        raise ValueError("A recorded review must include reviewer identity, reason and timestamp.")
    return ReviewDecisionData(
        case_id=case.case_id,
        status=case.status,
        version=case.version,
        reviewer_id=case.reviewer_id,
        reason_code=case.review_reason_code,
        note=case.review_note,
        reviewed_at=case.reviewed_at,
    )
