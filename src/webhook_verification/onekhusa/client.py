"""OneKhusa adapter façade.

This module is the copyable integration surface: token acquisition plus
Collections push initiation. It depends on nothing from the demo application.
"""

from __future__ import annotations

import httpx

from webhook_verification.onekhusa.config import OneKhusaSettings
from webhook_verification.onekhusa.contracts import PushPaymentRequest, PushPaymentResult
from webhook_verification.onekhusa.push import PushPaymentClient
from webhook_verification.onekhusa.token import AccessTokenProvider


class OneKhusaClient:
    """Token acquisition and Collections push initiation."""

    def __init__(self, settings: OneKhusaSettings, http: httpx.AsyncClient) -> None:
        self._tokens = AccessTokenProvider(settings, http)
        self._push = PushPaymentClient(settings, http, self._tokens)

    async def initiate_push_payment(
        self,
        request: PushPaymentRequest,
        *,
        idempotency_key: str,
    ) -> PushPaymentResult:
        return await self._push.initiate(request, idempotency_key=idempotency_key)
