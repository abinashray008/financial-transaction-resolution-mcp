"""Deterministic duplicate-charge detection.

The rules below are fixed and explainable. A candidate only reaches this
service if the repository already scoped it to the same account, merchant and
currency, and to the requested date and amount windows.
"""

from dataclasses import dataclass
from decimal import Decimal

from ..enums import Confidence, TransactionStatus
from ..models import Transaction

_CONFIDENCE_RANK = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}


@dataclass(frozen=True, slots=True)
class DuplicateAssessment:
    """The outcome of a duplicate check for one subject transaction."""

    duplicate_likely: bool
    confidence: Confidence
    candidate_transaction_ids: tuple[str, ...]
    reasons: tuple[str, ...]


class DuplicateChargeService:
    """Classifies near-identical charges on the same account and merchant."""

    def assess(
        self,
        *,
        subject: Transaction,
        candidates: list[Transaction],
        date_tolerance_days: int,
        amount_tolerance: Decimal,
    ) -> DuplicateAssessment:
        """Assess whether any candidate is likely a duplicate of the subject."""
        if not candidates:
            return DuplicateAssessment(
                duplicate_likely=False,
                confidence=Confidence.LOW,
                candidate_transaction_ids=(),
                reasons=(
                    f"No other transaction on this account shares merchant {subject.merchant_id} and "
                    f"currency {subject.currency} within {date_tolerance_days} day(s) and an amount "
                    f"tolerance of {amount_tolerance}.",
                ),
            )

        reasons: list[str] = []
        best = Confidence.LOW
        for candidate in candidates:
            confidence, reason = self._classify(subject, candidate, date_tolerance_days)
            reasons.append(reason)
            if _CONFIDENCE_RANK[confidence] > _CONFIDENCE_RANK[best]:
                best = confidence

        return DuplicateAssessment(
            duplicate_likely=_CONFIDENCE_RANK[best] >= _CONFIDENCE_RANK[Confidence.MEDIUM],
            confidence=best,
            candidate_transaction_ids=tuple(candidate.transaction_id for candidate in candidates),
            reasons=tuple(reasons),
        )

    @staticmethod
    def _classify(
        subject: Transaction,
        candidate: Transaction,
        date_tolerance_days: int,
    ) -> tuple[Confidence, str]:
        label = candidate.transaction_id
        day_gap = abs((candidate.transaction_date - subject.transaction_date).days)
        exact_amount = candidate.amount == subject.amount
        statuses = {subject.status, candidate.status}

        if statuses == {TransactionStatus.AUTHORIZATION_HOLD, TransactionStatus.POSTED}:
            return Confidence.LOW, (
                f"{label}: an authorization hold paired with a posted charge at the same merchant is the "
                f"normal settlement pattern, not a duplicate."
            )

        if subject.recurring or candidate.recurring:
            return Confidence.LOW, (
                f"{label}: at least one of the two charges is flagged as a recurring subscription, so "
                f"repeated charges at this merchant are expected."
            )

        if TransactionStatus.REVERSED in statuses:
            return Confidence.LOW, (
                f"{label}: one of the two charges is reversed, so the pair nets out rather than duplicating."
            )

        if exact_amount and day_gap == 0:
            channel_note = (
                " Both charges used the same capture channel."
                if candidate.card_present == subject.card_present
                else " The two charges used different capture channels, which can indicate a retried payment."
            )
            return Confidence.HIGH, (
                f"{label}: identical amount {subject.amount} {subject.currency} at merchant "
                f"{subject.merchant_id} on the same transaction date.{channel_note}"
            )

        if exact_amount and day_gap <= date_tolerance_days:
            return Confidence.MEDIUM, (
                f"{label}: identical amount {subject.amount} {subject.currency} at merchant "
                f"{subject.merchant_id}, {day_gap} day(s) apart and within the {date_tolerance_days} day "
                f"tolerance."
            )

        return Confidence.LOW, (
            f"{label}: amount {candidate.amount} {candidate.currency} differs from the subject amount "
            f"{subject.amount} {subject.currency} and only falls inside the requested tolerance, "
            f"{day_gap} day(s) apart."
        )
