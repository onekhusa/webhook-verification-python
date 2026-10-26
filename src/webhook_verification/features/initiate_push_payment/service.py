from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import structlog

from webhook_verification.features.configuration.settings import Settings
from webhook_verification.onekhusa.client import OneKhusaClient
from webhook_verification.onekhusa.client.push import (
    PushPaymentRequest,
    provider_idempotency_key,
)
from webhook_verification.onekhusa.errors import OneKhusaError
from webhook_verification.shared.payments.models import (
    PLACEHOLDER_REFERENCE_PREFIX,
    Payment,
    build_payment,
)
from webhook_verification.shared.payments.store import InMemoryPaymentStore

logger = structlog.get_logger(__name__)


class ProviderSubmissionError(Exception):
    def __init__(self, payment: Payment, cause: OneKhusaError) -> None:
        super().__init__(str(cause))
        self.payment = payment
        self.status_code = cause.status_code


class InitiatePushPayment:
    """Idempotently submit a payment to the OneKhusa sandbox."""

    def __init__(
        self,
        settings: Settings,
        store: InMemoryPaymentStore,
        client: OneKhusaClient,
    ) -> None:
        self._settings = settings
        self._store = store
        self._client = client

    async def execute(self, request: PushPaymentRequest) -> Payment:
        if not self._settings.onekhusa_is_configured:
            raise OneKhusaError("OneKhusa calls are disabled or not fully configured")
        if not self._settings.onekhusa_is_sandbox:
            raise OneKhusaError("Only the OneKhusa sandbox endpoint is allowed")

        source_reference = request.source_reference_number
        if source_reference is None:
            raise ValueError("A merchant source reference is required for OneKhusa requests")

        fingerprint = hashlib.sha256(request.model_dump_json(by_alias=True).encode()).hexdigest()

        async with self._store.locked() as session:
            existing = session.find_by_source_reference(source_reference)
            if existing is not None:
                if session.provider_fingerprint(source_reference) != fingerprint:
                    raise ValueError("Source reference is already in use for another request")
                payment = existing.model_copy(deep=True)
            else:
                now = datetime.now(UTC)
                payment = session.add(
                    build_payment(
                        payment_id=str(uuid4()),
                        source_reference_number=source_reference,
                        transaction_reference_number=(
                            f"{PLACEHOLDER_REFERENCE_PREFIX}{uuid4().hex[:10].upper()}"
                        ),
                        connector_id=request.connector_id,
                        payer_account_number=request.payer_account_number,
                        transaction_amount=request.transaction_amount,
                        transaction_description=request.transaction_description,
                        captured_by=request.captured_by,
                        now=now,
                    ),
                    provider_fingerprint=fingerprint,
                )

        merchant_number = (
            request.merchant_account_number or self._settings.onekhusa_merchant_account_number or 0
        )

        try:
            result = await self._client.initiate_push_payment(
                request,
                source_reference_number=source_reference,
                idempotency_key=provider_idempotency_key(
                    merchant_number,
                    source_reference,
                ),
            )
        except OneKhusaError as exc:
            async with self._store.locked() as session:
                failed = session.set_provider_result(
                    payment.payment_id,
                    http_status=exc.status_code,
                    message=str(exc),
                )
            logger.warning(
                "onekhusa_push_failed",
                source_reference=source_reference,
                status_code=exc.status_code,
            )
            raise ProviderSubmissionError(failed, exc) from exc

        async with self._store.locked() as session:
            return session.set_provider_result(
                payment.payment_id,
                http_status=result.http_status,
                message=result.message,
                transaction_reference_number=result.transaction_reference_number,
            )
