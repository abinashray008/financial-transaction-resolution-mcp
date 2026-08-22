"""Duplicate-charge detection.

The end-to-end cases run against the seeded scenarios. The rules that need a
transaction pair the dataset does not contain are exercised directly against
the domain service.
"""

from datetime import date
from decimal import Decimal

import pytest

from src.contracts.requests import CheckDuplicateChargeRequest
from src.domain.criteria import MAX_DATE_TOLERANCE_DAYS
from src.domain.enums import Confidence, TransactionStatus
from src.domain.exceptions import ErrorCode
from src.domain.models import Transaction
from src.domain.services.duplicate_charge import DuplicateChargeService
from src.tools.check_duplicate_charge_tool import check_duplicate_charge
from tests.conftest import SCENARIO_ACCOUNT, assert_error, assert_ok


def check(container, transaction_id: str, **kwargs):
    return check_duplicate_charge(
        container,
        CheckDuplicateChargeRequest(account_id=SCENARIO_ACCOUNT, transaction_id=transaction_id, **kwargs),
    )


def make_transaction(
    transaction_id: str,
    *,
    amount: str = "50.00",
    transaction_date: date = date(2026, 6, 10),
    status: TransactionStatus = TransactionStatus.POSTED,
    recurring: bool = False,
    card_present: bool = True,
) -> Transaction:
    return Transaction(
        transaction_id=transaction_id,
        account_id=SCENARIO_ACCOUNT,
        merchant_id="MERCH-0007",
        raw_descriptor="IRONWOOD HDWR 101 SEATTLE WA",
        amount=Decimal(amount),
        currency="USD",
        transaction_date=transaction_date,
        posted_date=None if status is not TransactionStatus.POSTED else transaction_date,
        status=status,
        card_present=card_present,
        recurring=recurring,
    )


def test_identical_same_day_charges_are_high_confidence(container):
    response = check(container, "TXN-SCN-DUP-A")

    assert_ok(response)
    assert response.data is not None
    assert response.data.duplicate_likely is True
    assert response.data.confidence == Confidence.HIGH
    assert response.data.candidate_transaction_ids == ["TXN-SCN-DUP-B"]
    assert "identical amount" in response.data.reasons[0]


def test_the_check_is_symmetric(container):
    response = check(container, "TXN-SCN-DUP-B")

    assert_ok(response)
    assert response.data is not None
    assert response.data.candidate_transaction_ids == ["TXN-SCN-DUP-A"]
    assert response.data.confidence == Confidence.HIGH


def test_a_monthly_subscription_has_no_candidates_in_the_window(container):
    response = check(container, "TXN-SCN-SUB-01")

    assert_ok(response)
    assert response.data is not None
    assert response.data.duplicate_likely is False
    assert response.data.confidence == Confidence.LOW
    assert response.data.candidate_transaction_ids == []
    assert "No other transaction" in response.data.reasons[0]


def test_a_hold_settling_into_a_posted_charge_is_not_a_duplicate(container):
    """Same merchant, same amount, but the expected hotel settlement pattern."""
    response = check(container, "TXN-SCN-HOLD-02")

    assert_ok(response)
    assert response.data is not None
    assert response.data.candidate_transaction_ids == ["TXN-SCN-HOLD-01"]
    assert response.data.duplicate_likely is False
    assert response.data.confidence == Confidence.LOW
    assert "authorization hold" in response.data.reasons[0]


def test_a_zero_day_tolerance_still_finds_a_same_day_duplicate(container):
    response = check(container, "TXN-SCN-DUP-A", date_tolerance_days=0)

    assert_ok(response)
    assert response.data is not None
    assert response.data.confidence == Confidence.HIGH


def test_an_unrelated_transaction_has_no_duplicates(container):
    response = check(container, "TXN-SCN-POSTED-01")

    assert_ok(response)
    assert response.data is not None
    assert response.data.duplicate_likely is False
    assert response.data.candidate_transaction_ids == []


