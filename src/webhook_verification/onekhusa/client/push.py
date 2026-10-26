from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

from webhook_verification.features.configuration.settings import Settings
from webhook_verification.onekhusa.client.connectors import validate_connector_id
from webhook_verification.onekhusa.client.token import AccessTokenProvider
from webhook_verification.onekhusa.errors import OneKhusaError, response_error

logger = logging.getLogger(__name__)

AccountReference = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]
Reference = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class PushPaymentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    merchant_account_number: int | None = Field(
        default=None,
        alias="merchantAccountNumber",
        ge=10_000_000,
        le=99_999_999,
    )
    connector_id: int = Field(alias="connectorId", gt=0)
    payer_account_number: AccountReference = Field(alias="payerAccountNumber")
    source_reference_number: Reference | None = Field(
        default=None,
        alias="sourceReferenceNumber",
    )
    transaction_description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ] = Field(alias="transactionDescription")
    transaction_amount: Decimal = Field(
        alias="transactionAmount",
        gt=0,
        max_digits=18,
        decimal_places=2,
    )
    captured_by: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
    ] = Field(alias="capturedBy")

    @field_validator("connector_id")
    @classmethod
    def validate_connector(cls, value: int) -> int:
        return validate_connector_id(value)


@dataclass(frozen=True, slots=True)
class PushPaymentResult:
    http_status: int
    transaction_reference_number: str | None
    message: str


class PushPaymentClient:
    """Submit OneKhusa Collections push payments."""

    def __init__(
        self,
        settings: Settings,
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
        source_reference_number: str,
        idempotency_key: str,
    ) -> PushPaymentResult:
        logger.info(
            "Initiating OneKhusa push payment: source_reference=%s",
            source_reference_number,
        )

        if not self._settings.onekhusa_is_configured:
            logger.error("OneKhusa is disabled or its credentials are incomplete")
            raise OneKhusaError("OneKhusa is disabled or its credentials are incomplete")

        if self._settings.onekhusa_merchant_account_number is None:
            logger.error("OneKhusa merchant account number is not configured")
            raise OneKhusaError("ONEKHUSA_MERCHANT_ACCOUNT_NUMBER is required")

        configured_merchant = self._settings.onekhusa_merchant_account_number
        if request.merchant_account_number not in {None, configured_merchant}:
            logger.warning(
                "Push payment rejected because the merchant account does not match "
                "the configured merchant account: source_reference=%s",
                source_reference_number,
            )
            raise OneKhusaError(
                "The request merchant account must match ONEKHUSA_MERCHANT_ACCOUNT_NUMBER"
            )

        token = await self._tokens.get()
        body = self._request_body(request, source_reference_number, configured_merchant)

        headers = {
            "Authorization": f"Bearer {token.get_secret_value()}",
            "Accept-Language": "en",
            "X-Idempotency-Key": idempotency_key,
            "Content-Type": "application/json",
        }
        url = f"{self._settings.onekhusa_base_url.rstrip('/')}/collections/push/direct/initiate"

        logger.debug(
            "Sending push-payment request to OneKhusa: source_reference=%s",
            source_reference_number,
        )

        try:
            response = await self._http.post(url, content=body, headers=headers)
        except httpx.TimeoutException as exc:
            logger.exception(
                "OneKhusa push-payment request timed out: source_reference=%s",
                source_reference_number,
            )
            raise OneKhusaError(
                "OneKhusa push request timed out; the transaction outcome is unknown"
            ) from exc
        except httpx.RequestError as exc:
            logger.exception(
                "OneKhusa push-payment connection failed: source_reference=%s",
                source_reference_number,
            )
            raise OneKhusaError(
                "Could not connect to OneKhusa; the transaction outcome may be unknown"
            ) from exc

        logger.info(
            "OneKhusa push-payment response received: source_reference=%s status_code=%d",
            source_reference_number,
            response.status_code,
        )

        if not 200 <= response.status_code < 300:
            error = response_error(response)
            logger.warning(
                "OneKhusa rejected push-payment request: "
                "source_reference=%s status_code=%d error=%s",
                source_reference_number,
                response.status_code,
                error,
            )
            raise error

        reference = self._transaction_reference(response, source_reference_number)

        logger.info(
            "OneKhusa accepted push-payment request: source_reference=%s transaction_reference=%s",
            source_reference_number,
            reference or "not_provided",
        )

        return PushPaymentResult(
            http_status=response.status_code,
            transaction_reference_number=reference,
            message="OneKhusa accepted the push-payment request",
        )

    def _request_body(
        self,
        request: PushPaymentRequest,
        source_reference_number: str,
        configured_merchant: int,
    ) -> bytes:
        payload: dict[str, Any] = request.model_dump(by_alias=True, exclude_none=True)
        payload["merchantAccountNumber"] = request.merchant_account_number or configured_merchant
        payload["sourceReferenceNumber"] = source_reference_number

        amount_text = format(request.transaction_amount, "f")
        payload["transactionAmount"] = amount_text

        body = json.dumps(payload, separators=(",", ":"))
        # OneKhusa expects transactionAmount as an unquoted JSON number.
        return body.replace(
            f'"transactionAmount":{json.dumps(amount_text)}',
            f'"transactionAmount":{amount_text}',
            1,
        ).encode()

    @staticmethod
    def _transaction_reference(
        response: httpx.Response,
        source_reference_number: str,
    ) -> str | None:
        try:
            response_payload: Any = response.json()
        except ValueError:
            response_payload = None
            logger.warning(
                "OneKhusa returned a non-JSON success response: source_reference=%s",
                source_reference_number,
            )

        reference = (
            response_payload.get("transactionReferenceNumber")
            if isinstance(response_payload, dict)
            else None
        )

        if reference is not None and not isinstance(reference, str):
            logger.warning(
                "OneKhusa returned an invalid transaction reference type: source_reference=%s",
                source_reference_number,
            )
            return None

        return reference


def provider_idempotency_key(merchant_account_number: int, source_reference_number: str) -> str:
    """Stable idempotency key for an identical merchant submission."""

    digest = hashlib.sha256(
        f"{merchant_account_number}:{source_reference_number}".encode()
    ).hexdigest()
    return f"push-{digest}"
