from fastapi import APIRouter
from datetime import datetime, timezone
from app.core.config import settings
from app.schemas.health import HealthCheckResponse

router = APIRouter()


@router.get("/health", response_model=HealthCheckResponse, summary="Service Health & Diagnostic Check")
async def health_check():
    """Returns the operational status, version, and runtime constraints of the Enlighten Me API."""
    return HealthCheckResponse(
        status="ok",
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
        timestamp=datetime.now(timezone.utc),
        max_audio_mb=round(settings.MAX_AUDIO_BYTES / (1024 * 1024), 2),
        timeout_seconds=settings.ROUTER_TIMEOUT_SECONDS,
    )