def test_tolerances_are_echoed_back(container):
    response = check(container, "TXN-SCN-DUP-A", date_tolerance_days=5, amount_tolerance=Decimal("2.50"))

    assert_ok(response)
    assert response.data is not None
    assert response.data.date_tolerance_days == 5
    assert response.data.amount_tolerance == Decimal("2.50")


def test_an_unknown_transaction_is_reported_as_not_found(container):
    response = check(container, "TXN-NOPE")

    assert_error(response, ErrorCode.TRANSACTION_NOT_FOUND)


def test_an_out_of_range_date_tolerance_is_rejected(container):
    response = check(container, "TXN-SCN-DUP-A", date_tolerance_days=MAX_DATE_TOLERANCE_DAYS + 1)

    assert_error(response, ErrorCode.INVALID_INPUT)


def test_a_negative_amount_tolerance_is_rejected(container):
    response = check(container, "TXN-SCN-DUP-A", amount_tolerance=Decimal("-1"))

    assert_error(response, ErrorCode.INVALID_AMOUNT_RANGE)


@pytest.fixture
def service() -> DuplicateChargeService:
    return DuplicateChargeService()


def test_same_amount_a_few_days_apart_is_medium_confidence(service):
    subject = make_transaction("TXN-A", transaction_date=date(2026, 6, 10))
    candidate = make_transaction("TXN-B", transaction_date=date(2026, 6, 12))

    assessment = service.assess(
        subject=subject,
        candidates=[candidate],
        date_tolerance_days=3,
        amount_tolerance=Decimal("0"),
    )

    assert assessment.confidence == Confidence.MEDIUM
    assert assessment.duplicate_likely is True
    assert "2 day(s) apart" in assessment.reasons[0]


def test_a_recurring_charge_is_downgraded(service):
    subject = make_transaction("TXN-A", recurring=True)
    candidate = make_transaction("TXN-B", recurring=True)

    assessment = service.assess(
        subject=subject,
        candidates=[candidate],
        date_tolerance_days=3,
        amount_tolerance=Decimal("0"),
    )

    assert assessment.confidence == Confidence.LOW
    assert assessment.duplicate_likely is False
    assert "recurring subscription" in assessment.reasons[0]


def test_a_reversed_charge_is_downgraded(service):
    subject = make_transaction("TXN-A")
    candidate = make_transaction("TXN-B", status=TransactionStatus.REVERSED)

    assessment = service.assess(
        subject=subject,
        candidates=[candidate],
        date_tolerance_days=3,
        amount_tolerance=Decimal("0"),
    )

    assert assessment.confidence == Confidence.LOW
    assert "reversed" in assessment.reasons[0]


def test_an_amount_inside_the_tolerance_but_not_equal_is_low_confidence(service):
    subject = make_transaction("TXN-A", amount="50.00")
    candidate = make_transaction("TXN-B", amount="51.00")

    assessment = service.assess(
        subject=subject,
        candidates=[candidate],
        date_tolerance_days=3,
        amount_tolerance=Decimal("2.00"),
    )

    assert assessment.confidence == Confidence.LOW
    assert assessment.duplicate_likely is False


def test_a_channel_mismatch_is_called_out(service):
    subject = make_transaction("TXN-A", card_present=True)
    candidate = make_transaction("TXN-B", card_present=False)

    assessment = service.assess(
        subject=subject,
        candidates=[candidate],
        date_tolerance_days=3,
        amount_tolerance=Decimal("0"),
    )

    assert assessment.confidence == Confidence.HIGH
    assert "different capture channels" in assessment.reasons[0]


def test_the_strongest_candidate_sets_the_overall_confidence(service):
    subject = make_transaction("TXN-A", transaction_date=date(2026, 6, 10))
    weak = make_transaction("TXN-B", amount="49.00", transaction_date=date(2026, 6, 11))
    strong = make_transaction("TXN-C", transaction_date=date(2026, 6, 10))

    assessment = service.assess(
        subject=subject,
        candidates=[weak, strong],
        date_tolerance_days=3,
        amount_tolerance=Decimal("2.00"),
    )

    assert assessment.confidence == Confidence.HIGH
    assert assessment.candidate_transaction_ids == ("TXN-B", "TXN-C")
    assert len(assessment.reasons) == 2
