"""Synthetic policy: ``policy://fees/late-payment``.

Fictional guidance for late-payment fees on synthetic card accounts. Not a real
issuer policy and not affiliated with any financial institution.
"""

from typing import Any

POLICY_URI = "policy://fees/late-payment"

DISCLAIMER = (
    "This policy is fictional and synthetically generated for a demo MCP server. "
    "It is not affiliated with or representative of any financial institution."
)


def get_late_payment_fee_policy() -> dict[str, Any]:
    """Return the late-payment fee policy payload."""
    return {
        "uri": POLICY_URI,
        "policy_id": "POL-FEE-LATE-001",
        "title": "Late Payment Fee",
        "category": "fees",
        "version": "1.0",
        "effective_date": "2026-01-01",
        "disclaimer": DISCLAIMER,
        "summary": (
            "Describes when a synthetic late-payment fee may be assessed after a minimum "
            "payment is not received by the statement due date."
        ),
        "fee_rule": {
            "flat_fee_amount": "39.00",
            "flat_fee_currency": "USD",
            "grace_period_days": 1,
            "applies_when": [
                "The account status is active.",
                "No qualifying payment posted on or before the statement due date plus the grace period.",
                "The account is not in a synthetic hardship or fee-waiver program.",
            ],
            "does_not_apply_when": [
                "A payment covering at least the minimum due posted within the grace period.",
                "The account is closed or suspended before the due date.",
                "The billing cycle has no minimum payment due.",
            ],
            "first_late_fee_cap_note": (
                "For demo purposes, the first late fee in a rolling twelve-month window is capped "
                "at $29.00; subsequent fees use the flat $39.00 amount."
            ),
        },
        "required_investigation_steps": [
            "Confirm account status and open date with get_account_summary.",
            "If a specific fee transaction is in question, confirm it with get_transaction_details.",
            "Do not infer payment history that tools did not return.",
            "Recommend specialist review when payment timing cannot be verified from available tools.",
        ],
        "cardholder_explanation_template": (
            "A late-payment fee may appear when the minimum payment is not received by the due date "
            "plus a one-day synthetic grace period. The illustrative fee is $39.00 USD, with a lower "
            "first-fee cap of $29.00 in a rolling twelve-month window. This server cannot waive fees."
        ),
        "prohibited_actions": [
            "Do not waive, reverse, or credit a late fee from this server.",
            "Do not claim a payment posted unless a tool response shows it.",
            "Do not treat this policy as advice for live card accounts.",
        ],
    }
