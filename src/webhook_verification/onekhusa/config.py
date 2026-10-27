"""Configuration owned by the OneKhusa adapter.

This module deliberately depends on nothing outside ``onekhusa``. A consumer can
copy the ``onekhusa`` package, build :class:`OneKhusaSettings` from their own
environment, and leave the demo application behind.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from webhook_verification.onekhusa.webhook.events import PushWebhookEvent

DEFAULT_BASE_URL = "https://api.onekhusa.com/sandbox/v1"


class OneKhusaSettings(BaseModel):
    """Credentials, endpoints and webhook secrets for OneKhusa Collections."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = False
    base_url: str = DEFAULT_BASE_URL
    api_key: SecretStr = SecretStr("")
    api_secret: SecretStr = SecretStr("")
    organisation_id: str = ""
    merchant_account_number: int | None = Field(
        default=None,
        ge=10_000_000,
        le=99_999_999,
    )
    connect_timeout_seconds: float = Field(default=5.0, gt=0)
    read_timeout_seconds: float = Field(default=20.0, gt=0)
    webhook_secrets: dict[PushWebhookEvent, SecretStr] = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith("https://"):
            raise ValueError("ONEKHUSA_BASE_URL must use HTTPS")
        return normalized

    @property
    def is_configured(self) -> bool:
        """True when a call could be made with the current credentials."""

        return bool(
            self.enabled
            and self.api_key.get_secret_value()
            and self.api_secret.get_secret_value()
            and self.organisation_id
            and self.merchant_account_number
        )

    @property
    def is_sandbox(self) -> bool:
        """Only documented sandbox endpoints are accepted by this reference."""

        parsed_url = urlsplit(self.base_url)
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

    def webhook_secret(self, event: PushWebhookEvent) -> SecretStr | None:
        """Return the configured secret for an event, or None when unusable."""

        secret = self.webhook_secrets.get(event)
        if secret is None or not secret.get_secret_value():
            return None
        return secret
