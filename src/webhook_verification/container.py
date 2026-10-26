from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request

if TYPE_CHECKING:
    from webhook_verification.features.configuration.settings import Settings
    from webhook_verification.features.initiate_push_payment.service import (
        InitiatePushPayment,
    )
    from webhook_verification.features.payments.service import PaymentsService
    from webhook_verification.features.receive_webhook.service import ReceiveWebhook
    from webhook_verification.onekhusa.client import OneKhusaClient
    from webhook_verification.shared.payments.store import InMemoryPaymentStore


@dataclass(slots=True)
class Container:
    """Composition root values shared by every feature router."""

    settings: Settings
    store: InMemoryPaymentStore
    onekhusa: OneKhusaClient
    payments: PaymentsService
    initiate_push_payment: InitiatePushPayment
    receive_webhook: ReceiveWebhook


def get_container(request: Request) -> Container:
    container: object = request.app.state.container
    if not isinstance(container, Container):
        raise RuntimeError("Application container is not configured")
    return container


ContainerDep = Annotated[Container, Depends(get_container)]
