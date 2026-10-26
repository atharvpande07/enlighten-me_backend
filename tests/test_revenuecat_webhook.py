import uuid
from unittest.mock import patch, MagicMock
import pytest
from starlette.testclient import TestClient
from app.core.config import settings
from app.services.subscription_service import SubscriptionService, PRO_ENTITLEMENT_ID


def test_webhook_missing_auth(client: TestClient):
    payload = {
        "api_version": "1.0",
        "event": {
            "type": "INITIAL_PURCHASE",
            "app_user_id": str(uuid.uuid4()),
            "entitlement_id": PRO_ENTITLEMENT_ID,
        },
    }
    response = client.post("/api/v1/webhooks/revenuecat", json=payload)
    assert response.status_code == 401
    assert "Missing Authorization" in response.json()["detail"]


def test_webhook_invalid_secret(client: TestClient):
    payload = {
        "api_version": "1.0",
        "event": {
            "type": "INITIAL_PURCHASE",
            "app_user_id": str(uuid.uuid4()),
            "entitlement_id": PRO_ENTITLEMENT_ID,
        },
    }
    headers = {"Authorization": "Bearer wrong_secret_key"}
    response = client.post("/api/v1/webhooks/revenuecat", json=payload, headers=headers)
    assert response.status_code == 401
    assert "Invalid RevenueCat webhook secret" in response.json()["detail"]


def test_webhook_initial_purchase_pro_upgrade(client: TestClient):
    user_id = str(uuid.uuid4())
    payload = {
        "api_version": "1.0",
        "event": {
            "type": "INITIAL_PURCHASE",
            "id": "evt-123",
            "app_user_id": user_id,
            "entitlement_id": PRO_ENTITLEMENT_ID,
            "entitlement_ids": [PRO_ENTITLEMENT_ID],
            "product_id": "enlighten_pro_monthly_399",
            "expiration_at_ms": 1735689600000,
        },
    }
    headers = {"Authorization": f"Bearer {settings.REVENUECAT_WEBHOOK_SECRET}"}

    with patch("app.services.subscription_service.SubscriptionService.handle_revenuecat_event") as mock_handler:
        mock_handler.return_value = {
            "action": "UPGRADED_PRO",
            "plan_tier": "PRO",
            "fup_seconds_limit": 144000,
            "fup_seconds_used": 0,
            "user_id": user_id,
        }

        response = client.post("/api/v1/webhooks/revenuecat", json=payload, headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "received"
        assert data["event_type"] == "INITIAL_PURCHASE"
        assert data["app_user_id"] == user_id
        assert "UPGRADED_PRO" in data["message"]


def test_subscription_service_initial_purchase_db_logic():
    user_id = "test-user-pro-1"
    from app.schemas.webhook import RevenueCatEvent
    event = RevenueCatEvent(
        type="INITIAL_PURCHASE",
        app_user_id=user_id,
        entitlement_id=PRO_ENTITLEMENT_ID,
        entitlement_ids=[PRO_ENTITLEMENT_ID],
        expiration_at_ms=1735689600000,
    )

    mock_client = MagicMock()
    # Mock existing subscription found
    mock_client.table().select().eq().execute.return_value = MagicMock(data=[{"id": "sub-1"}])
    mock_client.table().update().eq().execute.return_value = MagicMock(data=[{}])

    result = SubscriptionService.handle_revenuecat_event(event, db_client=mock_client)
    assert result["action"] == "UPGRADED_PRO"
    assert result["plan_tier"] == "PRO"
    assert result["fup_seconds_limit"] == 144000
    assert result["fup_seconds_used"] == 0

    # Verify update called with reset quota
    call_args = mock_client.table().update.call_args[0][0]
    assert call_args["fup_seconds_used"] == 0
    assert call_args["fup_seconds_limit"] == 144000
    assert call_args["status"] == "ACTIVE"
    assert call_args["plan_tier"] == "PRO"


def test_subscription_service_renewal_db_logic():
    user_id = "test-user-pro-renewal"
    from app.schemas.webhook import RevenueCatEvent
    event = RevenueCatEvent(
        type="RENEWAL",
        app_user_id=user_id,
        entitlement_id=PRO_ENTITLEMENT_ID,
        entitlement_ids=[PRO_ENTITLEMENT_ID],
    )

    mock_client = MagicMock()
    mock_client.table().select().eq().execute.return_value = MagicMock(data=[{"id": "sub-2"}])
    mock_client.table().update().eq().execute.return_value = MagicMock(data=[{}])

    result = SubscriptionService.handle_revenuecat_event(event, db_client=mock_client)
    assert result["action"] == "UPGRADED_PRO"
    assert result["fup_seconds_used"] == 0
    assert result["fup_seconds_limit"] == 144000


def test_subscription_service_expiration_db_logic():
    user_id = "test-user-expired"
    from app.schemas.webhook import RevenueCatEvent
    event = RevenueCatEvent(
        type="EXPIRATION",
        app_user_id=user_id,
    )

    mock_client = MagicMock()
    mock_client.table().update().eq().execute.return_value = MagicMock(data=[{}])

    result = SubscriptionService.handle_revenuecat_event(event, db_client=mock_client)
    assert result["action"] == "DOWNGRADED_FREE"

    call_args = mock_client.table().update.call_args[0][0]
    assert call_args["status"] == "EXPIRED"
    assert call_args["plan_tier"] == "FREE_TIER"
    assert call_args["fup_seconds_limit"] == 10800  # Reset to 3 hours


def test_subscription_service_cancellation_db_logic():
    user_id = "test-user-canceled"
    from app.schemas.webhook import RevenueCatEvent
    event = RevenueCatEvent(
        type="CANCELLATION",
        app_user_id=user_id,
    )

    mock_client = MagicMock()
    mock_client.table().update().eq().execute.return_value = MagicMock(data=[{}])

    result = SubscriptionService.handle_revenuecat_event(event, db_client=mock_client)
    assert result["action"] == "CANCELED"

    call_args = mock_client.table().update.call_args[0][0]
    assert call_args["status"] == "CANCELED"
