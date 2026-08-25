"""The MCP surface: discovery, schemas and a full investigation through a client."""

import json

import pytest
from fastmcp import Client

from src.app.container import Container
from src.config.settings import settings
from src.contracts.responses import SynthesisResult
from src.domain.enums import ApprovalDecision
from src.server import create_mcp_server
from tests.conftest import OTHER_ACCOUNT, SCENARIO_ACCOUNT

EXPECTED_TOOLS = {
    "get_account_summary",
    "search_transactions",
    "get_transaction_details",
    "resolve_merchant",
    "check_duplicate_charge",
    "get_audit_trace",
    "synthesize_investigation",
    "create_dispute_draft",
    "submit_dispute_case",
}
WRITE_TOOLS = {"submit_dispute_case"}


@pytest.fixture
def server(container: Container):
    return create_mcp_server(container)


async def test_every_tool_is_discoverable(server):
    async with Client(server) as client:
        tools = await client.list_tools()

    assert {tool.name for tool in tools} == EXPECTED_TOOLS


async def test_evidence_tools_are_annotated_read_only(server):
    async with Client(server) as client:
        tools = await client.list_tools()

    for tool in tools:
        assert tool.annotations is not None, f"{tool.name} has no annotations"
        if tool.name in WRITE_TOOLS:
            assert tool.annotations.readOnlyHint is False, f"{tool.name} should be writable"
            continue
        assert tool.annotations.readOnlyHint is True, f"{tool.name} is not marked read-only"
        if tool.name == "synthesize_investigation":
            assert tool.annotations.openWorldHint is True
        else:
            assert tool.annotations.openWorldHint is False


async def test_every_tool_documents_its_inputs_and_outputs(server):
    async with Client(server) as client:
        tools = await client.list_tools()

    for tool in tools:
        assert tool.description, f"{tool.name} has no description"
        assert tool.inputSchema.get("properties"), f"{tool.name} has no input schema"
        assert tool.outputSchema is not None, f"{tool.name} has no output schema"
        if tool.name == "submit_dispute_case":
            properties = set(tool.inputSchema.get("properties", {}))
            assert properties == {"request_id", "approval_id"}
            assert "approved" not in properties


async def test_the_prompt_is_discoverable_with_its_arguments(server):
    async with Client(server) as client:
        prompts = await client.list_prompts()

    assert [prompt.name for prompt in prompts] == ["investigate_transaction"]
    argument_names = {argument.name for argument in prompts[0].arguments or []}
    assert argument_names == {"account_id", "transaction_id"}


async def test_the_prompt_renders_the_investigation_workflow(server):
    async with Client(server) as client:
        result = await client.get_prompt(
            "investigate_transaction",
            {
                "account_id": SCENARIO_ACCOUNT,
                "transaction_id": "TXN-SCN-DUP-A",
            },
        )

    rendered = result.messages[0].content.text

    assert SCENARIO_ACCOUNT in rendered
    assert "TXN-SCN-DUP-A" in rendered
    assert "customer_statement" not in rendered
    assert "get_account_summary" in rendered
    assert "check_duplicate_charge" in rendered
    assert "synthesize_investigation" in rendered
    assert "create_dispute_draft" in rendered
    assert "submit_dispute_case" in rendered
    assert "Operating loop" in rendered
    assert "Phase D" in rendered
    assert "policy://disputes/unrecognized-transaction" in rendered
    assert "policy://fees/foreign-transaction" in rendered
    assert "policy://fees/late-payment" in rendered
    assert "selected_policy_uri" in rendered
    assert "fictional" in rendered
    assert "minted" in rendered
    assert "approval_id" in rendered
    assert "Untrusted data" in rendered
    assert "opaque tokens" in rendered


async def test_the_prompt_asks_when_transaction_id_is_missing(server):
    async with Client(server) as client:
        result = await client.get_prompt(
            "investigate_transaction",
            {"account_id": SCENARIO_ACCOUNT},
        )

    rendered = result.messages[0].content.text

    assert "not yet provided" in rendered
    assert "ask the caller" in rendered
    assert "Phase 0" in rendered
    assert "transaction_id" in rendered


async def test_the_prompt_asks_for_missing_account_and_transaction_ids(server):
    async with Client(server) as client:
        result = await client.get_prompt(
            "investigate_transaction",
            {},
        )

    rendered = result.messages[0].content.text

    assert "Phase 0" in rendered
    assert "ask the caller for it" in rendered
    assert rendered.count("not yet provided") >= 2
    assert "Never invent `account_id` or `transaction_id`" in rendered


async def test_the_status_resource_reports_a_ready_dataset(server):
    async with Client(server) as client:
        resources = await client.list_resources()
        contents = await client.read_resource("status://server")

    assert {str(resource.uri) for resource in resources} == {
        "status://server",
        "policy://disputes/unrecognized-transaction",
        "policy://fees/foreign-transaction",
        "policy://fees/late-payment",
    }
    status = json.loads(contents[0].text)
    assert status["read_only_evidence_tools"] is True
    assert status["dispute_registration"] is True
    assert status["dataset_ready"] is True
    assert status["merchant_count"] == 75
    assert status["http_auth"] in {"descope", "not_configured"}
    assert isinstance(status["descope_configured"], bool)


