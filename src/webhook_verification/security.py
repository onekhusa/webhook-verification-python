import hashlib
import hmac

from pydantic import SecretStr


def verify_webhook_signature(raw_body: bytes, signature: str | None, secret: SecretStr) -> bool:
    if not signature:
        return False
    provided = signature.strip().lower()
    if len(provided) != 128 or any(character not in "0123456789abcdef" for character in provided):
        return False
    expected = hmac.new(
        secret.get_secret_value().encode("utf-8"),
        raw_body,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(expected, provided)


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
