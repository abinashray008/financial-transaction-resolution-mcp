"""Server configuration, loaded from the environment or a local ``.env`` file."""

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

IN_MEMORY_DATABASE = ":memory:"


class Settings(BaseSettings):
    """Runtime configuration for the Financial Transaction Resolution MCP server."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    server_name: str = Field(
        default="financial-transaction-resolution",
        alias="SERVER_NAME",
        description="Name advertised to MCP clients.",
    )
    server_version: str = Field(
        default="0.1.0",
        alias="SERVER_VERSION",
        description="Version advertised to MCP clients.",
    )
    database_path: str = Field(
        default="data/transactions.db",
        alias="DATABASE_PATH",
        description="SQLite file holding the synthetic dataset, relative to the project root.",
    )
    checkpoint_path: str = Field(
        default="data/checkpoints.db",
        alias="CHECKPOINT_PATH",
        description=(
            "SQLite file for LangGraph HITL workflow checkpoints, relative to the project root. "
            "Demo only; production should use PostgreSQL (PostgresSaver)."
        ),
    )
    log_level: str = Field(
        default="INFO",
        alias="LOG_LEVEL",
        description="Log level for the server's stderr logger.",
    )
    gemini_api_key: str = Field(
        default="",
        alias="GEMINI_API_KEY",
        description="API key for Gemini synthesis. Required only for synthesize_investigation.",
    )
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        alias="GEMINI_MODEL",
        description="Gemini model id used to synthesize a customer-facing investigation reply.",
    )
    opik_api_key: str = Field(
        default="",
        alias="OPIK_API_KEY",
        description="API key for Opik Cloud. Optional; evidence tools run without it.",
    )
    opik_workspace: str = Field(
        default="",
        alias="OPIK_WORKSPACE",
        description="Opik Cloud workspace name.",
    )
    opik_project_name: str = Field(
        default="financial-transaction-resolution",
        alias="OPIK_PROJECT_NAME",
        description="Opik project that receives investigation traces.",
    )
    opik_use_local: bool = Field(
        default=False,
        alias="OPIK_USE_LOCAL",
        description="If true, send traces to a self-hosted Opik instance instead of Opik Cloud.",
    )
    opik_url_override: str = Field(
        default="",
        alias="OPIK_URL_OVERRIDE",
        description="Opik API URL override, for example http://localhost:5173/api.",
    )
    opik_enabled: bool = Field(
        default=True,
        alias="OPIK_ENABLED",
        description="Master switch. Tracing still requires OPIK_API_KEY or OPIK_USE_LOCAL.",
    )
    descope_config_url: str = Field(
        default="",
        alias="DESCOPE_CONFIG_URL",
        description=("Descope MCP Server or inbound-app OpenID configuration URL. Required for HTTP transport."),
    )
    base_url: str = Field(
        default="http://127.0.0.1:8000",
        alias="BASE_URL",
        description="Public URL of this MCP server, advertised in OAuth protected-resource metadata.",
    )
    http_host: str = Field(
        default="127.0.0.1",
        alias="HTTP_HOST",
        description="Bind address for HTTP transport.",
    )
    http_port: int = Field(
        default=8000,
        alias="HTTP_PORT",
        description="Bind port for HTTP transport.",
    )
    confirmation_ttl_seconds: int = Field(
        default=900,
        alias="CONFIRMATION_TTL_SECONDS",
        description="How long a synthesize_investigation confirmation_token remains usable.",
        ge=60,
        le=86_400,
    )
    review_auth_mode: Literal["jwt", "local-demo"] = Field(
        default="jwt",
        alias="REVIEW_AUTH_MODE",
        description=(
            "jwt: reviewer identity comes from a verified JWT. "
            "local-demo: allow X-Reviewer-Id and HTML form reviewer ids (local only)."
        ),
    )
    review_required_scope: str = Field(
        default="dispute:review",
        alias="REVIEW_REQUIRED_SCOPE",
        description="Scope or role a verified reviewer JWT must include.",
        min_length=1,
        max_length=128,
    )

    @field_validator("review_auth_mode", mode="before")
    @classmethod
    def _normalize_review_auth_mode(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("review_required_scope", mode="before")
    @classmethod
    def _strip_review_required_scope(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @property
    def descope_configured(self) -> bool:
        """Whether a Descope well-known URL is present."""
        return bool(self.descope_config_url.strip())

    @property
    def resolved_database_path(self) -> Path:
        """Absolute path of the SQLite file."""
        candidate = Path(self.database_path)
        return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate

    @property
    def resolved_checkpoint_path(self) -> str:
        """Path passed to the LangGraph SQLite checkpointer."""
        if self.checkpoint_path == IN_MEMORY_DATABASE:
            return IN_MEMORY_DATABASE
        candidate = Path(self.checkpoint_path)
        resolved = candidate if candidate.is_absolute() else PROJECT_ROOT / candidate
        return str(resolved)

    @property
    def database_url(self) -> str:
        """SQLAlchemy URL for the configured database."""
        if self.database_path == IN_MEMORY_DATABASE:
            return "sqlite+pysqlite:///:memory:"
        return f"sqlite+pysqlite:///{self.resolved_database_path}"

    @property
    def opik_tracing_enabled(self) -> bool:
        """Whether agent traces should be exported to Opik."""
        if not self.opik_enabled:
            return False
        return bool(self.opik_api_key.strip()) or self.opik_use_local


settings = Settings()
