from fastapi import APIRouter
from app.api.endpoints.health import router as health_router
from app.api.endpoints.lectures import router as lectures_router
from app.api.endpoints.webhooks import router as webhooks_router

api_router = APIRouter()

# Mount API endpoints
api_router.include_router(health_router, tags=["Health"])
api_router.include_router(lectures_router, tags=["Lectures"])
api_router.include_router(webhooks_router, tags=["Webhooks"])
