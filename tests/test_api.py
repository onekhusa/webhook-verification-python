import hashlib
import hmac
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from pydantic import SecretStr

from webhook_verification.domain import PushWebhookEvent
from webhook_verification.main import create_app
from webhook_verification.schemas import PushPaymentRequest, PushWebhookPayload
from webhook_verification.settings import Settings

SUCCESS = PushWebhookEvent.SUCCESS
FAILED = PushWebhookEvent.FAILED
REVERSED = PushWebhookEvent.REVERSED
SECRETS = {
    SUCCESS.value: SecretStr("success-event-secret"),
    FAILED.value: SecretStr("failed-event-secret"),
    REVERSED.value: SecretStr("reversed-event-secret"),
}
PAYMENT = {
    "connectorId": 892353,
    "payerAccountNumber": "2659912345678",
    "transactionAmount": "12500.00",
    "transactionDescription": "Invoice INV-1042",
    "capturedBy": "demo-merchant",
    "sourceReferenceNumber": "ORDER-1042",
}


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        Settings(
            app_env="test",
            simulation_enabled=True,
            one_khusa_webhook_secrets=SECRETS,
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as test_client:
        async with app.router.lifespan_context(app):
            yield test_client


async def create_simulation(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.post("/api/simulations", json=PAYMENT)
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


@pytest.mark.asyncio
async def test_simulator_ui_is_served_without_database(client: httpx.AsyncClient) -> None:
    response = await client.get("/")

    assert response.status_code == 200
    assert "Push payment" in response.text
    assert "local simulation makes no network calls" in response.text.lower()
    assert "Payment succeeded" in response.text
    assert "database" in response.text.lower()


@pytest.mark.asyncio
async def test_create_simulation_is_memory_only_and_masks_payer(client: httpx.AsyncClient) -> None:
    created = await client.post("/api/simulations", json=PAYMENT)

    assert created.status_code == 201
    body = created.json()
    assert body["sourceReferenceNumber"] == "ORDER-1042"
    assert body["payerAccountLastFour"] == "5678"
    assert "payerAccountNumber" not in body
    assert body["status"] == "pending"
    assert "database_url" not in Settings.model_fields


@pytest.mark.asyncio
async def test_simulate_success_and_reversal_lifecycle(client: httpx.AsyncClient) -> None:
    transaction = await create_simulation(client)
    simulation_id = transaction["simulationId"]

    success = await client.post(
        f"/api/simulations/{simulation_id}/events",
        json={"event": SUCCESS.value},
    )
    assert success.status_code == 200
    assert success.json()["status"] == "succeeded"
    assert success.json()["events"][0]["signatureVerified"] is True

    reversal = await client.post(
        f"/api/simulations/{simulation_id}/events",
        json={"event": REVERSED.value},
    )
    assert reversal.status_code == 200
    assert reversal.json()["status"] == "reversed"
    assert len(reversal.json()["events"]) == 2


@pytest.mark.asyncio
async def test_failed_event_marks_transaction_failed(client: httpx.AsyncClient) -> None:
    transaction = await create_simulation(client)
    response = await client.post(
        f"/api/simulations/{transaction['simulationId']}/events",
        json={"event": FAILED.value},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"


@pytest.mark.asyncio
async def test_invalid_transition_is_rejected(client: httpx.AsyncClient) -> None:
    transaction = await create_simulation(client)
    simulation_id = transaction["simulationId"]
    await client.post(
        f"/api/simulations/{simulation_id}/events",
        json={"event": FAILED.value},
    )

    invalid = await client.post(
        f"/api/simulations/{simulation_id}/events",
        json={"event": SUCCESS.value},
    )

    assert invalid.status_code == 409
    current = await client.get("/api/simulations")
    assert current.json()[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_webhook_signature_is_verified_before_state_update(client: httpx.AsyncClient) -> None:
    transaction = await create_simulation(client)
    payload = PushWebhookPayload(
        connector_id=transaction["connectorId"],
        source_reference_number=transaction["sourceReferenceNumber"],
        transaction_reference_number=transaction["transactionReferenceNumber"],
        transaction_status_code="S",
    )
    body = payload.model_dump_json(by_alias=True).encode()
    signature = hmac.new(
        SECRETS[SUCCESS.value].get_secret_value().encode(),
        body,
        hashlib.sha512,
    ).hexdigest()

    rejected = await client.post(
        "/webhook/pushpayment",
        content=body,
        headers={
            "X-OneKhusa-Webhook-Event": SUCCESS.value,
            "X-OneKhusa-Webhook-Signature": "0" * 128,
        },
    )
    assert rejected.status_code == 401

    accepted = await client.post(
        "/webhook/pushpayment",
        content=body,
        headers={
            "X-OneKhusa-Webhook-Event": SUCCESS.value,
            "X-OneKhusa-Webhook-Signature": signature,
        },
    )
    assert accepted.status_code == 200
    assert accepted.text == "acknowledged"

    current = await client.get("/api/simulations")
    assert current.json()[0]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_clear_session_removes_all_in_memory_simulations(client: httpx.AsyncClient) -> None:
    await create_simulation(client)
    cleared = await client.delete("/api/simulations")

    assert cleared.status_code == 204
    assert (await client.get("/api/simulations")).json() == []


@pytest.mark.asyncio
async def test_simulation_ui_is_disabled_in_production() -> None:
    app = create_app(Settings(app_env="production", simulation_enabled=True))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_simulations_do_not_survive_application_restart(client: httpx.AsyncClient) -> None:
    await create_simulation(client)
    restarted_app = create_app(
        Settings(
            app_env="test",
            simulation_enabled=True,
            one_khusa_webhook_secrets=SECRETS,
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=restarted_app),
        base_url="http://test",
    ) as restarted_client:
        async with restarted_app.router.lifespan_context(restarted_app):
            assert (await restarted_client.get("/api/simulations")).json() == []


def test_simulation_payload_schema_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        PushPaymentRequest.model_validate({**PAYMENT, "unknown": "value"})


def onekhusa_settings(**overrides: Any) -> Settings:
    return Settings(
        app_env="test",
        simulation_enabled=True,
        onekhusa_enabled=True,
        onekhusa_api_key=SecretStr("sandbox-key"),
        onekhusa_api_secret=SecretStr("s" * 45),
        onekhusa_organisation_id="sandbox-organisation",
        onekhusa_merchant_account_number=12345678,
        one_khusa_webhook_secrets=SECRETS,
        **overrides,
    )


@pytest.mark.asyncio
async def test_onekhusa_sandbox_request_uses_credentials_and_idempotency() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/account/getAccessToken"):
            return httpx.Response(
                200,
                json={
                    "accessToken": "sandbox-token",
                    "expiresOn": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                    "expiryInMinutes": 60,
                },
            )
        return httpx.Response(
            202,
            json={"transactionReferenceNumber": "PROVIDER-TXN-1042"},
        )

    provider_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = create_app(onekhusa_settings(), http_client=provider_http)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        async with app.router.lifespan_context(app):
            first = await client.post("/api/onekhusa/push-payments", json=PAYMENT)
            second = await client.post("/api/onekhusa/push-payments", json=PAYMENT)
            webhook_payload = PushWebhookPayload(
                connector_id=PAYMENT["connectorId"],
                source_reference_number=PAYMENT["sourceReferenceNumber"],
                transaction_reference_number="PROVIDER-TXN-1042",
                transaction_status_code="S",
            )
            webhook_body = webhook_payload.model_dump_json(by_alias=True).encode()
            webhook_signature = hmac.new(
                SECRETS[SUCCESS.value].get_secret_value().encode(),
                webhook_body,
                hashlib.sha512,
            ).hexdigest()
            callback = await client.post(
                "/webhook/pushpayment",
                content=webhook_body,
                headers={
                    "X-OneKhusa-Webhook-Event": SUCCESS.value,
                    "X-OneKhusa-Webhook-Signature": webhook_signature,
                },
            )
            transaction_after_callback = await client.get("/api/simulations")

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["simulationId"] == second.json()["simulationId"]
    assert first.json()["status"] == "pending"
    assert first.json()["transactionReferenceNumber"] == "PROVIDER-TXN-1042"
    assert first.json()["providerHttpStatus"] == 202
    assert callback.status_code == 200
    assert transaction_after_callback.json()[0]["status"] == "succeeded"
    assert len(requests) == 3

    token_call = requests[0]
    assert token_call.url.path.endswith("/account/getAccessToken")
    assert token_call.headers["accept-language"] == "en"
    assert token_call.read() == (
        b'{"apiKey":"sandbox-key","apiSecret":"sssssssssssssssssssssssssssssssssssssssssssss",'
        b'"organisationId":"sandbox-organisation","merchantAccountNumber":12345678}'
    )

    first_push, second_push = requests[1:]
    assert first_push.url.path.endswith("/collections/push/direct/initiate")
    assert first_push.headers["authorization"] == "Bearer sandbox-token"
    assert first_push.headers["accept-language"] == "en"
    assert first_push.headers["x-idempotency-key"] == second_push.headers["x-idempotency-key"]
    assert first_push.headers["x-idempotency-key"].startswith("push-")
    assert b'"transactionAmount":12500.00' in first_push.read()
    assert b'"sourceReferenceNumber":"ORDER-1042"' in first_push.read()
    assert first_push.read() == second_push.read()
    await provider_http.aclose()


@pytest.mark.asyncio
async def test_onekhusa_requires_source_reference_before_provider_call() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    provider_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = create_app(onekhusa_settings(), http_client=provider_http)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        async with app.router.lifespan_context(app):
            response = await client.post(
                "/api/onekhusa/push-payments",
                json={
                    key: value for key, value in PAYMENT.items() if key != "sourceReferenceNumber"
                },
            )

    assert response.status_code == 422
    assert requests == []
    await provider_http.aclose()


@pytest.mark.asyncio
async def test_onekhusa_provider_error_does_not_expose_provider_detail_or_secret() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/account/getAccessToken"):
            return httpx.Response(
                200,
                json={
                    "accessToken": "sandbox-token",
                    "expiresOn": "2099-01-01T00:00:00Z",
                    "expiryInMinutes": 60,
                },
            )
        return httpx.Response(401, json={"detail": "sandbox-key is unauthorized"})

    provider_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = create_app(onekhusa_settings(), http_client=provider_http)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        async with app.router.lifespan_context(app):
            response = await client.post("/api/onekhusa/push-payments", json=PAYMENT)

    assert response.status_code == 502
    assert response.json()["detail"]["message"] == "OneKhusa returned HTTP 401"
    assert "sandbox-key" not in response.text
    assert response.json()["detail"]["transaction"]["status"] == "pending"
    await provider_http.aclose()


def test_non_sandbox_url_is_not_exposed_as_sandbox_configuration() -> None:
    settings = onekhusa_settings(onekhusa_base_url="https://attacker.example/sandbox/v1")

    assert not settings.onekhusa_is_sandbox
