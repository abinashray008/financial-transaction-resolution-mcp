"""Descope OAuth for the HTTP MCP transport.

Stdio stays local-trust because MCP OAuth (dynamic client registration and bearer
tokens) is an HTTP concern. HTTP refuses to start unless a Descope well-known URL
is configured. Construction is network-free; JWKS is fetched later during token
validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from fastmcp.server.auth.providers.descope import DescopeProvider

from ..config.settings import Settings, settings

_WELL_KNOWN_SUFFIX = "/.well-known/openid-configuration"


class AuthConfigurationError(ValueError):
    """Raised when HTTP is requested without a usable Descope configuration."""


@dataclass(frozen=True, slots=True)
class DescopeConnection:
    """Parsed Descope well-known URL, ready to construct ``DescopeProvider``."""

    config_url: str | None
    project_id: str | None
    descope_base_url: str | None


def issuer_from_config_url(config_url: str) -> str:
    """Strip the OpenID well-known suffix so clients get the authorization-server issuer."""
    candidate = config_url.strip()
    if candidate.endswith(_WELL_KNOWN_SUFFIX):
        return candidate[: -len(_WELL_KNOWN_SUFFIX)]
    return candidate


def parse_descope_config_url(config_url: str) -> DescopeConnection:
    """Accept either Descope well-known URL shape FastMCP documents.

    Resource-specific MCP Server::

        https://api.descope.com/v1/apps/agentic/P.../M.../.well-known/openid-configuration

    Project-level inbound app (FastMCP 3.4.7 still needs the legacy constructor)::

        https://api.descope.com/v1/apps/P.../.well-known/openid-configuration
    """
    candidate = config_url.strip()
    if not candidate:
        raise AuthConfigurationError(
            "DESCOPE_CONFIG_URL is empty. Create an MCP Server at https://app.descope.com/mcp-servers "
            "with Dynamic Client Registration enabled, then set DESCOPE_CONFIG_URL to its well-known URL.",
        )
    parsed = urlparse(candidate)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise AuthConfigurationError(
            "DESCOPE_CONFIG_URL must be an http(s) OpenID configuration URL from the Descope console.",
        )
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise AuthConfigurationError("DESCOPE_CONFIG_URL must use https unless it points at localhost.")

    issuer = issuer_from_config_url(candidate)
    path_parts = [part for part in urlparse(issuer).path.strip("/").split("/") if part]
    descope_base_url = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")

    if "agentic" in path_parts:
        agentic_index = path_parts.index("agentic")
        if agentic_index + 1 >= len(path_parts) or not path_parts[agentic_index + 1].startswith("P"):
            raise AuthConfigurationError(
                "DESCOPE_CONFIG_URL looks like a Descope MCP Server URL but the project id after "
                "'agentic' is missing. Copy the well-known URL from MCP Server settings.",
            )
        return DescopeConnection(config_url=candidate, project_id=None, descope_base_url=None)

    if len(path_parts) >= 3 and path_parts[0] == "v1" and path_parts[1] == "apps" and path_parts[2].startswith("P"):
        return DescopeConnection(
            config_url=None,
            project_id=path_parts[2],
            descope_base_url=descope_base_url,
        )

    raise AuthConfigurationError(
        "DESCOPE_CONFIG_URL must be a Descope well-known URL containing '/v1/apps/agentic/P…/' "
        "(MCP Server) or '/v1/apps/P…/' (project inbound app). Copy it from "
        "https://app.descope.com/mcp-servers with Dynamic Client Registration enabled.",
    )


def build_descope_provider(app_settings: Settings | None = None) -> DescopeProvider:
    """Build a ``DescopeProvider`` from settings. Does not contact Descope."""
    cfg = app_settings or settings
    connection = parse_descope_config_url(cfg.descope_config_url)
    base_url = cfg.base_url.strip() or "http://127.0.0.1:8000"
    if connection.config_url is not None:
        return DescopeProvider(config_url=connection.config_url, base_url=base_url)
    return DescopeProvider(
        project_id=connection.project_id,
        descope_base_url=connection.descope_base_url,
        base_url=base_url,
    )


def resolve_runtime_auth(*, transport: str, app_settings: Settings | None = None) -> DescopeProvider | None:
    """Attach Descope only on HTTP. Stdio remains unauthenticated local-trust."""
    cfg = app_settings or settings
    if transport == "stdio":
        return None
    if transport not in {"http", "sse", "streamable-http"}:
        raise AuthConfigurationError(f"Unknown transport {transport!r}. Use 'stdio' or 'http'.")
    return build_descope_provider(cfg)
