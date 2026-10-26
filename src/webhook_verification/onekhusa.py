import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
)

from webhook_verification.schemas import PushPaymentRequest
from webhook_verification.settings import Settings


logger = logging.getLogger(__name__)


class OneKhusaError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AccessTokenResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    access_token: SecretStr = Field(alias="accessToken")
    expires_on: datetime = Field(alias="expiresOn")
    expiry_in_minutes: int = Field(alias="expiryInMinutes", gt=0)

    @field_validator("expires_on")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expiresOn must include a timezone")
        return value


@dataclass(frozen=True, slots=True)
class PushPaymentResult:
    http_status: int
    transaction_reference_number: str | None
    message: str


class OneKhusaClient:
    """Async client for token acquisition and Collections push initiation."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http
        self._token: SecretStr | None = None
        self._expires_at = datetime.min.replace(tzinfo=UTC)
        self._token_lock = asyncio.Lock()

        logger.debug("OneKhusa client initialized")

    async def initiate_push_payment(
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
            raise OneKhusaError(
                "OneKhusa is disabled or its credentials are incomplete"
            )

        if self._settings.onekhusa_merchant_account_number is None:
            logger.error("OneKhusa merchant account number is not configured")
            raise OneKhusaError(
                "ONEKHUSA_MERCHANT_ACCOUNT_NUMBER is required"
            )

        if request.merchant_account_number not in {
            None,
            self._settings.onekhusa_merchant_account_number,
        }:
            logger.warning(
                "Push payment rejected because the merchant account does not match "
                "the configured merchant account: source_reference=%s",
                source_reference_number,
            )
            raise OneKhusaError(
                "The request merchant account must match "
                "ONEKHUSA_MERCHANT_ACCOUNT_NUMBER"
            )

        token = await self._get_access_token()

        payload = request.model_dump(by_alias=True, exclude_none=True)
        payload["merchantAccountNumber"] = (
            request.merchant_account_number
            or self._settings.onekhusa_merchant_account_number
        )
        payload["sourceReferenceNumber"] = source_reference_number

        amount_text = format(request.transaction_amount, "f")
        payload["transactionAmount"] = amount_text

        body = json.dumps(payload, separators=(",", ":"))
        body = body.replace(
            f'"transactionAmount":{json.dumps(amount_text)}',
            f'"transactionAmount":{amount_text}',
            1,
        )

        headers = {
            "Authorization": f"Bearer {token.get_secret_value()}",
            "Accept-Language": "en",
            "X-Idempotency-Key": idempotency_key,
            "Content-Type": "application/json",
        }

        url = (
            f"{self._settings.onekhusa_base_url.rstrip('/')}"
            "/collections/push/direct/initiate"
        )

        logger.debug(
            "Sending push-payment request to OneKhusa: "
            "source_reference=%s",
            source_reference_number,
        )

        try:
            response = await self._http.post(
                url,
                content=body,
                headers=headers,
            )
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
                "OneKhusa push-payment connection failed: "
                "source_reference=%s",
                source_reference_number,
            )
            raise OneKhusaError(
                "Could not connect to OneKhusa; "
                "the transaction outcome may be unknown"
            ) from exc

        logger.info(
            "OneKhusa push-payment response received: "
            "source_reference=%s status_code=%d",
            source_reference_number,
            response.status_code,
        )

        if not 200 <= response.status_code < 300:
            error = self._response_error(response)
            print(response.text)
            logger.warning(
                "OneKhusa rejected push-payment request: "
                "source_reference=%s status_code=%d error=%s",
                source_reference_number,
                response.status_code,
                error,
            )
            raise error

        try:
            response_payload: Any = response.json()
        except ValueError:
            response_payload = None
            logger.warning(
                "OneKhusa returned a non-JSON success response: "
                "source_reference=%s",
                source_reference_number,
            )

        reference = (
            response_payload.get("transactionReferenceNumber")
            if isinstance(response_payload, dict)
            else None
        )

        if reference is not None and not isinstance(reference, str):
            logger.warning(
                "OneKhusa returned an invalid transaction reference type: "
                "source_reference=%s",
                source_reference_number,
            )
            reference = None

        logger.info(
            "OneKhusa accepted push-payment request: "
            "source_reference=%s transaction_reference=%s",
            source_reference_number,
            reference or "not_provided",
        )

        return PushPaymentResult(
            http_status=response.status_code,
            transaction_reference_number=reference,
            message="OneKhusa accepted the push-payment request",
        )

    async def _get_access_token(self) -> SecretStr:
        now = datetime.now(UTC)

        if self._token is not None and now < self._expires_at - timedelta(
            seconds=30
        ):
            logger.debug("Using cached OneKhusa access token")
            return self._token

        logger.debug("OneKhusa access token is missing or near expiry")

        async with self._token_lock:
            # Recheck after acquiring the lock to avoid duplicate token requests.
            now = datetime.now(UTC)

            if self._token is not None and now < self._expires_at - timedelta(
                seconds=30
            ):
                logger.debug(
                    "Using cached OneKhusa access token after acquiring lock"
                )
                return self._token

            payload = {
                "apiKey": self._settings.onekhusa_api_key.get_secret_value(),
                "apiSecret": self._settings.onekhusa_api_secret.get_secret_value(),
                "organisationId": self._settings.onekhusa_organisation_id,
                "merchantAccountNumber": (
                    self._settings.onekhusa_merchant_account_number
                ),
            }

            url = (
                f"{self._settings.onekhusa_base_url.rstrip('/')}"
                "/account/getAccessToken"
            )

            logger.info("Requesting a new OneKhusa access token")

            try:
                response = await self._http.post(
                    url,
                    json=payload,
                    headers={"Accept-Language": "en"},
                )
            except httpx.TimeoutException as exc:
                logger.exception("OneKhusa access-token request timed out")
                raise OneKhusaError(
                    "OneKhusa access-token request timed out"
                ) from exc
            except httpx.RequestError as exc:
                logger.exception(
                    "Could not connect to OneKhusa for an access token"
                )
                raise OneKhusaError(
                    "Could not connect to OneKhusa for an access token"
                ) from exc

            logger.info(
                "OneKhusa access-token response received: status_code=%d",
                response.status_code,
            )

            if not 200 <= response.status_code < 300:
                error = self._response_error(response)
                logger.warning(
                    "OneKhusa access-token request failed: status_code=%d error=%s",
                    response.status_code,
                    error,
                )
                raise error

            try:
                token_response = AccessTokenResponse.model_validate(
                    response.json()
                )
            except (ValueError, ValidationError) as exc:
                logger.exception(
                    "OneKhusa returned an invalid access-token response"
                )
                raise OneKhusaError(
                    "OneKhusa returned an invalid access-token response"
                ) from exc

            self._token = token_response.access_token
            self._expires_at = token_response.expires_on

            logger.info(
                "OneKhusa access token acquired successfully: expires_at=%s",
                self._expires_at.isoformat(),
            )

            return self._token

    @staticmethod
    def _response_error(response: httpx.Response) -> OneKhusaError:
        detail = f"OneKhusa returned HTTP {response.status_code}"

        try:
            body = response.json()
        except ValueError:
            body = None

        if isinstance(body, dict):
            error_code = body.get("errorCode")
            if isinstance(error_code, str):
                detail = f"{detail} ({error_code[:24]})"

        return OneKhusaError(
            detail,
            status_code=response.status_code,
        )


def create_http_client(settings: Settings) -> httpx.AsyncClient:
    logger.debug("Creating asynchronous HTTP client for OneKhusa")

    return httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=settings.onekhusa_connect_timeout_seconds,
            read=settings.onekhusa_read_timeout_seconds,
            write=settings.onekhusa_read_timeout_seconds,
            pool=settings.onekhusa_connect_timeout_seconds,
        ),
        follow_redirects=False,
    )
