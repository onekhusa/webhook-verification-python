from __future__ import annotations

import pytest

from tests.support import webhook_bytes
from webhook_verification.onekhusa.webhook.events import PushWebhookEvent
from webhook_verification.onekhusa.webhook.payload import PushWebhookPayload
from webhook_verification.shared.payments.models import TransactionStatus


def test_parses_the_shared_success_payload() -> None:
    payload = PushWebhookPayload.model_validate_json(webhook_bytes(PushWebhookEvent.SUCCESS))

    assert payload.connector_id == 892353
    assert payload.source_reference_number == "ORDER-1042"
    assert payload.transaction_reference_number == "PROVIDER-TXN-1042"
    assert payload.transaction_status_code == "S"


def test_event_values_map_to_transaction_statuses() -> None:
    assert PushWebhookEvent.SUCCESS.transaction_status is TransactionStatus.SUCCEEDED
    assert PushWebhookEvent.FAILED.transaction_status is TransactionStatus.FAILED
    assert PushWebhookEvent.REVERSED.transaction_status is TransactionStatus.REVERSED


@pytest.mark.parametrize(
    "value",
    ["pushpayment.unknown", "SUCCESS", "", "pushpayment.success "],
)
def test_rejects_unknown_event_values(value: str) -> None:
    with pytest.raises(ValueError):
        PushWebhookEvent(value)
