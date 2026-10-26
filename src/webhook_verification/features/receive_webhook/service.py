from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from pydantic import SecretStr

from webhook_verification.onekhusa.webhook.events import PushWebhookEvent
from webhook_verification.onekhusa.webhook.payload import PushWebhookPayload
from webhook_verification.onekhusa.webhook.signature import verify_webhook_signature
from webhook_verification.shared.payments.models import (
    PLACEHOLDER_REFERENCE_PREFIX,
    InvalidTransition,
    Payment,
    TransactionState,
    TransactionStatus,
)
from webhook_verification.shared.payments.store import InMemoryPaymentStore

logger = structlog.get_logger(__name__)


class InvalidSignature(Exception):
    pass


class InvalidWebhookTransition(Exception):
    pass


@dataclass(frozen=True, slots=True)
class WebhookOutcome:
    payment: Payment | None
    duplicate: bool
    matched: bool


class ReceiveWebhook:
    """Verify, de-duplicate and apply an OneKhusa push-payment callback."""

    def __init__(self, store: InMemoryPaymentStore) -> None:
        self._store = store

    async def process(
        self,
        *,
        event: PushWebhookEvent,
        payload: PushWebhookPayload,
        raw_body: bytes,
        signature: str | None,
        secret: SecretStr,
    ) -> WebhookOutcome:
        if not verify_webhook_signature(raw_body, signature, secret):
            logger.warning(
                "onekhusa_webhook_invalid_signature",
                event_type=event.value,
            )
            raise InvalidSignature

        source_reference = payload.source_reference_number
        provider_reference = payload.transaction_reference_number

        if not source_reference and not provider_reference:
            logger.warning(
                "onekhusa_webhook_missing_references",
                event_type=event.value,
            )
            raise ValueError("Webhook must contain a source or transaction reference")

        identity = provider_reference or source_reference or ""
        receipt_key = hashlib.sha256(f"{event.value}:{identity}".encode()).hexdigest()

        async with self._store.locked() as session:
            payment = session.find_for_webhook(
                source_reference=source_reference,
                provider_reference=provider_reference,
            )

            if session.is_duplicate_receipt(receipt_key):
                logger.info(
                    "onekhusa_webhook_duplicate",
                    event_type=event.value,
                    matched=payment is not None,
                )
                return WebhookOutcome(
                    payment=(payment.model_copy(deep=True) if payment is not None else None),
                    duplicate=True,
                    matched=payment is not None,
                )

            if payment is None:
                logger.warning(
                    "onekhusa_webhook_unmatched",
                    event_type=event.value,
                    source_reference=source_reference,
                    provider_reference=provider_reference,
                )
                # Do not cache unmatched receipts. A retry may arrive after the
                # corresponding transaction has been created.
                return WebhookOutcome(payment=None, duplicate=False, matched=False)

            # A webhook can arrive before the initiation response has saved the
            # provider's transaction reference.
            if provider_reference and payment.transaction_reference_number.startswith(
                PLACEHOLDER_REFERENCE_PREFIX
            ):
                payment.transaction_reference_number = provider_reference
                logger.info(
                    "onekhusa_webhook_provider_reference_reconciled",
                    source_reference=source_reference,
                    provider_reference=provider_reference,
                )

            try:
                state = TransactionState(TransactionStatus(payment.status))
                next_state = state.transition(event.transaction_status)
            except (InvalidTransition, ValueError) as exc:
                logger.warning(
                    "onekhusa_webhook_invalid_transition",
                    event_type=event.value,
                    source_reference=source_reference,
                    current_status=payment.status,
                    error=str(exc),
                )
                raise InvalidWebhookTransition(str(exc)) from exc

            payment.status = next_state.status.value
            payment.updated_at = datetime.now(UTC)
            session.remember_receipt(receipt_key)
            payment.events.append(
                {
                    "event": event.value,
                    "receivedAt": payment.updated_at.isoformat(),
                    "signatureVerified": True,
                }
            )

            logger.info(
                "onekhusa_webhook_processed",
                event_type=event.value,
                source_reference=source_reference,
                provider_reference=payment.transaction_reference_number,
                status=payment.status,
            )

            return WebhookOutcome(
                payment=payment.model_copy(deep=True),
                duplicate=False,
                matched=True,
            )
