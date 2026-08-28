"""Identifier validation.

Validation lives in the application layer rather than in the MCP signatures so
that a malformed identifier produces the same structured ``INVALID_INPUT``
response as any other expected failure, instead of a transport-level error.
"""

import json
import re

from ..domain.enums import (
    APPROVE_REASON_CODES,
    REJECT_REASON_CODES,
    ReviewDecision,
    ReviewReasonCode,
)
from ..domain.exceptions import InvalidInputError
from ..security.prompt_injection import contains_disallowed_controls, json_strings_are_safe

ACCOUNT_ID_PATTERN = re.compile(r"^ACCT-\d{4,8}$")
TRANSACTION_ID_PATTERN = re.compile(r"^TXN-[A-Z0-9][A-Z0-9-]{0,40}$")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
CASE_ID_PATTERN = re.compile(r"^DSP-[A-Z0-9]{4,32}$")
CONFIRMATION_TOKEN_PATTERN = re.compile(r"^cnf_[A-Za-z0-9_-]{32,128}$")
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{8,128}$")
REVIEWER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:@|-]{1,128}$")
MAX_DESCRIPTOR_LENGTH = 128
MAX_CASE_VERSION = 1_000_000
MAX_MERCHANT_QUERY_LENGTH = 128
MAX_FINDINGS_LENGTH = 100_000
MAX_SYNTHESIS_SUMMARY_LENGTH = 20_000
MAX_REVIEW_NOTE_LENGTH = 500
_CONTROL_CHAR_MESSAGE = "must not contain control characters."


def validate_account_id(value: str) -> str:
    """Normalize and check an account identifier."""
    candidate = value.strip().upper()
    if not ACCOUNT_ID_PATTERN.match(candidate):
        raise InvalidInputError("account_id must look like 'ACCT-0001'.")
    return candidate


def validate_transaction_id(value: str) -> str:
    """Normalize and check a transaction identifier."""
    candidate = value.strip().upper()
    if not TRANSACTION_ID_PATTERN.match(candidate):
        raise InvalidInputError("transaction_id must look like 'TXN-0001'.")
    return candidate


def validate_request_id(value: str) -> str:
    """Check a caller-supplied correlation id."""
    candidate = value.strip()
    if not REQUEST_ID_PATTERN.match(candidate):
        raise InvalidInputError(
            "request_id must be 1-64 characters of letters, digits, dash, underscore, dot or colon.",
        )
    return candidate


def validate_case_id(value: str) -> str:
    """Check a server-minted dispute case identifier."""
    candidate = value.strip().upper()
    if not CASE_ID_PATTERN.match(candidate):
        raise InvalidInputError("case_id must look like 'DSP-1A2B3C4D'.")
    return candidate


def validate_confirmation_token(value: str) -> str:
    """Check a one-time confirmation token issued by ``synthesize_investigation``."""
    candidate = value.strip()
    if not CONFIRMATION_TOKEN_PATTERN.match(candidate):
        raise InvalidInputError(
            "confirmation_token must be the opaque token returned by synthesize_investigation.",
        )
    return candidate


def validate_idempotency_key(value: str) -> str:
    """Check the caller's retry key for a confirmation."""
    candidate = value.strip()
    if not IDEMPOTENCY_KEY_PATTERN.match(candidate):
        raise InvalidInputError(
            "idempotency_key must be 8-128 characters of letters, digits, dash, underscore, dot or colon.",
        )
    return candidate


def validate_case_version(value: object) -> int:
    """Check the reviewer's expected case version for optimistic concurrency."""
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise InvalidInputError("expected_version must be a positive integer.")
    try:
        candidate = int(value)
    except ValueError as error:
        raise InvalidInputError("expected_version must be a positive integer.") from error
    if candidate < 1 or candidate > MAX_CASE_VERSION:
        raise InvalidInputError("expected_version must be a positive integer.")
    return candidate


def validate_reviewer_id(value: str) -> str:
    """Check the authenticated reviewer identity stored on an approval record."""
    candidate = value.strip()
    if not REVIEWER_ID_PATTERN.match(candidate):
        raise InvalidInputError(
            "reviewer_id must be 1-128 characters of letters, digits, dash, underscore, dot, colon, at or pipe.",
        )
    return candidate


