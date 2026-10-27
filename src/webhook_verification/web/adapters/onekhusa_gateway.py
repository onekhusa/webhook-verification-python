"""Implement the payment gateway port using the OneKhusa adapter."""

from __future__ import annotations

from webhook_verification.onekhusa.client import OneKhusaClient
from webhook_verification.onekhusa.config import OneKhusaSettings
from webhook_verification.onekhusa.contracts import (
    PushPaymentRequest,
    provider_idempotency_key,
)
from webhook_verification.onekhusa.errors import (
    OneKhusaError,
    OneKhusaInvalidResponse,
    OneKhusaNotConfigured,
    OneKhusaRejected,
    OneKhusaUnavailable,
)
from webhook_verification.payments.errors import (
    ProviderInvalidResponse,
    ProviderNotConfigured,
    ProviderRejected,
    ProviderUnavailable,
)
from webhook_verification.payments.ports import (
    InitiatePaymentCommand,
    ProviderAcceptance,
)


class OneKhusaPushPaymentGateway:
    """Translate domain commands into OneKhusa initiation calls."""

    def __init__(self, settings: OneKhusaSettings, client: OneKhusaClient) -> None:
        self._settings = settings
        self._client = client

    async def initiate(self, command: InitiatePaymentCommand) -> ProviderAcceptance:
        if not self._settings.is_configured:
            raise ProviderNotConfigured(
                "OneKhusa is disabled or its credentials are incomplete"
            )
        if not self._settings.is_sandbox:
            raise ProviderNotConfigured(
                "Only the OneKhusa sandbox endpoint is allowed"
            )

        merchant_account_number = (
            command.merchant_account_number or self._settings.merchant_account_number
        )
        if merchant_account_number is None:
            raise ProviderNotConfigured(
                "ONEKHUSA_MERCHANT_ACCOUNT_NUMBER is required"
            )

        request = PushPaymentRequest(
            merchant_account_number=command.merchant_account_number,
            connector_id=command.connector_id,
            payer_account_number=command.payer_account_number,
            merchant_reference=command.merchant_reference,
            transaction_description=command.transaction_description,
            transaction_amount=command.transaction_amount,
            captured_by=command.captured_by,
        )

        try:
            result = await self._client.initiate_push_payment(
                request,
                idempotency_key=provider_idempotency_key(
                    merchant_account_number,
                    command.merchant_reference,
                ),
            )
        except OneKhusaNotConfigured as exc:
            raise ProviderNotConfigured(str(exc), status_code=exc.status_code) from exc
        except OneKhusaUnavailable as exc:
            raise ProviderUnavailable(str(exc), status_code=exc.status_code) from exc
        except OneKhusaRejected as exc:
            raise ProviderRejected(str(exc), status_code=exc.status_code) from exc
        except OneKhusaInvalidResponse as exc:
            raise ProviderInvalidResponse(
                str(exc), status_code=exc.status_code
            ) from exc
        except OneKhusaError as exc:
            # Unknown outcome: do not let an unexpected provider failure look
            # like a definitive rejection.
            raise ProviderUnavailable(str(exc), status_code=exc.status_code) from exc

        return ProviderAcceptance(
            http_status=result.http_status,
            provider_transaction_reference=result.provider_transaction_reference,
            message=result.message,
        )
