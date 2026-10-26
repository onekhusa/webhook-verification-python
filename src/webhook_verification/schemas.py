from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from webhook_verification.domain import PushWebhookEvent

AccountReference = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]
Reference = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class PushPaymentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    merchant_account_number: int | None = Field(
        default=None, alias="merchantAccountNumber", ge=10_000_000, le=99_999_999
    )
    connector_id: int = Field(alias="connectorId", gt=0)
    payer_account_number: AccountReference = Field(alias="payerAccountNumber")
    source_reference_number: Reference | None = Field(default=None, alias="sourceReferenceNumber")
    transaction_description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ] = Field(alias="transactionDescription")
    transaction_amount: Decimal = Field(
        alias="transactionAmount", gt=0, max_digits=18, decimal_places=2
    )
    captured_by: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
    ] = Field(alias="capturedBy")


class PushWebhookPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    connector_id: int = Field(alias="connectorId", gt=0)
    source_reference_number: str | None = Field(default=None, alias="sourceReferenceNumber")
    transaction_reference_number: str | None = Field(
        default=None, alias="transactionReferenceNumber"
    )
    transaction_amount: Decimal | None = Field(default=None, alias="transactionAmount", gt=0)
    transaction_status_code: str | None = Field(default=None, alias="transactionStatusCode")
    response_code: str | None = Field(default=None, alias="responseCode")
    transaction_date: datetime | None = Field(default=None, alias="transactionDate")


class SimulationEventRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    event: PushWebhookEvent

    @field_validator("event", mode="before")
    @classmethod
    def validate_event(cls, value: object) -> object:
        allowed = {event.value for event in PushWebhookEvent}
        if not isinstance(value, str) or value not in allowed:
            raise ValueError("Unsupported push-payment event")
        return value


class SimulationTransaction(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    simulation_id: str = Field(alias="simulationId")
    source_reference_number: str = Field(alias="sourceReferenceNumber")
    transaction_reference_number: str = Field(alias="transactionReferenceNumber")
    connector_id: int = Field(alias="connectorId")
    payer_account_last_four: str = Field(alias="payerAccountLastFour")
    transaction_amount: Decimal = Field(alias="transactionAmount")
    transaction_description: str = Field(alias="transactionDescription")
    captured_by: str = Field(alias="capturedBy")
    mode: str = "simulated"
    status: str
    provider_http_status: int | None = Field(default=None, alias="providerHttpStatus")
    provider_message: str | None = Field(default=None, alias="providerMessage")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    events: list[dict[str, Any]]
