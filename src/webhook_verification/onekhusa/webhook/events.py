from __future__ import annotations

from enum import StrEnum

from webhook_verification.shared.payments.models import TransactionStatus


class PushWebhookEvent(StrEnum):
    SUCCESS = "pushpayment.success"
    FAILED = "pushpayment.failed"
    REVERSED = "pushpayment.reversed"

    @property
    def transaction_status(self) -> TransactionStatus:
        return {
            PushWebhookEvent.SUCCESS: TransactionStatus.SUCCEEDED,
            PushWebhookEvent.FAILED: TransactionStatus.FAILED,
            PushWebhookEvent.REVERSED: TransactionStatus.REVERSED,
        }[self]
