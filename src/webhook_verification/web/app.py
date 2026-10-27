from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import structlog
from fastapi import FastAPI

from webhook_verification.config import Settings, get_settings
from webhook_verification.onekhusa.client import OneKhusaClient
from webhook_verification.onekhusa.http import create_http_client
from webhook_verification.payments.clock import SystemClock
from webhook_verification.payments.initiate import InitiatePushPayment
from webhook_verification.payments.queries import PaymentsService
from webhook_verification.payments.receive_webhook import ReceiveWebhook
from webhook_verification.payments.repository import InMemoryPaymentRepository
from webhook_verification.web.adapters.onekhusa_gateway import (
    OneKhusaPushPaymentGateway,
)
from webhook_verification.web.container import Container
from webhook_verification.web.errors import install_error_handlers
from webhook_verification.web.routes.configuration import (
    router as configuration_router,
)
from webhook_verification.web.routes.payments import router as payments_router
from webhook_verification.web.routes.ui import router as ui_router
from webhook_verification.web.routes.webhooks import router as webhooks_router


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

    onekhusa_settings = app_settings.onekhusa
    if onekhusa_settings.enabled and not onekhusa_settings.is_sandbox:
        logger.warning(
            "onekhusa_non_sandbox_endpoint",
            base_url=onekhusa_settings.base_url,
        )

    owned_http_client: httpx.AsyncClient | None = None
    provider_http = http_client
    if provider_http is None:
        provider_http = create_http_client(onekhusa_settings)
        owned_http_client = provider_http

    repository = InMemoryPaymentRepository()
    clock = SystemClock()
    onekhusa = OneKhusaClient(onekhusa_settings, provider_http)
    gateway = OneKhusaPushPaymentGateway(onekhusa_settings, onekhusa)

    container = Container(
        settings=app_settings,
        repository=repository,
        onekhusa=onekhusa,
        payments=PaymentsService(repository),
        initiate_push_payment=InitiatePushPayment(repository, gateway, clock),
        receive_webhook=ReceiveWebhook(repository, clock),
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        logger.info("application_started", app="onekhusa-push-payment-demo")
        try:
            yield
        finally:
            if owned_http_client is not None:
                await owned_http_client.aclose()
            logger.info("application_stopped", app="onekhusa-push-payment-demo")

    application = FastAPI(
        title="OneKhusa Push Payment Demo",
        description=(
            "Reference integration for OneKhusa Collections push payments. "
            "In-memory state; sandbox only."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )
    application.state.container = container
    install_error_handlers(application)

    application.include_router(ui_router)
    application.include_router(configuration_router)
    application.include_router(payments_router)
    application.include_router(webhooks_router)

    logger.info("application_configured", app="onekhusa-push-payment-demo")
    return application


app = create_app()
