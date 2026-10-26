from typing import Optional
from supabase import create_client, Client
from app.core.config import settings
from app.core.logging import logger

_supabase_admin_client: Optional[Client] = None


def get_supabase_admin_client() -> Client:
    """Returns the singleton Supabase client authenticated with the Service Role key.
    
    This client bypasses RLS and is strictly intended for server-side trusted transactions
    such as FUP quota verification and RevenueCat billing sync.
    """
    global _supabase_admin_client
    if _supabase_admin_client is None:
        try:
            _supabase_admin_client = create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_SERVICE_ROLE_KEY,
            )
            logger.info("Initialized Supabase Service Role client.")
        except Exception as err:
            logger.error("Failed to initialize Supabase client: %s", str(err))
            raise
    return _supabase_admin_client
