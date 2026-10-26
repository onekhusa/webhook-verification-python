from __future__ import annotations

import httpx
import pytest

from tests.support import asgi_client, base_settings


@pytest.mark.asyncio
async def test_dashboard_renders_the_onekhusa_only_layout(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "OneKhusa · Push Payment Test Bench" in response.text
    assert "/assets/app.css" in response.text
    assert "/assets/app.js" in response.text
    assert "/assets/logo.svg" in response.text
    assert "payment-form" in response.text
    assert "Send push to OneKhusa sandbox" in response.text
    assert "Local simulation" not in response.text
    assert "simulate callback" not in response.text.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "media_type"),
    [
        ("app.css", "text/css"),
        ("app.js", "text/javascript"),
        ("logo.svg", "image/svg+xml"),
    ],
)
async def test_known_assets_are_served_with_their_media_type(
    client: httpx.AsyncClient,
    filename: str,
    media_type: str,
) -> None:
    response = await client.get(f"/assets/{filename}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(media_type)
    assert response.content


@pytest.mark.asyncio
async def test_unknown_assets_are_not_served(client: httpx.AsyncClient) -> None:
    for filename in ["dashboard.html", "layout.html", "missing.css", "app.py"]:
        response = await client.get(f"/assets/{filename}")

        assert response.status_code == 404
        assert response.json()["detail"] == "Asset not found"


@pytest.mark.asyncio
async def test_dashboard_is_hidden_in_production() -> None:
    async with asgi_client(base_settings(app_env="production")) as client:
        response = await client.get("/")

    assert response.status_code == 404
    assert response.json()["detail"] == "Payment dashboard is disabled"


@pytest.mark.asyncio
async def test_dashboard_explains_missing_configuration() -> None:
    async with asgi_client(base_settings()) as client:
        response = await client.get("/")
        config = await client.get("/api/config")

    assert response.status_code == 200
    assert config.json()["onekhusaEnabled"] is False
