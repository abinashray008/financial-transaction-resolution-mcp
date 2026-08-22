"""Resolve the authenticated reviewer identity for the human review application.

The MCP write tool never accepts a reviewer id. HTTP review routes take identity
from a **verified** bearer JWT (signature, issuer, audience, expiry) and require
an explicit review scope such as ``dispute:review``. ``X-Reviewer-Id`` and HTML
form fields are not trusted except in the explicitly named ``local-demo`` mode.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from starlette.requests import Request

from ..app.validators import validate_reviewer_id
from ..config.settings import Settings, settings
from ..domain.exceptions import InvalidInputError

logger = logging.getLogger(__name__)

ReviewAuthMode = Literal["jwt", "local-demo"]

DEFAULT_REVIEW_SCOPE = "dispute:review"
_AUTHORIZATION_CLAIM_KEYS = ("scope", "scp", "roles", "role", "permissions")


class ReviewAuthError(Exception):
    """HTTP authentication or authorization failure on a review route."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class TokenClaims(Protocol):
    """Subset of FastMCP ``AccessToken`` used after signature verification."""

    scopes: list[str]
    claims: Mapping[str, Any]


class TokenVerifier(Protocol):
    """Anything that can verify a bearer JWT (DescopeProvider, JWTVerifier)."""

    async def verify_token(self, token: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class ReviewAuth:
    """How review routes establish reviewer identity."""

    mode: ReviewAuthMode
    verifier: TokenVerifier | None = None
    required_scope: str = DEFAULT_REVIEW_SCOPE

    @classmethod
    def local_demo(cls, *, required_scope: str = DEFAULT_REVIEW_SCOPE) -> ReviewAuth:
        """Allow spoofable form/header identity. Local demos only."""
        return cls(mode="local-demo", verifier=None, required_scope=required_scope)

    @property
    def is_local_demo(self) -> bool:
        return self.mode == "local-demo"


def build_review_auth(
    *,
    auth: TokenVerifier | None,
    app_settings: Settings | None = None,
) -> ReviewAuth:
    """Bind review-route auth to settings. ``local-demo`` logs a warning."""
    cfg = app_settings or settings
    required_scope = cfg.review_required_scope.strip() or DEFAULT_REVIEW_SCOPE
    if cfg.review_auth_mode == "local-demo":
        logger.warning(
            "REVIEW_AUTH_MODE=local-demo: reviewer identity is taken from X-Reviewer-Id "
            "or the HTML form and is not authenticated. Do not use this outside a local demo.",
        )
        return ReviewAuth.local_demo(required_scope=required_scope)
    return ReviewAuth(mode="jwt", verifier=auth, required_scope=required_scope)


async def authenticate_reviewer(
    request: Request,
    review_auth: ReviewAuth,
    *,
    form_reviewer_id: str | None = None,
    require_identity: bool = True,
) -> str | None:
    """Return a reviewer id, or ``None`` when local-demo GET does not need one.

    Raises ``ReviewAuthError`` (401/403) or ``InvalidInputError``.
    """
    if review_auth.is_local_demo:
        return _local_demo_identity(
            request,
            form_reviewer_id=form_reviewer_id,
            require_identity=require_identity,
        )
    return await _jwt_identity(request, review_auth)


async def reviewer_id_from_request(
    request: Request,
    review_auth: ReviewAuth,
    *,
    form_reviewer_id: str | None = None,
) -> str:
    """Return the authenticated reviewer id for a decision POST."""
    reviewer_id = await authenticate_reviewer(
        request,
        review_auth,
        form_reviewer_id=form_reviewer_id,
        require_identity=True,
    )
    if reviewer_id is None:
        raise InvalidInputError(
            "A reviewer identity is required. In local-demo mode send X-Reviewer-Id "
            "or a form reviewer_id. Otherwise send a verified bearer token.",
        )
    return reviewer_id


def has_review_permission(access: TokenClaims, required_scope: str) -> bool:
    """Whether verified claims include the review scope or an equivalent role."""
    if required_scope in access.scopes:
        return True
    return required_scope in _authorization_values(access.claims)


def _local_demo_identity(
    request: Request,
    *,
    form_reviewer_id: str | None,
    require_identity: bool,
) -> str | None:
    header = request.headers.get("x-reviewer-id")
    if header and header.strip():
        return validate_reviewer_id(header)
    if form_reviewer_id and form_reviewer_id.strip():
        return validate_reviewer_id(form_reviewer_id)
    if not require_identity:
        return None
    raise InvalidInputError(
        "A reviewer identity is required. In local-demo mode send X-Reviewer-Id or a form reviewer_id.",
    )


async def _jwt_identity(request: Request, review_auth: ReviewAuth) -> str:
    token = _bearer_token(request)
    if token is None:
        raise ReviewAuthError(
            401,
            "UNAUTHORIZED",
            "A bearer token is required to access the review application.",
        )
    if review_auth.verifier is None:
        raise ReviewAuthError(
            401,
            "UNAUTHORIZED",
            "Review authentication is not configured. HTTP review routes require a "
            "JWT verifier, or REVIEW_AUTH_MODE=local-demo for a local demo.",
        )
    access = await review_auth.verifier.verify_token(token)
    if access is None:
        raise ReviewAuthError(
            401,
            "UNAUTHORIZED",
            "The bearer token is invalid or expired.",
        )
    if not has_review_permission(access, review_auth.required_scope):
        raise ReviewAuthError(
            403,
            "FORBIDDEN",
            f"This token is not authorized to review disputes. "
            f"A {review_auth.required_scope!r} scope or role is required.",
        )
    subject = access.claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise ReviewAuthError(
            401,
            "UNAUTHORIZED",
            "The bearer token is missing a subject claim.",
        )
    return validate_reviewer_id(subject)


def _bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    return token or None


def _authorization_values(claims: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for key in _AUTHORIZATION_CLAIM_KEYS:
        raw = claims.get(key)
        if isinstance(raw, str):
            values.extend(part for part in raw.split() if part)
        elif isinstance(raw, list):
            values.extend(item for item in raw if isinstance(item, str) and item)
    return values
