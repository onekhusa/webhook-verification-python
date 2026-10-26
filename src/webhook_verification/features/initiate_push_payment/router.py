from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from webhook_verification.container import ContainerDep
from webhook_verification.features.initiate_push_payment.service import (
    ProviderSubmissionError,
)
from webhook_verification.onekhusa.client.push import PushPaymentRequest
from webhook_verification.onekhusa.errors import OneKhusaError
from webhook_verification.shared.payments.models import Payment

router = APIRouter()


@router.post(
    "/api/onekhusa/push-payments",
    response_model=Payment,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["onekhusa"],
)
async def create_onekhusa_push_payment(
    payload: PushPaymentRequest,
    container: ContainerDep,
) -> Payment:
    if not container.settings.onekhusa_is_configured:
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
        return await container.initiate_push_payment.execute(payload)
    except ProviderSubmissionError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": str(exc),
                "sourceReferenceNumber": exc.payment.source_reference_number,
                "paymentId": exc.payment.payment_id,
                "status": exc.payment.status,
                "transaction": exc.payment.model_dump(by_alias=True, mode="json"),
            },
        ) from exc
    except OneKhusaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
