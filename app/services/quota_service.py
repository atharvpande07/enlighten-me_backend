from typing import Optional, Dict, Any
from fastapi import HTTPException, status
from app.core.config import settings
from app.core.logging import logger
from app.db.supabase_client import get_supabase_admin_client


class QuotaService:
    @staticmethod
    def get_or_create_subscription(user_id: str, db_client=None) -> Dict[str, Any]:
        """Fetches the user's subscription record or creates a default Free Tier record if absent."""
        client = db_client or get_supabase_admin_client()
        
        try:
            response = client.table("subscriptions").select("*").eq("user_id", user_id).execute()
            if response.data and len(response.data) > 0:
                return response.data[0]

            # Provision default Free Tier row if not present
            logger.info("Provisioning initial Free Tier subscription for user: %s", user_id)
            insert_data = {
                "user_id": user_id,
                "revenuecat_app_user_id": user_id,
                "status": "FREE",
                "plan_tier": "FREE_TIER",
                "fup_seconds_limit": settings.DEFAULT_FREE_FUP_LIMIT,
                "fup_seconds_used": 0,
            }
            res = client.table("subscriptions").insert(insert_data).execute()
            return res.data[0]
        except Exception as err:
            logger.error("Error retrieving or creating subscription for user %s: %s", user_id, str(err))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error while verifying user subscription quota.",
            )

    @staticmethod
    def validate_fup_quota(user_id: str, duration_seconds: int, db_client=None) -> Dict[str, Any]:
        """Validates that adding duration_seconds does not exceed the user's monthly FUP limit.
        
        Raises HTTP 403 Forbidden with FUP_EXCEEDED error code if the limit would be breached.
        """
        subscription = QuotaService.get_or_create_subscription(user_id, db_client=db_client)
        limit = subscription.get("fup_seconds_limit", settings.DEFAULT_FREE_FUP_LIMIT)
        used = subscription.get("fup_seconds_used", 0)

        projected_used = used + duration_seconds
        if projected_used > limit:
            remaining = max(0, limit - used)
            logger.warning(
                "FUP quota exceeded for user %s. Attempted: %ds, Available: %ds (Limit: %ds, Used: %ds)",
                user_id, duration_seconds, remaining, limit, used
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error_code": "FUP_EXCEEDED",
                    "detail": "You have exhausted your lecture processing quota this month.",
                },
            )

        remaining_fup_seconds = limit - projected_used
        return {
            "is_allowed": True,
            "fup_seconds_limit": limit,
            "fup_seconds_used": used,
            "projected_fup_seconds": projected_used,
            "remaining_fup_seconds": remaining_fup_seconds,
            "plan_tier": subscription.get("plan_tier", "FREE_TIER"),
        }

    @staticmethod
    def deduct_fup_quota(user_id: str, duration_seconds: int, db_client=None) -> int:
        """Atomically increments the user's fup_seconds_used and returns the remaining quota in seconds."""
        client = db_client or get_supabase_admin_client()
        sub = QuotaService.get_or_create_subscription(user_id, db_client=client)

        limit = sub.get("fup_seconds_limit", settings.DEFAULT_FREE_FUP_LIMIT)
        new_used = sub.get("fup_seconds_used", 0) + duration_seconds

        try:
            client.table("subscriptions").update({"fup_seconds_used": new_used}).eq("user_id", user_id).execute()
            remaining = max(0, limit - new_used)
            logger.info("Deducted %ds from user %s. Remaining quota: %ds", duration_seconds, user_id, remaining)
            return remaining
        except Exception as err:
            logger.error("Failed to deduct FUP seconds for user %s: %s", user_id, str(err))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to record lecture duration against Fair Usage Policy quota.",
            )
