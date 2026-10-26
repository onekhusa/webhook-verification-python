from __future__ import annotations

from webhook_verification.shared.payments.models import Payment
from webhook_verification.shared.payments.store import InMemoryPaymentStore


class PaymentsService:
    """Read and clear process-local OneKhusa payments."""

    def __init__(self, store: InMemoryPaymentStore) -> None:
        self._store = store

    async def list(self) -> list[Payment]:
        async with self._store.locked() as session:
            return session.list()

    async def get(self, payment_id: str) -> Payment:
        async with self._store.locked() as session:
            return session.get(payment_id)

    async def clear(self) -> None:
        async with self._store.locked() as session:
            session.clear()
