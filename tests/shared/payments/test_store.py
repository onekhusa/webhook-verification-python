from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.support import make_payment
from webhook_verification.shared.payments.models import PaymentNotFound
from webhook_verification.shared.payments.store import (
    MAX_PAYMENTS,
    InMemoryPaymentStore,
)


@pytest.mark.asyncio
async def test_add_and_get_return_snapshots() -> None:
    store = InMemoryPaymentStore()

    async with store.locked() as session:
        saved = session.add(make_payment("1"))
    saved.status = "failed"

    async with store.locked() as session:
        current = session.get("pay-1")

    assert current.status == "pending"
    assert current.source_reference_number == "ORDER-1"


@pytest.mark.asyncio
async def test_get_missing_payment_raises() -> None:
    store = InMemoryPaymentStore()

    async with store.locked() as session:
        with pytest.raises(PaymentNotFound):
            session.get("missing")


@pytest.mark.asyncio
async def test_duplicate_source_reference_is_rejected() -> None:
    store = InMemoryPaymentStore()

    async with store.locked() as session:
        session.add(make_payment("1"))
        with pytest.raises(ValueError, match="already in use"):
            session.add(make_payment("2", source_reference_number="ORDER-1"))


@pytest.mark.asyncio
async def test_store_trims_to_the_oldest_recent_payments() -> None:
    store = InMemoryPaymentStore()
    start = datetime.now(UTC) - timedelta(days=1)

    async with store.locked() as session:
        for index in range(MAX_PAYMENTS + 1):
            session.add(
                make_payment(
                    str(index),
                    created_at=start + timedelta(seconds=index),
                )
            )
        payments = session.list()

    assert len(payments) == MAX_PAYMENTS
    assert payments[-1].source_reference_number == "ORDER-1"
    assert payments[0].source_reference_number == f"ORDER-{MAX_PAYMENTS}"


@pytest.mark.asyncio
async def test_receipts_are_deduplicated() -> None:
    store = InMemoryPaymentStore()

    async with store.locked() as session:
        assert not session.is_duplicate_receipt("receipt-1")
        session.remember_receipt("receipt-1")
        assert session.is_duplicate_receipt("receipt-1")


@pytest.mark.asyncio
async def test_clear_removes_payments_receipts_and_fingerprints() -> None:
    store = InMemoryPaymentStore()

    async with store.locked() as session:
        session.add(make_payment("1"), provider_fingerprint="fingerprint")
        session.remember_receipt("receipt-1")
        session.clear()
        assert session.list() == []
        assert not session.is_duplicate_receipt("receipt-1")
        assert session.provider_fingerprint("ORDER-1") is None


@pytest.mark.asyncio
async def test_webhook_matching_rules() -> None:
    store = InMemoryPaymentStore()

    async with store.locked() as session:
        session.add(make_payment("1"))
        session.add(
            make_payment(
                "2",
                transaction_reference_number="PROVIDER-2",
            )
        )
        session.add(
            make_payment(
                "3",
                transaction_reference_number="PENDING-TXN-PLACEHOLDER",
            )
        )

        # Source reference alone is sufficient.
        assert (
            session.find_for_webhook(
                source_reference="ORDER-1",
                provider_reference=None,
            )
            is not None
        )
        # Both references must agree once a provider reference exists.
        assert (
            session.find_for_webhook(
                source_reference="ORDER-2",
                provider_reference="PROVIDER-2",
            )
            is not None
        )
        assert (
            session.find_for_webhook(
                source_reference="ORDER-2",
                provider_reference="PROVIDER-OTHER",
            )
            is None
        )
        # A OneKhusa placeholder is reconciled by an early callback.
        assert (
            session.find_for_webhook(
                source_reference="ORDER-3",
                provider_reference="PROVIDER-3",
            )
            is not None
        )
        # Provider reference alone can identify a payment.
        assert (
            session.find_for_webhook(
                source_reference=None,
                provider_reference="PROVIDER-2",
            )
            is not None
        )
        # Unknown references never match.
        assert (
            session.find_for_webhook(
                source_reference=None,
                provider_reference="PROVIDER-MISSING",
            )
            is None
        )
