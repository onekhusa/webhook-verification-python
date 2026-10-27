"""Provider-facing errors.

These errors describe what OneKhusa did, not what an HTTP API should return.
The web layer translates them into API errors. Messages are safe to log and
return to callers: provider response bodies are never echoed.
"""

from __future__ import annotations

import httpx


class OneKhusaError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class OneKhusaNotConfigured(OneKhusaError):
    """The adapter is disabled or credentials are incomplete."""


class OneKhusaUnavailable(OneKhusaError):
    """The outcome is unknown: timeout, connection failure or provider 5xx."""


class OneKhusaRejected(OneKhusaError):
    """OneKhusa definitively rejected the request."""


class OneKhusaInvalidResponse(OneKhusaError):
    """OneKhusa returned a response this adapter cannot understand."""


def response_error(response: httpx.Response) -> OneKhusaError:
    """Build a safe provider error without echoing the response body."""

    detail = f"OneKhusa returned HTTP {response.status_code}"

    try:
        body = response.json()
    except ValueError:
        body = None

    if isinstance(body, dict):
        error_code = body.get("errorCode")
        if isinstance(error_code, str):
            detail = f"{detail} ({error_code[:24]})"

    if response.status_code >= 500:
        return OneKhusaUnavailable(detail, status_code=response.status_code)
    return OneKhusaRejected(detail, status_code=response.status_code)
