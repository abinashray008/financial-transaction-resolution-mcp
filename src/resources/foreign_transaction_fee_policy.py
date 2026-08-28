"""Synthetic policy: ``policy://fees/foreign-transaction``.

Fictional guidance for foreign-transaction fees on synthetic card activity. Not
a real issuer policy and not affiliated with any financial institution.
"""

from functools import lru_cache
from typing import Any

POLICY_URI = "policy://fees/foreign-transaction"

DISCLAIMER = (
    "This policy is fictional and synthetically generated for a demo MCP server. "
    "It is not affiliated with or representative of any financial institution."
)


@lru_cache(maxsize=1)
def get_foreign_transaction_fee_policy() -> dict[str, Any]:
    """Return the foreign-transaction fee policy payload."""
    return {
        "uri": POLICY_URI,
        "policy_id": "POL-FEE-FX-001",
        "title": "Foreign Transaction Fee",
        "category": "fees",
        "version": "1.0",
        "effective_date": "2026-01-01",
        "disclaimer": DISCLAIMER,
        "summary": (
            "Explains when a synthetic foreign-transaction fee may appear alongside a "
            "charge settled outside the account holder's home currency or country."
        ),
        "fee_rule": {
            "assessment_rate": "0.0275",
            "assessment_rate_display": "2.75% of the transaction amount",
            "applies_when": [
                "The merchant country differs from the account holder's country of residence.",
                "Or the transaction currency is not the account's billing currency.",
            ],
            "does_not_apply_when": [
                "The merchant country and currency both match the account's home settings.",
                "The charge is reversed before posting.",
                "The product type is marked foreign-fee exempt in the synthetic catalog.",
            ],
            "currency_conversion_note": (
                "Converted amounts in tool responses are informational only. Do not invent "
                "FX rates that are not present in the transaction payload."
            ),
        },
        "required_investigation_steps": [
            "Confirm the transaction with get_transaction_details.",
            "Note merchant.country, currency, and amount from the tool response.",
            (
                "Compare merchant country with the account holder's state/country "
                "context from get_account_summary when relevant."
            ),
            "If the descriptor is unclear, call resolve_merchant before explaining the fee.",
        ],
        "cardholder_explanation_template": (
            "A foreign-transaction fee may apply when a charge posts in another currency or "
            "with a merchant outside the home country. On this synthetic account the illustrative "
            "rate is 2.75% of the transaction amount. Confirm the merchant country and currency "
            "from the investigation tools before discussing the fee."
        ),
        "prohibited_actions": [
            "Do not waive, reverse, or credit a fee from this server.",
            "Do not claim a real FX rate or bank conversion was used unless the tool payload includes it.",
            "Do not treat this policy as advice for live card accounts.",
        ],
    }
