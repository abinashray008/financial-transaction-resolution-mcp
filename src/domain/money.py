"""Money helpers.

Amounts are stored as integer minor units (cents) so that SQLite comparisons
and equality checks are exact. ``Decimal`` is the only representation that
leaves this module.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

TWO_PLACES = Decimal("0.01")


def to_minor_units(amount: Decimal) -> int:
    """Convert a decimal amount to integer minor units, rounding half up."""
    try:
        quantized = amount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:  # pragma: no cover - guards absurd inputs
        raise ValueError("Amount cannot be represented in minor units.") from exc
    return int(quantized * 100)


def from_minor_units(minor_units: int) -> Decimal:
    """Convert integer minor units back to a two-decimal amount."""
    return (Decimal(minor_units) / Decimal(100)).quantize(TWO_PLACES)