async def test_policy_resources_return_synthetic_guidance(server):
    async with Client(server) as client:
        unrecognized = json.loads((await client.read_resource("policy://disputes/unrecognized-transaction"))[0].text)
        foreign_fee = json.loads((await client.read_resource("policy://fees/foreign-transaction"))[0].text)
        late_fee = json.loads((await client.read_resource("policy://fees/late-payment"))[0].text)

    assert unrecognized["policy_id"] == "POL-DSP-UNREC-001"
    assert "fictional" in unrecognized["disclaimer"]
    assert foreign_fee["fee_rule"]["assessment_rate"] == "0.0275"
    assert late_fee["fee_rule"]["flat_fee_amount"] == "39.00"


async def test_an_expected_failure_arrives_as_a_structured_error(server):
    """A domain failure is data, not a transport exception."""
    async with Client(server) as client:
        result = await client.call_tool("get_account_summary", {"account_id": "ACCT-9999"})

    payload = result.structured_content
    assert payload is not None
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "ACCOUNT_NOT_FOUND"
    assert payload["data"] is None


async def test_error_messages_carry_no_implementation_detail(server):
    async with Client(server) as client:
        result = await client.call_tool(
            "get_transaction_details", {"account_id": "ACCT-9999", "transaction_id": "TXN-X"}
        )

    message = result.structured_content["error"]["message"]

    assert "SELECT" not in message.upper()
    assert "Traceback" not in message
    assert "/" not in message


async def test_cross_account_access_is_blocked_through_the_client(server):
    async with Client(server) as client:
        result = await client.call_tool(
            "get_transaction_details",
            {"account_id": OTHER_ACCOUNT, "transaction_id": "TXN-SCN-DUP-A"},
        )

    assert result.structured_content["error"]["code"] == "TRANSACTION_NOT_FOUND"


