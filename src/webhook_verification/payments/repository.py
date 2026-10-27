"""Process-local repository used by the demo application.

This adapter exists to make the demo runnable. It is deliberately not a
production store: state disappears on restart and is capped at
``MAX_PAYMENTS``. A durable adapter implements the same
:class:`~webhook_verification.payments.ports.PaymentRepository` protocol.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from webhook_verification.payments.errors import (
    DuplicateMerchantReference,
    PaymentNotFound,
)
from webhook_verification.payments.models import Payment

if TYPE_CHECKING:
    from webhook_verification.payments.ports import PaymentTransaction

MAX_PAYMENTS = 100
MAX_RECEIPTS = MAX_PAYMENTS * 10


class InMemoryPaymentRepository:
    def __init__(self) -> None:
        self._payments: dict[str, Payment] = {}
        self._receipts: set[str] = set()
        self._receipt_order: list[str] = []
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[PaymentTransaction]:
        """Hold the store lock for the duration of one unit of work."""

        async with self._lock:
            yield InMemoryPaymentTransaction(self)

    async def get(self, payment_id: str) -> Payment:
        async with self.transaction() as transaction:
            return transaction.get(payment_id)

    async def list(self, limit: int | None = None) -> list[Payment]:
        async with self.transaction() as transaction:
            payments = transaction.list()
        if limit is not None:
            return payments[:limit]
        return payments

    async def clear(self) -> None:
        async with self.transaction():
            self._payments.clear()
            self._receipts.clear()
            self._receipt_order.clear()


class InMemoryPaymentTransaction:
    """A synchronous view of the store, valid only inside ``transaction()``."""

    __slots__ = ("_repository",)

    def __init__(self, repository: InMemoryPaymentRepository) -> None:
        self._repository = repository

    def add(self, payment: Payment) -> Payment:
        if payment.payment_id in self._repository._payments:
            raise DuplicateMerchantReference(
                f"Payment id {payment.payment_id} is already in use"
            )
        if any(
            stored.merchant_reference_number == payment.merchant_reference_number
            for stored in self._repository._payments.values()
        ):
            raise DuplicateMerchantReference(
                "Merchant reference is already in use. "
                "Use a new reference for a different payment."
            )

        self._repository._payments[payment.payment_id] = snapshot(payment)
        self._trim()
        return snapshot(payment)

    def get(self, payment_id: str) -> Payment:
        payment = self._repository._payments.get(payment_id)
        if payment is None:
            raise PaymentNotFound(payment_id)
        return snapshot(payment)

    def find_by_merchant_reference(self, reference: str) -> Payment | None:
        for payment in self._repository._payments.values():
            if payment.merchant_reference_number == reference:
                return snapshot(payment)
        return None

    def find_by_provider_reference(self, reference: str) -> Payment | None:
        for payment in self._repository._payments.values():
            if payment.provider_transaction_reference == reference:
                return snapshot(payment)
        return None

    def save(self, payment: Payment) -> Payment:
        stored = self._repository._payments.get(payment.payment_id)
        if stored is None:
            raise PaymentNotFound(payment.payment_id)
        if stored.merchant_reference_number != payment.merchant_reference_number:
            raise ValueError("merchant_reference_number cannot be changed")
        self._repository._payments[payment.payment_id] = snapshot(payment)
        return snapshot(payment)

    def list(self) -> list[Payment]:
        ordered = sorted(
            self._repository._payments.values(),
            key=lambda payment: payment.created_at,
            reverse=True,
        )
        return [snapshot(payment) for payment in ordered]

    def receipt_seen(self, receipt_key: str) -> bool:
        return receipt_key in self._repository._receipts

    def claim_receipt(self, receipt_key: str) -> None:
        receipts = self._repository._receipts
        if receipt_key in receipts:
            return
        receipts.add(receipt_key)
        self._repository._receipt_order.append(receipt_key)
        while len(self._repository._receipt_order) > MAX_RECEIPTS:
            expired = self._repository._receipt_order.pop(0)
            receipts.discard(expired)

    def _trim(self) -> None:
        payments = self._repository._payments
        while len(payments) > MAX_PAYMENTS:
            oldest_id = min(
                payments,
                key=lambda payment_id: payments[payment_id].created_at,
            )
            payments.pop(oldest_id)


def snapshot(payment: Payment) -> Payment:
    return payment.model_copy(deep=True)
