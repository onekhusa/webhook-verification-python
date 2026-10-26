from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import secrets
from collections import deque
from datetime import UTC, datetime
from uuid import uuid4

import structlog
from pydantic import SecretStr

from webhook_verification.domain import (
    InvalidTransition,
    PushWebhookEvent,
    TransactionState,
    TransactionStatus,
)
from webhook_verification.onekhusa import OneKhusaClient, OneKhusaError
from webhook_verification.schemas import (
    PushPaymentRequest,
    PushWebhookPayload,
    SimulationTransaction,
)
from webhook_verification.security import verify_webhook_signature
from webhook_verification.settings import Settings

logger = structlog.get_logger(__name__)
MAX_SIMULATIONS = 100


class InvalidSignature(Exception):
    pass


class TransactionNotFound(Exception):
    pass


class InvalidSimulationTransition(Exception):
    pass


class ProviderSubmissionError(Exception):
    def __init__(
        self,
        transaction: SimulationTransaction,
        cause: OneKhusaError,
    ) -> None:
        super().__init__(str(cause))
        self.transaction = transaction
        self.status_code = cause.status_code


class InMemoryPaymentService:
    """Process-local simulator state; no database or disk writes are performed."""

    def __init__(
        self,
        settings: Settings,
        onekhusa_client: OneKhusaClient | None = None,
    ) -> None:
        self._settings = settings
        self._onekhusa_client = onekhusa_client
        self._transactions: dict[str, SimulationTransaction] = {}
        self._provider_fingerprints: dict[str, str] = {}
        self._receipts: set[str] = set()
        self._receipt_order: deque[str] = deque()
        self._lock = asyncio.Lock()
        self._demo_secret = SecretStr(secrets.token_hex(32))

    async def create_simulation(self, request: PushPaymentRequest) -> SimulationTransaction:
        return await self._create_transaction(request, mode="simulated")

    async def initiate_onekhusa(
        self,
        request: PushPaymentRequest,
    ) -> SimulationTransaction:
        if self._onekhusa_client is None or not self._settings.onekhusa_is_configured:
            raise OneKhusaError("OneKhusa calls are disabled or not fully configured")
        if not self._settings.onekhusa_is_sandbox:
            raise OneKhusaError("Only the OneKhusa sandbox endpoint is allowed by this simulator")
        source_reference = request.source_reference_number
        if source_reference is None:
            raise ValueError("A merchant source reference is required for OneKhusa requests")
        request_with_reference = request.model_copy(
            update={"source_reference_number": source_reference}
        )
        fingerprint = hashlib.sha256(
            request_with_reference.model_dump_json(by_alias=True).encode()
        ).hexdigest()
        async with self._lock:
            transaction = next(
                (
                    item
                    for item in self._transactions.values()
                    if item.source_reference_number == source_reference
                ),
                None,
            )
            if transaction is not None and (
                transaction.mode != "onekhusa"
                or self._provider_fingerprints.get(source_reference) != fingerprint
            ):
                raise ValueError("Source reference is already in use for another request")
            if transaction is not None:
                transaction = transaction.model_copy(deep=True)
        if transaction is None:
            transaction = await self._create_transaction(
                request_with_reference,
                mode="onekhusa",
                provider_fingerprint=fingerprint,
            )
        try:
            result = await self._onekhusa_client.initiate_push_payment(
                request_with_reference,
                source_reference_number=source_reference,
                idempotency_key=self._provider_idempotency_key(
                    request_with_reference,
                    source_reference,
                ),
            )
        except OneKhusaError as exc:
            async with self._lock:
                saved = self._transactions[transaction.simulation_id]
                saved.provider_http_status = exc.status_code
                saved.provider_message = str(exc)
                saved.updated_at = datetime.now(UTC)
                failed_attempt = saved.model_copy(deep=True)
            raise ProviderSubmissionError(failed_attempt, exc) from exc

        async with self._lock:
            saved = self._transactions[transaction.simulation_id]
            saved.provider_http_status = result.http_status
            saved.provider_message = result.message
            if result.transaction_reference_number:
                saved.transaction_reference_number = result.transaction_reference_number
            saved.updated_at = datetime.now(UTC)
            return saved.model_copy(deep=True)

    def _provider_idempotency_key(
        self,
        request: PushPaymentRequest,
        source_reference_number: str,
    ) -> str:
        merchant_number = (
            request.merchant_account_number or self._settings.onekhusa_merchant_account_number or 0
        )
        digest = hashlib.sha256(f"{merchant_number}:{source_reference_number}".encode()).hexdigest()
        return f"push-{digest}"

    async def _create_transaction(
        self,
        request: PushPaymentRequest,
        *,
        mode: str,
        provider_fingerprint: str | None = None,
    ) -> SimulationTransaction:
        now = datetime.now(UTC)
        transaction = SimulationTransaction(
            simulation_id=str(uuid4()),
            source_reference_number=request.source_reference_number
            or f"SIM-{uuid4().hex[:12].upper()}",
            transaction_reference_number=f"SIM-TXN-{uuid4().hex[:10].upper()}",
            connector_id=request.connector_id,
            payer_account_last_four=re.sub(
                r"[^A-Za-z0-9]",
                "",
                request.payer_account_number,
            )[-4:],
            transaction_amount=request.transaction_amount,
            transaction_description=request.transaction_description,
            captured_by=request.captured_by,
            mode=mode,
            status=TransactionStatus.PENDING.value,
            created_at=now,
            updated_at=now,
            events=[],
        )
        async with self._lock:
            if any(
                item.source_reference_number == transaction.source_reference_number
                for item in self._transactions.values()
            ):
                raise ValueError("Source reference is already in use in this simulation")
            self._transactions[transaction.simulation_id] = transaction
            if provider_fingerprint is not None:
                self._provider_fingerprints[transaction.source_reference_number] = (
                    provider_fingerprint
                )
            self._trim()
        return transaction.model_copy(deep=True)

    async def list_simulations(self) -> list[SimulationTransaction]:
        async with self._lock:
            transactions = sorted(
                self._transactions.values(),
                key=lambda item: item.created_at,
                reverse=True,
            )
            return [transaction.model_copy(deep=True) for transaction in transactions]

    async def get_simulation(self, simulation_id: str) -> SimulationTransaction:
        async with self._lock:
            transaction = self._transactions.get(simulation_id)
            if transaction is None:
                raise TransactionNotFound(simulation_id)
            return transaction.model_copy(deep=True)

    async def clear_simulations(self) -> None:
        async with self._lock:
            self._transactions.clear()
            self._provider_fingerprints.clear()
            self._receipts.clear()
            self._receipt_order.clear()

    async def simulate_event(
        self,
        simulation_id: str,
        event: PushWebhookEvent,
    ) -> tuple[SimulationTransaction, bool]:
        transaction = await self.get_simulation(simulation_id)
        payload = PushWebhookPayload(
            connector_id=transaction.connector_id,
            source_reference_number=transaction.source_reference_number,
            transaction_reference_number=transaction.transaction_reference_number,
            transaction_amount=transaction.transaction_amount,
            transaction_status_code={
                PushWebhookEvent.SUCCESS: "S",
                PushWebhookEvent.FAILED: "F",
                PushWebhookEvent.REVERSED: "R",
            }[event],
            transaction_date=datetime.now(UTC),
        )
        raw_body = json.dumps(
            payload.model_dump(mode="json", by_alias=True, exclude_none=True),
            separators=(",", ":"),
        ).encode()
        signature = hmac.new(
            self._demo_secret.get_secret_value().encode(),
            raw_body,
            hashlib.sha512,
        ).hexdigest()
        processed, duplicate, matched = await self.process_webhook(
            event,
            payload,
            raw_body,
            signature,
            self._demo_secret,
        )
        if processed is None or not matched:
            raise TransactionNotFound(simulation_id)
        return processed, duplicate

    
    async def process_webhook(
        self,
        event: PushWebhookEvent,
        payload: PushWebhookPayload,
        raw_body: bytes,
        signature: str | None,
        secret: SecretStr,
    ) -> tuple[SimulationTransaction | None, bool, bool]:
        if not verify_webhook_signature(raw_body, signature, secret):
            logger.warning(
                "onekhusa_webhook_invalid_signature",
                event_type=event.value,
            )
            raise InvalidSignature

        source_reference = payload.source_reference_number
        provider_reference = payload.transaction_reference_number

        if not source_reference and not provider_reference:
            logger.warning(
                "onekhusa_webhook_missing_references",
                event_type=event.value,
            )
            raise ValueError(
                "Webhook must contain a source or transaction reference"
            )

        identity = provider_reference or source_reference or ""
        receipt_key = hashlib.sha256(
            f"{event.value}:{identity}".encode()
        ).hexdigest()

        async with self._lock:
            # Find the transaction before checking deduplication.
            # This also handles receipts cached by the previous implementation.
            transaction = self._find_transaction(payload)

            if receipt_key in self._receipts:
                logger.info(
                    "onekhusa_webhook_duplicate",
                    event_type=event.value,
                    matched=transaction is not None,
                )
                return (
                    transaction.model_copy(deep=True)
                    if transaction is not None
                    else None,
                    True,
                    transaction is not None,
                )

            if transaction is None:
                logger.warning(
                    "onekhusa_webhook_unmatched",
                    event_type=event.value,
                    source_reference=source_reference,
                    provider_reference=provider_reference,
                )

                # Do not cache unmatched receipts. A retry may arrive after
                # the corresponding transaction has been persisted in memory.
                return None, False, False

            # A webhook can arrive before the initiation response has saved
            # the provider's transaction reference.
            if (
                transaction.mode == "onekhusa"
                and provider_reference
                and transaction.transaction_reference_number.startswith(
                    "SIM-TXN-"
                )
            ):
                transaction.transaction_reference_number = provider_reference

                logger.info(
                    "onekhusa_webhook_provider_reference_reconciled",
                    source_reference=source_reference,
                    provider_reference=provider_reference,
                )

            try:
                state = TransactionState(
                    TransactionStatus(transaction.status)
                )
                next_state = state.transition(event.transaction_status)
            except (InvalidTransition, ValueError) as exc:
                logger.warning(
                    "onekhusa_webhook_invalid_transition",
                    event_type=event.value,
                    source_reference=source_reference,
                    current_status=transaction.status,
                    error=str(exc),
                )
                raise InvalidSimulationTransition(str(exc)) from exc

            transaction.status = next_state.status.value
            transaction.updated_at = datetime.now(UTC)

            self._remember_receipt(receipt_key)

            transaction.events.append(
                {
                    "event": event.value,
                    "receivedAt": transaction.updated_at.isoformat(),
                    "signatureVerified": True,
                }
            )

            logger.info(
                "onekhusa_webhook_processed",
                event_type=event.value,
                source_reference=source_reference,
                provider_reference=(
                    transaction.transaction_reference_number
                ),
                status=transaction.status,
            )

            return transaction.model_copy(deep=True), False, True


 
    def _find_transaction(
        self,
        payload: PushWebhookPayload,
    ) -> SimulationTransaction | None:
        source_reference = payload.source_reference_number
        provider_reference = payload.transaction_reference_number

        # Prefer the merchant's source reference when supplied.
        if source_reference:
            transaction = next(
                (
                    item
                    for item in self._transactions.values()
                    if item.source_reference_number == source_reference
                ),
                None,
            )

            if transaction is None:
                return None

            # No provider reference was supplied, so the source reference
            # is sufficient to identify the transaction.
            if not provider_reference:
                return transaction

            # Both references match.
            if (
                transaction.transaction_reference_number
                == provider_reference
            ):
                return transaction

            # Allow an early webhook to match before the initiation response
            # replaces the locally generated placeholder reference.
            if (
                transaction.mode == "onekhusa"
                and transaction.transaction_reference_number.startswith(
                    "SIM-TXN-"
                )
            ):
                return transaction

            # Do not silently accept conflicting references when the
            # transaction already has an established provider reference.
            return None

        # If no source reference was supplied, match by transaction reference.
        if provider_reference:
            return next(
                (
                    item
                    for item in self._transactions.values()
                    if item.transaction_reference_number
                    == provider_reference
                ),
                None,
            )

        return None


    def _trim(self) -> None:
        while len(self._transactions) > MAX_SIMULATIONS:
            oldest_id = min(
                self._transactions,
                key=lambda item_id: self._transactions[item_id].created_at,
            )
            removed = self._transactions.pop(oldest_id)
            self._provider_fingerprints.pop(removed.source_reference_number, None)

    def _remember_receipt(self, receipt_key: str) -> None:
        self._receipts.add(receipt_key)
        self._receipt_order.append(receipt_key)
        while len(self._receipt_order) > MAX_SIMULATIONS * 10:
            self._receipts.discard(self._receipt_order.popleft())
