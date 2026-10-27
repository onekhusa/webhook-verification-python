from __future__ import annotations

from webhook_verification.payments.models import Payment
from webhook_verification.payments.ports import PaymentRepository


class PaymentsService:
    """Read and clear process-local OneKhusa payments."""

    def __init__(self, repository: PaymentRepository) -> None:
        self._repository = repository

    async def list(self) -> list[Payment]:
        return await self._repository.list()

    async def get(self, payment_id: str) -> Payment:
        return await self._repository.get(payment_id)

    async def clear(self) -> None:
        await self._repository.clear()
