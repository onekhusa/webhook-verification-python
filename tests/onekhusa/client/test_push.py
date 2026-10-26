from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError

from tests.support import (
    expected_token_request,
    onekhusa_settings,
    payment_payload,
    token_response,
)
from webhook_verification.onekhusa.client import OneKhusaClient
from webhook_verification.onekhusa.client.push import PushPaymentRequest
from webhook_verification.onekhusa.errors import OneKhusaError


def provider_handler(
    requests: list[httpx.Request],
    *,
    push_status: int = 202,
    push_json: dict[str, object] | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/account/getAccessToken"):
            expires_on = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
            return httpx.Response(200, json=token_response(expires_on))
        return httpx.Response(
            push_status,
            json=push_json
            if push_json is not None
            else {"transactionReferenceNumber": "PROVIDER-TXN-1042"},
        )

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_push_request_serializes_amount_headers_and_reference() -> None:
    requests: list[httpx.Request] = []
    http = httpx.AsyncClient(transport=provider_handler(requests))
    client = OneKhusaClient(onekhusa_settings(), http)
    request = PushPaymentRequest.model_validate(payment_payload())

    result = await client.initiate_push_payment(
        request,
        source_reference_number="ORDER-1042",
        idempotency_key="push-test",
    )

    assert result.http_status == 202
    assert result.transaction_reference_number == "PROVIDER-TXN-1042"
    assert len(requests) == 2

    token_call, push_call = requests
    assert token_call.read() == expected_token_request()
    assert push_call.url.path == "/sandbox/v1/collections/push/direct/initiate"
    assert push_call.headers["authorization"] == "Bearer sandbox-token"
    assert push_call.headers["accept-language"] == "en"
    assert push_call.headers["x-idempotency-key"] == "push-test"
    body = push_call.read()
    assert b'"transactionAmount":12500.00' in body
    assert b'"sourceReferenceNumber":"ORDER-1042"' in body
    assert b'"merchantAccountNumber":12345678' in body
    await http.aclose()


@pytest.mark.asyncio
async def test_disabled_client_does_not_call_the_provider() -> None:
    requests: list[httpx.Request] = []
    http = httpx.AsyncClient(transport=provider_handler(requests))
    client = OneKhusaClient(onekhusa_settings(onekhusa_enabled=False), http)

    with pytest.raises(OneKhusaError, match="disabled or its credentials"):
        await client.initiate_push_payment(
            PushPaymentRequest.model_validate(payment_payload()),
            source_reference_number="ORDER-1042",
            idempotency_key="push-test",
        )

    assert requests == []
    await http.aclose()


@pytest.mark.asyncio
async def test_timeout_is_reported_as_an_unknown_outcome() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/account/getAccessToken"):
            expires_on = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
            return httpx.Response(200, json=token_response(expires_on))
        raise httpx.ReadTimeout("timed out", request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OneKhusaClient(onekhusa_settings(), http)

    with pytest.raises(OneKhusaError, match="outcome is unknown"):
        await client.initiate_push_payment(
            PushPaymentRequest.model_validate(payment_payload()),
            source_reference_number="ORDER-1042",
            idempotency_key="push-test",
        )
    await http.aclose()


def test_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        PushPaymentRequest.model_validate({**payment_payload(), "unknown": "value"})
