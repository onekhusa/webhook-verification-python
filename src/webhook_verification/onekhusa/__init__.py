"""OneKhusa Collections protocol adapter."""

from webhook_verification.onekhusa.client import OneKhusaClient
from webhook_verification.onekhusa.errors import OneKhusaError

__all__ = ["OneKhusaClient", "OneKhusaError"]
