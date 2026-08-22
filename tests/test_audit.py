"""Audit logging and its sanitization guarantees."""

from src.app.data_seed import CUSTOMERS
from src.contracts.requests import (
    GetAccountSummaryRequest,
    GetAuditTraceRequest,
    GetTransactionDetailsRequest,
)
from src.domain.exceptions import ErrorCode
from src.tools.get_account_summary_tool import get_account_summary
from src.tools.get_audit_trace_tool import get_audit_trace
from src.tools.get_transaction_details_tool import get_transaction_details
from tests.conftest import SCENARIO_ACCOUNT, assert_error, assert_ok


def trace(container, request_id: str):
    return get_audit_trace(container, GetAuditTraceRequest(request_id=request_id))


def test_a_successful_call_is_recorded(container):
    get_account_summary(
        container,
        GetAccountSummaryRequest(account_id=SCENARIO_ACCOUNT, request_id="req-success"),
    )

    response = trace(container, "req-success")

    assert_ok(response)
    assert response.data is not None
    assert response.data.event_count == 1
    event = response.data.events[0]
    assert event.tool_name == "get_account_summary"
    assert event.outcome == "success"
    assert event.duration_ms >= 0


def test_the_recorded_account_id_is_masked(container):
    get_account_summary(
        container,
        GetAccountSummaryRequest(account_id=SCENARIO_ACCOUNT, request_id="req-masked"),
    )

    response = trace(container, "req-masked")

    assert response.data is not None
    assert response.data.events[0].account_id_masked == "ACCT-****0001"


def test_a_failed_call_records_the_error_code_as_its_outcome(container):
    get_account_summary(
        container,
        GetAccountSummaryRequest(account_id="ACCT-9999", request_id="req-failure"),
    )

    response = trace(container, "req-failure")

    assert response.data is not None
    assert response.data.events[0].outcome == ErrorCode.ACCOUNT_NOT_FOUND.value


def test_several_calls_share_one_correlation_id(container):
    for _ in range(3):
        get_account_summary(
            container,
            GetAccountSummaryRequest(account_id=SCENARIO_ACCOUNT, request_id="req-shared"),
        )

    response = trace(container, "req-shared")

    assert response.data is not None
    assert response.data.event_count == 3


def test_events_never_contain_descriptors_names_or_amounts(container):
    """The audit service has no parameter that could carry them."""
    get_transaction_details(
        container,
        GetTransactionDetailsRequest(
            account_id=SCENARIO_ACCOUNT,
            transaction_id="TXN-SCN-DESC-01",
            request_id="req-sanitized",
        ),
    )

    response = trace(container, "req-sanitized")

    assert response.data is not None
    serialized = response.data.model_dump_json()

    assert "RVRBND" not in serialized
    assert "Riverbend" not in serialized
    assert "6.75" not in serialized
    assert "TXN-SCN-DESC-01" not in serialized
    for customer in CUSTOMERS:
        assert customer.first_name not in serialized
        assert customer.last_name not in serialized


def test_an_event_exposes_only_the_permitted_fields(container):
    get_account_summary(
        container,
        GetAccountSummaryRequest(account_id=SCENARIO_ACCOUNT, request_id="req-fields"),
    )

    response = trace(container, "req-fields")

    assert response.data is not None
    assert set(response.data.events[0].model_dump().keys()) == {
        "event_id",
        "tool_name",
        "request_id",
        "timestamp",
        "account_id_masked",
        "outcome",
        "duration_ms",
    }


def test_a_malformed_account_id_is_audited_without_being_stored_verbatim(container):
    get_account_summary(
        container,
        GetAccountSummaryRequest(account_id="ACCT-0001 leaked secret", request_id="req-malformed"),
    )

    response = trace(container, "req-malformed")

    assert response.data is not None
    event = response.data.events[0]
    assert event.outcome == ErrorCode.INVALID_INPUT.value
    assert event.account_id_masked is not None
    assert "leaked" not in event.account_id_masked
    assert "secret" not in event.account_id_masked


def test_reading_a_trace_does_not_append_to_it(container):
    get_account_summary(
        container,
        GetAccountSummaryRequest(account_id=SCENARIO_ACCOUNT, request_id="req-stable"),
    )

    first = trace(container, "req-stable")
    second = trace(container, "req-stable")

    assert first.data is not None
    assert second.data is not None
    assert first.data.event_count == second.data.event_count == 1


def test_an_unknown_correlation_id_returns_an_empty_trace(container):
    response = trace(container, "req-never-used")

    assert_ok(response)
    assert response.data is not None
    assert response.data.event_count == 0
    assert response.data.events == []


def test_a_malformed_correlation_id_is_rejected(container):
    response = trace(container, "not a valid id!")

    assert_error(response, ErrorCode.INVALID_INPUT)


def test_tools_without_an_account_record_no_account(container):
    from src.contracts.requests import ResolveMerchantRequest
    from src.tools.resolve_merchant_tool import resolve_merchant

    resolve_merchant(
        container,
        ResolveMerchantRequest(raw_descriptor="LUMEN STREAM", request_id="req-no-account"),
    )

    response = trace(container, "req-no-account")

    assert response.data is not None
    assert response.data.events[0].account_id_masked is None
