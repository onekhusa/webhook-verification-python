from __future__ import annotations

from fastapi import APIRouter, Response, status

from webhook_verification.container import ContainerDep
from webhook_verification.shared.payments.models import Payment

router = APIRouter()


@router.get(
    "/api/payments",
    response_model=list[Payment],
    tags=["payments"],
)
async def list_payments(container: ContainerDep) -> list[Payment]:
    return await container.payments.list()


@router.delete(
    "/api/payments",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["payments"],
)
async def clear_payments(container: ContainerDep) -> Response:
    await container.payments.clear()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
