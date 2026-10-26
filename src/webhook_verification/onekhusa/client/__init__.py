"""OneKhusa client façade."""

from __future__ import annotations

import httpx

from webhook_verification.features.configuration.settings import Settings
from webhook_verification.onekhusa.client.push import (
    PushPaymentClient,
    PushPaymentRequest,
    PushPaymentResult,
)
from webhook_verification.onekhusa.client.token import AccessTokenProvider


class OneKhusaClient:
    """Token acquisition and Collections push initiation."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._tokens = AccessTokenProvider(settings, http)
        self._push = PushPaymentClient(settings, http, self._tokens)

    async def initiate_push_payment(
        self,
        request: PushPaymentRequest,
        *,
        source_reference_number: str,
        idempotency_key: str,
    ) -> PushPaymentResult:
        return await self._push.initiate(
            request,
            source_reference_number=source_reference_number,
            idempotency_key=idempotency_key,
        )


__all__ = [
    "OneKhusaClient",
    "PushPaymentRequest",
    "PushPaymentResult",
]
