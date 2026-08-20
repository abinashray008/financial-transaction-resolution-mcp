"""Domain errors and the stable error codes exposed to MCP clients.

Every message on these exceptions is written to be client-safe: no SQL, no
stack traces, no filesystem paths, no hints about data outside the requested
account.
"""

from enum import StrEnum


class ErrorCode(StrEnum):
    """Stable, client-visible error codes."""

    INVALID_INPUT = "INVALID_INPUT"
    ACCOUNT_NOT_FOUND = "ACCOUNT_NOT_FOUND"
    TRANSACTION_NOT_FOUND = "TRANSACTION_NOT_FOUND"
    INVALID_DATE_RANGE = "INVALID_DATE_RANGE"
    INVALID_AMOUNT_RANGE = "INVALID_AMOUNT_RANGE"
    SYNTHESIS_UNAVAILABLE = "SYNTHESIS_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class DomainError(Exception):
    """Base class for expected failures that map to a structured tool response."""

    code: ErrorCode = ErrorCode.INTERNAL_ERROR

    def __init__(self, safe_message: str) -> None:
        super().__init__(safe_message)
        self.safe_message = safe_message


class InvalidInputError(DomainError):
    """An identifier or filter value is malformed."""

    code = ErrorCode.INVALID_INPUT


class AccountNotFoundError(DomainError):
    """No account exists for the supplied identifier."""

    code = ErrorCode.ACCOUNT_NOT_FOUND


class TransactionNotFoundError(DomainError):
    """No transaction with that identifier exists on the supplied account."""

    code = ErrorCode.TRANSACTION_NOT_FOUND


class TransactionAccountMismatchError(TransactionNotFoundError):
    """The transaction exists but belongs to a different account.

    This deliberately inherits ``TransactionNotFoundError`` and therefore
    reports ``TRANSACTION_NOT_FOUND``. A caller must not be able to tell "does
    not exist" apart from "belongs to somebody else"; the repository queries
    are account-scoped, so the two cases are indistinguishable by construction.
    """


class InvalidDateRangeError(DomainError):
    """The start date is after the end date."""

    code = ErrorCode.INVALID_DATE_RANGE


class InvalidAmountRangeError(DomainError):
    """The minimum amount is above the maximum, or an amount is negative."""

    code = ErrorCode.INVALID_AMOUNT_RANGE


class DataStoreUnavailableError(DomainError):
    """The synthetic dataset is missing or unreadable."""

    code = ErrorCode.INTERNAL_ERROR

    def __init__(self) -> None:
        super().__init__("The synthetic transaction dataset is unavailable. Regenerate it before retrying.")


class SynthesisUnavailableError(DomainError):
    """Gemini synthesis could not run (missing key, empty reply, or provider failure)."""

    code = ErrorCode.SYNTHESIS_UNAVAILABLE
