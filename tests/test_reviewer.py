"""Verified reviewer identity for the human review application."""

from __future__ import annotations

import base64
import json

import pytest
from fastmcp.server.auth.providers.jwt import JWTVerifier, RSAKeyPair
from pydantic import ValidationError
from starlette.requests import Request
from starlette.testclient import TestClient

from src.config.settings import Settings
from src.domain.exceptions import InvalidInputError
from src.security.reviewer import (
    DEFAULT_REVIEW_SCOPE,
    ReviewAuth,
    ReviewAuthError,
    authenticate_reviewer,
    build_review_auth,
    has_review_permission,
    reviewer_id_from_request,
)
from src.server import create_mcp_server
from tests.test_dispute_workflow import _draft

REVIEW_ISSUER = "https://auth.test/review"
REVIEW_AUDIENCE = "financial-transaction-resolution-tests"


@pytest.fixture(scope="module")
def review_keys() -> RSAKeyPair:
    return RSAKeyPair.generate()


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def _jwt_review_auth(keys: RSAKeyPair, *, required_scope: str = DEFAULT_REVIEW_SCOPE) -> ReviewAuth:
    return ReviewAuth(
        mode="jwt",
        verifier=JWTVerifier(
            public_key=keys.public_key,
            issuer=REVIEW_ISSUER,
            audience=REVIEW_AUDIENCE,
            algorithm="RS256",
        ),
        required_scope=required_scope,
    )


def _token(
    keys: RSAKeyPair,
    *,
    subject: str = "rev-jwt-1",
    scopes: list[str] | None = None,
    issuer: str = REVIEW_ISSUER,
    audience: str = REVIEW_AUDIENCE,
    expires_in_seconds: int = 3600,
    additional_claims: dict[str, object] | None = None,
) -> str:
    return keys.create_token(
        subject=subject,
        issuer=issuer,
        audience=audience,
        scopes=scopes if scopes is not None else [DEFAULT_REVIEW_SCOPE],
        expires_in_seconds=expires_in_seconds,
        additional_claims=additional_claims,
    )


def _request(**headers: str) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/reviews/inv-1/decision",
            "raw_path": b"/reviews/inv-1/decision",
            "query_string": b"",
            "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
            "client": ("127.0.0.1", 123),
            "server": ("test", 80),
        }
    )


def _unsigned_jwt(*, subject: str = "rev-forged") -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = (
        base64.urlsafe_b64encode(json.dumps({"sub": subject, "scope": DEFAULT_REVIEW_SCOPE}).encode())
        .rstrip(b"=")
        .decode()
    )
    return f"{header}.{payload}.x"


def test_local_demo_mode_is_explicit():
    auth = build_review_auth(auth=None, app_settings=_settings(review_auth_mode="local-demo"))

    assert auth.is_local_demo is True
    assert auth.verifier is None


def test_jwt_mode_is_the_default():
    auth = build_review_auth(auth=None, app_settings=_settings())

    assert auth.mode == "jwt"
    assert auth.required_scope == DEFAULT_REVIEW_SCOPE


def test_invalid_review_auth_mode_is_rejected():
    with pytest.raises(ValidationError):
        _settings(review_auth_mode="trusted-header")


def test_has_review_permission_accepts_scope_or_role():
    class _Access:
        def __init__(self, scopes: list[str], claims: dict[str, object]) -> None:
            self.scopes = scopes
            self.claims = claims

    assert has_review_permission(_Access(["dispute:review"], {}), "dispute:review") is True
    assert has_review_permission(_Access([], {"roles": ["dispute:review"]}), "dispute:review") is True
    assert has_review_permission(_Access([], {"permissions": ["other"]}), "dispute:review") is False


@pytest.mark.asyncio
async def test_local_demo_accepts_header_or_form_identity():
    review_auth = ReviewAuth.local_demo()

    from_header = await reviewer_id_from_request(_request(**{"x-reviewer-id": "rev-header-1"}), review_auth)
    from_form = await reviewer_id_from_request(_request(), review_auth, form_reviewer_id="rev-form-1")

    assert from_header == "rev-header-1"
    assert from_form == "rev-form-1"


@pytest.mark.asyncio
async def test_local_demo_does_not_read_unverified_jwt():
    review_auth = ReviewAuth.local_demo()

    with pytest.raises(InvalidInputError, match="reviewer identity is required"):
        await reviewer_id_from_request(
            _request(authorization=f"Bearer {_unsigned_jwt()}"),
            review_auth,
        )


@pytest.mark.asyncio
async def test_jwt_mode_requires_a_bearer_token(review_keys: RSAKeyPair):
    review_auth = _jwt_review_auth(review_keys)

    with pytest.raises(ReviewAuthError) as raised:
        await authenticate_reviewer(_request(**{"x-reviewer-id": "rev-spoof"}), review_auth)

    assert raised.value.status_code == 401
    assert raised.value.code == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_jwt_mode_rejects_unsigned_payload(review_keys: RSAKeyPair):
    review_auth = _jwt_review_auth(review_keys)

    with pytest.raises(ReviewAuthError) as raised:
        await authenticate_reviewer(_request(authorization=f"Bearer {_unsigned_jwt()}"), review_auth)

    assert raised.value.status_code == 401


