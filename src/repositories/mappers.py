"""Row-to-domain mapping."""

from ..domain.enums import AccountStatus, AccountType, TransactionStatus
from ..domain.models import Account, Customer, Merchant, Transaction
from ..domain.money import from_minor_units
from .models import AccountRow, CustomerRow, MerchantRow, TransactionRow


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
