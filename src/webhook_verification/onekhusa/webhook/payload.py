from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PushWebhookPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    connector_id: int = Field(alias="connectorId", gt=0)
    source_reference_number: str | None = Field(
        default=None,
        alias="sourceReferenceNumber",
    )
    merchant_reference_number: str | None = Field(
        default=None,
        alias="merchantReferenceNumber",
    )
    transaction_reference_number: str | None = Field(
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
        "source_reference_number",
        "merchant_reference_number",
        "transaction_reference_number",
        mode="before",
    )
    @classmethod
    def normalize_reference(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value
