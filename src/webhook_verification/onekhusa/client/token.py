from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
)

from webhook_verification.features.configuration.settings import Settings
from webhook_verification.onekhusa.errors import OneKhusaError, response_error

logger = logging.getLogger(__name__)


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


class AccessTokenProvider:
    """Acquire and cache a OneKhusa access token in process memory."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http
        self._token: SecretStr | None = None
        self._expires_at = datetime.min.replace(tzinfo=UTC)
        self._lock = asyncio.Lock()

    async def get(self) -> SecretStr:
        now = datetime.now(UTC)
        if self._token is not None and now < self._expires_at - timedelta(seconds=30):
            logger.debug("Using cached OneKhusa access token")
            return self._token

        logger.debug("OneKhusa access token is missing or near expiry")

        async with self._lock:
            now = datetime.now(UTC)
            if self._token is not None and now < self._expires_at - timedelta(seconds=30):
                logger.debug("Using cached OneKhusa access token after acquiring lock")
                return self._token

            token = await self._request_token()
            self._token = token.access_token
            self._expires_at = token.expires_on

            logger.info(
                "OneKhusa access token acquired: expires_at=%s",
                self._expires_at.isoformat(),
            )
            return token.access_token

    async def _request_token(self) -> AccessTokenResponse:
        payload = {
            "apiKey": self._settings.onekhusa_api_key.get_secret_value(),
            "apiSecret": self._settings.onekhusa_api_secret.get_secret_value(),
            "organisationId": self._settings.onekhusa_organisation_id,
            "merchantAccountNumber": self._settings.onekhusa_merchant_account_number,
        }
        url = f"{self._settings.onekhusa_base_url.rstrip('/')}/account/getAccessToken"

        logger.info("Requesting a new OneKhusa access token")

        try:
            response = await self._http.post(
                url,
                json=payload,
                headers={"Accept-Language": "en"},
            )
        except httpx.TimeoutException as exc:
            logger.exception("OneKhusa access-token request timed out")
            raise OneKhusaError("OneKhusa access-token request timed out") from exc
        except httpx.RequestError as exc:
            logger.exception("Could not connect to OneKhusa for an access token")
            raise OneKhusaError("Could not connect to OneKhusa for an access token") from exc

        logger.info(
            "OneKhusa access-token response received: status_code=%d",
            response.status_code,
        )

        if not 200 <= response.status_code < 300:
            error = response_error(response)
            logger.warning(
                "OneKhusa access-token request failed: status_code=%d error=%s",
                response.status_code,
                error,
            )
            raise error

        try:
            return AccessTokenResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            logger.exception("OneKhusa returned an invalid access-token response")
            raise OneKhusaError("OneKhusa returned an invalid access-token response") from exc
