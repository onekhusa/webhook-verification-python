"""Errors raised by the payment domain and application layer.

Provider failures are translated into the ``ProviderError`` hierarchy by the
adapter. The web layer maps these errors onto HTTP responses once, in
``web.errors``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from webhook_verification.payments.models import Payment


class PaymentError(Exception):
    """Base class for expected, user-facing payment failures."""


class PaymentNotFound(PaymentError):
    def __init__(self, payment_id: str) -> None:
        super().__init__(f"Payment {payment_id} was not found")
        self.payment_id = payment_id


class InvalidTransition(PaymentError):
    pass


class DuplicateMerchantReference(PaymentError):
    pass


class MerchantReferenceConflict(PaymentError):
    """The merchant reference is already used by a different request body."""


class InvalidWebhookSignature(PaymentError):
    pass


class InvalidWebhookPayload(PaymentError):
    pass


class ProviderError(PaymentError):
    """A provider call failed.

    ``code`` and ``retryable`` are part of the public API contract, so the web
    layer can return a stable machine-readable error without understanding
    OneKhusa specifics.
    """

    code = "provider_error"
    retryable = False

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ProviderNotConfigured(ProviderError):
    code = "provider_not_configured"


class ProviderUnavailable(ProviderError):
    code = "provider_unavailable"
    retryable = True


class ProviderRejected(ProviderError):
    code = "provider_rejected"


class ProviderInvalidResponse(ProviderError):
    code = "provider_invalid_response"


class ProviderSubmissionFailed(ProviderError):
    """The provider call failed after a local payment record was created."""

    def __init__(self, payment: Payment, cause: ProviderError) -> None:
        super().__init__(str(cause), status_code=cause.status_code)
        self.payment = payment
        self.code = cause.code
        self.retryable = cause.retryable
