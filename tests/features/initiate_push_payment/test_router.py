from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from tests.support import (
    asgi_client,
    onekhusa_settings,
    payment_payload,
    provider_transport,
)


def idempotency_key(merchant_account_number: int, source_reference: str) -> str:
    digest = hashlib.sha256(f"{merchant_account_number}:{source_reference}".encode()).hexdigest()
    return f"push-{digest}"


@pytest.mark.asyncio
async def test_accepted_payment_is_recorded_and_sent_to_the_sandbox() -> None:
    requests: list[httpx.Request] = []
    http = httpx.AsyncClient(transport=provider_transport(requests))
    settings = onekhusa_settings()

    async with asgi_client(settings, http_client=http) as client:
        response = await client.post(
            "/api/onekhusa/push-payments",
            json=payment_payload(),
        )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["transactionReferenceNumber"] == "PROVIDER-TXN-1042"
    assert body["providerHttpStatus"] == 202
    assert body["payerAccountLastFour"] == "5678"
    assert "payerAccountNumber" not in body

    token_call, push_call = requests
    assert token_call.url.path == "/sandbox/v1/account/getAccessToken"
    assert push_call.headers["x-idempotency-key"] == idempotency_key(
        12345678,
        "ORDER-1042",
    )
    raw_body = push_call.read()
    assert b'"transactionAmount":12500.00' in raw_body
    assert b'"sourceReferenceNumber":"ORDER-1042"' in raw_body
    await http.aclose()


@pytest.mark.asyncio
async def test_retry_reuses_the_record_and_the_provider_idempotency_key() -> None:
    requests: list[httpx.Request] = []
    http = httpx.AsyncClient(transport=provider_transport(requests))

    async with asgi_client(onekhusa_settings(), http_client=http) as client:
        first = await client.post(
            "/api/onekhusa/push-payments",
            json=payment_payload(),
        )
        second = await client.post(
            "/api/onekhusa/push-payments",
            json=payment_payload(),
        )
        listed = await client.get("/api/payments")

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["paymentId"] == first.json()["paymentId"]
    assert len(listed.json()) == 1

    push_calls = [
        request
        for request in requests
        if request.url.path.endswith("/collections/push/direct/initiate")
    ]
    assert len(push_calls) == 2
    assert (
        push_calls[0].headers["x-idempotency-key"] == (push_calls[1].headers["x-idempotency-key"])
    )
    await http.aclose()


@pytest.mark.asyncio
async def test_missing_source_reference_is_rejected() -> None:
    requests: list[httpx.Request] = []
    http = httpx.AsyncClient(transport=provider_transport(requests))
    payload = payment_payload()
    payload.pop("sourceReferenceNumber")

    async with asgi_client(onekhusa_settings(), http_client=http) as client:
        response = await client.post("/api/onekhusa/push-payments", json=payload)

    assert response.status_code == 422
    assert "sourceReferenceNumber is required" in response.json()["detail"]
    assert requests == []
    await http.aclose()


@pytest.mark.asyncio
async def test_provider_failure_is_redacted_and_recorded() -> None:
    requests: list[httpx.Request] = []
    http = httpx.AsyncClient(
        transport=provider_transport(
            requests,
            push_status=401,
            push_json={
                "errorCode": "invalid_credentials",
                "message": "provider-secret-detail",
            },
        )
    )

    async with asgi_client(onekhusa_settings(), http_client=http) as client:
        response = await client.post(
            "/api/onekhusa/push-payments",
            json=payment_payload(),
        )
        listed = await client.get("/api/payments")

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert "HTTP 401" in detail["message"]
    assert "invalid_credentials" in detail["message"]
    assert "provider-secret-detail" not in json.dumps(response.json())
    assert detail["status"] == "pending"
    assert listed.json()[0]["providerHttpStatus"] == 401
    await http.aclose()


@pytest.mark.asyncio
async def test_conflicting_source_reference_returns_conflict() -> None:
    requests: list[httpx.Request] = []
    http = httpx.AsyncClient(transport=provider_transport(requests))

    async with asgi_client(onekhusa_settings(), http_client=http) as client:
        first = await client.post(
            "/api/onekhusa/push-payments",
            json=payment_payload(),
        )
        assert first.status_code == 202
        response = await client.post(
            "/api/onekhusa/push-payments",
            json={**payment_payload(), "transactionAmount": "1.00"},
        )

    assert response.status_code == 409
    assert "already in use" in response.json()["detail"]
    await http.aclose()


@pytest.mark.asyncio
async def test_disabled_onekhusa_returns_service_unavailable() -> None:
    http = httpx.AsyncClient(transport=provider_transport([]))

    async with asgi_client(
        onekhusa_settings(onekhusa_enabled=False),
        http_client=http,
    ) as client:
        response = await client.post(
            "/api/onekhusa/push-payments",
            json=payment_payload(),
        )

    assert response.status_code == 503
    await http.aclose()


@pytest.mark.asyncio
async def test_non_sandbox_base_url_is_refused() -> None:
    requests: list[httpx.Request] = []
    http = httpx.AsyncClient(transport=provider_transport(requests))

    async with asgi_client(
        onekhusa_settings(onekhusa_base_url="https://api.onekhusa.com/v1"),
        http_client=http,
    ) as client:
        response = await client.post(
            "/api/onekhusa/push-payments",
            json=payment_payload(),
        )

    assert response.status_code == 502
    assert "sandbox" in response.json()["detail"]
    assert requests == []
    await http.aclose()
