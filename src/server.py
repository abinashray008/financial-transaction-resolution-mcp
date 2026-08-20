"""Server entry point.

Creates the FastMCP application, wires the dependency container into the
routers, and runs over stdio.
"""

import logging
from argparse import ArgumentParser

from fastmcp import FastMCP

from .app.container import Container, build_container
from .config.settings import settings
from .observability.tracing import configure_opik
from .routers.prompts import register_mcp_prompts
from .routers.resources import register_mcp_resources
from .routers.tools import register_mcp_tools
from .utils.logging import configure_logging

logger = logging.getLogger(__name__)

INSTRUCTIONS = """Read-only investigation tools for synthetic financial card transactions.

All customers, accounts, transactions, policies and decision rules served here are fictional and
synthetically generated. No employer, card-network or customer data was used. This server is not
affiliated with or representative of any financial institution.

Every evidence tool is read-only and scoped to a single account. Start with the
`investigate_transaction` prompt: map the customer's concern to a policy resource
(`policy://disputes/unrecognized-transaction`, `policy://fees/foreign-transaction`, or
`policy://fees/late-payment`), gather evidence with the tools, then finish with
`synthesize_investigation`, which calls Gemini to draft the customer-facing reply using that policy.
Tool responses share one envelope: `status`, `request_id`, and either `data` or a structured
`error`. Pass the `request_id` to `get_audit_trace` to see what was called.
"""


def create_mcp_server(container: Container | None = None) -> FastMCP:
    """Create and configure the MCP server instance.

    Accepts a container so tests can point the server at their own database.
    """
    configure_logging(settings.log_level)
    configure_opik()
    resolved = container or build_container()

    if not resolved.dataset_ready():
        logger.warning(
            "The synthetic dataset is missing. Run 'uv run python scripts/generate_data.py --seed 42'.",
        )

    mcp: FastMCP = FastMCP(
        name=settings.server_name,
        version=settings.server_version,
        instructions=INSTRUCTIONS,
        # An unexpected exception must never carry SQL, paths or stack detail to
        # a client. Expected failures use the structured error envelope instead.
        mask_error_details=True,
    )

    register_mcp_tools(mcp, resolved)
    register_mcp_resources(mcp, resolved)
    register_mcp_prompts(mcp)
    return mcp


# Module-level instance so `fastmcp run src/server.py` and the MCP Inspector can
# discover the server without executing the __main__ block.
mcp = create_mcp_server()


if __name__ == "__main__":
    parser = ArgumentParser(description="Financial Transaction Resolution MCP server")
    parser.add_argument(
        "--transport",
        "-t",
        choices=["stdio"],
        default="stdio",
        help="Transport to serve on. Only stdio is supported in this increment.",
    )
    parser.parse_args()
    mcp.run()
