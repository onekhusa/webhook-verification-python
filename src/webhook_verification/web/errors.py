"""One place that turns application errors into HTTP responses.

Every error uses the same envelope::

    {"error": {"code": "...", "message": "...", "retryable": false}}

Routers therefore stay thin: they raise domain errors and do not hand-build
status codes.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from webhook_verification.payments.errors import (
    DuplicateMerchantReference,
    InvalidTransition,
    InvalidWebhookPayload,
    InvalidWebhookSignature,
    MerchantReferenceConflict,
    PaymentNotFound,
    ProviderInvalidResponse,
    ProviderNotConfigured,
    ProviderRejected,
    ProviderSubmissionFailed,
    ProviderUnavailable,
)
from webhook_verification.payments.models import Payment
from webhook_verification.web.schemas import PaymentResponse


class ApiError(Exception):
    """An expected HTTP failure raised by a route."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        payment: Payment | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.payment = payment


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    payment: Payment | None = None,
    details: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    if payment is not None:
        error["payment"] = PaymentResponse.from_payment(payment).model_dump(
            by_alias=True,
            mode="json",
        )
    if details is not None:
        error["details"] = details
    return JSONResponse(status_code=status_code, content={"error": error})


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(
            exc.status_code,
            exc.code,
            exc.message,
            retryable=exc.retryable,
            payment=exc.payment,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        details = [
            {
                "location": ".".join(str(part) for part in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return error_response(
            422,
            "invalid_request",
            "Request validation failed",
            details=details,
        )

    @app.exception_handler(PaymentNotFound)
    async def handle_payment_not_found(
        request: Request,
        exc: PaymentNotFound,
    ) -> JSONResponse:
        return error_response(404, "payment_not_found", str(exc))

    @app.exception_handler(MerchantReferenceConflict)
    async def handle_merchant_reference_conflict(
        request: Request,
        exc: MerchantReferenceConflict,
    ) -> JSONResponse:
        return error_response(409, "merchant_reference_conflict", str(exc))

    @app.exception_handler(DuplicateMerchantReference)
    async def handle_duplicate_merchant_reference(
        request: Request,
        exc: DuplicateMerchantReference,
    ) -> JSONResponse:
        return error_response(409, "merchant_reference_conflict", str(exc))

    @app.exception_handler(InvalidTransition)
    async def handle_invalid_transition(
        request: Request,
        exc: InvalidTransition,
    ) -> JSONResponse:
        return error_response(409, "invalid_transition", str(exc))

    @app.exception_handler(InvalidWebhookSignature)
    async def handle_invalid_signature(
        request: Request,
        exc: InvalidWebhookSignature,
    ) -> JSONResponse:
        return error_response(401, "invalid_webhook_signature", "Invalid webhook signature")

    @app.exception_handler(InvalidWebhookPayload)
    async def handle_invalid_webhook_payload(
        request: Request,
        exc: InvalidWebhookPayload,
    ) -> JSONResponse:
        return error_response(400, "invalid_webhook_payload", str(exc))

    @app.exception_handler(ProviderSubmissionFailed)
    async def handle_provider_submission_failed(
        request: Request,
        exc: ProviderSubmissionFailed,
    ) -> JSONResponse:
        return error_response(
            502,
            exc.code,
            str(exc),
            retryable=exc.retryable,
            payment=exc.payment,
        )

    @app.exception_handler(ProviderNotConfigured)
    async def handle_provider_not_configured(
        request: Request,
        exc: ProviderNotConfigured,
    ) -> JSONResponse:
        return error_response(503, exc.code, str(exc))

    @app.exception_handler(ProviderUnavailable)
    async def handle_provider_unavailable(
        request: Request,
        exc: ProviderUnavailable,
    ) -> JSONResponse:
        return error_response(503, exc.code, str(exc), retryable=True)

    @app.exception_handler(ProviderRejected)
    async def handle_provider_rejected(
        request: Request,
        exc: ProviderRejected,
    ) -> JSONResponse:
        return error_response(502, exc.code, str(exc))

    @app.exception_handler(ProviderInvalidResponse)
    async def handle_provider_invalid_response(
        request: Request,
        exc: ProviderInvalidResponse,
    ) -> JSONResponse:
        return error_response(502, exc.code, str(exc))
