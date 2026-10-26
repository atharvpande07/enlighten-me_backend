from datetime import datetime, timezone
from typing import Optional, Dict, Any
from app.core.config import settings
from app.core.logging import logger
from app.db.supabase_client import get_supabase_admin_client
from app.schemas.webhook import RevenueCatEvent

PRO_ENTITLEMENT_ID = "PRO_MONTHLY_399"


class SubscriptionService:
    @staticmethod
    def handle_revenuecat_event(
        event: RevenueCatEvent,
        db_client=None,
    ) -> Dict[str, Any]:
        """Processes automated subscription webhook events from RevenueCat and syncs FUP quotas in Supabase."""
        client = db_client or get_supabase_admin_client()
        user_id = event.app_user_id or event.original_app_user_id

        # Determine entitlement status
        all_entitlements = set(event.entitlement_ids or [])
        if event.entitlement_id:
            all_entitlements.add(event.entitlement_id)
        
        is_pro = PRO_ENTITLEMENT_ID in all_entitlements or "pro" in all_entitlements

        event_type = event.type.upper()
        logger.info(
            "Processing RevenueCat webhook event: %s for user: %s (Entitlements: %s)",
            event_type, user_id, list(all_entitlements)
        )

        # Parse expiration date if provided
        period_end: Optional[str] = None
        if event.expiration_at_ms:
            dt = datetime.fromtimestamp(event.expiration_at_ms / 1000.0, tz=timezone.utc)
            period_end = dt.isoformat()

        # 1. INITIAL PURCHASE OR RENEWAL (Elevate to Pro & Reset FUP Usage)
        if event_type in ["INITIAL_PURCHASE", "RENEWAL"] and is_pro:
            update_payload = {
                "status": "ACTIVE",
                "plan_tier": "PRO",
                "fup_seconds_limit": settings.DEFAULT_PRO_FUP_LIMIT,  # 144,000s = 40 hours
                "fup_seconds_used": 0,                               # Full quota reset
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            if period_end:
                update_payload["current_period_end"] = period_end

            # Upsert into subscriptions table
            try:
                # Check if subscription row exists
                existing = client.table("subscriptions").select("id").eq("user_id", user_id).execute()
                if existing.data and len(existing.data) > 0:
                    client.table("subscriptions").update(update_payload).eq("user_id", user_id).execute()
                else:
                    insert_data = {
                        "user_id": user_id,
                        "revenuecat_app_user_id": user_id,
                        **update_payload,
                    }
                    client.table("subscriptions").insert(insert_data).execute()

                logger.info(
                    "FUP quota reset & upgraded to PRO for user %s: Limit=%ds, Used=0s",
                    user_id, settings.DEFAULT_PRO_FUP_LIMIT
                )
                return {
                    "action": "UPGRADED_PRO",
                    "plan_tier": "PRO",
                    "fup_seconds_limit": settings.DEFAULT_PRO_FUP_LIMIT,
                    "fup_seconds_used": 0,
                    "user_id": user_id,
                }
            except Exception as err:
                logger.error("Database update failed for RevenueCat event %s: %s", event_type, str(err))
                raise

        # 2. CANCELLATION (User canceled auto-renewal; remains active until period end)
        elif event_type == "CANCELLATION":
            try:
                client.table("subscriptions").update({
                    "status": "CANCELED",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("user_id", user_id).execute()

                logger.info("Subscription marked CANCELED for user %s (quota retained until expiry).", user_id)
                return {"action": "CANCELED", "user_id": user_id}
            except Exception as err:
                logger.error("Failed to mark subscription canceled for user %s: %s", user_id, str(err))
                raise

        # 3. EXPIRATION (Subscription expired; downgrade to Free Tier)
        elif event_type == "EXPIRATION":
            try:
                client.table("subscriptions").update({
                    "status": "EXPIRED",
                    "plan_tier": "FREE_TIER",
                    "fup_seconds_limit": settings.DEFAULT_FREE_FUP_LIMIT,  # Downgrade to 10,800s (3 hours)
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("user_id", user_id).execute()

                logger.info("Subscription EXPIRED for user %s: Downgraded to FREE_TIER (10,800s).", user_id)
                return {"action": "DOWNGRADED_FREE", "user_id": user_id}
            except Exception as err:
                logger.error("Failed to downgrade expired subscription for user %s: %s", user_id, str(err))
                raise

        # 4. OTHER / INFORMATIONAL EVENTS (e.g., TEST, BILLING_ISSUE, TRANSFER)
        else:
            logger.info("Acknowledged non-modifying RevenueCat event: %s for user %s", event_type, user_id)
            return {"action": "IGNORED", "event_type": event_type, "user_id": user_id}
