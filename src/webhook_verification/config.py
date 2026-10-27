"""Application settings.

The OneKhusa adapter owns its own settings model. This module is the single
environment loader for the demo and composes the adapter settings, so the
adapter never imports application code.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from webhook_verification.onekhusa.config import OneKhusaSettings
from webhook_verification.onekhusa.webhook.events import PushWebhookEvent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    app_env: Literal["development", "test", "production"] = "development"
    onekhusa_enabled: bool = Field(default=False, validation_alias="ONEKHUSA_ENABLED")
    onekhusa_base_url: str = Field(
        default="https://api.onekhusa.com/sandbox/v1",
        validation_alias="ONEKHUSA_BASE_URL",
    )
    onekhusa_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias="ONEKHUSA_API_KEY",
    )
    onekhusa_api_secret: SecretStr = Field(
        default=SecretStr(""),
        validation_alias="ONEKHUSA_API_SECRET",
    )
    onekhusa_organisation_id: str = Field(
        default="",
        validation_alias="ONEKHUSA_ORGANISATION_ID",
    )
    onekhusa_merchant_account_number: int | None = Field(
        default=None,
        ge=10_000_000,
        le=99_999_999,
        validation_alias="ONEKHUSA_MERCHANT_ACCOUNT_NUMBER",
    )
    onekhusa_connect_timeout_seconds: float = Field(
        default=5.0,
        gt=0,
        validation_alias="ONEKHUSA_CONNECT_TIMEOUT_SECONDS",
    )
    onekhusa_read_timeout_seconds: float = Field(
        default=20.0,
        gt=0,
        validation_alias="ONEKHUSA_READ_TIMEOUT_SECONDS",
    )
    onekhusa_webhook_secrets: dict[PushWebhookEvent, SecretStr] = Field(
        default_factory=dict,
        validation_alias="ONEKHUSA_WEBHOOK_SECRETS",
    )
    max_webhook_body_bytes: int = Field(default=1_048_576, ge=1)

    @property
    def onekhusa(self) -> OneKhusaSettings:
        """Build the adapter settings from the flat environment variables."""

        return OneKhusaSettings(
            enabled=self.onekhusa_enabled,
            base_url=self.onekhusa_base_url,
            api_key=self.onekhusa_api_key,
            api_secret=self.onekhusa_api_secret,
            organisation_id=self.onekhusa_organisation_id,
            merchant_account_number=self.onekhusa_merchant_account_number,
            connect_timeout_seconds=self.onekhusa_connect_timeout_seconds,
            read_timeout_seconds=self.onekhusa_read_timeout_seconds,
            webhook_secrets=self.onekhusa_webhook_secrets,
        )

    @property
    def onekhusa_is_configured(self) -> bool:
        return self.onekhusa.is_configured

    @property
    def onekhusa_is_sandbox(self) -> bool:
        return self.onekhusa.is_sandbox


@lru_cache
def get_settings() -> Settings:
    return Settings()
