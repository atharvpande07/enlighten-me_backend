import secrets
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header, status
from app.core.config import settings
from app.core.logging import logger
from app.schemas.webhook import RevenueCatWebhookPayload, WebhookResponse
from app.services.subscription_service import SubscriptionService

router = APIRouter()


async def verify_revenuecat_webhook_secret(
    authorization: Optional[str] = Header(None, description="Bearer <WEBHOOK_SECRET_KEY>"),
) -> bool:
    """Validates the incoming RevenueCat server-to-server webhook Authorization header."""
    if not authorization:
        logger.warning("Rejected RevenueCat webhook request: Missing Authorization header.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header with webhook secret.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer":
        logger.warning("Rejected RevenueCat webhook request: Malformed Authorization header.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed Authorization header. Format: Bearer <WEBHOOK_SECRET_KEY>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    provided_secret = parts[1]
    expected_secret = settings.REVENUECAT_WEBHOOK_SECRET

    # Constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(provided_secret, expected_secret):
        logger.warning("Rejected RevenueCat webhook request: Invalid secret key provided.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid RevenueCat webhook secret key.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return True


@router.post(
    "/webhooks/revenuecat",
    response_model=WebhookResponse,
    status_code=status.HTTP_200_OK,
    summary="RevenueCat Subscription Sync Webhook",
    description=(
        "Silent server-to-server endpoint receiving automated billing events from RevenueCat. "
        "Upon INITIAL_PURCHASE or RENEWAL of PRO_MONTHLY_399, resets FUP usage to 0 and raises "
        "quota to 144,000s (40 hours)."
    ),
)
async def revenuecat_subscription_webhook(
    payload: RevenueCatWebhookPayload,
    authenticated: bool = Depends(verify_revenuecat_webhook_secret),
):
    event = payload.event
    user_id = event.app_user_id or event.original_app_user_id or "unknown"
    logger.info("Received authenticated RevenueCat event: %s for user: %s", event.type, user_id)

    try:
        result = SubscriptionService.handle_revenuecat_event(event)
        return WebhookResponse(
            status="received",
            event_type=event.type,
            app_user_id=user_id,
            message=f"Event processed successfully: {result.get('action')}",
        )
    except Exception as err:
        logger.error("Failed to process RevenueCat webhook event: %s", str(err))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error executing subscription sync: {str(err)}",
        )
