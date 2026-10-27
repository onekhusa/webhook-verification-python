from __future__ import annotations

from fastapi import APIRouter

from webhook_verification.web.container import ContainerDep

router = APIRouter()


@router.get("/api/config", tags=["configuration"])
async def get_client_config(container: ContainerDep) -> dict[str, object]:
    settings = container.settings.onekhusa
    return {
        "onekhusaEnabled": settings.is_configured,
        "onekhusaSandbox": settings.is_sandbox,
        "onekhusaBaseUrl": (
            settings.base_url
            if settings.is_configured and settings.is_sandbox
            else None
        ),
    }


@router.get("/api/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "healthy"}
