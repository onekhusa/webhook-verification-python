"""OneKhusa push-payment webhook payload.

Reference semantics, in OneKhusa's own field names:

- ``merchantReferenceNumber`` echoes the merchant reference submitted on
  initiation.
- ``sourceReferenceNumber`` is the payer's bank or MNO reference. It is not the
  merchant reference, despite the confusing name.
- ``transactionReferenceNumber`` is the provider transaction reference.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PushWebhookPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    connector_id: int = Field(alias="connectorId", gt=0)
    payer_reference_number: str | None = Field(
        default=None,
        alias="sourceReferenceNumber",
    )
    merchant_reference_number: str | None = Field(
        default=None,
        alias="merchantReferenceNumber",
    )
    provider_transaction_reference: str | None = Field(
        default=None,
        alias="transactionReferenceNumber",
    )
    transaction_amount: Decimal | None = Field(
        default=None,
        alias="transactionAmount",
        gt=0,
    )
    transaction_status_code: str | None = Field(
        default=None,
        alias="transactionStatusCode",
    )
    response_code: str | None = Field(default=None, alias="responseCode")
    transaction_date: datetime | None = Field(default=None, alias="transactionDate")

    @field_validator(
        "payer_reference_number",
        "merchant_reference_number",
        "provider_transaction_reference",
        mode="before",
    )
    @classmethod
    def normalize_reference(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value
