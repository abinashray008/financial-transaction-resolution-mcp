"""Account identifier and card masking."""

import pytest

from src.security.masking import (
    CARD_MASK_PREFIX,
    MASK_SEGMENT,
    mask_account_id,
    mask_card,
    mask_optional_account_id,
)


def test_account_id_keeps_prefix_and_last_four():
    assert mask_account_id("ACCT-0001") == "ACCT-****0001"


def test_account_id_hides_everything_but_the_last_four():
    masked = mask_account_id("ACCT-12345678")

    assert masked == "ACCT-****5678"
    assert "1234" not in masked


def test_account_id_without_a_prefix_is_still_masked():
    assert mask_account_id("998877665544") == "****5544"


def test_account_id_is_normalized_before_masking():
    assert mask_account_id("  ACCT-0001  ") == "ACCT-****0001"


def test_empty_account_id_is_rejected():
    with pytest.raises(ValueError):
        mask_account_id("   ")


def test_card_shows_only_the_last_four():
    assert mask_card("4412") == f"{CARD_MASK_PREFIX}4412"


def test_card_masking_cannot_leak_a_full_number():
    """Even handed a full PAN, only four digits survive."""
    masked = mask_card("4111111111111234")

    assert masked == f"{CARD_MASK_PREFIX}1234"
    assert "4111" not in masked
    assert len(masked.replace(CARD_MASK_PREFIX, "")) == 4


def test_card_without_digits_is_rejected():
    with pytest.raises(ValueError):
        mask_card("no digits here")


def test_optional_masking_passes_through_none():
    assert mask_optional_account_id(None) is None


def test_optional_masking_never_raises_on_unusable_input():
    assert mask_optional_account_id("   ") == MASK_SEGMENT
    assert mask_optional_account_id("!!!") == MASK_SEGMENT


def test_optional_masking_strips_free_text_from_a_malformed_identifier():
    """A malformed identifier must not smuggle free text into the audit log."""
    masked = mask_optional_account_id("ACCT-0001 <script>alert('x')</script>")

    assert masked is not None
    assert "<script>" not in masked
    assert "alert" not in masked
    assert len(masked) <= 40
