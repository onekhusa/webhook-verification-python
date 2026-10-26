from __future__ import annotations

import httpx


class OneKhusaError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def response_error(response: httpx.Response) -> OneKhusaError:
    """Build a safe error without echoing provider response bodies."""

    detail = f"OneKhusa returned HTTP {response.status_code}"

    try:
        body = response.json()
    except ValueError:
        body = None

    if isinstance(body, dict):
        error_code = body.get("errorCode")
        if isinstance(error_code, str):
            detail = f"{detail} ({error_code[:24]})"

    return OneKhusaError(detail, status_code=response.status_code)
