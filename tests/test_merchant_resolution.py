"""Deterministic merchant descriptor resolution."""

from src.contracts.requests import ResolveMerchantRequest
from src.domain.enums import Confidence
from src.domain.exceptions import ErrorCode
from src.domain.services.merchant_resolver import normalize_descriptor
from src.tools.resolve_merchant_tool import resolve_merchant
from tests.conftest import assert_error, assert_ok


def resolve(container, descriptor: str):
    return resolve_merchant(container, ResolveMerchantRequest(raw_descriptor=descriptor))


def test_normalization_strips_aggregator_prefix_and_store_number():
    normalized = normalize_descriptor("SQ *RVRBND COFFEE 8821 SEATTLE WA")

    assert normalized.text == "RVRBND COFFEE SEATTLE WA"


def test_normalization_drops_noise_tokens():
    normalized = normalize_descriptor("Northwind Grocery Co Inc")

    assert normalized.text == "NORTHWIND GROCERY"


def test_descriptor_that_differs_from_the_display_name_still_resolves(container):
    response = resolve(container, "SQ *RVRBND COFFEE 8821 SEATTLE WA")

    assert_ok(response)
    assert response.data is not None
    assert response.data.matched is True
    assert response.data.merchant_id == "MERCH-0002"
    assert response.data.display_name == "Riverbend Coffee Roasters"
    assert response.data.match_confidence == Confidence.HIGH
    assert response.data.matched_pattern == "RVRBND COFFEE"


def test_the_explanation_names_the_rule_and_the_pattern(container):
    response = resolve(container, "HALCYON ELEC 0417 SEATTLE WA")

    assert_ok(response)
    assert response.data is not None
    assert response.data.merchant_id == "MERCH-0003"
    assert response.data.match_rule == "prefix_match"
    assert "HALCYON ELEC" in response.data.explanation


def test_an_exact_pattern_scores_highest(container):
    response = resolve(container, "LUMEN STREAM")

    assert_ok(response)
    assert response.data is not None
    assert response.data.merchant_id == "MERCH-0004"
    assert response.data.match_rule == "exact_match"
    assert response.data.match_score == 1.0


def test_resolution_is_deterministic(container):
    first = resolve(container, "CASCADE HTL 221 PORTLAND OR")
    second = resolve(container, "CASCADE HTL 221 PORTLAND OR")

    assert first.data is not None
    assert second.data is not None
    assert first.data.model_dump() == second.data.model_dump()


def test_an_unknown_descriptor_does_not_invent_a_merchant(container):
    response = resolve(container, "ZZQQ UNRECOGNISED VENDOR")

    assert_ok(response)
    assert response.data is not None
    assert response.data.matched is False
    assert response.data.merchant_id is None
    assert response.data.display_name is None


def test_country_and_category_come_from_the_catalog(container):
    response = resolve(container, "MAISON VERTE PARIS FR")

    assert_ok(response)
    assert response.data is not None
    assert response.data.merchant_id == "MERCH-0006"
    assert response.data.country == "FR"
    assert response.data.category == "dining"


def test_a_blank_descriptor_is_rejected(container):
    response = resolve(container, "   ")

    assert_error(response, ErrorCode.INVALID_INPUT)


def test_an_overlong_descriptor_is_rejected(container):
    response = resolve(container, "X" * 500)

    assert_error(response, ErrorCode.INVALID_INPUT)
