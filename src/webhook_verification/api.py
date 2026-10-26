import json
from typing import cast

import structlog
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import ValidationError

from webhook_verification.application import (
    InMemoryPaymentService,
    InvalidSignature,
    InvalidSimulationTransition,
    ProviderSubmissionError,
    TransactionNotFound,
)
from webhook_verification.domain import PushWebhookEvent
from webhook_verification.onekhusa import OneKhusaError
from webhook_verification.schemas import (
    PushPaymentRequest,
    PushWebhookPayload,
    SimulationEventRequest,
    SimulationTransaction,
)
from webhook_verification.settings import Settings

logger = structlog.get_logger(__name__)
router = APIRouter()


def _service(request: Request) -> InMemoryPaymentService:
    return cast(InMemoryPaymentService, request.app.state.payment_service)


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def _require_simulation_mode(request: Request) -> None:
    settings = _settings(request)
    if settings.app_env == "production" or not settings.simulation_enabled:
        raise HTTPException(status_code=404, detail="Payment simulator is disabled")


@router.get("/api/config", tags=["simulator"])
async def get_client_config(request: Request) -> dict[str, object]:
    settings = _settings(request)
    return {
        "simulationEnabled": settings.simulation_enabled and settings.app_env != "production",
        "onekhusaEnabled": settings.onekhusa_is_configured,
        "onekhusaSandbox": settings.onekhusa_is_sandbox,
        "onekhusaBaseUrl": settings.onekhusa_base_url if settings.onekhusa_is_sandbox else None,
    }


@router.get("/", include_in_schema=False)
async def simulator_home(request: Request) -> Response:
    settings = _settings(request)
    if settings.app_env == "production" or not (
        settings.simulation_enabled or settings.onekhusa_is_configured
    ):
        raise HTTPException(status_code=404, detail="Payment simulator is disabled")
    return Response(
        content=(request.app.state.static_dir / "index.html").read_text(encoding="utf-8"),
        media_type="text/html",
    )


@router.get("/api/simulations", tags=["simulator"])
async def list_simulations(request: Request) -> list[SimulationTransaction]:
    return await _service(request).list_simulations()


@router.post(
    "/api/simulations",
    response_model=SimulationTransaction,
    status_code=status.HTTP_201_CREATED,
    tags=["simulator"],
)
async def create_simulation(
    payload: PushPaymentRequest,
    request: Request,
) -> SimulationTransaction:
    _require_simulation_mode(request)
    try:
        return await _service(request).create_simulation(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/api/onekhusa/push-payments",
    response_model=SimulationTransaction,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["onekhusa"],
)
async def create_onekhusa_push_payment(
    payload: PushPaymentRequest,
    request: Request,
) -> SimulationTransaction:
    if not _settings(request).onekhusa_is_configured:
        raise HTTPException(
            status_code=503,
            detail="OneKhusa is disabled or required credentials are not configured",
        )
    if payload.source_reference_number is None:
        raise HTTPException(
            status_code=422,
            detail="sourceReferenceNumber is required for OneKhusa requests",
        )
    try:
        return await _service(request).initiate_onekhusa(payload)
    except ProviderSubmissionError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": str(exc),
                "sourceReferenceNumber": exc.transaction.source_reference_number,
                "simulationId": exc.transaction.simulation_id,
                "status": exc.transaction.status,
                "transaction": exc.transaction.model_dump(by_alias=True, mode="json"),
            },
        ) from exc
    except OneKhusaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/api/simulations/{simulation_id}/events",
    response_model=SimulationTransaction,
    tags=["simulator"],
)
async def simulate_event(
    simulation_id: str,
    payload: SimulationEventRequest,
    request: Request,
) -> SimulationTransaction:
    _require_simulation_mode(request)
    try:
        transaction, _ = await _service(request).simulate_event(
            simulation_id,
            payload.event,
        )
    except TransactionNotFound as exc:
        raise HTTPException(status_code=404, detail="Simulation was not found") from exc
    except InvalidSimulationTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return transaction


@router.delete("/api/simulations", status_code=status.HTTP_204_NO_CONTENT, tags=["simulator"])
async def clear_simulations(request: Request) -> Response:
    _require_simulation_mode(request)
    await _service(request).clear_simulations()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/webhook/pushpayment", status_code=status.HTTP_200_OK, tags=["webhooks"])
async def receive_push_webhook(request: Request) -> Response:
    settings = _settings(request)
    content_length = request.headers.get("content-length")
    if (
        content_length
        and content_length.isdigit()
        and int(content_length) > settings.max_webhook_body_bytes
    ):
        raise HTTPException(status_code=413, detail="Webhook payload is too large")

    raw_body = await request.body()
    if len(raw_body) > settings.max_webhook_body_bytes:
        raise HTTPException(status_code=413, detail="Webhook payload is too large")

    event_header = request.headers.get("X-OneKhusa-Webhook-Event")
    signature = request.headers.get("X-OneKhusa-Webhook-Signature")
    # print(request.headers)
    if not event_header:
        raise HTTPException(status_code=400, detail="Missing webhook event header")
    try:
        event = PushWebhookEvent(event_header)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Unsupported push-payment webhook event",
        ) from exc
    print(event.value)
    secret = settings.one_khusa_webhook_secrets.get(event)
    print(secret)
    if secret is None or not secret.get_secret_value():
        logger.error("onekhusa_webhook_secret_missing", event_type=event.value)
        raise HTTPException(status_code=503, detail="Webhook verification is not configured")
    try:
        payload = PushWebhookPayload.model_validate_json(raw_body)
        transaction, duplicate, matched = await _service(request).process_webhook(
            event,
            payload,
            raw_body,
            signature,
            secret,
        )
    except InvalidSignature as exc:
        logger.warning("onekhusa_webhook_signature_invalid", event_type=event.value)
        raise HTTPException(status_code=401, detail="Invalid webhook signature") from exc
    except (ValueError, ValidationError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc
    except InvalidSimulationTransition as exc:
        logger.error("onekhusa_webhook_transition_rejected", event_type=event.value)
        raise HTTPException(status_code=409, detail="Invalid transaction state transition") from exc

    logger.info(
        "onekhusa_webhook_processed",
        event_type=event.value,
        duplicate=duplicate,
        matched=matched,
        source_reference=payload.source_reference_number,
        provider_reference=payload.transaction_reference_number,
        transaction_status=transaction.status if transaction else None,
    )
    return Response(content="acknowledged", media_type="text/plain", status_code=status.HTTP_200_OK)


@router.get("/api/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "healthy"}
