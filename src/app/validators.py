"""Identifier validation.

Validation lives in the application layer rather than in the MCP signatures so
that a malformed identifier produces the same structured ``INVALID_INPUT``
response as any other expected failure, instead of a transport-level error.
"""

import json
import re

from ..domain.exceptions import InvalidInputError

ACCOUNT_ID_PATTERN = re.compile(r"^ACCT-\d{4,8}$")
TRANSACTION_ID_PATTERN = re.compile(r"^TXN-[A-Z0-9][A-Z0-9-]{0,40}$")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
MAX_DESCRIPTOR_LENGTH = 128
MAX_FINDINGS_LENGTH = 100_000
MAX_SYNTHESIS_SUMMARY_LENGTH = 20_000
MAX_DECISION_NOTE_LENGTH = 500


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


def validate_raw_descriptor(value: str) -> str:
    """Check a statement descriptor before it is normalized."""
    candidate = value.strip()
    if not candidate:
        raise InvalidInputError("raw_descriptor must not be blank.")
    if len(candidate) > MAX_DESCRIPTOR_LENGTH:
        raise InvalidInputError(f"raw_descriptor must be at most {MAX_DESCRIPTOR_LENGTH} characters.")
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
    return candidate
