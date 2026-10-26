from __future__ import annotations

import hashlib
import hmac

from pydantic import SecretStr


def sign_webhook_payload(raw_body: bytes, secret: SecretStr) -> str:
    """Return the lowercase HMAC-SHA512 hex digest for the exact body bytes."""

    return hmac.new(
        secret.get_secret_value().encode("utf-8"),
        raw_body,
        hashlib.sha512,
    ).hexdigest()


def verify_webhook_signature(
    raw_body: bytes,
    signature: str | None,
    secret: SecretStr,
) -> bool:
    """Verify an OneKhusa webhook signature over the exact raw body bytes."""

    if not signature:
        return False
    provided = signature.strip().lower()
    if len(provided) != 128 or any(character not in "0123456789abcdef" for character in provided):
        return False
    return hmac.compare_digest(sign_webhook_payload(raw_body, secret), provided)
