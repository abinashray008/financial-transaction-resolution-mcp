"""Transaction search: filters, ranges and account scoping."""

from datetime import date
from decimal import Decimal

from src.contracts.requests import SearchTransactionsRequest
from src.domain.criteria import MAX_LIMIT
from src.domain.enums import TransactionStatus
from src.domain.exceptions import ErrorCode
from src.tools.search_transactions_tool import search_transactions
from tests.conftest import SCENARIO_ACCOUNT, assert_error, assert_ok


def search(container, **kwargs):
    return search_transactions(container, SearchTransactionsRequest(**kwargs))


def test_search_returns_only_the_requested_account(container):
    response = search(container, account_id=SCENARIO_ACCOUNT, limit=MAX_LIMIT)

    assert_ok(response)
    assert response.data is not None
    assert response.data.masked_account_id == "ACCT-****0001"
    assert response.data.returned_count == len(response.data.transactions)


def test_date_range_filter_is_inclusive(container):
    response = search(
        container,
        account_id=SCENARIO_ACCOUNT,
        start_date=date(2026, 6, 12),
        end_date=date(2026, 6, 12),
        limit=MAX_LIMIT,
    )

    assert_ok(response)
    assert response.data is not None
    assert {t.transaction_id for t in response.data.transactions} == {"TXN-SCN-DUP-A", "TXN-SCN-DUP-B"}


def test_amount_range_filter(container):
    response = search(
        container,
        account_id=SCENARIO_ACCOUNT,
        minimum_amount=Decimal("89.99"),
        maximum_amount=Decimal("89.99"),
        limit=MAX_LIMIT,
    )

    assert_ok(response)
    assert response.data is not None
    assert all(t.amount == Decimal("89.99") for t in response.data.transactions)
    assert {t.transaction_id for t in response.data.transactions} == {"TXN-SCN-DUP-A", "TXN-SCN-DUP-B"}


def test_merchant_query_matches_the_statement_descriptor(container):
    response = search(container, account_id=SCENARIO_ACCOUNT, merchant_query="rvrbnd", limit=MAX_LIMIT)

    assert_ok(response)
    assert response.data is not None
    assert [t.transaction_id for t in response.data.transactions] == ["TXN-SCN-DESC-01"]


def test_merchant_query_matches_the_merchant_display_name(container):
    response = search(container, account_id=SCENARIO_ACCOUNT, merchant_query="Riverbend", limit=MAX_LIMIT)

    assert_ok(response)
    assert response.data is not None
    assert [t.transaction_id for t in response.data.transactions] == ["TXN-SCN-DESC-01"]


def test_merchant_query_wildcards_cannot_widen_the_search(container):
    """A LIKE wildcard must be treated as a literal character."""
    response = search(container, account_id=SCENARIO_ACCOUNT, merchant_query="%", limit=MAX_LIMIT)

    assert_ok(response)
    assert response.data is not None
    assert response.data.returned_count == 0


def test_status_filter(container):
    response = search(
        container,
        account_id=SCENARIO_ACCOUNT,
        status=TransactionStatus.AUTHORIZATION_HOLD,
        limit=MAX_LIMIT,
    )

    assert_ok(response)
    assert response.data is not None
    assert [t.transaction_id for t in response.data.transactions] == ["TXN-SCN-HOLD-01"]


def test_limit_is_applied_and_truncation_is_reported(container):
    response = search(container, account_id=SCENARIO_ACCOUNT, limit=2)

    assert_ok(response)
    assert response.data is not None
    assert response.data.returned_count == 2
    assert response.data.truncated is True


def test_results_are_ordered_newest_first(container):
    response = search(container, account_id=SCENARIO_ACCOUNT, limit=MAX_LIMIT)

    assert_ok(response)
    assert response.data is not None
    dates = [t.transaction_date for t in response.data.transactions]
    assert dates == sorted(dates, reverse=True)


def test_applied_filters_are_echoed_back(container):
    response = search(container, account_id=SCENARIO_ACCOUNT, merchant_query="lumen", limit=7)

    assert_ok(response)
    assert response.data is not None
    assert response.data.applied_filters.merchant_query == "lumen"
    assert response.data.applied_filters.limit == 7


def test_reversed_date_range_is_rejected(container):
    response = search(
        container,
        account_id=SCENARIO_ACCOUNT,
        start_date=date(2026, 6, 30),
        end_date=date(2026, 6, 1),
    )

    assert_error(response, ErrorCode.INVALID_DATE_RANGE)


def test_reversed_amount_range_is_rejected(container):
    response = search(
        container,
        account_id=SCENARIO_ACCOUNT,
        minimum_amount=Decimal("500.00"),
        maximum_amount=Decimal("10.00"),
    )

    assert_error(response, ErrorCode.INVALID_AMOUNT_RANGE)


def test_negative_amount_is_rejected(container):
    response = search(container, account_id=SCENARIO_ACCOUNT, minimum_amount=Decimal("-1.00"))

    assert_error(response, ErrorCode.INVALID_AMOUNT_RANGE)


def test_blank_merchant_query_is_rejected(container):
    response = search(container, account_id=SCENARIO_ACCOUNT, merchant_query="   ")

    assert_error(response, ErrorCode.INVALID_INPUT)


def test_limit_above_the_maximum_is_rejected(container):
    response = search(container, account_id=SCENARIO_ACCOUNT, limit=MAX_LIMIT + 1)

    assert_error(response, ErrorCode.INVALID_INPUT)


def test_limit_below_one_is_rejected(container):
    response = search(container, account_id=SCENARIO_ACCOUNT, limit=0)

    assert_error(response, ErrorCode.INVALID_INPUT)


def test_malformed_account_id_is_rejected(container):
    response = search(container, account_id="not-an-account")

    assert_error(response, ErrorCode.INVALID_INPUT)


def test_unknown_account_is_reported_as_not_found(container):
    response = search(container, account_id="ACCT-9999")

    assert_error(response, ErrorCode.ACCOUNT_NOT_FOUND)
