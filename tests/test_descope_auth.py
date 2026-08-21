"""Descope HTTP authentication wiring. No live Descope tenant is contacted."""

import pytest
from fastmcp.server.auth.providers.descope import DescopeProvider

from src.config.settings import Settings
from src.security.descope import (
    AuthConfigurationError,
    build_descope_provider,
    parse_descope_config_url,
    resolve_runtime_auth,
)

AGENTIC_URL = "https://api.descope.com/v1/apps/agentic/P2TESTPROJECTID/M2TESTMCPID/.well-known/openid-configuration"
PROJECT_URL = "https://api.descope.com/v1/apps/P2TESTPROJECTID/.well-known/openid-configuration"


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_empty_config_url_is_rejected():
    with pytest.raises(AuthConfigurationError, match="DESCOPE_CONFIG_URL is empty"):
        parse_descope_config_url("  ")


def test_non_https_remote_url_is_rejected():
    with pytest.raises(AuthConfigurationError, match="must use https"):
        parse_descope_config_url("http://api.descope.com/v1/apps/P2TESTPROJECTID/.well-known/openid-configuration")


def test_unrelated_url_is_rejected():
    with pytest.raises(AuthConfigurationError, match="well-known URL"):
        parse_descope_config_url("https://example.com/.well-known/openid-configuration")


def test_agentic_mcp_server_url_is_passed_as_config_url():
    connection = parse_descope_config_url(AGENTIC_URL)

    assert connection.config_url == AGENTIC_URL
    assert connection.project_id is None
    assert connection.descope_base_url is None


def test_project_inbound_app_url_uses_legacy_constructor_fields():
    connection = parse_descope_config_url(PROJECT_URL)

    assert connection.config_url is None
    assert connection.project_id == "P2TESTPROJECTID"
    assert connection.descope_base_url == "https://api.descope.com"


def test_build_provider_from_agentic_url_sets_project_id_and_base_url():
    provider = build_descope_provider(
        _settings(descope_config_url=AGENTIC_URL, base_url="http://127.0.0.1:8000"),
    )

    assert isinstance(provider, DescopeProvider)
    assert provider.project_id == "P2TESTPROJECTID"
    assert provider.descope_base_url == "https://api.descope.com"
    assert str(provider.base_url).rstrip("/") == "http://127.0.0.1:8000"


def test_build_provider_from_project_url_sets_project_id_and_base_url():
    provider = build_descope_provider(
        _settings(descope_config_url=PROJECT_URL, base_url="https://mcp.example.test"),
    )

    assert isinstance(provider, DescopeProvider)
    assert provider.project_id == "P2TESTPROJECTID"
    assert provider.descope_base_url == "https://api.descope.com"
    assert str(provider.base_url).rstrip("/") == "https://mcp.example.test"


def test_stdio_does_not_require_descope():
    auth = resolve_runtime_auth(transport="stdio", app_settings=_settings(descope_config_url=""))

    assert auth is None


def test_http_requires_descope_config():
    with pytest.raises(AuthConfigurationError, match="DESCOPE_CONFIG_URL is empty"):
        resolve_runtime_auth(transport="http", app_settings=_settings(descope_config_url=""))


def test_http_attaches_descope_when_configured():
    auth = resolve_runtime_auth(
        transport="http",
        app_settings=_settings(descope_config_url=AGENTIC_URL, base_url="http://127.0.0.1:9000"),
    )

    assert isinstance(auth, DescopeProvider)
    assert auth.project_id == "P2TESTPROJECTID"


def test_unknown_transport_is_rejected():
    with pytest.raises(AuthConfigurationError, match="Unknown transport"):
        resolve_runtime_auth(transport="ftp", app_settings=_settings())


def test_settings_report_whether_descope_is_configured():
    assert _settings(descope_config_url="").descope_configured is False
    assert _settings(descope_config_url=AGENTIC_URL).descope_configured is True


@pytest.mark.asyncio
async def test_attaching_descope_does_not_hide_tools_from_an_in_process_client(container):
    """HTTP JWT checks are transport-level; in-process tests still see every tool."""
    from fastmcp import Client

    from src.server import create_mcp_server
    from tests.test_mcp_server import EXPECTED_TOOLS

    server = create_mcp_server(
        container,
        auth=build_descope_provider(_settings(descope_config_url=AGENTIC_URL)),
    )
    async with Client(server) as client:
        tools = await client.list_tools()

    assert {tool.name for tool in tools} == EXPECTED_TOOLS


def test_http_root_reports_that_the_listener_is_running(container):
    from starlette.testclient import TestClient

    from src.server import create_mcp_server

    server = create_mcp_server(container)
    with TestClient(server.http_app()) as client:
        landing = client.get("/", headers={"accept": "application/json"})
        health = client.get("/health")

    assert landing.status_code == 200
    body = landing.json()
    assert body["status"] == "ok"
    assert body["mcp_endpoint"] == "/mcp"
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


def test_http_mcp_is_unauthorized_without_a_descope_token(container):
    from starlette.testclient import TestClient

    from src.server import create_mcp_server

    server = create_mcp_server(
        container,
        auth=build_descope_provider(
            _settings(descope_config_url=AGENTIC_URL, base_url="http://127.0.0.1:8000"),
        ),
    )
    with TestClient(server.http_app()) as client:
        landing = client.get("/", headers={"accept": "application/json"})
        mcp = client.get("/mcp")
        metadata = client.get("/.well-known/oauth-protected-resource")

    assert landing.status_code == 200
    assert landing.json()["auth"] == "descope"
    assert mcp.status_code == 401
    assert "Bearer" in mcp.headers.get("www-authenticate", "")
    assert metadata.status_code == 200
    assert metadata.json()["resource"] == "http://127.0.0.1:8000/mcp"
