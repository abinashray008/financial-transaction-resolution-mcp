"""Deterministic dispute-draft construction."""

import json

from src.domain.enums import DisputeReasonCode
from src.domain.services.dispute_evidence import (
    DEFAULT_POLICY_URI,
    PROPOSED_ACTION,
    REQUIRED_EVIDENCE_TOOLS,
    build_dispute_evidence,
    hash_dispute_evidence,
)
from src.resources.policies import POLICY_LOADERS
from src.security.masking import mask_account_id

ACCOUNT_ID = "ACCT-0001"
MASKED_ACCOUNT = mask_account_id(ACCOUNT_ID)


def _draft(*, findings: dict, synthesis: str = "Customer does not recognize the charge."):
    return build_dispute_evidence(
        account_id=ACCOUNT_ID,
        masked_account_id=MASKED_ACCOUNT,
        transaction_id="TXN-SCN-DUP-A",
        investigation_id="inv-draft-1",
        merchant_display_name="Halcyon Electronics",
        amount="89.99",
        currency="USD",
        transaction_date="2026-06-12",
        synthesis_summary=synthesis,
        investigation_findings=json.dumps(findings),
        proposed_reason="Unrecognized charge at Halcyon Electronics for 89.99 USD on 2026-06-12.",
    )


def test_policy_reason_map_covers_every_server_policy():
    assert DEFAULT_POLICY_URI in POLICY_LOADERS
    assert set(POLICY_LOADERS) >= {DEFAULT_POLICY_URI}


def test_sparse_findings_are_pending_specialist_review():
    draft = _draft(findings={"get_transaction_details": {"status": "ok", "data": {"transaction": {}}}})

    assert draft.reason_code == DisputeReasonCode.NEEDS_SPECIALIST_REVIEW
    assert draft.applied_policy == DEFAULT_POLICY_URI
    assert draft.proposed_action == PROPOSED_ACTION
    assert len(draft.evidence_hash) == 64
    assert ACCOUNT_ID not in " ".join(draft.verified_evidence)
    missing_tools = {tool for tool in REQUIRED_EVIDENCE_TOOLS if any(tool in item for item in draft.missing_evidence)}
    assert missing_tools == {"get_account_summary", "resolve_merchant", "check_duplicate_charge"}


def test_duplicate_likely_with_complete_evidence():
    draft = _draft(
        findings={
            "selected_policy_uri": "policy://disputes/unrecognized-transaction",
            "get_account_summary": {"status": "ok", "data": {"account_status": "active"}},
            "get_transaction_details": {"status": "ok", "data": {"transaction": {"transaction_id": "TXN-SCN-DUP-A"}}},
            "resolve_merchant": {
                "status": "ok",
                "data": {"matched": True, "display_name": "Halcyon Electronics", "match_confidence": "HIGH"},
            },
            "check_duplicate_charge": {
                "status": "ok",
                "data": {
                    "duplicate_likely": True,
                    "confidence": "HIGH",
                    "candidate_transaction_ids": ["TXN-SCN-DUP-B"],
                },
            },
        }
    )

    assert draft.reason_code == DisputeReasonCode.LIKELY_DUPLICATE
    assert draft.missing_evidence == ()
    assert any("TXN-SCN-DUP-B" in item for item in draft.verified_evidence)


def test_foreign_fee_policy_reason_when_evidence_is_complete():
    draft = _draft(
        findings={
            "selected_policy_uri": "policy://fees/foreign-transaction",
            "get_account_summary": {"status": "ok", "data": {"account_status": "active"}},
            "get_transaction_details": {"status": "ok", "data": {"transaction": {"transaction_id": "TXN-SCN-DUP-A"}}},
            "resolve_merchant": {
                "status": "ok",
                "data": {"matched": True, "display_name": "Halcyon Electronics", "match_confidence": "HIGH"},
            },
            "check_duplicate_charge": {
                "status": "ok",
                "data": {"duplicate_likely": False, "confidence": "LOW", "candidate_transaction_ids": []},
            },
        }
    )

    assert draft.reason_code == DisputeReasonCode.FOREIGN_TRANSACTION_FEE
    assert draft.applied_policy == "policy://fees/foreign-transaction"


def test_evidence_hash_is_stable_and_changes_when_reason_changes():
    findings = {"get_transaction_details": {"status": "ok", "data": {"transaction": {}}}}
    first = _draft(findings=findings)
    second = _draft(findings=findings)
    different = _draft(findings=findings, synthesis="A different narrative.")

    assert first.evidence_hash == second.evidence_hash
    assert first.evidence_hash != different.evidence_hash
    rebuilt = hash_dispute_evidence(
        account_id=ACCOUNT_ID,
        transaction_id="TXN-SCN-DUP-A",
        investigation_id="inv-draft-1",
        reason=first.reason,
        reason_code=first.reason_code.value,
        verified_evidence=first.verified_evidence,
        missing_evidence=first.missing_evidence,
        applied_policy=first.applied_policy,
        proposed_action=first.proposed_action,
        merchant_display_name="Halcyon Electronics",
        amount="89.99",
        currency="USD",
        transaction_date="2026-06-12",
        synthesis_summary="Customer does not recognize the charge.",
    )
    assert rebuilt == first.evidence_hash
