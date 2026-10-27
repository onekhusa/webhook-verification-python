"""Authenticate and translate an OneKhusa callback.

Order matters and is enforced here: the HMAC is verified over the exact raw
body bytes before the JSON is parsed. Unsigned or tampered payloads therefore
never reach the parser or the application layer.
"""

from __future__ import annotations

import structlog
from pydantic import SecretStr, ValidationError

from webhook_verification.onekhusa.webhook.events import PushWebhookEvent
from webhook_verification.onekhusa.webhook.payload import PushWebhookPayload
from webhook_verification.onekhusa.webhook.signature import verify_webhook_signature
from webhook_verification.payments.errors import (
    InvalidWebhookPayload,
    InvalidWebhookSignature,
)
from webhook_verification.payments.models import PaymentEventKind
from webhook_verification.payments.ports import WebhookNotification

logger = structlog.get_logger(__name__)

_EVENT_KIND = {
    PushWebhookEvent.SUCCESS: PaymentEventKind.SUCCESS,
    PushWebhookEvent.FAILED: PaymentEventKind.FAILED,
    PushWebhookEvent.REVERSED: PaymentEventKind.REVERSED,
}


def authenticate_and_parse_push_webhook(
    *,
    raw_body: bytes,
    signature: str | None,
    secret: SecretStr,
    event: PushWebhookEvent,
) -> WebhookNotification:
    """Verify the signature, then parse and map the payload."""

    if not verify_webhook_signature(raw_body, signature, secret):
        logger.warning("onekhusa_webhook_invalid_signature", webhook_event=event.value)
        raise InvalidWebhookSignature("Invalid webhook signature")

    try:
        payload = PushWebhookPayload.model_validate_json(raw_body)
    except ValidationError as exc:
        logger.warning("onekhusa_webhook_invalid_payload", webhook_event=event.value)
        raise InvalidWebhookPayload("Invalid webhook payload") from exc

    # Modern payloads echo the merchant reference in ``merchantReferenceNumber``.
    # Legacy payloads put it in ``sourceReferenceNumber``; that field normally
    # carries the payer's bank/MNO reference, so only use it as a fallback.
    merchant_reference = (
        payload.merchant_reference_number or payload.payer_reference_number
    )

    return WebhookNotification(
        event=_EVENT_KIND[event],
        merchant_reference=merchant_reference,
        provider_transaction_reference=payload.provider_transaction_reference,
    )
