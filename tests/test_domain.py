import pytest

from webhook_verification.domain import (
    InvalidTransition,
    PushWebhookEvent,
    TransactionState,
    TransactionStatus,
)
from webhook_verification.schemas import PushPaymentRequest


def test_push_payment_request_validates_essential_fields() -> None:
    request = PushPaymentRequest.model_validate(
        {
            "connectorId": 10,
            "payerAccountNumber": " 2659912345678 ",
            "transactionAmount": "10.25",
            "transactionDescription": " Invoice ",
            "capturedBy": " checkout ",
        }
    )

    assert request.payer_account_number == "2659912345678"
    assert request.transaction_amount == 10.25
    assert request.transaction_description == "Invoice"
    assert request.source_reference_number is None


@pytest.mark.parametrize(
    "payload",
    [
        {
            "connectorId": 0,
            "payerAccountNumber": "123",
            "transactionAmount": 10,
            "transactionDescription": "test",
            "capturedBy": "test",
        },
        {
            "connectorId": 1,
            "payerAccountNumber": "123",
            "transactionAmount": 0,
            "transactionDescription": "test",
            "capturedBy": "test",
        },
        {
            "connectorId": 1,
            "payerAccountNumber": "123",
            "transactionAmount": 10,
            "transactionDescription": "",
            "capturedBy": "test",
        },
    ],
)
def test_push_payment_request_rejects_invalid_input(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        PushPaymentRequest.model_validate(payload)


def test_transaction_lifecycle_accepts_success_then_reversal() -> None:
    state = TransactionState(TransactionStatus.PENDING)
    state = state.transition(PushWebhookEvent.SUCCESS.transaction_status)
    assert state.status is TransactionStatus.SUCCEEDED
    state = state.transition(PushWebhookEvent.REVERSED.transaction_status)
    assert state.status is TransactionStatus.REVERSED


def test_failed_event_maps_to_failed_status() -> None:
    state = TransactionState(TransactionStatus.PENDING)

    failed_state = state.transition(PushWebhookEvent.FAILED.transaction_status)

    assert failed_state.status is TransactionStatus.FAILED


def test_transaction_lifecycle_rejects_terminal_conflicts() -> None:
    with pytest.raises(InvalidTransition):
        TransactionState(TransactionStatus.FAILED).transition(TransactionStatus.SUCCEEDED)
