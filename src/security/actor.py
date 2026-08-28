"""Resolve the authenticated host-agent identity for lifecycle audit events.

HTTP MCP calls take identity from a verified bearer token when one is present.
Stdio and in-process tests have no token, so they record an explicit local-trust
actor rather than inventing a customer or reviewer.
"""

from __future__ import annotations

from ..domain.enums import AuditActorType

LOCAL_HOST_ACTOR_ID = "local-stdio"


def current_host_actor() -> tuple[AuditActorType, str]:
    """Return the host-agent actor type and a sanitizable identifier."""
    try:
        from fastmcp.server.dependencies import get_access_token
    except Exception:
        return AuditActorType.HOST_AGENT, LOCAL_HOST_ACTOR_ID

    try:
        token = get_access_token()
    except Exception:
        return AuditActorType.HOST_AGENT, LOCAL_HOST_ACTOR_ID
    if token is None:
        return AuditActorType.HOST_AGENT, LOCAL_HOST_ACTOR_ID
    claims = getattr(token, "claims", None)
    subject = claims.get("sub") if isinstance(claims, dict) else None
    if isinstance(subject, str) and subject.strip():
        return AuditActorType.HOST_AGENT, subject.strip()
    client_id = getattr(token, "client_id", None)
    if isinstance(client_id, str) and client_id.strip():
        return AuditActorType.HOST_AGENT, client_id.strip()
    return AuditActorType.HOST_AGENT, LOCAL_HOST_ACTOR_ID
