"""Registry of synthetic policy resources this server actually serves.

``synthesize_investigation`` loads policy from here instead of trusting a
policy document the caller embedded in investigation findings.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .foreign_transaction_fee_policy import POLICY_URI as FOREIGN_TRANSACTION_FEE_POLICY_URI
from .foreign_transaction_fee_policy import get_foreign_transaction_fee_policy
from .late_payment_fee_policy import POLICY_URI as LATE_PAYMENT_FEE_POLICY_URI
from .late_payment_fee_policy import get_late_payment_fee_policy
from .unrecognized_transaction_policy import POLICY_URI as UNRECOGNIZED_TRANSACTION_POLICY_URI
from .unrecognized_transaction_policy import get_unrecognized_transaction_policy

PolicyLoader = Callable[[], dict[str, Any]]

POLICY_LOADERS: dict[str, PolicyLoader] = {
    UNRECOGNIZED_TRANSACTION_POLICY_URI: get_unrecognized_transaction_policy,
    FOREIGN_TRANSACTION_FEE_POLICY_URI: get_foreign_transaction_fee_policy,
    LATE_PAYMENT_FEE_POLICY_URI: get_late_payment_fee_policy,
}


def load_policy(uri: str) -> dict[str, Any] | None:
    """Return the server-owned policy for ``uri``, or ``None`` if it is unknown."""
    loader = POLICY_LOADERS.get(uri.strip())
    return None if loader is None else loader()


def trusted_policy_json(findings: object) -> str | None:
    """Load the authoritative policy named by ``selected_policy_uri`` in findings."""
    if not isinstance(findings, dict):
        return None
    uri = findings.get("selected_policy_uri")
    if not isinstance(uri, str):
        return None
    policy = load_policy(uri)
    if policy is None:
        return None
    return json.dumps(policy, ensure_ascii=False, sort_keys=True)


def drop_caller_policy_document(findings: object) -> object:
    """Remove a caller-supplied ``policy`` object so it cannot override ours."""
    if not isinstance(findings, dict) or "policy" not in findings:
        return findings
    return {key: value for key, value in findings.items() if key != "policy"}
