from __future__ import annotations

from enum import StrEnum


class PushWebhookEvent(StrEnum):
    """Event names carried by the X-OneKhusa-Webhook-Event header."""

    SUCCESS = "pushpayment.success"
    FAILED = "pushpayment.failed"
    REVERSED = "pushpayment.reversed"
