from __future__ import annotations

import json
from decimal import Decimal

import pytest
from pydantic import SecretStr

from tests.support import FIXTURE_SECRET, make_payment, sign
from webhook_verification.features.receive_webhook.service import (
    InvalidSignature,
    InvalidWebhookTransition,
    ReceiveWebhook,
    WebhookOutcome,
)
from webhook_verification.onekhusa.webhook.events import PushWebhookEvent
from webhook_verification.onekhusa.webhook.payload import PushWebhookPayload
from webhook_verification.shared.payments.store import InMemoryPaymentStore

SUCCESS = PushWebhookEvent.SUCCESS
FAILED = PushWebhookEvent.FAILED

STATUS_CODES = {SUCCESS: "S", FAILED: "F"}


def success_payload(
    *,
    source_reference: str = "ORDER-1",
    provider_reference: str = "PROVIDER-1",
    event: PushWebhookEvent = SUCCESS,
) -> PushWebhookPayload:
    return PushWebhookPayload(
        connector_id=1,
        source_reference_number=source_reference,
        transaction_reference_number=provider_reference,
        transaction_amount=Decimal("10.00"),
        transaction_status_code=STATUS_CODES[event],
    )


def payload_bytes(payload: PushWebhookPayload) -> bytes:
    return json.dumps(
        payload.model_dump(mode="json", by_alias=True, exclude_none=True),
        separators=(",", ":"),
    ).encode()


async def process(
    store: InMemoryPaymentStore,
    payload: PushWebhookPayload,
    *,
    event: PushWebhookEvent = SUCCESS,
    signature: str | None = None,
) -> WebhookOutcome:
    body = payload_bytes(payload)
    return await ReceiveWebhook(store).process(
        event=event,
        payload=payload,
        raw_body=body,
        signature=signature if signature is not None else sign(body),
        secret=SecretStr(FIXTURE_SECRET),
    )


@pytest.mark.asyncio
async def test_reconciles_a_provider_reference_for_a_onekhusa_placeholder() -> None:
    store = InMemoryPaymentStore()
    async with store.locked() as session:
        session.add(
            make_payment(
                "1",
                transaction_reference_number="PENDING-TXN-PLACEHOLDER",
            )
        )

    outcome = await process(store, success_payload(provider_reference="PROVIDER-1"))

    assert outcome.matched is True
    assert outcome.payment is not None
    assert outcome.payment.transaction_reference_number == "PROVIDER-1"
    assert outcome.payment.status == "succeeded"


@pytest.mark.asyncio
async def test_conflicting_provider_references_do_not_match() -> None:
    store = InMemoryPaymentStore()
    async with store.locked() as session:
        session.add(
            make_payment(
                "1",
                transaction_reference_number="PROVIDER-1",
            )
        )

    outcome = await process(
        store,
        success_payload(provider_reference="PROVIDER-OTHER"),
    )

    assert outcome.matched is False
    async with store.locked() as session:
        assert session.get("pay-1").status == "pending"


@pytest.mark.asyncio
async def test_unmatched_receipts_are_not_cached_for_retries() -> None:
    store = InMemoryPaymentStore()
    payload = success_payload()

    first = await process(store, payload)
    async with store.locked() as session:
        session.add(make_payment("1"))
    second = await process(store, payload)

    assert first.matched is False
    assert second.matched is True
    assert second.duplicate is False


@pytest.mark.asyncio
async def test_duplicate_receipts_are_reported() -> None:
    store = InMemoryPaymentStore()
    async with store.locked() as session:
        session.add(make_payment("1"))
    payload = success_payload()

    first = await process(store, payload)
    second = await process(store, payload)

    assert first.duplicate is False
    assert second.duplicate is True
    assert second.matched is True
    assert second.payment is not None
    assert len(second.payment.events) == 1


@pytest.mark.asyncio
async def test_invalid_signature_does_not_change_state() -> None:
    store = InMemoryPaymentStore()
    async with store.locked() as session:
        session.add(make_payment("1"))

    with pytest.raises(InvalidSignature):
        await process(store, success_payload(), signature="0" * 128)

    async with store.locked() as session:
        assert session.get("pay-1").status == "pending"


@pytest.mark.asyncio
async def test_terminal_state_transition_is_rejected() -> None:
    store = InMemoryPaymentStore()
    async with store.locked() as session:
        session.add(make_payment("1"))

    await process(store, success_payload(event=FAILED), event=FAILED)

    with pytest.raises(InvalidWebhookTransition):
        await process(store, success_payload())
