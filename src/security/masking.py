"""PII masking helpers.

Nothing that leaves the server and nothing that reaches the audit log passes
through unmasked. These helpers are deliberately defensive: if a caller ever
hands them more digits than a last-four, the extra digits are dropped rather
than echoed back.
"""

import re

MASK_SEGMENT = "****"
CARD_MASK_PREFIX = "\u2022\u2022\u2022\u2022 "
_VISIBLE_TAIL = 4
_MAX_PREFIX = 8
_MAX_INPUT = 32

_NON_DIGITS = re.compile(r"\D")
_DISALLOWED = re.compile(r"[^A-Za-z0-9-]")
# Reviewer subjects arrive from a JWT and may be emails or namespaced ids.
_ACTOR_DISALLOWED = re.compile(r"[^A-Za-z0-9_.:@|-]")
_ACTOR_VISIBLE_EDGE = 2


def _sanitize(value: str) -> str:
    """Drop anything that is not part of an identifier and cap the length.

    Callers control the identifier they send, so this keeps free text out of
    the audit log even when the identifier turns out to be invalid.
    """
    return _DISALLOWED.sub("", value.strip())[:_MAX_INPUT]


def mask_account_id(account_id: str) -> str:
    """Mask an account identifier, keeping its prefix and last four characters.

    ``ACCT-0001`` becomes ``ACCT-****0001``.
    """
    return _mask_prefixed_id(account_id)


def mask_customer_id(customer_id: str) -> str:
    """Mask a customer identifier. Names are never used or returned.

    ``CUST-0001`` becomes ``CUST-****0001``.
    """
    return _mask_prefixed_id(customer_id)


def _mask_prefixed_id(identifier: str) -> str:
    cleaned = _sanitize(identifier)
    if not cleaned:
        raise ValueError("Cannot mask an empty identifier.")

    prefix, separator, body = cleaned.rpartition("-")
    if not separator:
        prefix, body = "", cleaned

    masked_body = f"{MASK_SEGMENT}{body[-_VISIBLE_TAIL:]}"
    if not prefix:
        return masked_body
    return f"{prefix[:_MAX_PREFIX]}-{masked_body}"


def mask_optional_account_id(account_id: str | None) -> str | None:
    """Mask an account identifier when one is present.

    Unmaskable input becomes a bare mask rather than an error, so a malformed
    identifier can still be audited without ever being stored verbatim.
    """
    if account_id is None:
        return None
    if not _sanitize(account_id):
        return MASK_SEGMENT
    return mask_account_id(account_id)


def mask_actor_id(actor_id: str | None) -> str | None:
    """Mask an authenticated actor identity for the lifecycle audit log.

    Enough of the identity survives to tell two reviewers apart in a trail,
    but a full email address or JWT subject is never stored.
    """
    if actor_id is None:
        return None
    cleaned = _ACTOR_DISALLOWED.sub("", actor_id.strip())[:_MAX_INPUT]
    if not cleaned:
        return MASK_SEGMENT
    if len(cleaned) <= _ACTOR_VISIBLE_EDGE * 2:
        return f"{cleaned[:1]}{MASK_SEGMENT}"
    return f"{cleaned[:_ACTOR_VISIBLE_EDGE]}{MASK_SEGMENT}{cleaned[-_ACTOR_VISIBLE_EDGE:]}"


def mask_card(card_last_four: str) -> str:
    """Render a card identifier as a masked last-four.

    Only the final four digits of the input survive, so passing a longer value
    can never leak a full card number.
    """
    digits = _NON_DIGITS.sub("", card_last_four)
    if not digits:
        raise ValueError("Cannot mask a card identifier without digits.")
    return f"{CARD_MASK_PREFIX}{digits[-_VISIBLE_TAIL:]}"
