"""Synthetic policy: ``policy://disputes/unrecognized-transaction``.

Fictional dispute guidance for charges a cardholder does not recognise. Not a
real issuer policy and not affiliated with any financial institution.
"""

from typing import Any

POLICY_URI = "policy://disputes/unrecognized-transaction"

DISCLAIMER = (
    "This policy is fictional and synthetically generated for a demo MCP server. "
    "It is not affiliated with or representative of any financial institution."
)


def get_unrecognized_transaction_policy() -> dict[str, Any]:
    """Return the unrecognized-transaction dispute policy payload."""
    return {
        "uri": POLICY_URI,
        "policy_id": "POL-DSP-UNREC-001",
        "title": "Unrecognized Transaction Dispute",
        "category": "disputes",
        "version": "1.1",
        "effective_date": "2026-01-01",
        "disclaimer": DISCLAIMER,
        "summary": (
            "Use when a cardholder reports a posted or pending charge they do not "
            "recognise. Evidence tools stay read-only. A dispute case may be registered "
            "only after synthesize_investigation and an explicit human approval through "
            "the LangGraph workflow (propose_dispute_case, then submit_dispute_decision)."
        ),
        "eligibility": [
            "The transaction belongs to the account under investigation.",
            "The charge is not an expected recurring subscription the cardholder previously authorised.",
            "The charge is not a settled authorization hold that matches a later posted amount.",
            "The cardholder has reviewed merchant resolution output when the descriptor is abbreviated.",
        ],
        "required_investigation_steps": [
            "Confirm account context with get_account_summary.",
            "Confirm the charge with get_transaction_details using account_id and transaction_id.",
            "Resolve unfamiliar descriptors with resolve_merchant.",
            "Run check_duplicate_charge to rule out an exact or near duplicate.",
            "Document request_id values for audit with get_audit_trace.",
            "Synthesize a customer-facing reply with synthesize_investigation.",
            "If the cardholder wants a case, call propose_dispute_case, then wait "
            "for an explicit human approval before submit_dispute_decision.",
        ],
        "outcomes": [
            {
                "code": "LIKELY_DUPLICATE",
                "when": ("check_duplicate_charge returns duplicate_likely true with MEDIUM or HIGH confidence."),
                "guidance": (
                    "Explain the paired transaction ids and confidence reasons; "
                    "offer the human-in-the-loop dispute workflow rather than claiming "
                    "a dispute was filed."
                ),
            },
            {
                "code": "MERCHANT_CLARIFIED",
                "when": ("resolve_merchant maps the descriptor to a recognisable display name with HIGH confidence."),
                "guidance": (
                    "Present the normalized merchant name and category so the cardholder can confirm recognition."
                ),
            },
            {
                "code": "NEEDS_SPECIALIST_REVIEW",
                "when": (
                    "Evidence is incomplete, confidence is LOW, or the cardholder "
                    "still does not recognise the merchant."
                ),
                "guidance": (
                    "Recommend one next step for a human specialist, or offer "
                    "propose_dispute_case if the cardholder still wants a case; never "
                    "treat registration as an issuer approval."
                ),
            },
        ],
        "prohibited_actions": [
            "Do not register a dispute case unless the end user explicitly approved the proposal in this conversation.",
            "Do not call submit_dispute_decision with approved=true to skip the human gate.",
            "Do not state that a card network or issuer approved, filed, submitted, or resolved a dispute.",
            "Do not invent transaction amounts, dates, or merchant names absent from tool evidence.",
        ],
    }
