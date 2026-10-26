from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import structlog
from fastapi import FastAPI

from webhook_verification.api import router
from webhook_verification.application import InMemoryPaymentService
from webhook_verification.onekhusa import OneKhusaClient, create_http_client
from webhook_verification.settings import Settings, get_settings


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

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        client = http_client or create_http_client(app_settings)

        application.state.payment_service = InMemoryPaymentService(
            app_settings,
            OneKhusaClient(app_settings, client),
        )

        logger.info("application_started", app="webhook-verification")

        try:
            yield
        finally:
            if http_client is None:
                await client.aclose()

            logger.info("application_stopped", app="webhook-verification")

    application = FastAPI(
        title="OneKhusa Push Payment Simulator",
        version="1.0.0",
        lifespan=lifespan,
    )

    application.state.settings = app_settings
    application.state.static_dir = Path(__file__).parent / "static"

    application.include_router(router)

    logger.info("application_configured", app="webhook-verification")

    return application


app = create_app()
