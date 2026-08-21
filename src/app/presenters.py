"""Domain-to-contract mapping.

Masking happens here, on the boundary, so no handler can accidentally return
an unmasked identifier.
"""

from ..contracts.responses import (
    AccountSummaryData,
    AuditEventView,
    DisputeDecisionData,
    DisputeProposalData,
    MerchantData,
    TransactionSummary,
)
from ..domain.enums import DisputeWorkflowStatus
from ..domain.models import (
    AccountWithCustomerState,
    AuditEvent,
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


def to_dispute_proposal(proposal: DisputeProposal) -> DisputeProposalData:
    """Present a proposed case without customer names or unmasked ids."""
    return DisputeProposalData(
        workflow_status=DisputeWorkflowStatus.AWAITING_APPROVAL,
        masked_account_id=mask_account_id(proposal.account_id),
        masked_customer_id=mask_customer_id(proposal.customer_id),
        transaction_id=proposal.transaction_id,
        merchant_display_name=proposal.merchant_display_name,
        amount=proposal.amount,
        currency=proposal.currency,
        transaction_date=proposal.transaction_date,
        reason=proposal.reason,
        message=proposal.message,
    )


def to_dispute_decision(decision: DisputeDecision) -> DisputeDecisionData:
    """Present the outcome of a human approve or decline decision."""
    return DisputeDecisionData(
        workflow_status=DisputeWorkflowStatus(decision.workflow_status),
        masked_account_id=mask_account_id(decision.account_id),
        masked_customer_id=mask_customer_id(decision.customer_id),
        transaction_id=decision.transaction_id,
        case_id=decision.case_id,
        reason=decision.reason,
        decision_note=decision.decision_note,
        registered=decision.case_id is not None,
    )
