"""MCP resource registration."""

from typing import Any

from fastmcp import FastMCP

from ..app.container import Container
from ..resources.foreign_transaction_fee_policy import (
    POLICY_URI as FOREIGN_TRANSACTION_FEE_POLICY_URI,
)
from ..resources.foreign_transaction_fee_policy import get_foreign_transaction_fee_policy
from ..resources.late_payment_fee_policy import POLICY_URI as LATE_PAYMENT_FEE_POLICY_URI
from ..resources.late_payment_fee_policy import get_late_payment_fee_policy
from ..resources.server_status_resource import get_server_status
from ..resources.unrecognized_transaction_policy import (
    POLICY_URI as UNRECOGNIZED_TRANSACTION_POLICY_URI,
)
from ..resources.unrecognized_transaction_policy import get_unrecognized_transaction_policy


def register_mcp_resources(mcp: FastMCP, container: Container) -> None:
    """Register every resource with the server instance."""

    @mcp.resource("status://server", mime_type="application/json")
    def server_status() -> dict[str, Any]:
        """Whether the synthetic dataset is loaded, plus non-identifying row counts."""
        return get_server_status(container)

    @mcp.resource(UNRECOGNIZED_TRANSACTION_POLICY_URI, mime_type="application/json")
    def unrecognized_transaction_policy() -> dict[str, Any]:
        """Synthetic dispute policy for unrecognized card transactions."""
        return get_unrecognized_transaction_policy()

    @mcp.resource(FOREIGN_TRANSACTION_FEE_POLICY_URI, mime_type="application/json")
    def foreign_transaction_fee_policy() -> dict[str, Any]:
        """Synthetic policy describing foreign-transaction fees."""
        return get_foreign_transaction_fee_policy()

    @mcp.resource(LATE_PAYMENT_FEE_POLICY_URI, mime_type="application/json")
    def late_payment_fee_policy() -> dict[str, Any]:
        """Synthetic policy describing late-payment fees."""
        return get_late_payment_fee_policy()
