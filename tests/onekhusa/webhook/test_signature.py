from __future__ import annotations

import hashlib
import hmac
from typing import Any

import pytest
from pydantic import SecretStr

from tests.support import (
    FIXTURE_SECRET,
    SIGNATURE_VECTORS,
    fixture_bytes,
    webhook_bytes,
)
from webhook_verification.onekhusa.webhook.events import PushWebhookEvent
from webhook_verification.onekhusa.webhook.signature import (
    sign_webhook_payload,
    verify_webhook_signature,
)


@pytest.mark.parametrize(
    "vector",
    SIGNATURE_VECTORS,
    ids=[str(vector["name"]) for vector in SIGNATURE_VECTORS],
)
def test_shared_signature_vectors(vector: dict[str, Any]) -> None:
    body = fixture_bytes(str(vector["bodyFile"]))

    assert (
        verify_webhook_signature(
            body,
            str(vector["signature"]),
            SecretStr(FIXTURE_SECRET),
        )
        == vector["valid"]
    )


def test_signing_matches_the_shared_success_vector() -> None:
    body = webhook_bytes(PushWebhookEvent.SUCCESS)
    expected = hmac.new(
        FIXTURE_SECRET.encode(),
        body,
        hashlib.sha512,
    ).hexdigest()

    assert sign_webhook_payload(body, SecretStr(FIXTURE_SECRET)) == expected


@pytest.mark.parametrize("signature", [None, "", "0" * 128, "z" * 128, "0" * 127])
def test_rejects_missing_or_malformed_signatures(signature: str | None) -> None:
    assert not verify_webhook_signature(
        b"{}",
        signature,
        SecretStr(FIXTURE_SECRET),
    )


def test_rejects_a_body_changed_by_one_byte() -> None:
    body = webhook_bytes(PushWebhookEvent.SUCCESS)
    signature = sign_webhook_payload(body, SecretStr(FIXTURE_SECRET))

    assert not verify_webhook_signature(
        body + b" ",
        signature,
        SecretStr(FIXTURE_SECRET),
    )
