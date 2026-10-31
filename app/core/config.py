import os
from typing import List, Union
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Enlighten Me API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Server & Environment
    ENVIRONMENT: str = "development"
    PORT: int = 8000
    DEBUG: bool = True
    
    # CORS Origins
    CORS_ORIGINS: List[str] = [
        "http://localhost:8081",
        "http://localhost:19006",
        "http://localhost:3000",
        "http://127.0.0.1:8081",
        "*",
    ]

    # Supabase Configuration
    SUPABASE_URL: str = "https://placeholder-project.supabase.co"
    SUPABASE_KEY: str = "placeholder-anon-key"
    SUPABASE_SERVICE_ROLE_KEY: str = "placeholder-service-role-key"
    SUPABASE_JWT_SECRET: str = "super-secret-jwt-token-key-for-local-testing-only"
    
    # AI Vendor Credentials & Models
    GROQ_API_KEY: str = "gsk_placeholder"
    GROQ_MODEL: str = "whisper-large-v3-turbo"
    GEMINI_API_KEY: str = "AIzaSy_placeholder"
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    GEMINI_FALLBACK_MODEL: str = "gemini-3.5-flash"
    
    # RevenueCat Webhook Secret
    REVENUECAT_WEBHOOK_SECRET: str = "placeholder_webhook_secret_key"
    
    # Payload & Routing Guardrails
    MAX_AUDIO_BYTES: int = 150_000_000  # 150 MB ceiling for client uploads (supports up to ~2.5 hours in original quality)
    GROQ_CHUNK_SIZE_LIMIT: int = 19_000_000  # 19 MB single-chunk ceiling for Groq Whisper
    GROQ_CHUNK_DURATION_SECONDS: int = 600  # 10 minutes (600s) per chunk slice for seamless transcription
    ROUTER_TIMEOUT_SECONDS: int = 180   # Explicit 180s timeout boundary for long lecture synthesis
    
    # Fair Usage Policy Defaults (in seconds)
    DEFAULT_FREE_FUP_LIMIT: int = 10800    # 3 Hours = 10,800s
    DEFAULT_PRO_FUP_LIMIT: int = 144000    # 40 Hours = 144,000s

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )


settings = Settings()
