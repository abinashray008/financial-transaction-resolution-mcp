"""Deterministic dispute-draft construction from investigation findings.

Creates a PENDING_REVIEW proposal: identifiers, reason code, verified vs
missing evidence, applied policy, proposed action, and a content hash.
No model calls and no database writes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from ..enums import Confidence, DisputeReasonCode

DEFAULT_POLICY_URI = "policy://disputes/unrecognized-transaction"
PROPOSED_ACTION = (
    "Register a synthetic dispute case file after explicit human approval. "
    "This does not file, approve, or resolve a dispute with an issuer or card network."
)
REQUIRED_EVIDENCE_TOOLS = (
    "get_account_summary",
    "get_transaction_details",
    "resolve_merchant",
    "check_duplicate_charge",
)
_POLICY_REASON: dict[str, DisputeReasonCode] = {
    "policy://disputes/unrecognized-transaction": DisputeReasonCode.UNRECOGNIZED_TRANSACTION,
    "policy://fees/foreign-transaction": DisputeReasonCode.FOREIGN_TRANSACTION_FEE,
    "policy://fees/late-payment": DisputeReasonCode.LATE_PAYMENT_FEE,
}
_CONFIDENCE_RANK = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}


@dataclass(frozen=True, slots=True)
class DisputeDraftContent:
    """The reviewable body of a dispute draft, independent of customer identity."""

    reason: str
    reason_code: DisputeReasonCode
    verified_evidence: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    applied_policy: str
    proposed_action: str
    draft_hash: str


def build_dispute_draft(
    *,
    account_id: str,
    masked_account_id: str,
    transaction_id: str,
    request_id: str,
    merchant_display_name: str,
    amount: str,
    currency: str,
    transaction_date: str,
    synthesis_summary: str,
    investigation_findings: str,
    proposed_reason: str,
) -> DisputeDraftContent:
    """Derive a hash-stable draft from stored facts plus caller-supplied findings."""
    findings = _parse_findings(investigation_findings)
    applied_policy = _applied_policy(findings)
    verified = _verified_evidence(
        findings,
        masked_account_id=masked_account_id,
        transaction_id=transaction_id,
        merchant_display_name=merchant_display_name,
        amount=amount,
        currency=currency,
        transaction_date=transaction_date,
    )
    missing = _missing_evidence(findings)
    reason_code = _reason_code(findings, applied_policy=applied_policy, missing=missing)
    draft_hash = hash_dispute_draft(
        account_id=account_id,
        transaction_id=transaction_id,
        request_id=request_id,
        reason=proposed_reason,
        reason_code=reason_code.value,
        verified_evidence=verified,
        missing_evidence=missing,
        applied_policy=applied_policy,
        proposed_action=PROPOSED_ACTION,
        merchant_display_name=merchant_display_name,
        amount=amount,
        currency=currency,
        transaction_date=transaction_date,
        synthesis_summary=synthesis_summary,
    )
    return DisputeDraftContent(
        reason=proposed_reason,
        reason_code=reason_code,
        verified_evidence=verified,
        missing_evidence=missing,
        applied_policy=applied_policy,
        proposed_action=PROPOSED_ACTION,
        draft_hash=draft_hash,
    )


def hash_dispute_draft(
    *,
    account_id: str,
    transaction_id: str,
    request_id: str,
    reason: str,
    reason_code: str,
    verified_evidence: tuple[str, ...],
    missing_evidence: tuple[str, ...],
    applied_policy: str,
    proposed_action: str,
    merchant_display_name: str,
    amount: str,
    currency: str,
    transaction_date: str,
    synthesis_summary: str,
) -> str:
    """SHA-256 over the canonical draft payload. Status is not hashed."""
    payload = {
        "account_id": account_id,
        "amount": amount,
        "applied_policy": applied_policy,
        "currency": currency,
        "merchant_display_name": merchant_display_name,
        "missing_evidence": list(missing_evidence),
        "proposed_action": proposed_action,
        "reason": reason,
        "reason_code": reason_code,
        "request_id": request_id,
        "synthesis_summary": synthesis_summary,
        "transaction_date": transaction_date,
        "transaction_id": transaction_id,
        "verified_evidence": list(verified_evidence),
    }
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_findings(investigation_findings: str) -> dict[str, object]:
    try:
        parsed = json.loads(investigation_findings)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _applied_policy(findings: dict[str, object]) -> str:
    uri = findings.get("selected_policy_uri")
    if isinstance(uri, str) and uri.strip() in _POLICY_REASON:
        return uri.strip()
    return DEFAULT_POLICY_URI


def _tool_envelope(findings: dict[str, object], tool_name: str) -> dict[str, object] | None:
    raw = findings.get(tool_name)
    return raw if isinstance(raw, dict) else None


def _ok_data(findings: dict[str, object], tool_name: str) -> dict[str, object] | None:
    envelope = _tool_envelope(findings, tool_name)
    if envelope is None or envelope.get("status") != "ok":
        return None
    data = envelope.get("data")
    return data if isinstance(data, dict) else None


def _missing_evidence(findings: dict[str, object]) -> tuple[str, ...]:
    missing: list[str] = []
    for tool_name in REQUIRED_EVIDENCE_TOOLS:
        envelope = _tool_envelope(findings, tool_name)
        if envelope is None:
            missing.append(f"{tool_name} result is missing from investigation findings.")
            continue
        status = envelope.get("status")
        if status != "ok":
            code = ""
            error = envelope.get("error")
            if isinstance(error, dict) and isinstance(error.get("code"), str):
                code = f" ({error['code']})"
            missing.append(f"{tool_name} returned an error{code}.")
            continue
        if _ok_data(findings, tool_name) is None:
            missing.append(f"{tool_name} result is missing data.")
    return tuple(missing)


def _verified_evidence(
    findings: dict[str, object],
    *,
    masked_account_id: str,
    transaction_id: str,
    merchant_display_name: str,
    amount: str,
    currency: str,
    transaction_date: str,
) -> tuple[str, ...]:
    verified: list[str] = [
        (f"Account {masked_account_id} and transaction {transaction_id} were supplied as the dispute subject."),
        (
            f"Posted facts from the account-scoped ledger: {merchant_display_name} "
            f"for {amount} {currency} on {transaction_date}."
        ),
    ]
    summary = _ok_data(findings, "get_account_summary")
    if summary is not None:
        account_status = summary.get("account_status")
        account_type = summary.get("account_type")
        parts = ["Account summary confirmed"]
        if isinstance(account_type, str) and account_type:
            parts.append(account_type)
        if isinstance(account_status, str) and account_status:
            parts.append(account_status)
        verified.append(" ".join(parts) + ".")
    details = _ok_data(findings, "get_transaction_details")
    if details is not None:
        transaction = details.get("transaction")
        detail_id = transaction_id
        if isinstance(transaction, dict) and isinstance(transaction.get("transaction_id"), str):
            detail_id = transaction["transaction_id"]
        verified.append(f"get_transaction_details confirmed {detail_id} on the supplied account.")
    merchant = _ok_data(findings, "resolve_merchant")
    if merchant is not None:
        display_name = merchant.get("display_name")
        confidence = merchant.get("match_confidence")
        if merchant.get("matched") and isinstance(display_name, str) and display_name:
            label = display_name
            if isinstance(confidence, str) and confidence:
                label = f"{display_name} ({confidence})"
            verified.append(f"Merchant resolved as {label}.")
        else:
            verified.append("Merchant resolution ran but did not produce a confident match.")
    duplicate = _ok_data(findings, "check_duplicate_charge")
    if duplicate is not None:
        likely = duplicate.get("duplicate_likely") is True
        confidence = duplicate.get("confidence")
        candidates = duplicate.get("candidate_transaction_ids")
        candidate_text = ""
        if isinstance(candidates, list) and candidates:
            ids = [item for item in candidates if isinstance(item, str)]
            if ids:
                candidate_text = f" versus {', '.join(ids)}"
        confidence_text = f" ({confidence})" if isinstance(confidence, str) and confidence else ""
        if likely:
            verified.append(f"Duplicate check reported a likely duplicate{candidate_text}{confidence_text}.")
        else:
            verified.append(f"Duplicate check did not report a likely duplicate{candidate_text}{confidence_text}.")
    return tuple(verified)


def _reason_code(
    findings: dict[str, object],
    *,
    applied_policy: str,
    missing: tuple[str, ...],
) -> DisputeReasonCode:
    if missing:
        return DisputeReasonCode.NEEDS_SPECIALIST_REVIEW
    duplicate = _ok_data(findings, "check_duplicate_charge")
    if duplicate is not None and duplicate.get("duplicate_likely") is True:
        confidence = duplicate.get("confidence")
        if isinstance(confidence, str):
            try:
                rank = _CONFIDENCE_RANK[Confidence(confidence)]
            except ValueError:
                rank = 0
            if rank >= _CONFIDENCE_RANK[Confidence.MEDIUM]:
                return DisputeReasonCode.LIKELY_DUPLICATE
    return _POLICY_REASON.get(applied_policy, DisputeReasonCode.UNRECOGNIZED_TRANSACTION)
