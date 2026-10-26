from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TransactionStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REVERSED = "reversed"


class InvalidTransition(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TransactionState:
    status: TransactionStatus

    def transition(self, target: TransactionStatus) -> TransactionState:
        allowed = {
            TransactionStatus.PENDING: {
                TransactionStatus.SUCCEEDED,
                TransactionStatus.FAILED,
            },
            TransactionStatus.SUCCEEDED: {TransactionStatus.REVERSED},
            TransactionStatus.FAILED: set(),
            TransactionStatus.REVERSED: set(),
        }
        if target == self.status:
            return self
        if target not in allowed[self.status]:
            raise InvalidTransition(f"Cannot transition {self.status} to {target}")
        return TransactionState(target)


class PaymentNotFound(Exception):
    pass


PLACEHOLDER_REFERENCE_PREFIX = "PENDING-TXN-"


class Payment(BaseModel):
    """A process-local push-payment record shared by every feature."""

    model_config = ConfigDict(populate_by_name=True)

    payment_id: str = Field(alias="paymentId")
    source_reference_number: str = Field(alias="sourceReferenceNumber")
    transaction_reference_number: str = Field(alias="transactionReferenceNumber")
    connector_id: int = Field(alias="connectorId")
    payer_account_last_four: str = Field(alias="payerAccountLastFour")
    transaction_amount: Decimal = Field(alias="transactionAmount")
    transaction_description: str = Field(alias="transactionDescription")
    captured_by: str = Field(alias="capturedBy")
    status: str
    provider_http_status: int | None = Field(default=None, alias="providerHttpStatus")
    provider_message: str | None = Field(default=None, alias="providerMessage")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    events: list[dict[str, Any]] = Field(default_factory=list)


def mask_account(account_number: str) -> str:
    """Keep only the trailing four alphanumeric characters of a payer account."""

    return re.sub(r"[^A-Za-z0-9]", "", account_number)[-4:]


def build_payment(
    *,
    payment_id: str,
    source_reference_number: str,
    transaction_reference_number: str,
    connector_id: int,
    payer_account_number: str,
    transaction_amount: Decimal,
    transaction_description: str,
    captured_by: str,
    now: datetime,
) -> Payment:
    return Payment(
        payment_id=payment_id,
        source_reference_number=source_reference_number,
        transaction_reference_number=transaction_reference_number,
        connector_id=connector_id,
        payer_account_last_four=mask_account(payer_account_number),
        transaction_amount=transaction_amount,
        transaction_description=transaction_description,
        captured_by=captured_by,
        status=TransactionStatus.PENDING.value,
        created_at=now,
        updated_at=now,
        events=[],
    )