def validate_raw_descriptor(value: str) -> str:
    """Check a statement descriptor before it is normalized."""
    candidate = value.strip()
    if not candidate:
        raise InvalidInputError("raw_descriptor must not be blank.")
    if len(candidate) > MAX_DESCRIPTOR_LENGTH:
        raise InvalidInputError(f"raw_descriptor must be at most {MAX_DESCRIPTOR_LENGTH} characters.")
    if contains_disallowed_controls(candidate, allow_newlines=False):
        raise InvalidInputError(f"raw_descriptor {_CONTROL_CHAR_MESSAGE}")
    return candidate


def validate_merchant_query(value: str | None) -> str | None:
    """Check an optional merchant search fragment."""
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        raise InvalidInputError("merchant_query must not be blank when provided.")
    if len(candidate) > MAX_MERCHANT_QUERY_LENGTH:
        raise InvalidInputError(f"merchant_query must be at most {MAX_MERCHANT_QUERY_LENGTH} characters.")
    if contains_disallowed_controls(candidate, allow_newlines=False):
        raise InvalidInputError(f"merchant_query {_CONTROL_CHAR_MESSAGE}")
    return candidate


def validate_investigation_findings(value: str) -> str:
    """Require findings to be non-empty JSON an agent can hand to Gemini."""
    candidate = value.strip()
    if not candidate:
        raise InvalidInputError("investigation_findings must not be blank.")
    if len(candidate) > MAX_FINDINGS_LENGTH:
        raise InvalidInputError(f"investigation_findings must be at most {MAX_FINDINGS_LENGTH} characters.")
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as error:
        raise InvalidInputError("investigation_findings must be valid JSON.") from error
    if not isinstance(parsed, dict | list):
        raise InvalidInputError("investigation_findings must be a JSON object or array.")
    if isinstance(parsed, dict) and not parsed:
        raise InvalidInputError("investigation_findings must include at least one tool result.")
    if isinstance(parsed, list) and not parsed:
        raise InvalidInputError("investigation_findings must include at least one tool result.")
    if not json_strings_are_safe(parsed):
        raise InvalidInputError(f"investigation_findings {_CONTROL_CHAR_MESSAGE}")
    return candidate


def validate_synthesis_summary(value: str) -> str:
    """Require the post-synthesis narrative that the dispute proposal is based on."""
    candidate = value.strip()
    if not candidate:
        raise InvalidInputError("synthesis_summary must not be blank.")
    if len(candidate) > MAX_SYNTHESIS_SUMMARY_LENGTH:
        raise InvalidInputError(
            f"synthesis_summary must be at most {MAX_SYNTHESIS_SUMMARY_LENGTH} characters.",
        )
    if contains_disallowed_controls(candidate, allow_newlines=True):
        raise InvalidInputError(f"synthesis_summary {_CONTROL_CHAR_MESSAGE}")
    return candidate


def validate_review_note(value: str | None) -> str | None:
    """Optional reviewer note attached to an approve or reject decision."""
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if len(candidate) > MAX_REVIEW_NOTE_LENGTH:
        raise InvalidInputError(f"note must be at most {MAX_REVIEW_NOTE_LENGTH} characters.")
    if contains_disallowed_controls(candidate, allow_newlines=True):
        raise InvalidInputError(f"note {_CONTROL_CHAR_MESSAGE}")
    return candidate


def validate_review_decision(value: object) -> ReviewDecision:
    """Check the reviewer's decision verb."""
    candidate = value.strip().upper() if isinstance(value, str) else ""
    try:
        return ReviewDecision(candidate)
    except ValueError as error:
        raise InvalidInputError("decision must be 'APPROVE' or 'REJECT'.") from error


def validate_review_reason_code(value: object, *, decision: ReviewDecision) -> ReviewReasonCode:
    """Check the reason code and that it is one this decision allows."""
    candidate = value.strip().upper() if isinstance(value, str) else ""
    try:
        reason_code = ReviewReasonCode(candidate)
    except ValueError as error:
        allowed = ", ".join(sorted(code.value for code in _allowed_reason_codes(decision)))
        raise InvalidInputError(f"reason_code must be one of: {allowed}.") from error
    if reason_code not in _allowed_reason_codes(decision):
        allowed = ", ".join(sorted(code.value for code in _allowed_reason_codes(decision)))
        raise InvalidInputError(f"reason_code for a {decision.value} decision must be one of: {allowed}.")
    return reason_code


def _allowed_reason_codes(decision: ReviewDecision) -> frozenset[ReviewReasonCode]:
    if decision is ReviewDecision.APPROVE:
        return APPROVE_REASON_CODES
    return REJECT_REASON_CODES
