from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from webhook_verification.onekhusa.webhook.events import PushWebhookEvent
from webhook_verification.web.adapters.onekhusa_webhook import (
    authenticate_and_parse_push_webhook,
)
from webhook_verification.web.container import ContainerDep
from webhook_verification.web.errors import ApiError

router = APIRouter()


@router.post(
    "/webhook/pushpayment",
    status_code=status.HTTP_200_OK,
    tags=["webhooks"],
)
@router.post(
    "/webhooks/onekhusa/push-payments",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def receive_push_webhook(request: Request, container: ContainerDep) -> Response:
    settings = container.settings
    raw_body = await _read_limited_body(request, settings.max_webhook_body_bytes)
    event = _webhook_event(request)

    secret = settings.onekhusa.webhook_secret(event)
    if secret is None:
        raise ApiError(
            503,
            "webhook_not_configured",
            "Webhook verification is not configured",
        )

    # Authentication happens before parsing inside this adapter. The use case
    # only sees a verified, provider-neutral notification.
    notification = authenticate_and_parse_push_webhook(
        raw_body=raw_body,
        signature=request.headers.get("X-OneKhusa-Webhook-Signature"),
        secret=secret,
        event=event,
    )
    await container.receive_webhook.process(notification)

    return Response(
        content="acknowledged",
        media_type="text/plain",
        status_code=status.HTTP_200_OK,
    )


def _webhook_event(request: Request) -> PushWebhookEvent:
    event_header = request.headers.get("X-OneKhusa-Webhook-Event")
    if not event_header:
        raise ApiError(400, "missing_webhook_event", "Missing webhook event header")
    try:
        return PushWebhookEvent(event_header)
    except ValueError as exc:
        raise ApiError(
            400,
            "unsupported_webhook_event",
            "Unsupported push-payment webhook event",
        ) from exc


async def _read_limited_body(request: Request, max_bytes: int) -> bytes:
    content_length = request.headers.get("content-length")
    if (
        content_length
        and content_length.isdigit()
        and int(content_length) > max_bytes
    ):
        raise ApiError(413, "webhook_body_too_large", "Webhook payload is too large")

    raw_body = await request.body()
    if len(raw_body) > max_bytes:
        raise ApiError(413, "webhook_body_too_large", "Webhook payload is too large")
    return raw_body
