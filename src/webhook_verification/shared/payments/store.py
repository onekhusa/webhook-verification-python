from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from webhook_verification.shared.payments.models import (
    PLACEHOLDER_REFERENCE_PREFIX,
    Payment,
    PaymentNotFound,
)

MAX_PAYMENTS = 100
MAX_RECEIPTS = MAX_PAYMENTS * 10


class InMemoryPaymentStore:
    """Process-local payment state; no database or disk writes are performed.

    Features access the mutable records through :meth:`locked`, which keeps
    matching, de-duplication and state transitions atomic without holding the
    lock across provider network calls.
    """

    def __init__(self) -> None:
        self._payments: dict[str, Payment] = {}
        self._provider_fingerprints: dict[str, str] = {}
        self._receipts: set[str] = set()
        self._receipt_order: list[str] = []
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def locked(self) -> AsyncIterator[PaymentSession]:
        async with self._lock:
            yield PaymentSession(self)


class PaymentSession:
    """Synchronous view over the store, valid only inside ``store.locked()``."""

    __slots__ = ("_store",)

    def __init__(self, store: InMemoryPaymentStore) -> None:
        self._store = store

    def list(self) -> list[Payment]:
        ordered = sorted(
            self._store._payments.values(),
            key=lambda payment: payment.created_at,
            reverse=True,
        )
        return [snapshot(payment) for payment in ordered]

    def get(self, payment_id: str) -> Payment:
        payment = self._store._payments.get(payment_id)
        if payment is None:
            raise PaymentNotFound(payment_id)
        return snapshot(payment)

    def clear(self) -> None:
        self._store._payments.clear()
        self._store._provider_fingerprints.clear()
        self._store._receipts.clear()
        self._store._receipt_order.clear()

    def add(
        self,
        payment: Payment,
        *,
        provider_fingerprint: str | None = None,
    ) -> Payment:
        if any(
            item.source_reference_number == payment.source_reference_number
            for item in self._store._payments.values()
        ):
            raise ValueError("Source reference is already in use")

        self._store._payments[payment.payment_id] = payment
        if provider_fingerprint is not None:
            self._store._provider_fingerprints[payment.source_reference_number] = (
                provider_fingerprint
            )
        self._trim()
        return snapshot(payment)

    def find_by_source_reference(self, source_reference: str) -> Payment | None:
        return next(
            (
                payment
                for payment in self._store._payments.values()
                if payment.source_reference_number == source_reference
            ),
            None,
        )

    def provider_fingerprint(self, source_reference: str) -> str | None:
        return self._store._provider_fingerprints.get(source_reference)

    def set_provider_result(
        self,
        payment_id: str,
        *,
        http_status: int | None,
        message: str,
        transaction_reference_number: str | None = None,
    ) -> Payment:
        payment = self._store._payments[payment_id]
        payment.provider_http_status = http_status
        payment.provider_message = message
        if transaction_reference_number:
            payment.transaction_reference_number = transaction_reference_number
        payment.updated_at = datetime.now(UTC)
        return snapshot(payment)

    def is_duplicate_receipt(self, receipt_key: str) -> bool:
        return receipt_key in self._store._receipts

    def remember_receipt(self, receipt_key: str) -> None:
        self._store._receipts.add(receipt_key)
        self._store._receipt_order.append(receipt_key)
        while len(self._store._receipt_order) > MAX_RECEIPTS:
            expired = self._store._receipt_order.pop(0)
            self._store._receipts.discard(expired)

    def find_for_webhook(
        self,
        *,
        merchant_reference: str | None,
        provider_reference: str | None,
    ) -> Payment | None:
        if merchant_reference:
            payment = self.find_by_source_reference(merchant_reference)
            if payment is not None:
                if not provider_reference:
                    return payment
                if payment.transaction_reference_number == provider_reference:
                    return payment
                if payment.transaction_reference_number.startswith(PLACEHOLDER_REFERENCE_PREFIX):
                    return payment
                # A matching merchant reference with a different, already known
                # provider reference is a conflict. Do not fall back to another
                # payment, or a callback could be applied to the wrong record.
                return None

        if provider_reference:
            return next(
                (
                    payment
                    for payment in self._store._payments.values()
                    if payment.transaction_reference_number == provider_reference
                ),
                None,
            )

        return None

    def _trim(self) -> None:
        while len(self._store._payments) > MAX_PAYMENTS:
            oldest_id = min(
                self._store._payments,
                key=lambda payment_id: self._store._payments[payment_id].created_at,
            )
            removed = self._store._payments.pop(oldest_id)
            self._store._provider_fingerprints.pop(
                removed.source_reference_number,
                None,
            )


def snapshot(payment: Payment) -> Payment:
    return payment.model_copy(deep=True)
