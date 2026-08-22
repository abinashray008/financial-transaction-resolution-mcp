"""Defenses against prompt injection into the host agent and Gemini.

Callers, tool arguments, statement descriptors and investigation JSON are
untrusted data. They must never be interpolated into prompts as if they were
instructions, and they must never be able to close a delimiter around
themselves.
"""

from __future__ import annotations

import re
import secrets

# Allow tab/newline/CR so JSON and multi-paragraph replies stay intact.
_DISALLOWED_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_NEWLINE_CONTROLS = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")

# High-signal attempts to steer the host agent rather than answer the customer.
_HOST_AGENT_HIJACK = re.compile(
    r"(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|above|system)\s+instructions"
    r"|call\s+submit_dispute_(?:case|decision)"
    r"|approved\s*=\s*true",
    re.IGNORECASE,
)


def contains_disallowed_controls(value: str, *, allow_newlines: bool = True) -> bool:
    """Whether ``value`` contains ASCII control characters that can break prompts."""
    pattern = _DISALLOWED_CONTROLS if allow_newlines else _NEWLINE_CONTROLS
    return pattern.search(value) is not None


def json_strings_are_safe(value: object) -> bool:
    """Walk parsed JSON and reject strings that carry control characters."""
    if isinstance(value, str):
        return not contains_disallowed_controls(value, allow_newlines=True)
    if isinstance(value, dict):
        return all(json_strings_are_safe(key) and json_strings_are_safe(item) for key, item in value.items())
    if isinstance(value, list):
        return all(json_strings_are_safe(item) for item in value)
    return True


def wrap_untrusted(payload: str, *, label: str = "untrusted_data") -> str:
    """Fence caller-supplied text with a nonce the payload cannot predict or close.

    The begin/end token is regenerated if it already appears in ``payload``, so a
    descriptor or findings blob cannot break out of the data region.
    """
    while True:
        token = secrets.token_hex(16)
        if token not in payload:
            break
    return f"<<<BEGIN_{label} token={token}>>>\n{payload}\n<<<END_{label} token={token}>>>"


def looks_like_host_agent_hijack(text: str) -> bool:
    """True when model output tries to override the host agent instead of answering."""
    return _HOST_AGENT_HIJACK.search(text) is not None
