"""Account isolation.

One customer must not be able to reach another customer's transaction, and
must not be able to tell that it exists. The seed data puts an identical
charge on two different accounts specifically so these tests are meaningful.
"""

from src.contracts.requests import (
    CheckDuplicateChargeRequest,
    GetTransactionDetailsRequest,
    SearchTransactionsRequest,
)
from src.domain.criteria import MAX_LIMIT
from src.domain.exceptions import ErrorCode
from src.tools.check_duplicate_charge_tool import check_duplicate_charge
from src.tools.get_transaction_details_tool import get_transaction_details
from src.tools.search_transactions_tool import search_transactions
from tests.conftest import OTHER_ACCOUNT, SCENARIO_ACCOUNT, assert_error, assert_ok

# A real transaction that belongs to ACCT-0001.
FIRST_ACCOUNT_TRANSACTION = "TXN-SCN-DUP-A"
# A real transaction that belongs to ACCT-0002.
SECOND_ACCOUNT_TRANSACTION = "TXN-SCN-OTHER-01"


def details(container, account_id: str, transaction_id: str):
    return get_transaction_details(
        container,
        GetTransactionDetailsRequest(account_id=account_id, transaction_id=transaction_id),
    )


def test_the_owning_account_can_read_its_own_transaction(container):
    response = details(container, SCENARIO_ACCOUNT, FIRST_ACCOUNT_TRANSACTION)

    assert_ok(response)
    assert response.data is not None
    assert response.data.transaction.transaction_id == FIRST_ACCOUNT_TRANSACTION


def test_another_account_cannot_read_that_transaction(container):
    """Supplying a valid transaction id from another account must not work."""
    response = details(container, OTHER_ACCOUNT, FIRST_ACCOUNT_TRANSACTION)

    assert_error(response, ErrorCode.TRANSACTION_NOT_FOUND)


def test_isolation_holds_in_the_other_direction(container):
    response = details(container, SCENARIO_ACCOUNT, SECOND_ACCOUNT_TRANSACTION)

    assert_error(response, ErrorCode.TRANSACTION_NOT_FOUND)


def test_a_foreign_transaction_is_indistinguishable_from_a_missing_one(container):
    """The response must not work as an oracle for which ids exist."""
    foreign = details(container, OTHER_ACCOUNT, FIRST_ACCOUNT_TRANSACTION)
    missing = details(container, OTHER_ACCOUNT, "TXN-DOES-NOT-EXIST")

    assert foreign.error is not None
    assert missing.error is not None
    assert foreign.error.code == missing.error.code
    assert foreign.error.message == missing.error.message


def test_search_never_returns_another_accounts_transactions(container):
    first = search_transactions(
        container,
        SearchTransactionsRequest(account_id=SCENARIO_ACCOUNT, limit=MAX_LIMIT),
    )
    second = search_transactions(
        container,
        SearchTransactionsRequest(account_id=OTHER_ACCOUNT, limit=MAX_LIMIT),
    )

    assert_ok(first)
    assert_ok(second)
    assert first.data is not None
    assert second.data is not None

    first_ids = {t.transaction_id for t in first.data.transactions}
    second_ids = {t.transaction_id for t in second.data.transactions}

    assert first_ids and second_ids
    assert first_ids.isdisjoint(second_ids)
    assert SECOND_ACCOUNT_TRANSACTION not in first_ids
    assert FIRST_ACCOUNT_TRANSACTION not in second_ids


def test_duplicate_detection_does_not_cross_accounts(container):
    """An identical charge on another account is not a duplicate candidate."""
    response = check_duplicate_charge(
        container,
        CheckDuplicateChargeRequest(
            account_id=SCENARIO_ACCOUNT,
            transaction_id=FIRST_ACCOUNT_TRANSACTION,
        ),
    )

    assert_ok(response)
    assert response.data is not None
    assert SECOND_ACCOUNT_TRANSACTION not in response.data.candidate_transaction_ids


def test_duplicate_check_rejects_a_transaction_on_another_account(container):
    response = check_duplicate_charge(
        container,
        CheckDuplicateChargeRequest(
            account_id=OTHER_ACCOUNT,
            transaction_id=FIRST_ACCOUNT_TRANSACTION,
        ),
    )

    assert_error(response, ErrorCode.TRANSACTION_NOT_FOUND)
