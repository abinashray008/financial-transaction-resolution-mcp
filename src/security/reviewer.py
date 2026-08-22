"""Resolve the authenticated reviewer identity for the human review application.

The MCP write tool never accepts a reviewer id. HTTP review routes take it from
the caller's session: a validated ``X-Reviewer-Id`` header, or the ``sub`` claim
of a bearer JWT when the human app forwarded its access token.
"""

from __future__ import annotations

import base64
import json

from starlette.requests import Request

from ..app.validators import validate_reviewer_id
from ..domain.exceptions import InvalidInputError


def reviewer_id_from_request(request: Request, *, form_reviewer_id: str | None = None) -> str:
    """Return a validated reviewer id or raise ``InvalidInputError``."""
    header = request.headers.get("x-reviewer-id")
    if header and header.strip():
        return validate_reviewer_id(header)

    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        subject = _unverified_jwt_subject(auth.split(" ", 1)[1].strip())
        if subject:
            return validate_reviewer_id(subject)

    if form_reviewer_id and form_reviewer_id.strip():
        return validate_reviewer_id(form_reviewer_id)

    raise InvalidInputError(
        "A reviewer identity is required. Send X-Reviewer-Id or a bearer token with a sub claim.",
    )


def _unverified_jwt_subject(token: str) -> str | None:
    """Read ``sub`` from a JWT payload without verifying the signature.

    Custom FastMCP routes are not wrapped by Descope. The human review app is
    expected to set ``X-Reviewer-Id`` from its authenticated session; the bearer
    fallback is only for hosts that already attach the access token.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload + padding)
        claims = json.loads(decoded)
    except ValueError, json.JSONDecodeError:
        return None
    if not isinstance(claims, dict):
        return None
    subject = claims.get("sub")
    return subject if isinstance(subject, str) and subject.strip() else None
