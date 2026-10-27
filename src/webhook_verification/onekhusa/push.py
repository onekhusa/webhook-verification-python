from __future__ import annotations

import logging

import httpx

from webhook_verification.onekhusa.config import OneKhusaSettings
from webhook_verification.onekhusa.contracts import (
    ACCEPTED_RESPONSE_CODE,
    PushPaymentRequest,
    PushPaymentResult,
    encode_initiate_request,
)
from webhook_verification.onekhusa.errors import (
    OneKhusaNotConfigured,
    OneKhusaRejected,
    OneKhusaUnavailable,
    response_error,
)
from webhook_verification.onekhusa.token import AccessTokenProvider

logger = logging.getLogger(__name__)


class PushPaymentClient:
    """Submit OneKhusa Collections push payments."""

    def __init__(
        self,
        settings: OneKhusaSettings,
        http: httpx.AsyncClient,
        tokens: AccessTokenProvider,
    ) -> None:
        self._settings = settings
        self._http = http
        self._tokens = tokens

    async def initiate(
        self,
        request: PushPaymentRequest,
        *,
        idempotency_key: str,
    ) -> PushPaymentResult:
        merchant_reference = request.merchant_reference

        logger.info(
            "Initiating OneKhusa push payment: merchant_reference=%s",
            merchant_reference,
        )

        if not self._settings.is_configured:
            logger.error("OneKhusa is disabled or its credentials are incomplete")
            raise OneKhusaNotConfigured(
                "OneKhusa is disabled or its credentials are incomplete"
            )

        configured_merchant = self._settings.merchant_account_number
        if configured_merchant is None:
            logger.error("OneKhusa merchant account number is not configured")
            raise OneKhusaNotConfigured("ONEKHUSA_MERCHANT_ACCOUNT_NUMBER is required")

        if request.merchant_account_number not in {None, configured_merchant}:
            logger.warning(
                "Push payment rejected because the merchant account does not match "
                "the configured merchant account: merchant_reference=%s",
                merchant_reference,
            )
            raise OneKhusaRejected(
                "The request merchant account must match ONEKHUSA_MERCHANT_ACCOUNT_NUMBER"
            )

        token = await self._tokens.get()
        body = encode_initiate_request(request, configured_merchant)

        headers = {
            "Authorization": f"Bearer {token.get_secret_value()}",
            "Accept-Language": "en",
            "X-Idempotency-Key": idempotency_key,
            "Content-Type": "application/json",
        }
        url = f"{self._settings.base_url}/collections/push/direct/initiate"
        logger.debug(
            "Sending push-payment request to OneKhusa: merchant_reference=%s",
            merchant_reference,
        )

        try:
            response = await self._http.post(url, content=body, headers=headers)
        except httpx.TimeoutException as exc:
            logger.exception(
                "OneKhusa push-payment request timed out: merchant_reference=%s",
                merchant_reference,
            )
            raise OneKhusaUnavailable(
                "OneKhusa push request timed out; the transaction outcome is unknown"
            ) from exc
        except httpx.RequestError as exc:
            logger.exception(
                "OneKhusa push-payment connection failed: merchant_reference=%s",
                merchant_reference,
            )
            raise OneKhusaUnavailable(
                "Could not connect to OneKhusa; the transaction outcome may be unknown"
            ) from exc

        logger.info(
            "OneKhusa push-payment response received: merchant_reference=%s status_code=%d",
            merchant_reference,
            response.status_code,
        )

        if not 200 <= response.status_code < 300:
            error = response_error(response)
            logger.warning(
                "OneKhusa rejected push-payment request: "
                "merchant_reference=%s status_code=%d error=%s",
                merchant_reference,
                response.status_code,
                error,
            )
            raise error

        response_code = self._acceptance_response_code(response, merchant_reference)

        logger.info(
            "OneKhusa accepted push-payment request: merchant_reference=%s response_code=%s",
            merchant_reference,
            response_code or "not_provided",
        )

        return PushPaymentResult(
            http_status=response.status_code,
            provider_transaction_reference=None,
            message="OneKhusa accepted the push-payment request",
        )

    @staticmethod
    def _acceptance_response_code(
        response: httpx.Response,
        merchant_reference: str,
    ) -> str | None:
        try:
            response_payload = response.json()
        except ValueError:
            logger.warning(
                "OneKhusa returned a non-JSON success response: merchant_reference=%s",
                merchant_reference,
            )
            return None

        if not isinstance(response_payload, dict):
            logger.warning(
                "OneKhusa returned an unexpected success response: merchant_reference=%s",
                merchant_reference,
            )
            return None

        response_code = response_payload.get("responseCode")
        if response_code is not None and response_code != ACCEPTED_RESPONSE_CODE:
            logger.warning(
                "OneKhusa returned an unexpected response code: "
                "merchant_reference=%s response_code=%s",
                merchant_reference,
                response_code,
            )
            raise OneKhusaRejected(f"OneKhusa returned response code {response_code}")

        logger.info(
            "OneKhusa push-payment acknowledgement: merchant_reference=%s "
            "response_code=%s amount_to_pay=%s",
            merchant_reference,
            response_code or "not_provided",
            response_payload.get("amountToPay", "not_provided"),
        )

        return response_code if isinstance(response_code, str) else None
