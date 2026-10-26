from __future__ import annotations

import httpx

from webhook_verification.features.configuration.settings import Settings


def create_http_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=settings.onekhusa_connect_timeout_seconds,
            read=settings.onekhusa_read_timeout_seconds,
            write=settings.onekhusa_read_timeout_seconds,
            pool=settings.onekhusa_connect_timeout_seconds,
        ),
        follow_redirects=False,
    )
