"""Identifier validation.

Validation lives in the application layer rather than in the MCP signatures so
that a malformed identifier produces the same structured ``INVALID_INPUT``
response as any other expected failure, instead of a transport-level error.
"""

import json
import re

from ..domain.exceptions import InvalidInputError
from ..security.prompt_injection import contains_disallowed_controls, json_strings_are_safe

ACCOUNT_ID_PATTERN = re.compile(r"^ACCT-\d{4,8}$")
TRANSACTION_ID_PATTERN = re.compile(r"^TXN-[A-Z0-9][A-Z0-9-]{0,40}$")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
APPROVAL_ID_PATTERN = re.compile(r"^apr-[A-Za-z0-9]{3,32}$")
REVIEWER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:@|-]{1,128}$")
MAX_DESCRIPTOR_LENGTH = 128
MAX_MERCHANT_QUERY_LENGTH = 128
MAX_FINDINGS_LENGTH = 100_000
MAX_SYNTHESIS_SUMMARY_LENGTH = 20_000
MAX_DECISION_NOTE_LENGTH = 500
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


def validate_approval_id(value: str) -> str:
    """Check a minted one-time approval id."""
    candidate = value.strip()
    if not APPROVAL_ID_PATTERN.match(candidate):
        raise InvalidInputError("approval_id must look like 'apr-901'.")
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


def validate_decision_note(value: str | None) -> str | None:
    """Optional human note attached to an approve or decline decision."""
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if len(candidate) > MAX_DECISION_NOTE_LENGTH:
        raise InvalidInputError(f"decision_note must be at most {MAX_DECISION_NOTE_LENGTH} characters.")
    if contains_disallowed_controls(candidate, allow_newlines=True):
        raise InvalidInputError(f"decision_note {_CONTROL_CHAR_MESSAGE}")
    return candidate
