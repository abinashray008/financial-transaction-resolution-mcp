"""MCP prompt registration."""

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ..prompts.investigate_transaction_prompt import (
    investigate_transaction_prompt as build_investigation_prompt,
)


def register_mcp_prompts(mcp: FastMCP) -> None:
    """Register every reusable prompt with the server instance."""

    @mcp.prompt(title="Investigate a transaction")
    def investigate_transaction(
        account_id: Annotated[
            str,
            Field(description="Account under investigation, for example 'ACCT-0001'. Ask the caller if unknown."),
        ] = "",
        transaction_id: Annotated[
            str,
            Field(
                description=(
                    "Transaction under investigation, for example 'TXN-SCN-DUP-A'. Ask the caller if unknown."
                ),
            ),
        ] = "",
    ) -> str:
        """Structured agentic workflow for investigating a card transaction: ask for any
        missing account_id or transaction_id, select and read the matching policy resource for the
        customer's concern, gather evidence, call `synthesize_investigation` so Gemini can draft
        the customer-facing reply, then if the customer confirms they do not recognize the charge
        call `confirm_unrecognized_transaction` with the issued confirmation_token.
        """
        return build_investigation_prompt(
            account_id=account_id,
            transaction_id=transaction_id,
        )
