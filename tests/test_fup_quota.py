import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException
from app.services.quota_service import QuotaService


def test_quota_validation_success():
    # Mock subscription with 10,800s limit, 3,600s used (7,200s remaining)
    mock_sub = {
        "user_id": "test-user-1",
        "plan_tier": "FREE_TIER",
        "fup_seconds_limit": 10800,
        "fup_seconds_used": 3600,
    }
    
    mock_client = MagicMock()
    mock_client.table().select().eq().execute.return_value = MagicMock(data=[mock_sub])
    
    # Attempt a 1,800s (30m) lecture
    result = QuotaService.validate_fup_quota("test-user-1", 1800, db_client=mock_client)
    assert result["is_allowed"] is True
    assert result["remaining_fup_seconds"] == 5400  # 10800 - (3600 + 1800)
    assert result["fup_seconds_limit"] == 10800


def test_quota_validation_exceeded():
    # Mock subscription near limit: 10,800s limit, 10,000s used (800s remaining)
    mock_sub = {
        "user_id": "test-user-2",
        "plan_tier": "FREE_TIER",
        "fup_seconds_limit": 10800,
        "fup_seconds_used": 10000,
    }
    
    mock_client = MagicMock()
    mock_client.table().select().eq().execute.return_value = MagicMock(data=[mock_sub])
    
    # Attempt a 1,800s (30m) lecture, which exceeds the limit
    with pytest.raises(HTTPException) as exc_info:
        QuotaService.validate_fup_quota("test-user-2", 1800, db_client=mock_client)
        
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error_code"] == "FUP_EXCEEDED"
    assert "quota this month" in exc_info.value.detail["detail"]


def test_quota_deduction():
    mock_sub = {
        "user_id": "test-user-3",
        "plan_tier": "PRO",
        "fup_seconds_limit": 144000,
        "fup_seconds_used": 10000,
    }
    
    mock_client = MagicMock()
    mock_client.table().select().eq().execute.return_value = MagicMock(data=[mock_sub])
    mock_client.table().update().eq().execute.return_value = MagicMock(data=[{}])
    
    # Deduct 3,600s (1h)
    remaining = QuotaService.deduct_fup_quota("test-user-3", 3600, db_client=mock_client)
    # Remaining = 144,000 - (10,000 + 3,600) = 130,400
    assert remaining == 130400
    mock_client.table().update.assert_called_with({"fup_seconds_used": 13600})
