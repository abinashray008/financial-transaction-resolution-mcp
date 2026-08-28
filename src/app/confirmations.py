"""Issue and verify the customer's confirmation that a charge is unrecognized.

``synthesize_investigation`` issues a short-lived, one-time token together with
an immutable copy of the evidence the reply was based on. The host agent shows
the reply, asks the customer, and only then hands that token back to
``confirm_unrecognized_transaction``.

The token is the whole point of the gate: the model never mints it, the caller
cannot forge it, and it is bound to one investigation, account and transaction.
Only its SHA-256 digest is stored, so a leaked row cannot be replayed.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from ..domain.exceptions import (
    AccountNotFoundError,
    ConfirmationExpiredError,
    ConfirmationMismatchError,
    ConfirmationNotFoundError,
    DisputeAlreadyExistsError,
    TransactionNotFoundError,
)
from ..domain.models import CustomerConfirmation, IssuedConfirmation
from ..domain.services.dispute_evidence import build_case_reason, build_dispute_evidence
from ..repositories.accounts import AccountRepository
from ..repositories.confirmations import ConfirmationRepository
from ..repositories.disputes import DisputeRepository
from ..repositories.transactions import TransactionRepository
from ..security.masking import mask_account_id

DEFAULT_CONFIRMATION_TTL_SECONDS = 900
CONFIRMATION_TOKEN_PREFIX = "cnf_"
_TRANSACTION_NOT_FOUND_MESSAGE = "No transaction with that transaction_id exists on the supplied account."


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _confirmation_id_factory() -> str:
    return f"cnf-{uuid.uuid4().hex[:12]}"


def _case_id_factory() -> str:
    return f"DSP-{uuid.uuid4().hex[:8].upper()}"


def _snapshot_id_factory() -> str:
    return f"snp-{uuid.uuid4().hex[:12]}"


def new_confirmation_token() -> str:
    """Mint an opaque one-time confirmation token."""
    return f"{CONFIRMATION_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def hash_confirmation_token(token: str) -> str:
    """Digest a confirmation token for storage and lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ConfirmationService:
    """Creates confirmation challenges and verifies them exactly once."""

    def __init__(
        self,
        *,
        confirmations: ConfirmationRepository,
        accounts: AccountRepository,
        transactions: TransactionRepository,
        disputes: DisputeRepository,
        clock: Callable[[], datetime] = _utc_now,
        confirmation_id_factory: Callable[[], str] = _confirmation_id_factory,
        case_id_factory: Callable[[], str] = _case_id_factory,
        snapshot_id_factory: Callable[[], str] = _snapshot_id_factory,
        token_factory: Callable[[], str] = new_confirmation_token,
        ttl_seconds: int = DEFAULT_CONFIRMATION_TTL_SECONDS,
    ) -> None:
        self._confirmations = confirmations
        self._accounts = accounts
        self._transactions = transactions
        self._disputes = disputes
        self._clock = clock
        self._confirmation_id_factory = confirmation_id_factory
        self._case_id_factory = case_id_factory
        self._snapshot_id_factory = snapshot_id_factory
        self._token_factory = token_factory
        self._ttl_seconds = ttl_seconds

    def new_snapshot_id(self) -> str:
        """Identifier for the evidence snapshot written when a case is created."""
        return self._snapshot_id_factory()

    def now(self) -> datetime:
        """The service clock, so callers timestamp consistently with it."""
        return self._clock()

    def issue(
        self,
        *,
        investigation_id: str,
        account_id: str,
        transaction_id: str,
        synthesis_summary: str,
        investigation_findings: str,
    ) -> IssuedConfirmation:
        """Snapshot the evidence for a charge and mint a one-time confirmation token."""
        record = self._accounts.get_with_customer_state(account_id)
        if record is None:
            raise AccountNotFoundError("No account exists for the supplied account_id.")
        txn = self._transactions.get_for_account(account_id, transaction_id)
        if txn is None:
            raise TransactionNotFoundError(_TRANSACTION_NOT_FOUND_MESSAGE)
        if self._disputes.get_for_account(account_id, transaction_id) is not None:
            raise DisputeAlreadyExistsError(
                "A dispute case already exists for this account and transaction.",
            )

        amount = str(txn.transaction.amount)
        transaction_date = txn.transaction.transaction_date.isoformat()
        merchant_display_name = txn.merchant.display_name
        reason = build_case_reason(
            merchant_display_name=merchant_display_name,
            amount=amount,
            currency=txn.transaction.currency,
            transaction_date=transaction_date,
            synthesis_summary=synthesis_summary,
        )
        evidence = build_dispute_evidence(
            account_id=account_id,
            masked_account_id=mask_account_id(account_id),
            transaction_id=transaction_id,
            investigation_id=investigation_id,
            merchant_display_name=merchant_display_name,
            amount=amount,
            currency=txn.transaction.currency,
            transaction_date=transaction_date,
            synthesis_summary=synthesis_summary,
            investigation_findings=investigation_findings,
            proposed_reason=reason,
        )
        now = self._clock()
        confirmation = CustomerConfirmation(
            confirmation_id=self._confirmation_id_factory(),
            investigation_id=investigation_id,
            account_id=account_id,
            transaction_id=transaction_id,
            case_id=self._case_id_factory(),
            customer_id=record.account.customer_id,
            evidence_hash=evidence.evidence_hash,
            reason=reason,
            reason_code=evidence.reason_code,
            snapshot={
                "investigation_id": investigation_id,
                "masked_account_id": mask_account_id(account_id),
                "transaction_id": transaction_id,
                "merchant_display_name": merchant_display_name,
                "amount": amount,
                "currency": txn.transaction.currency,
                "transaction_date": transaction_date,
                "reason": reason,
                "reason_code": evidence.reason_code.value,
                "verified_evidence": list(evidence.verified_evidence),
                "missing_evidence": list(evidence.missing_evidence),
                "applied_policy": evidence.applied_policy,
                "proposed_action": evidence.proposed_action,
                "synthesis_summary": synthesis_summary,
                "evidence_hash": evidence.evidence_hash,
            },
            amount=txn.transaction.amount,
            currency=txn.transaction.currency,
            merchant_display_name=merchant_display_name,
            created_at=now,
            expires_at=now + timedelta(seconds=self._ttl_seconds),
            consumed_at=None,
        )
        token = self._token_factory()
        self._confirmations.insert(confirmation, token_hash=hash_confirmation_token(token))
        return IssuedConfirmation(confirmation=confirmation, confirmation_token=token)

    def peek(self, *, confirmation_token: str) -> CustomerConfirmation:
        """Load a challenge without consuming it. Used for idempotent retries."""
        stored = self._confirmations.get_by_token_hash(hash_confirmation_token(confirmation_token))
        if stored is None:
            raise ConfirmationNotFoundError(
                "No customer confirmation matches this confirmation_token.",
            )
        return stored

    def consume(
        self,
        *,
        confirmation_token: str,
        investigation_id: str,
        account_id: str,
        transaction_id: str,
    ) -> CustomerConfirmation:
        """Verify a token against its investigation subject, then mark it used."""
        token_hash = hash_confirmation_token(confirmation_token)
        stored = self._confirmations.get_by_token_hash(token_hash)
        if stored is None:
            raise ConfirmationNotFoundError(
                "No pending customer confirmation matches this confirmation_token.",
            )
        self._assert_same_subject(
            stored,
            investigation_id=investigation_id,
            account_id=account_id,
            transaction_id=transaction_id,
        )
        now = self._clock()
        if now >= stored.expires_at:
            raise ConfirmationExpiredError(
                "This confirmation_token has expired. Re-run synthesize_investigation and ask again.",
            )
        return self._confirmations.consume(token_hash, consumed_at=now)

    def assert_same_subject(
        self,
        stored: CustomerConfirmation,
        *,
        investigation_id: str,
        account_id: str,
        transaction_id: str,
    ) -> None:
        """Reject a token replayed against another investigation, account or charge."""
        self._assert_same_subject(
            stored,
            investigation_id=investigation_id,
            account_id=account_id,
            transaction_id=transaction_id,
        )

    @staticmethod
    def _assert_same_subject(
        stored: CustomerConfirmation,
        *,
        investigation_id: str,
        account_id: str,
        transaction_id: str,
    ) -> None:
        """Reject a token replayed against another investigation, account or charge.

        Compared without early exit so a caller cannot learn which field of a
        real token they guessed correctly.
        """
        matches = (
            _secret_equal(stored.investigation_id, investigation_id)
            & _secret_equal(stored.account_id, account_id)
            & _secret_equal(stored.transaction_id, transaction_id)
        )
        if not matches:
            raise ConfirmationMismatchError(
                "This confirmation_token was not issued for this investigation, account and transaction.",
            )


def _secret_equal(left: str, right: str) -> bool:
    """Constant-time equality that does not leak identifier length."""
    left_digest = hashlib.sha256(left.encode("utf-8")).digest()
    right_digest = hashlib.sha256(right.encode("utf-8")).digest()
    return hmac.compare_digest(left_digest, right_digest)
