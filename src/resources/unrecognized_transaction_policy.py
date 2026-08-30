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
        "version": "1.2",
        "effective_date": "2026-01-01",
        "disclaimer": DISCLAIMER,
        "summary": (
            "Use when a cardholder reports a posted or pending charge they do not "
            "recognise. Evidence tools stay read-only. After synthesize_investigation, "
            "show the customer_response. If a likely duplicate was found, ask whether "
            "they already contacted the merchant about the duplicate charge. A case "
            "may be opened only after that yes answer and confirm_unrecognized_transaction "
            "with the server-issued token. If they have not contacted the merchant, "
            "tell them to do so first and return if they do not get assistance."
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
            "Present the customer_response, then follow post_synthesis.",
        ],
        "post_synthesis": {
            "when": (
                "After synthesize_investigation has returned and the customer_response "
                "has been shown to the cardholder."
            ),
            "likely_duplicate": {
                "when": "check_duplicate_charge returned duplicate_likely true.",
                "ask": (
                    "Ask the cardholder whether they already contacted the merchant "
                    "about the duplicate charge. Do not skip this question. Do not "
                    "answer it on their behalf."
                ),
                "if_yes": (
                    "If they say yes they contacted the merchant, and data.confirmation "
                    "is present, call confirm_unrecognized_transaction with the issued "
                    "confirmation_token to register an internal PENDING_REVIEW case."
                ),
                "if_no": (
                    "If they say no they have not contacted the merchant, do not open "
                    "a case. Ask them to contact the merchant first, then return so a "
                    "case can be raised if they do not get the required assistance."
                ),
            },
            "no_likely_duplicate": {
                "when": "check_duplicate_charge did not find a likely duplicate.",
                "ask": ("Ask the cardholder in their own words whether they recognise the charge."),
                "if_unrecognized": (
                    "If they explicitly confirm they do not recognise the charge and "
                    "data.confirmation is present, call confirm_unrecognized_transaction "
                    "with the issued confirmation_token."
                ),
            },
        },
        "outcomes": [
            {
                "code": "LIKELY_DUPLICATE",
                "when": ("check_duplicate_charge returns duplicate_likely true with MEDIUM or HIGH confidence."),
                "guidance": (
                    "Explain the paired transaction ids and confidence reasons. After "
                    "the synthesized reply, ask if they already contacted the merchant "
                    "about the duplicate. Open a case only if they say yes and a "
                    "confirmation_token was issued. If they say no, ask them to contact "
                    "the merchant first and return if they do not get assistance."
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
                    "Recommend one next step for a human specialist, or follow "
                    "post_synthesis if they still want a case; never treat case "
                    "creation as an issuer approval."
                ),
            },
        ],
        "prohibited_actions": [
            "Do not open a dispute case for a likely duplicate unless the customer confirmed they already contacted the merchant about the charge.",
            "Do not open a dispute case for a non-duplicate unrecognized charge unless the customer explicitly confirmed they do not recognise it.",
            "Do not call confirm_unrecognized_transaction without the server-issued confirmation_token, and never treat approved=true as proof.",
            "Do not state that a card network or issuer approved, filed, submitted, or resolved a dispute.",
            "Do not invent transaction amounts, dates, or merchant names absent from tool evidence.",
        ],
    }
