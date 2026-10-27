"""Wire contracts for OneKhusa Collections push payments.

The field names here mirror the OneKhusa documentation. Internal application
code uses the neutral command types in ``payments.ports``; this module is the
only place where ``sourceReferenceNumber`` appears on the initiation side.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

ACCEPTED_RESPONSE_CODE = "I100"
MIN_CONNECTOR_ID = 1
_AMOUNT_SENTINEL = "onekhusa-amount-placeholder-7f3c"

AccountReference = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]
Reference = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class InvalidConnectorError(ValueError):
    pass


def validate_connector_id(connector_id: object) -> int:
    """Return a valid OneKhusa connector identifier or raise."""

    if (
        isinstance(connector_id, bool)
        or not isinstance(connector_id, int)
        or connector_id < MIN_CONNECTOR_ID
    ):
        raise InvalidConnectorError(
            f"connectorId must be an integer greater than or equal to {MIN_CONNECTOR_ID}"
        )
    return connector_id


class PushPaymentRequest(BaseModel):
    """Documented OneKhusa initiation request.

    ``merchant_reference`` is serialized as ``sourceReferenceNumber``. That is
    the value OneKhusa later echoes as ``merchantReferenceNumber`` in webhooks.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    merchant_account_number: int | None = Field(
        default=None,
        alias="merchantAccountNumber",
        ge=10_000_000,
        le=99_999_999,
    )
    connector_id: int = Field(alias="connectorId", gt=0)
    payer_account_number: AccountReference = Field(alias="payerAccountNumber")
    merchant_reference: Reference = Field(alias="sourceReferenceNumber")
    transaction_description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ] = Field(alias="transactionDescription")
    transaction_amount: Decimal = Field(
        alias="transactionAmount",
        gt=0,
        max_digits=18,
        decimal_places=2,
    )
    captured_by: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
    ] = Field(alias="capturedBy")

    @field_validator("connector_id")
    @classmethod
    def validate_connector(cls, value: int) -> int:
        return validate_connector_id(value)


@dataclass(frozen=True, slots=True)
class PushPaymentResult:
    http_status: int
    provider_transaction_reference: str | None
    message: str


def encode_initiate_request(
    request: PushPaymentRequest,
    configured_merchant_account_number: int,
) -> bytes:
    """Serialize the documented request, with an unquoted JSON amount.

    OneKhusa expects ``transactionAmount`` as a JSON number. ``Decimal`` is not
    serializable by the standard library, so the amount is encoded as a
    validated decimal string through a sentinel and the result is re-parsed to
    prove it is still valid JSON.
    """

    payload: dict[str, Any] = request.model_dump(
        by_alias=True,
        exclude_none=True,
        mode="json",
    )
    payload["merchantAccountNumber"] = (
        request.merchant_account_number or configured_merchant_account_number
    )
    payload["transactionAmount"] = _AMOUNT_SENTINEL

    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    marker = json.dumps(_AMOUNT_SENTINEL)
    if body.count(marker) != 1:
        raise ValueError("Could not encode transactionAmount exactly once")

    encoded = body.replace(marker, _decimal_number(request.transaction_amount), 1)
    json.loads(encoded)
    return encoded.encode()


def _decimal_number(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("transactionAmount must be finite")
    return format(value, "f")


def provider_idempotency_key(merchant_account_number: int, merchant_reference: str) -> str:
    """Stable idempotency key for an identical merchant submission."""

    digest = hashlib.sha256(
        f"{merchant_account_number}:{merchant_reference}".encode()
    ).hexdigest()
    return f"push-{digest}"
