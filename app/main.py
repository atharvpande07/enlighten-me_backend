from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.core.logging import logger, setup_logging
from app.api.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup sequence
    setup_logging()
    logger.info("Initializing Enlighten Me Backend v%s in [%s] mode...", settings.VERSION, settings.ENVIRONMENT)
    logger.info("Audio Payload Limit: %s MB | Timeout: %ss", round(settings.MAX_AUDIO_BYTES / 1024 / 1024, 2), settings.ROUTER_TIMEOUT_SECONDS)
    yield
    # Shutdown sequence
    logger.info("Enlighten Me Backend gracefully shutting down.")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Stateless audio-to-study-guide router for Enlighten Me (Groq Whisper + Gemini 2.5 Flash + Supabase)",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# CORS Middleware for mobile client and web previews
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API v1 Central Router
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint for quick ping and API discovery."""
    return {
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "online",
        "api_v1": f"{settings.API_V1_STR}/health",
        "docs": "/docs" if settings.DEBUG else "Disabled in production",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.PORT, reload=True)

