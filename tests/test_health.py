from starlette.testclient import TestClient
from app.core.config import settings


def test_root_endpoint(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "version" in data


def test_health_check_endpoint(client: TestClient):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["max_audio_mb"] == round(settings.MAX_AUDIO_BYTES / (1024 * 1024), 2)
    assert data["timeout_seconds"] == settings.ROUTER_TIMEOUT_SECONDS
