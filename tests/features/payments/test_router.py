from __future__ import annotations

import httpx
import pytest

from tests.support import create_onekhusa_payment


@pytest.mark.asyncio
async def test_payment_list_starts_empty(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/payments")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_payments_are_listed_and_masked(
    client: httpx.AsyncClient,
) -> None:
    created = await create_onekhusa_payment(client)

    listed = await client.get("/api/payments")

    assert listed.status_code == 200
    body = listed.json()
    assert len(body) == 1
    assert body[0]["paymentId"] == created["paymentId"]
    assert body[0]["sourceReferenceNumber"] == "ORDER-1042"
    assert body[0]["payerAccountLastFour"] == "5678"
    assert body[0]["status"] == "pending"
    assert "payerAccountNumber" not in body[0]
    assert "mode" not in body[0]


@pytest.mark.asyncio
async def test_clear_removes_every_payment(client: httpx.AsyncClient) -> None:
    await create_onekhusa_payment(client)

    cleared = await client.delete("/api/payments")

    assert cleared.status_code == 204
    assert cleared.content == b""
    assert (await client.get("/api/payments")).json() == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/simulations"),
        ("DELETE", "/api/simulations"),
        ("POST", "/api/simulations"),
        ("POST", "/api/simulations/missing/events"),
    ],
)
async def test_simulation_endpoints_are_gone(
    client: httpx.AsyncClient,
    method: str,
    path: str,
) -> None:
    response = await client.request(method, path, json={})

    assert response.status_code == 404
