from __future__ import annotations

import httpx
import pytest

from tests.support import (
    asgi_client,
    base_settings,
    create_onekhusa_payment,
    post_webhook,
    sign,
    webhook_bytes,
    webhook_payload_for,
)
from webhook_verification.onekhusa.webhook.events import PushWebhookEvent

SUCCESS = PushWebhookEvent.SUCCESS
FAILED = PushWebhookEvent.FAILED


@pytest.mark.asyncio
async def test_signature_is_verified_before_a_state_update(
    client: httpx.AsyncClient,
) -> None:
    payment = await create_onekhusa_payment(client)
    body = webhook_payload_for(payment, SUCCESS)

    rejected = await post_webhook(
        client,
        SUCCESS,
        body=body,
        signature="0" * 128,
    )
    assert rejected.status_code == 401
    current = await client.get("/api/payments")
    assert current.json()[0]["status"] == "pending"

    accepted = await post_webhook(client, SUCCESS, body=body)
    assert accepted.status_code == 200
    assert accepted.text == "acknowledged"
    current = await client.get("/api/payments")
    assert current.json()[0]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_duplicate_callbacks_are_ignored(
    client: httpx.AsyncClient,
) -> None:
    payment = await create_onekhusa_payment(client)
    body = webhook_payload_for(payment, SUCCESS)

    first = await post_webhook(client, SUCCESS, body=body)
    second = await post_webhook(client, SUCCESS, body=body)

    assert first.status_code == 200
    assert second.status_code == 200
    current = await client.get("/api/payments")
    assert current.json()[0]["status"] == "succeeded"
    assert len(current.json()[0]["events"]) == 1


@pytest.mark.asyncio
async def test_unmatched_callbacks_are_acknowledged_without_state(
    client: httpx.AsyncClient,
) -> None:
    response = await post_webhook(client, SUCCESS)

    assert response.status_code == 200
    assert (await client.get("/api/payments")).json() == []


@pytest.mark.asyncio
async def test_invalid_transition_returns_conflict(
    client: httpx.AsyncClient,
) -> None:
    payment = await create_onekhusa_payment(client)
    failed = await post_webhook(
        client,
        FAILED,
        body=webhook_payload_for(payment, FAILED),
    )
    assert failed.status_code == 200

    conflict = await post_webhook(
        client,
        SUCCESS,
        body=webhook_payload_for(payment, SUCCESS),
    )

    assert conflict.status_code == 409
    current = await client.get("/api/payments")
    assert current.json()[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_missing_or_unknown_event_header_returns_bad_request(
    client: httpx.AsyncClient,
) -> None:
    missing = await client.post(
        "/webhook/pushpayment",
        content=b"{}",
        headers={"X-OneKhusa-Webhook-Signature": "0" * 128},
    )
    unknown = await client.post(
        "/webhook/pushpayment",
        content=b"{}",
        headers={
            "X-OneKhusa-Webhook-Event": "pushpayment.unknown",
            "X-OneKhusa-Webhook-Signature": "0" * 128,
        },
    )

    assert missing.status_code == 400
    assert missing.json()["detail"] == "Missing webhook event header"
    assert unknown.status_code == 400
    assert unknown.json()["detail"] == "Unsupported push-payment webhook event"


@pytest.mark.asyncio
async def test_unconfigured_secret_returns_service_unavailable() -> None:
    settings = base_settings(onekhusa_webhook_secrets={})
    async with asgi_client(settings) as client:
        response = await post_webhook(client, SUCCESS)

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_oversized_payload_is_rejected() -> None:
    settings = base_settings(max_webhook_body_bytes=10)
    body = webhook_bytes(SUCCESS)
    async with asgi_client(settings) as client:
        response = await client.post(
            "/webhook/pushpayment",
            content=body,
            headers={
                "X-OneKhusa-Webhook-Event": SUCCESS.value,
                "X-OneKhusa-Webhook-Signature": sign(body),
            },
        )

    assert response.status_code == 413


@pytest.mark.asyncio
async def test_payload_without_references_is_rejected(
    client: httpx.AsyncClient,
) -> None:
    response = await post_webhook(client, SUCCESS, body=b'{"connectorId":1}')

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_malformed_json_is_rejected(client: httpx.AsyncClient) -> None:
    response = await post_webhook(client, SUCCESS, body=b"{not-json")

    assert response.status_code == 400
