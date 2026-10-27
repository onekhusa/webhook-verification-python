"""Browser dashboard and static assets. Demo-only, not part of the adapter."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from webhook_verification.web.container import ContainerDep
from webhook_verification.web.errors import ApiError

UI_DIR = Path(__file__).resolve().parents[1] / "ui"
TEMPLATES = Jinja2Templates(directory=str(UI_DIR))

router = APIRouter()

ASSET_MEDIA_TYPES = {
    "app.css": "text/css",
    "app.js": "text/javascript",
    "logo.svg": "image/svg+xml",
}


@router.get("/", include_in_schema=False)
async def dashboard(request: Request, container: ContainerDep) -> Response:
    if container.settings.app_env == "production":
        raise ApiError(404, "not_found", "Payment dashboard is disabled")
    return TEMPLATES.TemplateResponse(
        request,
        "dashboard.html",
        {"request": request},
    )


@router.get("/assets/{filename}", include_in_schema=False)
async def asset(filename: str) -> FileResponse:
    media_type = ASSET_MEDIA_TYPES.get(filename)
    if media_type is None:
        raise ApiError(404, "not_found", "Asset not found")

    path = UI_DIR / filename
    if not path.is_file():
        raise ApiError(404, "not_found", "Asset not found")
    return FileResponse(path, media_type=media_type)
