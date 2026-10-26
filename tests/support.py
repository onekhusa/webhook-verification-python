from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import httpx
from pydantic import SecretStr

from webhook_verification.features.configuration.settings import Settings
from webhook_verification.main import create_app
from webhook_verification.onekhusa.webhook.events import PushWebhookEvent
from webhook_verification.onekhusa.webhook.signature import sign_webhook_payload
from webhook_verification.shared.payments.models import Payment, build_payment

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"

WEBHOOK_BODY_FILES: dict[PushWebhookEvent, str] = {
    PushWebhookEvent.SUCCESS: "pushpayment.success.json",
    PushWebhookEvent.FAILED: "pushpayment.failed.json",
    PushWebhookEvent.REVERSED: "pushpayment.reversed.json",
}


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


def fixture_json(name: str) -> Any:
    return json.loads(fixture_bytes(name))


SIGNATURE_DATA: dict[str, Any] = cast(
    dict[str, Any],
    fixture_json("webhook-signature-vectors.json"),
)
FIXTURE_SECRET: str = cast(str, SIGNATURE_DATA["secret"])
SIGNATURE_VECTORS: list[dict[str, Any]] = cast(
    list[dict[str, Any]],
    SIGNATURE_DATA["vectors"],
)

WEBHOOK_SIGNATURES: dict[PushWebhookEvent, str] = {
    event: cast(
        str,
        next(
            vector["signature"]
            for vector in SIGNATURE_VECTORS
            if vector["valid"] and vector["bodyFile"] == body_file
        ),
    )
    for event, body_file in WEBHOOK_BODY_FILES.items()
}


def payment_payload() -> dict[str, Any]:
    return cast(dict[str, Any], fixture_json("initiate-push-payment.json"))


def webhook_bytes(event: PushWebhookEvent) -> bytes:
    return fixture_bytes(WEBHOOK_BODY_FILES[event])


def webhook_payload_for(
    payment: dict[str, Any],
    event: PushWebhookEvent,
) -> bytes:
    """Use the shared payload shape with the references of a recorded payment."""

    payload = cast(dict[str, Any], fixture_json(WEBHOOK_BODY_FILES[event]))
    payload["connectorId"] = payment["connectorId"]
    payload["sourceReferenceNumber"] = payment["sourceReferenceNumber"]
    payload["transactionReferenceNumber"] = payment["transactionReferenceNumber"]
    payload["transactionAmount"] = payment["transactionAmount"]
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()


def sign(body: bytes, secret: str = FIXTURE_SECRET) -> str:
    return sign_webhook_payload(body, SecretStr(secret))


def webhook_headers(
    event: PushWebhookEvent,
    signature: str | None,
) -> dict[str, str]:
    headers = {"X-OneKhusa-Webhook-Event": event.value}
    if signature is not None:
        headers["X-OneKhusa-Webhook-Signature"] = signature
    return headers


async def create_onekhusa_payment(
    client: httpx.AsyncClient,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = await client.post(
        "/api/onekhusa/push-payments",
        json=payload if payload is not None else payment_payload(),
    )
    assert response.status_code == 202
    return cast(dict[str, Any], response.json())


async def post_webhook(
    client: httpx.AsyncClient,
    event: PushWebhookEvent,
    *,
    body: bytes | None = None,
    signature: str | None = None,
    secret: str = FIXTURE_SECRET,
) -> httpx.Response:
    raw_body = body if body is not None else webhook_bytes(event)
    provided_signature = signature if signature is not None else sign(raw_body, secret)
    return await client.post(
        "/webhook/pushpayment",
        content=raw_body,
        headers=webhook_headers(event, provided_signature),
    )


def webhook_secrets() -> dict[str, SecretStr]:
    return {event.value: SecretStr(FIXTURE_SECRET) for event in PushWebhookEvent}


def base_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "app_env": "test",
        "onekhusa_webhook_secrets": webhook_secrets(),
    }
    values.update(overrides)
    return Settings(**values)


def onekhusa_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "app_env": "test",
        "onekhusa_enabled": True,
        "onekhusa_base_url": "https://api.onekhusa.com/sandbox/v1",
        "onekhusa_api_key": SecretStr("sandbox-key"),
        "onekhusa_api_secret": SecretStr("s" * 45),
        "onekhusa_organisation_id": "sandbox-organisation",
        "onekhusa_merchant_account_number": 12345678,
        "onekhusa_webhook_secrets": webhook_secrets(),
    }
    values.update(overrides)
    return Settings(**values)


def make_payment(
    suffix: str = "1",
    *,
    source_reference_number: str | None = None,
    transaction_reference_number: str | None = None,
    created_at: datetime | None = None,
    connector_id: int = 1,
) -> Payment:
    now = created_at or datetime.now(UTC)
    return build_payment(
        payment_id=f"pay-{suffix}",
        source_reference_number=source_reference_number or f"ORDER-{suffix}",
        transaction_reference_number=(transaction_reference_number or f"PROVIDER-{suffix}"),
        connector_id=connector_id,
        payer_account_number="2659912345678",
        transaction_amount=Decimal("10.00"),
        transaction_description="Fixture payment",
        captured_by="fixture-merchant",
        now=now,
    )


def token_response(expires_on: str) -> dict[str, object]:
    return {
        "accessToken": "sandbox-token",
        "expiresOn": expires_on,
        "expiryInMinutes": 60,
    }


def expected_token_request() -> bytes:
    return (
        b'{"apiKey":"sandbox-key","apiSecret":"sssssssssssssssssssssssssssssssssssssssssssss",'
        b'"organisationId":"sandbox-organisation","merchantAccountNumber":12345678}'
    )


@asynccontextmanager
async def asgi_client(
    settings: Settings,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, http_client=http_client)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        async with app.router.lifespan_context(app):
            yield client


def provider_transport(
    requests: list[httpx.Request],
    *,
    push_status: int = 202,
    push_json: dict[str, object] | None = None,
) -> httpx.MockTransport:
    """Mock OneKhusa token and push endpoints, recording every request."""

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
