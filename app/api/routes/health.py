"""Health and readiness endpoints for the application."""

import time
from fastapi import APIRouter, Request

from app.common.datetime import format_iso, get_utc_now
from app.core.config import settings
from app.schemas.responses import HealthResponse

router = APIRouter()


# "/" belongs to the dashboard. A root route here would shadow it and serve the
# portal's landing page as unauthenticated JSON.


@router.get("/health", response_model=HealthResponse)
async def get_health(request: Request) -> HealthResponse:
    """Detailed health check endpoint tracking version, uptime, and settings configuration."""
    start_time = getattr(request.app.state, "start_time", time.time())
    uptime_seconds = round(time.time() - start_time, 2)

    # Check configurations status of the WhatsApp credentials
    whatsapp_settings = settings.whatsapp
    whatsapp_configured = bool(
        whatsapp_settings.access_token and
        whatsapp_settings.phone_number_id and
        whatsapp_settings.verify_token and
        whatsapp_settings.app_secret
    )

    return HealthResponse(
        status="running",
        version=settings.app.version,
        environment=settings.app.environment,
        timestamp=format_iso(get_utc_now()),
        uptime_seconds=uptime_seconds,
        whatsapp_config_status=whatsapp_configured
    )
