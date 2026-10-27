"""Initiate a push payment through the provider gateway.

The use case owns the idempotency policy and the lifecycle of the local record.
It never imports OneKhusa details: the gateway adapter translates the provider
wire contract into :class:`~webhook_verification.payments.ports.ProviderAcceptance`.
"""

from __future__ import annotations

from uuid import uuid4

import structlog

from webhook_verification.payments.errors import (
    MerchantReferenceConflict,
    ProviderError,
    ProviderSubmissionFailed,
)
from webhook_verification.payments.models import Payment, build_payment
from webhook_verification.payments.ports import (
    Clock,
    InitiatePaymentCommand,
    PaymentRepository,
    PushPaymentGateway,
)

logger = structlog.get_logger(__name__)


class InitiatePushPayment:
    """Idempotently submit a payment to the OneKhusa sandbox."""

    def __init__(
        self,
        repository: PaymentRepository,
        gateway: PushPaymentGateway,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._clock = clock

    async def execute(self, command: InitiatePaymentCommand) -> Payment:
        fingerprint = command.fingerprint()

        async with self._repository.transaction() as transaction:
            existing = transaction.find_by_merchant_reference(command.merchant_reference)
            if existing is not None:
                if existing.submission_fingerprint != fingerprint:
                    raise MerchantReferenceConflict(
                        "Merchant reference is already in use for another request"
                    )
                payment = existing
            else:
                payment = transaction.add(
                    build_payment(
                        payment_id=str(uuid4()),
                        merchant_reference_number=command.merchant_reference,
                        connector_id=command.connector_id,
                        payer_account_number=command.payer_account_number,
                        transaction_amount=command.transaction_amount,
                        transaction_description=command.transaction_description,
                        captured_by=command.captured_by,
                        submission_fingerprint=fingerprint,
                        now=self._clock.now(),
                    )
                )

        try:
            acceptance = await self._gateway.initiate(command)
        except ProviderError as exc:
            async with self._repository.transaction() as transaction:
                failed = transaction.get(payment.payment_id)
                failed.submission_http_status = exc.status_code
                failed.submission_message = str(exc)
                failed.updated_at = self._clock.now()
                failed = transaction.save(failed)
            logger.warning(
                "onekhusa_push_failed",
                merchant_reference=command.merchant_reference,
                status_code=exc.status_code,
                error=str(exc),
            )
            raise ProviderSubmissionFailed(failed, exc) from exc

        async with self._repository.transaction() as transaction:
            current = transaction.get(payment.payment_id)
            current.submission_http_status = acceptance.http_status
            current.submission_message = acceptance.message
            if acceptance.provider_transaction_reference is not None:
                current.provider_transaction_reference = (
                    acceptance.provider_transaction_reference
                )
            current.updated_at = self._clock.now()
            return transaction.save(current)
