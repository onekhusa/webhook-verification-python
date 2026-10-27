"""Public request and response models for the demo HTTP API.

These are deliberately separate from the domain model and from the OneKhusa
wire contract. Field names here are the API's names, not OneKhusa's.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from webhook_verification.payments.models import Payment, PaymentEvent, PaymentStatus
from webhook_verification.payments.ports import InitiatePaymentCommand

MerchantReference = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
PayerAccount = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]


class InitiatePaymentRequest(BaseModel):
    """A request to initiate a push payment.

    ``merchantReferenceNumber`` is your own identifier. OneKhusa receives it as
    ``sourceReferenceNumber`` and echoes it as ``merchantReferenceNumber`` on
    every callback.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    merchant_reference_number: MerchantReference = Field(alias="merchantReferenceNumber")
    connector_id: int = Field(alias="connectorId", gt=0)
    payer_account_number: PayerAccount = Field(alias="payerAccountNumber")
    transaction_amount: Decimal = Field(
        alias="transactionAmount",
        gt=0,
        max_digits=18,
        decimal_places=2,
    )
    transaction_description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ] = Field(alias="transactionDescription")
    captured_by: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
    ] = Field(alias="capturedBy")
    merchant_account_number: int | None = Field(
        default=None,
        alias="merchantAccountNumber",
        ge=10_000_000,
        le=99_999_999,
    )

    def to_command(self) -> InitiatePaymentCommand:
        return InitiatePaymentCommand(
            merchant_reference=self.merchant_reference_number,
            connector_id=self.connector_id,
            payer_account_number=self.payer_account_number,
            transaction_amount=self.transaction_amount,
            transaction_description=self.transaction_description,
            captured_by=self.captured_by,
            merchant_account_number=self.merchant_account_number,
        )


class PaymentEventResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    event: str
    received_at: datetime = Field(alias="receivedAt")
    signature_verified: bool = Field(alias="signatureVerified")


class PaymentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    payment_id: str = Field(alias="paymentId")
    merchant_reference_number: str = Field(alias="merchantReferenceNumber")
    provider_transaction_reference: str | None = Field(
        default=None,
        alias="providerTransactionReference",
    )
    connector_id: int = Field(alias="connectorId")
    payer_account_last_four: str = Field(alias="payerAccountLastFour")
    transaction_amount: Decimal = Field(alias="transactionAmount")
    transaction_description: str = Field(alias="transactionDescription")
    captured_by: str = Field(alias="capturedBy")
    status: PaymentStatus
    submission_http_status: int | None = Field(
        default=None,
        alias="submissionHttpStatus",
    )
    submission_message: str | None = Field(default=None, alias="submissionMessage")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    events: list[PaymentEventResponse] = Field(default_factory=list)

    @classmethod
    def from_payment(cls, payment: Payment) -> PaymentResponse:
        return cls(
            payment_id=payment.payment_id,
            merchant_reference_number=payment.merchant_reference_number,
            provider_transaction_reference=payment.provider_transaction_reference,
            connector_id=payment.connector_id,
            payer_account_last_four=payment.payer_account_last_four,
            transaction_amount=payment.transaction_amount,
            transaction_description=payment.transaction_description,
            captured_by=payment.captured_by,
            status=payment.status,
            submission_http_status=payment.submission_http_status,
            submission_message=payment.submission_message,
            created_at=payment.created_at,
            updated_at=payment.updated_at,
            events=[_event_response(event) for event in payment.events],
        )


def _event_response(event: PaymentEvent) -> PaymentEventResponse:
    return PaymentEventResponse(
        event=event.kind.value,
        received_at=event.received_at,
        signature_verified=event.signature_verified,
    )


class ErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool = False
    payment: PaymentResponse | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
