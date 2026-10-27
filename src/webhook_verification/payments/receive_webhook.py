"""Apply an authenticated OneKhusa callback to a payment.

Authentication and parsing happen before this use case is called. This module
only receives a :class:`WebhookNotification`, which proves the callback was
verified and translated into domain terms by the adapter.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import structlog

from webhook_verification.payments.correlation import CorrelationOutcome, correlate
from webhook_verification.payments.errors import InvalidWebhookPayload
from webhook_verification.payments.models import (
    Payment,
    PaymentEvent,
    PaymentEventKind,
    PaymentState,
    PaymentStatus,
)
from webhook_verification.payments.ports import (
    Clock,
    PaymentRepository,
    WebhookNotification,
)

logger = structlog.get_logger(__name__)

_EVENT_STATUS = {
    PaymentEventKind.SUCCESS: PaymentStatus.SUCCEEDED,
    PaymentEventKind.FAILED: PaymentStatus.FAILED,
    PaymentEventKind.REVERSED: PaymentStatus.REVERSED,
}


@dataclass(frozen=True, slots=True)
class WebhookOutcome:
    payment: Payment | None
    duplicate: bool
    matched: bool


class ReceiveWebhook:
    """De-duplicate, correlate and apply a verified push-payment callback."""

    def __init__(self, repository: PaymentRepository, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    async def process(self, notification: WebhookNotification) -> WebhookOutcome:
        merchant_reference = notification.merchant_reference
        provider_reference = notification.provider_transaction_reference

        if not merchant_reference and not provider_reference:
            logger.warning(
                "onekhusa_webhook_missing_references",
                webhook_event=notification.event.value,
            )
            raise InvalidWebhookPayload(
                "Webhook must contain a merchant or provider reference"
            )

        identity = provider_reference or merchant_reference or ""
        receipt_key = hashlib.sha256(
            f"{notification.event.value}:{identity}".encode()
        ).hexdigest()

        async with self._repository.transaction() as transaction:
            result = correlate(
                transaction,
                merchant_reference=merchant_reference,
                provider_reference=provider_reference,
            )

            if result.outcome is CorrelationOutcome.CONFLICT:
                # Acknowledge the callback: retrying cannot resolve a conflict,
                # and applying it could update the wrong payment.
                logger.warning(
                    "onekhusa_webhook_reference_conflict",
                    webhook_event=notification.event.value,
                    merchant_reference=merchant_reference,
                    provider_reference=provider_reference,
                    reason=result.reason,
                )
                return WebhookOutcome(payment=None, duplicate=False, matched=False)

            if result.outcome is CorrelationOutcome.UNMATCHED or result.payment is None:
                logger.warning(
                    "onekhusa_webhook_unmatched",
                    webhook_event=notification.event.value,
                    merchant_reference=merchant_reference,
                    provider_reference=provider_reference,
                    reason=result.reason,
                )
                # Do not cache unmatched receipts. A retry may arrive after the
                # corresponding payment has been created.
                return WebhookOutcome(payment=None, duplicate=False, matched=False)

            payment = result.payment

            if transaction.receipt_seen(receipt_key):
                logger.info(
                    "onekhusa_webhook_duplicate",
                    webhook_event=notification.event.value,
                    matched=True,
                )
                return WebhookOutcome(
                    payment=payment,
                    duplicate=True,
                    matched=True,
                )

            # A callback can arrive before the initiation response has stored
            # the provider transaction reference. Adopt it on first sight.
            if (
                provider_reference is not None
                and payment.provider_transaction_reference is None
            ):
                payment.provider_transaction_reference = provider_reference
                logger.info(
                    "onekhusa_webhook_provider_reference_reconciled",
                    merchant_reference=payment.merchant_reference_number,
                    provider_reference=provider_reference,
                )

            next_status = PaymentState(payment.status).transition(
                _EVENT_STATUS[notification.event]
            )
            payment.status = next_status.status
            payment.updated_at = self._clock.now()
            payment.events.append(
                PaymentEvent(
                    kind=notification.event,
                    received_at=payment.updated_at,
                    signature_verified=True,
                )
            )
            transaction.claim_receipt(receipt_key)
            payment = transaction.save(payment)

            logger.info(
                "onekhusa_webhook_processed",
                webhook_event=notification.event.value,
                merchant_reference=payment.merchant_reference_number,
                provider_reference=payment.provider_transaction_reference,
                status=payment.status.value,
            )

            return WebhookOutcome(payment=payment, duplicate=False, matched=True)
