"""Merchant/provider reference correlation policy.

Correlation is business logic, not persistence. Keeping it here means a new
storage adapter cannot accidentally change which payment a callback updates.

Order of precedence:

1. Match the merchant reference. When a provider reference is present it must
   be absent locally or equal; a different, already-known provider reference is
   a conflict and must not fall back to another payment.
2. If the merchant reference is unknown, fall back to the provider reference.
3. Otherwise the callback is unmatched.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from webhook_verification.payments.models import Payment
from webhook_verification.payments.ports import PaymentTransaction


class CorrelationOutcome(StrEnum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class CorrelationResult:
    outcome: CorrelationOutcome
    payment: Payment | None = None
    reason: str = ""


def correlate(
    transaction: PaymentTransaction,
    *,
    merchant_reference: str | None,
    provider_reference: str | None,
) -> CorrelationResult:
    if merchant_reference:
        payment = transaction.find_by_merchant_reference(merchant_reference)
        if payment is not None:
            stored_provider_reference = payment.provider_transaction_reference
            if (
                not provider_reference
                or stored_provider_reference is None
                or stored_provider_reference == provider_reference
            ):
                return CorrelationResult(
                    CorrelationOutcome.MATCHED,
                    payment,
                    "matched by merchant reference",
                )
            return CorrelationResult(
                CorrelationOutcome.CONFLICT,
                None,
                "merchant reference matched a payment with a different provider reference",
            )

    if provider_reference:
        payment = transaction.find_by_provider_reference(provider_reference)
        if payment is not None:
            return CorrelationResult(
                CorrelationOutcome.MATCHED,
                payment,
                "matched by provider reference",
            )

    return CorrelationResult(
        CorrelationOutcome.UNMATCHED,
        None,
        "no stored payment matched the callback references",
    )
