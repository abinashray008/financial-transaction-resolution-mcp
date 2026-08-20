"""Domain-to-contract mapping.

Masking happens here, on the boundary, so no handler can accidentally return
an unmasked identifier.
"""

from ..contracts.responses import (
    AccountSummaryData,
    AuditEventView,
    MerchantData,
    TransactionSummary,
)
from ..domain.models import AccountWithCustomerState, AuditEvent, Merchant, TransactionWithMerchant
from ..security.masking import mask_account_id, mask_card


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
