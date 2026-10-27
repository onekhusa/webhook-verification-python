"""ASGI entrypoint.

Kept so existing commands such as
``uvicorn webhook_verification.main:app --app-dir src`` keep working. The
application itself lives in :mod:`webhook_verification.web.app`.
"""

from __future__ import annotations

from webhook_verification.web.app import app, create_app

__all__ = ["app", "create_app"]
