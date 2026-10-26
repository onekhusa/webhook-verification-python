from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import structlog
from fastapi import FastAPI

from webhook_verification.container import Container
from webhook_verification.features.configuration.router import (
    router as configuration_router,
)
from webhook_verification.features.configuration.settings import Settings, get_settings
from webhook_verification.features.initiate_push_payment.router import (
    router as initiate_push_payment_router,
)
from webhook_verification.features.initiate_push_payment.service import (
    InitiatePushPayment,
)
from webhook_verification.features.payments.router import router as payments_router
from webhook_verification.features.payments.service import PaymentsService
from webhook_verification.features.receive_webhook.router import (
    router as receive_webhook_router,
)
from webhook_verification.features.receive_webhook.service import ReceiveWebhook
from webhook_verification.onekhusa.client import OneKhusaClient
from webhook_verification.onekhusa.client.http import create_http_client
from webhook_verification.shared.payments.store import InMemoryPaymentStore
from webhook_verification.ui.routes import router as ui_router


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.stdlib.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def create_app(
    settings: Settings | None = None,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging()
    logger = structlog.get_logger(__name__)

    owned_client: httpx.AsyncClient | None = None
    client = http_client
    if client is None:
        client = create_http_client(app_settings)
        owned_client = client

    store = InMemoryPaymentStore()
    onekhusa = OneKhusaClient(app_settings, client)
    payments = PaymentsService(store)
    receive_webhook = ReceiveWebhook(store)

    container = Container(
        settings=app_settings,
        store=store,
        onekhusa=onekhusa,
        payments=payments,
        initiate_push_payment=InitiatePushPayment(app_settings, store, onekhusa),
        receive_webhook=receive_webhook,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        logger.info("application_started", app="webhook-verification")
        try:
            yield
        finally:
            if owned_client is not None:
                await owned_client.aclose()
            logger.info("application_stopped", app="webhook-verification")

    application = FastAPI(
        title="OneKhusa Push Payment Dashboard",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.state.container = container

    application.include_router(ui_router)
    application.include_router(configuration_router)
    application.include_router(payments_router)
    application.include_router(initiate_push_payment_router)
    application.include_router(receive_webhook_router)

    logger.info("application_configured", app="webhook-verification")
    return application


app = create_app()
