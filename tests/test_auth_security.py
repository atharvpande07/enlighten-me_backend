import uuid
from datetime import timedelta
import pytest
from starlette.testclient import TestClient
from fastapi import APIRouter, Depends
from app.core.security import get_current_user_id, create_mock_jwt
from app.main import app

# Create a temporary protected router to test auth dependency
test_router = APIRouter()

@test_router.get("/api/v1/test-protected")
def protected_route(user_id: str = Depends(get_current_user_id)):
    return {"message": "authorized", "user_id": user_id}

app.include_router(test_router)


def test_missing_auth_header(client: TestClient):
    response = client.get("/api/v1/test-protected")
    assert response.status_code == 401
    assert "Missing Authorization" in response.json()["detail"]


def test_invalid_jwt_token(client: TestClient):
    headers = {"Authorization": "Bearer invalid.token.signature"}
    response = client.get("/api/v1/test-protected", headers=headers)
    assert response.status_code == 401
    assert "Invalid or expired" in response.json()["detail"]


def test_expired_jwt_token(client: TestClient):
    user_id = str(uuid.uuid4())
    expired_token = create_mock_jwt(user_id, expires_delta=timedelta(hours=-1))
    headers = {"Authorization": f"Bearer {expired_token}"}
    response = client.get("/api/v1/test-protected", headers=headers)
    assert response.status_code == 401


def test_valid_jwt_token(client: TestClient):
    user_id = str(uuid.uuid4())
    valid_token = create_mock_jwt(user_id, expires_delta=timedelta(hours=2))
    headers = {"Authorization": f"Bearer {valid_token}"}
    response = client.get("/api/v1/test-protected", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "authorized"
    assert data["user_id"] == user_id
