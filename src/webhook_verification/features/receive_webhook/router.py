from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import ValidationError

from webhook_verification.container import ContainerDep
from webhook_verification.features.receive_webhook.service import (
    InvalidSignature,
    InvalidWebhookTransition,
)
from webhook_verification.onekhusa.webhook.events import PushWebhookEvent
from webhook_verification.onekhusa.webhook.payload import PushWebhookPayload

router = APIRouter()


@router.post(
    "/webhook/pushpayment",
    status_code=status.HTTP_200_OK,
    tags=["webhooks"],
)
async def receive_push_webhook(
    request: Request,
    container: ContainerDep,
) -> Response:
    settings = container.settings
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
    if not event_header:
        raise HTTPException(status_code=400, detail="Missing webhook event header")
    try:
        event = PushWebhookEvent(event_header)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Unsupported push-payment webhook event",
        ) from exc

    secret = settings.onekhusa_webhook_secrets.get(event)
    if secret is None or not secret.get_secret_value():
        raise HTTPException(
            status_code=503,
            detail="Webhook verification is not configured",
        )

    try:
        payload = PushWebhookPayload.model_validate_json(raw_body)
        await container.receive_webhook.process(
            event=event,
            payload=payload,
            raw_body=raw_body,
            signature=signature,
            secret=secret,
        )
    except InvalidSignature as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid webhook signature",
        ) from exc
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc
    except InvalidWebhookTransition as exc:
        raise HTTPException(
            status_code=409,
            detail="Invalid transaction state transition",
        ) from exc

    return Response(
        content="acknowledged",
        media_type="text/plain",
        status_code=status.HTTP_200_OK,
    )