async def test_end_to_end_investigation_of_a_duplicate_charge(engine):
    """The full workflow the prompt describes, driven through a real client."""
    from src.app.container import build_container_from_engine
    from src.server import create_mcp_server

    class FakeSynthesisClient:
        def synthesize(
            self,
            *,
            account_id: str,
            transaction_id: str,
            investigation_findings: str,
            trusted_policy: str | None = None,
        ) -> SynthesisResult:
            return SynthesisResult(
                customer_response=f"Verified: duplicate likely for {transaction_id} on {account_id}.",
                recommended_action="CREATE_DISPUTE_DRAFT",
                case_status="NOT_CREATED",
                claims_refund_issued=False,
                claims_transaction_reversed=False,
            )

    container = build_container_from_engine(engine, synthesis=FakeSynthesisClient())
    server = create_mcp_server(container)
    request_id = "inv-e2e-001"

    async with Client(server) as client:
        summary = await client.call_tool(
            "get_account_summary",
            {"account_id": SCENARIO_ACCOUNT, "request_id": request_id},
        )
        search = await client.call_tool(
            "search_transactions",
            {
                "account_id": SCENARIO_ACCOUNT,
                "minimum_amount": "89.99",
                "maximum_amount": "89.99",
                "request_id": request_id,
            },
        )
        details = await client.call_tool(
            "get_transaction_details",
            {
                "account_id": SCENARIO_ACCOUNT,
                "transaction_id": "TXN-SCN-DUP-A",
                "request_id": request_id,
            },
        )
        merchant = await client.call_tool(
            "resolve_merchant",
            {"raw_descriptor": "HALCYON ELEC 0417 SEATTLE WA", "request_id": request_id},
        )
        duplicate = await client.call_tool(
            "check_duplicate_charge",
            {
                "account_id": SCENARIO_ACCOUNT,
                "transaction_id": "TXN-SCN-DUP-A",
                "request_id": request_id,
            },
        )
        synthesized = await client.call_tool(
            "synthesize_investigation",
            {
                "account_id": SCENARIO_ACCOUNT,
                "transaction_id": "TXN-SCN-DUP-A",
                "investigation_findings": json.dumps(
                    {
                        "get_account_summary": summary.structured_content,
                        "search_transactions": search.structured_content,
                        "get_transaction_details": details.structured_content,
                        "resolve_merchant": merchant.structured_content,
                        "check_duplicate_charge": duplicate.structured_content,
                    }
                ),
                "request_id": request_id,
            },
        )
        findings = json.dumps(
            {
                "get_account_summary": summary.structured_content,
                "search_transactions": search.structured_content,
                "get_transaction_details": details.structured_content,
                "resolve_merchant": merchant.structured_content,
                "check_duplicate_charge": duplicate.structured_content,
            }
        )
        proposed = await client.call_tool(
            "create_dispute_draft",
            {
                "account_id": SCENARIO_ACCOUNT,
                "transaction_id": "TXN-SCN-DUP-A",
                "investigation_findings": findings,
                "synthesis_summary": synthesized.structured_content["data"]["customer_response"],
                "request_id": request_id,
            },
        )
        approval = container.approval_service.record_decision(
            request_id=request_id,
            reviewer_id="rev-e2e-1",
            decision=ApprovalDecision.APPROVED,
            decision_note="Customer confirmed the duplicate posting.",
        )
        decided = await client.call_tool(
            "submit_dispute_case",
            {
                "request_id": request_id,
                "approval_id": approval.approval_id,
            },
        )
        audit = await client.call_tool("get_audit_trace", {"request_id": request_id})

    # Step 1: minimum account context, with no customer name anywhere.
    account = summary.structured_content["data"]
    assert account["masked_account_id"] == "ACCT-****0001"
    assert account["masked_card"].endswith("4412")
    assert "Lindholm" not in json.dumps(summary.structured_content)

    # Step 2: locate the charge.
    found = {t["transaction_id"] for t in search.structured_content["data"]["transactions"]}
    assert found == {"TXN-SCN-DUP-A", "TXN-SCN-DUP-B"}

    # Step 3: confirm it.
    transaction = details.structured_content["data"]["transaction"]
    assert transaction["amount"] == "89.99"
    assert transaction["raw_descriptor"] == "HALCYON ELEC 0417 SEATTLE WA"

    # Step 4: resolve the unfamiliar descriptor.
    resolved = merchant.structured_content["data"]
    assert resolved["display_name"] == "Halcyon Electronics"
    assert resolved["match_confidence"] == "HIGH"

    # Step 5: the duplicate verdict, with its reasoning.
    verdict = duplicate.structured_content["data"]
    assert verdict["duplicate_likely"] is True
    assert verdict["confidence"] == "HIGH"
    assert verdict["candidate_transaction_ids"] == ["TXN-SCN-DUP-B"]
    assert verdict["reasons"]

    # Step 6: Gemini synthesis of the gathered tool envelopes.
    reply = synthesized.structured_content["data"]
    assert "duplicate likely" in reply["customer_response"]
    assert reply["model_name"] == settings.gemini_model
    assert reply["recommended_action"] == "CREATE_DISPUTE_DRAFT"
    assert reply["case_status"] == "NOT_CREATED"
    assert reply["claims_refund_issued"] is False
    assert reply["claims_transaction_reversed"] is False

    # Step 7: LangGraph returns a PENDING_REVIEW draft; no case is written yet.
    proposal = proposed.structured_content["data"]
    assert proposal["status"] == "pending_review"
    assert proposal["transaction_id"] == "TXN-SCN-DUP-A"
    assert proposal["reason_code"] == "LIKELY_DUPLICATE"
    assert proposal["applied_policy"] == "policy://disputes/unrecognized-transaction"
    assert proposal["draft_hash"]
    assert proposal["review_path"] == f"/reviews/{request_id}"
    assert proposal["missing_evidence"] == []
    assert "Lindholm" not in json.dumps(proposed.structured_content)

    # Step 8: after a minted approval_id, register a case for the same customer.
    decision = decided.structured_content["data"]
    assert decision["registered"] is True
    assert decision["case_id"].startswith("DSP-")
    assert decision["approval_id"] == approval.approval_id
    stored = container.disputes.get_for_account(SCENARIO_ACCOUNT, "TXN-SCN-DUP-A")
    account = container.accounts.get_with_customer_state(SCENARIO_ACCOUNT)
    assert stored is not None
    assert account is not None
    assert stored.customer_id == account.account.customer_id

    # Step 9: the whole investigation is auditable under one correlation id.
    trace = audit.structured_content["data"]
    assert trace["event_count"] == 8
    assert [event["tool_name"] for event in trace["events"]] == [
        "get_account_summary",
        "search_transactions",
        "get_transaction_details",
        "resolve_merchant",
        "check_duplicate_charge",
        "synthesize_investigation",
        "create_dispute_draft",
        "submit_dispute_case",
    ]
    assert "HALCYON" not in json.dumps(trace)


async def test_an_investigation_of_the_hotel_hold_reports_no_duplicate(server):
    """The same workflow must not raise a false positive on a settled hold."""
    async with Client(server) as client:
        duplicate = await client.call_tool(
            "check_duplicate_charge",
            {"account_id": SCENARIO_ACCOUNT, "transaction_id": "TXN-SCN-HOLD-02"},
        )

    verdict = duplicate.structured_content["data"]

    assert verdict["candidate_transaction_ids"] == ["TXN-SCN-HOLD-01"]
    assert verdict["duplicate_likely"] is False
    assert verdict["confidence"] == "LOW"
    assert "authorization hold" in verdict["reasons"][0]
