"""Deterministic merchant descriptor resolution.

Card descriptors rarely match a merchant's trading name: they are truncated,
prefixed by a payment aggregator and suffixed with a store number or city.
This service normalizes a descriptor and scores it against the merchant
catalog using fixed rules. No language model is involved, so the same
descriptor always resolves to the same merchant with the same confidence.
"""

import re
from dataclasses import dataclass

from ..enums import Confidence
from ..models import Merchant

# Payment aggregators and gateways that prefix the real merchant name.
AGGREGATOR_PREFIXES = frozenset({"SQ", "TST", "PP", "PAYPAL", "SP", "PY", "IC"})

# Tokens that carry no identifying signal.
NOISE_TOKENS = frozenset(
    {
        "INC",
        "LLC",
        "LTD",
        "CO",
        "CORP",
        "THE",
        "AND",
        "USA",
        "US",
        "POS",
        "PURCHASE",
        "PAYMENT",
        "DEBIT",
        "CREDIT",
        "AUTH",
        "RECURRING",
        "WWW",
        "COM",
        "HTTP",
        "HTTPS",
    }
)

EXACT_SCORE = 1.0
PREFIX_SCORE = 0.92
CONTAINS_SCORE = 0.85
HIGH_THRESHOLD = 0.8
MEDIUM_THRESHOLD = 0.5
LOW_THRESHOLD = 0.25

_SEPARATORS = re.compile(r"[^A-Z0-9]+")
_STORE_NUMBER = re.compile(r"^\d{3,}$")


@dataclass(frozen=True, slots=True)
class NormalizedDescriptor:
    """A descriptor reduced to its identifying tokens."""

    text: str
    tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ScoredCandidate:
    """One merchant pattern scored against the descriptor."""

    score: float
    rule: str
    merchant: Merchant
    pattern: str


@dataclass(frozen=True, slots=True)
class MerchantMatch:
    """The outcome of resolving one descriptor."""

    normalized_descriptor: str
    merchant: Merchant | None
    confidence: Confidence
    score: float
    rule: str
    matched_pattern: str | None
    explanation: str


def normalize_descriptor(descriptor: str) -> NormalizedDescriptor:
    """Reduce a raw descriptor to upper-case identifying tokens."""
    raw_tokens = [token for token in _SEPARATORS.split(descriptor.upper()) if token]

    while raw_tokens and raw_tokens[0] in AGGREGATOR_PREFIXES:
        raw_tokens.pop(0)

    tokens = tuple(token for token in raw_tokens if token not in NOISE_TOKENS and not _STORE_NUMBER.match(token))
    return NormalizedDescriptor(text=" ".join(tokens), tokens=tokens)


def _score_candidate(descriptor: NormalizedDescriptor, candidate: str) -> tuple[float, str]:
    """Score one descriptor against one merchant pattern or display name."""
    normalized_candidate = normalize_descriptor(candidate)
    if not normalized_candidate.text or not descriptor.text:
        return 0.0, "no_signal"

    if descriptor.text == normalized_candidate.text:
        return EXACT_SCORE, "exact_match"
    if descriptor.text.startswith(f"{normalized_candidate.text} "):
        return PREFIX_SCORE, "prefix_match"
    if f" {normalized_candidate.text} " in f" {descriptor.text} ":
        return CONTAINS_SCORE, "contains_match"

    descriptor_tokens = set(descriptor.tokens)
    candidate_tokens = set(normalized_candidate.tokens)
    union = descriptor_tokens | candidate_tokens
    if not union:
        return 0.0, "no_signal"
    return len(descriptor_tokens & candidate_tokens) / len(union), "token_overlap"


def _confidence_for(score: float) -> Confidence | None:
    if score >= HIGH_THRESHOLD:
        return Confidence.HIGH
    if score >= MEDIUM_THRESHOLD:
        return Confidence.MEDIUM
    if score >= LOW_THRESHOLD:
        return Confidence.LOW
    return None


class MerchantResolverService:
    """Resolves a raw card descriptor to a merchant in the catalog."""

    def resolve(self, raw_descriptor: str, merchants: list[Merchant]) -> MerchantMatch:
        """Return the best merchant match for a descriptor."""
        descriptor = normalize_descriptor(raw_descriptor)
        if not descriptor.text:
            return MerchantMatch(
                normalized_descriptor=descriptor.text,
                merchant=None,
                confidence=Confidence.LOW,
                score=0.0,
                rule="no_signal",
                matched_pattern=None,
                explanation="The descriptor contains no identifying tokens after normalization.",
            )

        scored: list[_ScoredCandidate] = []
        for merchant in merchants:
            for candidate in (*merchant.descriptor_patterns, merchant.display_name):
                score, rule = _score_candidate(descriptor, candidate)
                if score > 0:
                    scored.append(_ScoredCandidate(score=score, rule=rule, merchant=merchant, pattern=candidate))

        # Highest score wins; longer patterns and then lower merchant ids break
        # ties so the result never depends on catalog ordering.
        scored.sort(key=lambda item: (-item.score, -len(item.pattern), item.merchant.merchant_id))
        best = scored[0] if scored else None

        if best is None:
            return MerchantMatch(
                normalized_descriptor=descriptor.text,
                merchant=None,
                confidence=Confidence.LOW,
                score=0.0,
                rule="no_match",
                matched_pattern=None,
                explanation=(
                    f"No merchant in the catalog shares tokens with the normalized descriptor '{descriptor.text}'."
                ),
            )

        confidence = _confidence_for(best.score)
        if confidence is None:
            return MerchantMatch(
                normalized_descriptor=descriptor.text,
                merchant=None,
                confidence=Confidence.LOW,
                score=round(best.score, 4),
                rule="below_threshold",
                matched_pattern=None,
                explanation=(
                    f"The closest merchant scored {best.score:.2f}, below the {LOW_THRESHOLD:.2f} threshold "
                    f"required to report a match."
                ),
            )

        return MerchantMatch(
            normalized_descriptor=descriptor.text,
            merchant=best.merchant,
            confidence=confidence,
            score=round(best.score, 4),
            rule=best.rule,
            matched_pattern=best.pattern,
            explanation=self._explain(best, descriptor.text),
        )

    @staticmethod
    def _explain(best: _ScoredCandidate, normalized: str) -> str:
        merchant_name = best.merchant.display_name
        descriptions = {
            "exact_match": (
                f"The normalized descriptor '{normalized}' is identical to the registered pattern "
                f"'{best.pattern}' for {merchant_name}."
            ),
            "prefix_match": (
                f"The normalized descriptor '{normalized}' begins with the registered pattern "
                f"'{best.pattern}' for {merchant_name}; the remainder is store or location detail."
            ),
            "contains_match": (
                f"The registered pattern '{best.pattern}' for {merchant_name} appears inside the "
                f"normalized descriptor '{normalized}'."
            ),
            "token_overlap": (
                f"The normalized descriptor '{normalized}' shares {best.score:.0%} of its tokens with "
                f"'{best.pattern}' for {merchant_name}."
            ),
        }
        return descriptions.get(best.rule, f"Matched {merchant_name} with score {best.score:.2f}.")
