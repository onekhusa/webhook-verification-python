from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field

from webhook_verification.payments.errors import InvalidTransition


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REVERSED = "reversed"


class PaymentEventKind(StrEnum):
    """Provider-neutral event kinds recorded in a payment's history."""

    SUCCESS = "success"
    FAILED = "failed"
    REVERSED = "reversed"


class PaymentEvent(BaseModel):
    kind: PaymentEventKind
    received_at: datetime
    signature_verified: bool = True


@dataclass(frozen=True, slots=True)
class PaymentState:
    """The allowed lifecycle: pending -> succeeded|failed, succeeded -> reversed."""

    status: PaymentStatus

    def transition(self, target: PaymentStatus) -> PaymentState:
        allowed = {
            PaymentStatus.PENDING: {
                PaymentStatus.SUCCEEDED,
                PaymentStatus.FAILED,
            },
            PaymentStatus.SUCCEEDED: {PaymentStatus.REVERSED},
            PaymentStatus.FAILED: set(),
            PaymentStatus.REVERSED: set(),
        }
        if target == self.status:
            return self
        if target not in allowed[self.status]:
            raise InvalidTransition(f"Cannot transition {self.status} to {target}")
        return PaymentState(target)


class Payment(BaseModel):
    """A process-local push-payment record.

    This is the domain model. API field names are defined by
    ``web.schemas.PaymentResponse`` so the domain can evolve without silently
    changing the published JSON.
    """

    payment_id: str
    merchant_reference_number: str
    provider_transaction_reference: str | None = None
    connector_id: int
    payer_account_last_four: str
    transaction_amount: Decimal
    transaction_description: str
    captured_by: str
    status: PaymentStatus = PaymentStatus.PENDING
    submission_http_status: int | None = None
    submission_message: str | None = None
    created_at: datetime
    updated_at: datetime
    events: list[PaymentEvent] = Field(default_factory=list)
    submission_fingerprint: str = Field(default="", exclude=True)


def mask_account(account_number: str) -> str:
    """Keep only the trailing four alphanumeric characters of a payer account."""

    return re.sub(r"[^A-Za-z0-9]", "", account_number)[-4:]


def build_payment(
    *,
    payment_id: str,
    merchant_reference_number: str,
    connector_id: int,
    payer_account_number: str,
    transaction_amount: Decimal,
    transaction_description: str,
    captured_by: str,
    submission_fingerprint: str,
    now: datetime,
) -> Payment:
    return Payment(
        payment_id=payment_id,
        merchant_reference_number=merchant_reference_number,
        connector_id=connector_id,
        payer_account_last_four=mask_account(payer_account_number),
        transaction_amount=transaction_amount,
        transaction_description=transaction_description,
        captured_by=captured_by,
        status=PaymentStatus.PENDING,
        created_at=now,
        updated_at=now,
        submission_fingerprint=submission_fingerprint,
    )
