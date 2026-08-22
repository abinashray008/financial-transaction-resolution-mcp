"""The response envelope shared by every tool.

Each tool answers with the same shape: a status, the correlation id used for
auditing, and exactly one of ``data`` or ``error``. Clients can therefore
branch on ``status`` without special-casing individual tools.
"""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema

from ..domain.exceptions import ErrorCode

# Amounts stay ``Decimal`` in Python and serialize to JSON as strings, which
# keeps them exact. Pydantic's default schema for ``Decimal`` carries a regex
# its own engine cannot compile, so the schema is declared explicitly instead.
Money = Annotated[
    Decimal,
    WithJsonSchema({"type": "string", "description": "Exact decimal amount, serialized as a string."}),
]


class ToolErrorBody(BaseModel):
    """A stable, client-safe error."""

    model_config = ConfigDict(frozen=True)

    code: ErrorCode = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Client-safe explanation with no implementation detail.")


class ToolResponseBase(BaseModel):
    """Fields shared by every tool response."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok", "error"] = Field(description="Whether the call produced data or an error.")
    request_id: str = Field(description="Correlation id for this call; pass it to get_audit_trace.")
    error: ToolErrorBody | None = Field(default=None, description="Present only when status is 'error'.")
