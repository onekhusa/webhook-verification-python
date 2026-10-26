from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError

from tests.support import onekhusa_settings, token_response
from webhook_verification.onekhusa.client.token import (
    AccessTokenProvider,
    AccessTokenResponse,
)
from webhook_verification.onekhusa.errors import OneKhusaError


def token_handler(
    requests: list[httpx.Request],
    *,
    expires_in: timedelta = timedelta(hours=1),
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        expires_on = (datetime.now(UTC) + expires_in).isoformat()
        return httpx.Response(200, json=token_response(expires_on))

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_caches_the_access_token_until_near_expiry() -> None:
    requests: list[httpx.Request] = []
    http = httpx.AsyncClient(transport=token_handler(requests))
    provider = AccessTokenProvider(onekhusa_settings(), http)

    first = await provider.get()
    second = await provider.get()

    assert first.get_secret_value() == "sandbox-token"
    assert second.get_secret_value() == "sandbox-token"
    assert len(requests) == 1
    assert requests[0].url.path.endswith("/account/getAccessToken")
    assert requests[0].headers["accept-language"] == "en"
    await http.aclose()


@pytest.mark.asyncio
async def test_refreshes_an_expired_token() -> None:
    requests: list[httpx.Request] = []
    http = httpx.AsyncClient(transport=token_handler(requests, expires_in=timedelta(seconds=10)))
    provider = AccessTokenProvider(onekhusa_settings(), http)

    await provider.get()
    await provider.get()

    assert len(requests) == 2
    await http.aclose()


@pytest.mark.asyncio
async def test_rejects_an_invalid_token_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"accessToken": "only-a-token"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = AccessTokenProvider(onekhusa_settings(), http)

    with pytest.raises(OneKhusaError, match="invalid access-token response"):
        await provider.get()
    await http.aclose()


def test_token_expiry_requires_a_timezone() -> None:
    with pytest.raises(ValidationError):
        AccessTokenResponse.model_validate(
            {
                "accessToken": "token",
                "expiresOn": "2099-01-01T00:00:00",
                "expiryInMinutes": 60,
            }
        )
