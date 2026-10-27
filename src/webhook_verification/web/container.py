from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request

if TYPE_CHECKING:
    from webhook_verification.config import Settings
    from webhook_verification.onekhusa.client import OneKhusaClient
    from webhook_verification.payments.initiate import InitiatePushPayment
    from webhook_verification.payments.queries import PaymentsService
    from webhook_verification.payments.receive_webhook import ReceiveWebhook
    from webhook_verification.payments.repository import InMemoryPaymentRepository


@dataclass(slots=True)
class Container:
    """Composition root values shared by every router."""

    settings: Settings
    repository: InMemoryPaymentRepository
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
