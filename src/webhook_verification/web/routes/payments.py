from __future__ import annotations

from fastapi import APIRouter, Response, status

from webhook_verification.web.container import ContainerDep
from webhook_verification.web.errors import ApiError
from webhook_verification.web.schemas import InitiatePaymentRequest, PaymentResponse

router = APIRouter()


@router.get(
    "/api/payments",
    response_model=list[PaymentResponse],
    tags=["payments"],
)
async def list_payments(container: ContainerDep) -> list[PaymentResponse]:
    payments = await container.payments.list()
    return [PaymentResponse.from_payment(payment) for payment in payments]


@router.get(
    "/api/payments/{payment_id}",
    response_model=PaymentResponse,
    tags=["payments"],
)
async def get_payment(payment_id: str, container: ContainerDep) -> PaymentResponse:
    payment = await container.payments.get(payment_id)
    return PaymentResponse.from_payment(payment)


@router.delete(
    "/api/payments",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["payments"],
)
async def clear_payments(container: ContainerDep) -> Response:
    await container.payments.clear()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/api/onekhusa/push-payments",
    response_model=PaymentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["onekhusa"],
)
async def create_onekhusa_push_payment(
    payload: InitiatePaymentRequest,
    container: ContainerDep,
    response: Response,
) -> PaymentResponse:
    settings = container.settings.onekhusa
    if not settings.is_configured:
        raise ApiError(
            503,
            "onekhusa_not_configured",
            "OneKhusa is disabled or required credentials are not configured",
        )
    if not settings.is_sandbox:
        raise ApiError(
            503,
            "onekhusa_non_sandbox_endpoint",
            "Only the OneKhusa sandbox endpoint is allowed",
        )

    payment = await container.initiate_push_payment.execute(payload.to_command())
    response.headers["Location"] = f"/api/payments/{payment.payment_id}"
    return PaymentResponse.from_payment(payment)
