"""Domain-to-contract mapping.

Masking happens here, on the boundary, so no handler can accidentally return
an unmasked identifier.
"""

from ..contracts.responses import (
    AccountSummaryData,
    ApprovalRecordData,
    AuditEventView,
    DisputeDecisionData,
    DisputeDraftData,
    MerchantData,
    TransactionSummary,
)
from ..domain.enums import DisputeWorkflowStatus
from ..domain.models import (
    AccountWithCustomerState,
    AuditEvent,
    DisputeApproval,
    DisputeDecision,
    DisputeProposal,
    Merchant,
    TransactionWithMerchant,
)
from ..security.masking import mask_account_id, mask_card, mask_customer_id


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


def to_dispute_draft(proposal: DisputeProposal) -> DisputeDraftData:
    """Present a PENDING_REVIEW draft without customer names or unmasked ids."""
    return DisputeDraftData(
        status=DisputeWorkflowStatus.PENDING_REVIEW,
        masked_account_id=mask_account_id(proposal.account_id),
        masked_customer_id=mask_customer_id(proposal.customer_id),
        transaction_id=proposal.transaction_id,
        merchant_display_name=proposal.merchant_display_name,
        amount=proposal.amount,
        currency=proposal.currency,
        transaction_date=proposal.transaction_date,
        reason=proposal.reason,
        reason_code=proposal.reason_code,
        verified_evidence=list(proposal.verified_evidence),
        missing_evidence=list(proposal.missing_evidence),
        applied_policy=proposal.applied_policy,
        proposed_action=proposal.proposed_action,
        draft_hash=proposal.draft_hash,
        review_path=f"/reviews/{proposal.request_id}",
        message=proposal.message,
    )


def to_dispute_decision(decision: DisputeDecision) -> DisputeDecisionData:
    """Present the outcome of a verified approve or decline decision."""
    return DisputeDecisionData(
        workflow_status=DisputeWorkflowStatus(decision.workflow_status),
        masked_account_id=mask_account_id(decision.account_id),
        masked_customer_id=mask_customer_id(decision.customer_id),
        transaction_id=decision.transaction_id,
        case_id=decision.case_id,
        reason=decision.reason,
        decision_note=decision.decision_note,
        approval_id=decision.approval_id,
        registered=decision.case_id is not None,
    )


def to_approval_record(record: DisputeApproval) -> ApprovalRecordData:
    """Present a minted approval record to the human review application."""
    return ApprovalRecordData(
        approval_id=record.approval_id,
        request_id=record.request_id,
        draft_hash=record.draft_hash,
        reviewer_id=record.reviewer_id,
        decision=record.decision,
        decision_note=record.decision_note,
        created_at=record.created_at,
        decided_at=record.decided_at,
        expires_at=record.expires_at,
        consumed_at=record.consumed_at,
    )