@pytest.mark.asyncio
async def test_jwt_mode_rejects_wrong_signature(review_keys: RSAKeyPair):
    other_keys = RSAKeyPair.generate()
    review_auth = _jwt_review_auth(review_keys)

    with pytest.raises(ReviewAuthError) as raised:
        await authenticate_reviewer(
            _request(authorization=f"Bearer {_token(other_keys)}"),
            review_auth,
        )

    assert raised.value.status_code == 401


@pytest.mark.asyncio
async def test_jwt_mode_rejects_issuer_audience_and_expiry(review_keys: RSAKeyPair):
    review_auth = _jwt_review_auth(review_keys)

    cases = (
        _token(review_keys, issuer="https://evil.test"),
        _token(review_keys, audience="someone-else"),
        _token(review_keys, expires_in_seconds=-30),
    )
    for token in cases:
        with pytest.raises(ReviewAuthError) as raised:
            await authenticate_reviewer(_request(authorization=f"Bearer {token}"), review_auth)
        assert raised.value.status_code == 401


@pytest.mark.asyncio
async def test_jwt_mode_requires_review_scope(review_keys: RSAKeyPair):
    review_auth = _jwt_review_auth(review_keys)
    token = _token(review_keys, scopes=["mcp:tools"])

    with pytest.raises(ReviewAuthError) as raised:
        await authenticate_reviewer(_request(authorization=f"Bearer {token}"), review_auth)

    assert raised.value.status_code == 403
    assert raised.value.code == "FORBIDDEN"


@pytest.mark.asyncio
async def test_jwt_mode_accepts_role_claim(review_keys: RSAKeyPair):
    review_auth = _jwt_review_auth(review_keys)
    token = _token(review_keys, scopes=[], additional_claims={"roles": ["dispute:review"]})

    reviewer_id = await reviewer_id_from_request(
        _request(authorization=f"Bearer {token}"),
        review_auth,
        form_reviewer_id="rev-form-spoof",
    )

    assert reviewer_id == "rev-jwt-1"


@pytest.mark.asyncio
async def test_jwt_mode_identity_comes_from_sub_not_header(review_keys: RSAKeyPair):
    review_auth = _jwt_review_auth(review_keys)
    token = _token(review_keys, subject="rev-from-claims")

    reviewer_id = await reviewer_id_from_request(
        _request(authorization=f"Bearer {token}", **{"x-reviewer-id": "rev-header-spoof"}),
        review_auth,
        form_reviewer_id="rev-form-spoof",
    )

    assert reviewer_id == "rev-from-claims"


def test_http_review_get_and_post_require_verified_jwt(container, review_keys: RSAKeyPair):
    request_id = "inv-rev-jwt"
    assert _draft(container, request_id=request_id).status == "ok"
    server = create_mcp_server(container, review_auth=_jwt_review_auth(review_keys))
    token = _token(review_keys, subject="rev-http-jwt")

    with TestClient(server.http_app()) as client:
        denied_get = client.get(f"/reviews/{request_id}", headers={"accept": "application/json"})
        denied_post = client.post(
            f"/reviews/{request_id}/decision",
            headers={"x-reviewer-id": "rev-spoof", "accept": "application/json"},
            json={"decision": "approved"},
        )
        shown = client.get(
            f"/reviews/{request_id}",
            headers={"authorization": f"Bearer {token}", "accept": "application/json"},
        )
        minted = client.post(
            f"/reviews/{request_id}/decision",
            headers={
                "authorization": f"Bearer {token}",
                "x-reviewer-id": "rev-spoof",
                "accept": "application/json",
            },
            json={"decision": "approved", "decision_note": "Reviewed", "reviewer_id": "rev-form-spoof"},
        )

    assert denied_get.status_code == 401
    assert denied_get.json()["error"]["code"] == "UNAUTHORIZED"
    assert denied_get.headers.get("www-authenticate", "").startswith("Bearer")
    assert denied_post.status_code == 401
    assert shown.status_code == 200
    assert shown.json()["transaction_id"] == "TXN-SCN-DUP-A"
    assert minted.status_code == 201
    assert minted.json()["reviewer_id"] == "rev-http-jwt"


def test_http_review_html_has_no_reviewer_field_in_jwt_mode(container, review_keys: RSAKeyPair):
    request_id = "inv-rev-html-jwt"
    assert _draft(container, request_id=request_id).status == "ok"
    server = create_mcp_server(container, review_auth=_jwt_review_auth(review_keys))
    token = _token(review_keys)

    with TestClient(server.http_app()) as client:
        shown = client.get(
            f"/reviews/{request_id}",
            headers={"authorization": f"Bearer {token}", "accept": "text/html"},
        )

    assert shown.status_code == 200
    assert "Reviewer id" not in shown.text
    assert "Authenticated as" in shown.text
    assert "dispute:review" in shown.text
