from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TransactionStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REVERSED = "reversed"


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


class InvalidTransition(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TransactionState:
    status: TransactionStatus

    def transition(self, target: TransactionStatus) -> TransactionState:
        allowed = {
            TransactionStatus.PENDING: {
                TransactionStatus.SUCCEEDED,
                TransactionStatus.FAILED,
            },
            TransactionStatus.SUCCEEDED: {TransactionStatus.REVERSED},
            TransactionStatus.FAILED: set(),
            TransactionStatus.REVERSED: set(),
        }
        if target == self.status:
            return self
        if target not in allowed[self.status]:
            raise InvalidTransition(f"Cannot transition {self.status} to {target}")
        return TransactionState(target)
