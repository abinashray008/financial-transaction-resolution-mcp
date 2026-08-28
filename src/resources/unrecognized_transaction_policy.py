"""Synthetic policy: ``policy://disputes/unrecognized-transaction``.

Fictional dispute guidance for charges a cardholder does not recognise. Not a
real issuer policy and not affiliated with any financial institution.
"""

from functools import lru_cache
from typing import Any

POLICY_URI = "policy://disputes/unrecognized-transaction"

DISCLAIMER = (
    "This policy is fictional and synthetically generated for a demo MCP server. "
    "It is not affiliated with or representative of any financial institution."
)


@lru_cache(maxsize=1)
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
            "recognise. Evidence tools stay read-only. A dispute case may be opened "
            "only after synthesize_investigation, an explicit customer confirmation, "
            "and confirm_unrecognized_transaction with the server-issued token."
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
            "If the cardholder confirms they do not recognise the charge, call "
            "confirm_unrecognized_transaction with the issued confirmation_token.",
        ],
        "outcomes": [
            {
                "code": "LIKELY_DUPLICATE",
                "when": ("check_duplicate_charge returns duplicate_likely true with MEDIUM or HIGH confidence."),
                "guidance": (
                    "Explain the paired transaction ids and confidence reasons; "
                    "offer customer confirmation rather than claiming "
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
                    "customer confirmation and confirm_unrecognized_transaction if they "
                    "still do not recognise the charge; never treat case creation as "
                    "an issuer approval."
                ),
            },
        ],
        "prohibited_actions": [
            "Do not open a dispute case unless the customer explicitly confirmed they do not recognise the charge.",
            "Do not call confirm_unrecognized_transaction without the server-issued confirmation_token, and never treat approved=true as proof.",
            "Do not state that a card network or issuer approved, filed, submitted, or resolved a dispute.",
            "Do not invent transaction amounts, dates, or merchant names absent from tool evidence.",
        ],
    }
