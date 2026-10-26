import hashlib
import hmac

from pydantic import SecretStr

from webhook_verification.security import verify_webhook_signature


def test_verifies_signature_over_exact_raw_body_bytes() -> None:
    body = b'{ "transactionAmount": 10.00 }\n'
    secret = "event-secret"
    signature = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()

    assert verify_webhook_signature(body, signature, SecretStr(secret))
    assert not verify_webhook_signature(body + b" ", signature, SecretStr(secret))


def test_rejects_missing_malformed_and_wrong_signatures() -> None:
    body = b'{"ok":true}'
    secret = SecretStr("event-secret")

    assert not verify_webhook_signature(body, None, secret)
    assert not verify_webhook_signature(body, "", secret)
    assert not verify_webhook_signature(body, "0" * 128, secret)
