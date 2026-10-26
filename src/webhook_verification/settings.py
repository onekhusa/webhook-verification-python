from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    simulation_enabled: bool = False
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
    one_khusa_webhook_secrets: dict[str, SecretStr] = Field(
        default_factory=dict, validation_alias="ONEKHUSA_WEBHOOK_SECRETS"
    )
    max_webhook_body_bytes: int = Field(default=1_048_576, ge=1)

    @property
    def onekhusa_is_configured(self) -> bool:
        return bool(
            self.onekhusa_enabled
            and self.onekhusa_api_key.get_secret_value()
            and self.onekhusa_api_secret.get_secret_value()
            and self.onekhusa_organisation_id
            and self.onekhusa_merchant_account_number
        )

    @property
    def onekhusa_is_sandbox(self) -> bool:
        parsed_url = urlsplit(self.onekhusa_base_url)
        return (
            parsed_url.scheme == "https"
            and parsed_url.hostname == "api.onekhusa.com"
            and parsed_url.port in {None, 443}
            and parsed_url.username is None
            and parsed_url.password is None
            and parsed_url.path.lower().startswith("/sandbox/")
            and not parsed_url.query
            and not parsed_url.fragment
        )

    @field_validator("onekhusa_base_url")
    @classmethod
    def validate_onekhusa_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith("https://"):
            raise ValueError("ONEKHUSA_BASE_URL must use HTTPS")
        return normalized


@lru_cache
def get_settings() -> Settings:
    return Settings()
