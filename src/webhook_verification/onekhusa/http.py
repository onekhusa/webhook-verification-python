from __future__ import annotations

import httpx

from webhook_verification.onekhusa.config import OneKhusaSettings


def create_http_client(settings: OneKhusaSettings) -> httpx.AsyncClient:
    """Create the HTTP client used for every OneKhusa call."""

    return httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=settings.connect_timeout_seconds,
            read=settings.read_timeout_seconds,
            write=settings.read_timeout_seconds,
            pool=settings.connect_timeout_seconds,
        ),
        follow_redirects=False,
    )
