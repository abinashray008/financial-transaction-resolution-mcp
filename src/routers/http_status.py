"""Unauthenticated HTTP status routes for the streamable-HTTP listener.

FastMCP's MCP endpoint is ``/mcp``. A browser hitting ``/`` used to get 404,
which looks like the process failed to start. These routes are registered as
custom FastMCP HTTP routes and are not gated by Descope.
"""

from __future__ import annotations

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from ..config.settings import settings
from ..security.descope import issuer_from_config_url

_LANDING_STYLE = (
    "body{font-family:system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem;"
    "line-height:1.5;color:#111}"
    "code{background:#f4f4f4;padding:0.1rem 0.3rem}"
    "p{color:#333}"
)


def _issuer_url() -> str | None:
    candidate = settings.descope_config_url.strip()
    if not candidate:
        return None
    return issuer_from_config_url(candidate)


def _public_mcp_url() -> str:
    return f"{settings.base_url.rstrip('/')}/mcp"


def _landing_payload(*, auth_enabled: bool) -> dict[str, object]:
    return {
        "status": "ok",
        "server": settings.server_name,
        "version": settings.server_version,
        "mcp_endpoint": "/mcp",
        "mcp_url": _public_mcp_url(),
        "auth": "descope" if auth_enabled else "none",
        "hint": (
            "The MCP protocol is at /mcp, not /. Unauthenticated /mcp calls return 401 "
            "until the client finishes Descope OAuth."
        ),
    }


def register_http_status_routes(mcp: FastMCP, *, auth_enabled: bool) -> None:
    """Expose ``/``, ``/health``, and root OAuth resource metadata."""

    @mcp.custom_route("/", methods=["GET"], name="http_landing")
    async def landing(request: Request) -> Response:
        payload = _landing_payload(auth_enabled=auth_enabled)
        accept = request.headers.get("accept", "")
        if "text/html" in accept and "application/json" not in accept.split(",")[0]:
            auth_label = "Descope (required on /mcp)" if auth_enabled else "none (stdio-style)"
            html = (
                "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
                f"<title>{payload['server']}</title><style>{_LANDING_STYLE}</style></head><body>"
                f"<h1>{payload['server']}</h1>"
                "<p>The MCP HTTP listener is running.</p>"
                f"<p>Protocol endpoint: <code>{payload['mcp_url']}</code></p>"
                f"<p>Authentication: {auth_label}</p>"
                "<p>Opening this page in a browser is not how you use the server. "
                "Point Cursor or another MCP client at the <code>/mcp</code> URL.</p>"
                "</body></html>"
            )
            return HTMLResponse(html)
        return JSONResponse(payload)

    @mcp.custom_route("/health", methods=["GET"], name="http_health")
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    if not auth_enabled:
        return

    @mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"], name="oauth_resource")
    async def protected_resource_metadata(_request: Request) -> JSONResponse:
        issuer = _issuer_url()
        return JSONResponse(
            {
                "resource": _public_mcp_url(),
                "authorization_servers": [issuer] if issuer else [],
                "scopes_supported": [],
                "bearer_methods_supported": ["header"],
            }
        )
