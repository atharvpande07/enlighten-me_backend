from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from app.core.config import settings
from app.core.logging import logger

security_scheme = HTTPBearer(auto_error=False)


def decode_supabase_jwt(token: str) -> dict:
    """Decodes and validates a Supabase JWT token.
    
    1. First attempts local HS256 signature verification via SUPABASE_JWT_SECRET.
    2. If local verification fails or secret is unconfigured, falls back to Supabase Auth API verification.
    """
    # 1. Attempt local fast-path verification
    if settings.SUPABASE_JWT_SECRET and not settings.SUPABASE_JWT_SECRET.startswith("placeholder"):
        try:
            return jwt.decode(
                token,
                settings.SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                options={"verify_aud": False},  # Supabase aud defaults to 'authenticated'
            )
        except JWTError as err:
            logger.debug("Local JWT signature check failed: %s, checking Supabase Auth API...", str(err))

    # 2. Remote fallback verification via Supabase client
    try:
        from app.db.supabase_client import get_supabase_admin_client
        sb = get_supabase_admin_client()
        user_res = sb.auth.get_user(token)
        if user_res and user_res.user:
            return {
                "sub": str(user_res.user.id),
                "email": user_res.user.email,
                "role": "authenticated",
            }
    except Exception as api_err:
        logger.warning("Supabase Auth API token verification failed: %s", str(api_err))

    # 3. Development guest fallback for local testing
    if settings.DEBUG and token == "dev-guest-token":
        logger.info("Accepted dev-guest-token in DEBUG mode using student@enlightenme.dev test account.")
        return {
            "sub": "ca165e8e-ec4b-414c-88e2-5a27ad32e3b5",
            "email": "student@enlightenme.dev",
            "role": "authenticated",
        }

    logger.warning("Authentication failed: invalid token or unreachable auth provider.")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
) -> str:
    """FastAPI dependency to extract and verify the current authenticated user's ID from the JWT."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header with Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    payload = decode_supabase_jwt(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload is missing user subject identifier (sub).",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return str(user_id)


def create_mock_jwt(user_id: str, expires_delta: Optional[timedelta] = None) -> str:
    """Helper utility to generate mock Supabase-compatible JWTs for testing purposes."""
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=2))
    payload = {
        "sub": user_id,
        "role": "authenticated",
        "aud": "authenticated",
        "exp": int(expire.timestamp()),
        "iat": int(datetime.now(timezone.utc).timestamp()),
    }
    return jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")
