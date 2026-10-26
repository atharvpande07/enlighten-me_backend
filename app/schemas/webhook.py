from typing import Optional, List
from pydantic import BaseModel, Field


class RevenueCatEvent(BaseModel):
    type: str = Field(..., description="RevenueCat event type (e.g., INITIAL_PURCHASE, RENEWAL, CANCELLATION, EXPIRATION)")
    id: Optional[str] = Field(None, description="Unique event identifier")
    app_user_id: str = Field(..., description="The user identifier matching the student's Supabase auth UUID")
    original_app_user_id: Optional[str] = Field(None, description="The initial app user ID before aliases")
    entitlement_id: Optional[str] = Field(None, description="Active entitlement (e.g., PRO_MONTHLY_399)")
    entitlement_ids: Optional[List[str]] = Field(default_factory=list, description="List of all active entitlements")
    product_id: Optional[str] = Field(None, description="App Store or Play Store product ID")
    period_type: Optional[str] = Field(None, description="TRIAL, INTRO, or NORMAL")
    purchased_at_ms: Optional[int] = Field(None, description="Purchase timestamp in milliseconds")
    expiration_at_ms: Optional[int] = Field(None, description="Expiration timestamp in milliseconds")
    environment: Optional[str] = Field(None, description="SANDBOX or PRODUCTION")


class RevenueCatWebhookPayload(BaseModel):
    api_version: Optional[str] = Field("1.0", description="RevenueCat webhook API version")
    event: RevenueCatEvent = Field(..., description="Detailed event object")


class WebhookResponse(BaseModel):
    status: str = Field("received", description="Acknowledgment status")
    event_type: str = Field(..., description="Processed event type")
    app_user_id: str = Field(..., description="Target user identifier")
    message: str = Field(..., description="Summary of action taken")
