from pydantic import BaseModel, Field
from datetime import datetime, timezone


class HealthCheckResponse(BaseModel):
    status: str = Field(default="ok", description="Service health status")
    version: str = Field(..., description="API version")
    environment: str = Field(..., description="Current deployment environment")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="UTC timestamp of the check")
    max_audio_mb: float = Field(..., description="Configured maximum audio upload limit in MB")
    timeout_seconds: int = Field(..., description="Configured router timeout ceiling")
