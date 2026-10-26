from __future__ import annotations

from fastapi import APIRouter

from webhook_verification.container import ContainerDep

router = APIRouter()


@router.get("/api/config", tags=["configuration"])
async def get_client_config(container: ContainerDep) -> dict[str, object]:
    settings = container.settings
    return {
        "onekhusaEnabled": settings.onekhusa_is_configured,
        "onekhusaSandbox": settings.onekhusa_is_sandbox,
        "onekhusaBaseUrl": (
            settings.onekhusa_base_url
            if settings.onekhusa_is_configured and settings.onekhusa_is_sandbox
            else None
        ),
    }


@router.get("/api/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "healthy"}
