from __future__ import annotations

import pytest

from tests.support import make_payment
from webhook_verification.features.payments.service import PaymentsService
from webhook_verification.shared.payments.models import PaymentNotFound
from webhook_verification.shared.payments.store import InMemoryPaymentStore


@pytest.mark.asyncio
async def test_get_returns_a_stored_payment() -> None:
    store = InMemoryPaymentStore()
    service = PaymentsService(store)
    async with store.locked() as session:
        session.add(make_payment("1"))

    payment = await service.get("pay-1")

    assert payment.source_reference_number == "ORDER-1"


@pytest.mark.asyncio
async def test_get_missing_payment_raises() -> None:
    service = PaymentsService(InMemoryPaymentStore())

    with pytest.raises(PaymentNotFound):
        await service.get("missing")


@pytest.mark.asyncio
async def test_clear_removes_all_payments() -> None:
    store = InMemoryPaymentStore()
    service = PaymentsService(store)
    async with store.locked() as session:
        session.add(make_payment("1"))

    await service.clear()

    assert await service.list() == []
