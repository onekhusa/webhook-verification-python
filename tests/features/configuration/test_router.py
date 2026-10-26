from __future__ import annotations

import httpx
import pytest

from tests.support import asgi_client, base_settings, onekhusa_settings


@pytest.mark.asyncio
async def test_health_endpoint(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.asyncio
async def test_config_reports_disabled_onekhusa_without_a_base_url() -> None:
    async with asgi_client(base_settings()) as client:
        response = await client.get("/api/config")

    assert response.status_code == 200
    assert response.json() == {
        "onekhusaEnabled": False,
        "onekhusaSandbox": True,
        "onekhusaBaseUrl": None,
    }


@pytest.mark.asyncio
async def test_config_never_exposes_credentials_when_onekhusa_is_enabled() -> None:
    settings = onekhusa_settings()
    async with asgi_client(settings) as client:
        response = await client.get("/api/config")

    body = response.json()
    assert body["onekhusaEnabled"] is True
    assert body["onekhusaSandbox"] is True
    assert body["onekhusaBaseUrl"] == "https://api.onekhusa.com/sandbox/v1"
    assert "sandbox-key" not in response.text
    assert settings.onekhusa_api_secret.get_secret_value() not in response.text


@pytest.mark.asyncio
async def test_config_hides_a_non_sandbox_base_url() -> None:
    async with asgi_client(
        onekhusa_settings(onekhusa_base_url="https://api.onekhusa.com/v1")
    ) as client:
        response = await client.get("/api/config")

    body = response.json()
    assert body["onekhusaSandbox"] is False
    assert body["onekhusaBaseUrl"] is None
