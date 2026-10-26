from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from tests.support import (
    asgi_client,
    onekhusa_settings,
    payment_payload,
    provider_transport,
)
from webhook_verification.features.configuration.settings import Settings


@pytest.fixture
def payment_request() -> dict[str, Any]:
    return payment_payload()


@pytest.fixture
def settings() -> Settings:
    return onekhusa_settings()


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=provider_transport([])) as provider_http:
        async with asgi_client(settings, http_client=provider_http) as test_client:
            yield test_client
