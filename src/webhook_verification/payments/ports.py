"""The only seams the application layer depends on.

Three ports are enough for this reference:

- :class:`PaymentRepository` for storage, with an explicit transaction boundary
  so a durable adapter can make a webhook update atomic.
- :class:`PushPaymentGateway` for provider initiation, expressed in neutral
  domain terms.
- :class:`Clock` for deterministic timestamps in tests.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import AbstractAsyncContextManager
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from webhook_verification.payments.models import Payment, PaymentEventKind


@dataclass(frozen=True, slots=True)
class InitiatePaymentCommand:
    """A provider-neutral request to start a push payment."""

    merchant_reference: str
    connector_id: int
    payer_account_number: str
    transaction_amount: Decimal
    transaction_description: str
    captured_by: str
    merchant_account_number: int | None = None

    def fingerprint(self) -> str:
        """Stable digest used to detect a reused reference with a new body."""

        material = json.dumps(asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(material.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ProviderAcceptance:
    """What the provider returned after accepting an initiation request."""

    http_status: int
    provider_transaction_reference: str | None
    message: str


@dataclass(frozen=True, slots=True)
class WebhookNotification:
    """A verified, parsed callback, already mapped to domain terms."""

    event: PaymentEventKind
    merchant_reference: str | None
    provider_transaction_reference: str | None


class PaymentTransaction(Protocol):
    """Storage operations valid only inside an open transaction."""

    def add(self, payment: Payment) -> Payment: ...

    def get(self, payment_id: str) -> Payment: ...

    def find_by_merchant_reference(self, reference: str) -> Payment | None: ...

    def find_by_provider_reference(self, reference: str) -> Payment | None: ...

    def save(self, payment: Payment) -> Payment: ...

    def list(self) -> list[Payment]: ...

    def receipt_seen(self, receipt_key: str) -> bool: ...

    def claim_receipt(self, receipt_key: str) -> None: ...


class PaymentRepository(Protocol):
    """Store of payment records.

    ``transaction`` is the unit of work boundary. The in-memory adapter uses a
    lock; a database adapter should use a real transaction.
    """

    def transaction(self) -> AbstractAsyncContextManager[PaymentTransaction]: ...

    async def get(self, payment_id: str) -> Payment: ...

    async def list(self, limit: int | None = None) -> list[Payment]: ...

    async def clear(self) -> None: ...


class PushPaymentGateway(Protocol):
    """Provider initiation in domain terms."""

    async def initiate(self, command: InitiatePaymentCommand) -> ProviderAcceptance: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
