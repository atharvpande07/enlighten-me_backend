import io
import uuid
from unittest.mock import patch, MagicMock, AsyncMock
import pytest
from starlette.testclient import TestClient
from app.core.security import create_mock_jwt
from app.schemas.study_guide import StudyGuideContent, TimelineItem, ActionItem


def test_process_lecture_unauthorized(client: TestClient):
    """Assert missing JWT returns 401."""
    files = {"audio_file": ("lecture.m4a", b"dummy audio content", "audio/mp4")}
    data = {"duration_seconds": 1800}
    response = client.post("/api/v1/lectures/process", data=data, files=files)
    assert response.status_code == 401


def test_process_lecture_payload_too_large(client: TestClient):
    """Assert audio payload exceeding 24MB returns 413 Payload Too Large."""
    user_id = str(uuid.uuid4())
    token = create_mock_jwt(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    # Generate oversized payload > 24MB
    oversized_bytes = b"0" * (24_000_001)
    files = {"audio_file": ("oversized.m4a", oversized_bytes, "audio/mp4")}
    data = {"duration_seconds": 1800}

    with patch("app.services.quota_service.QuotaService.validate_fup_quota") as mock_quota:
        mock_quota.return_value = {"is_allowed": True}
        response = client.post("/api/v1/lectures/process", data=data, files=files, headers=headers)
        assert response.status_code == 413
        assert response.json()["detail"] == "Audio file exceeds 24MB limit."


def test_process_lecture_fup_exceeded(client: TestClient):
    """Assert user exceeding monthly FUP limit returns 403 Forbidden with FUP_EXCEEDED."""
    user_id = str(uuid.uuid4())
    token = create_mock_jwt(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    files = {"audio_file": ("lecture.m4a", b"valid audio data", "audio/mp4")}
    data = {"duration_seconds": 3600}

    from fastapi import HTTPException
    with patch("app.services.quota_service.QuotaService.validate_fup_quota") as mock_quota:
        mock_quota.side_effect = HTTPException(
            status_code=403,
            detail={
                "error_code": "FUP_EXCEEDED",
                "detail": "You have exhausted your lecture processing quota this month.",
            },
        )
        response = client.post("/api/v1/lectures/process", data=data, files=files, headers=headers)
        assert response.status_code == 403
        data = response.json()["detail"]
        assert data["error_code"] == "FUP_EXCEEDED"


def test_process_lecture_successful_pipeline(client: TestClient):
    """Assert successful 200 OK end-to-end processing pipeline matching the Master API Contract."""
    user_id = str(uuid.uuid4())
    token = create_mock_jwt(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    files = {"audio_file": ("os_lecture.m4a", b"fake audio binary bytes 16kHz mono 32kbps", "audio/mp4")}
    data = {"duration_seconds": 3420}

    mock_segments = [
        {
            "start_seconds": 135.0,
            "end_seconds": 870.0,
            "timestamp_start": "02:15",
            "timestamp_end": "14:30",
            "text": "Today we discuss the four conditions of Coffman Deadlock. Mutual Exclusion and Hold and wait.",
        }
    ]

    mock_study_guide = StudyGuideContent(
        is_valid_lecture=True,
        warning_banner="Partial summary generated: Audio quality was low in sections 12:00–35:00.",
        overall_summary="This lecture covered race conditions and mutex locks.",
        timestamped_timeline=[
            TimelineItem(
                timestamp_start="02:15",
                timestamp_end="14:30",
                topic="Four Conditions of Coffman Deadlock",
                summary="Detailed explanation of Mutual Exclusion and Hold and Wait.",
            )
        ],
        chronological_notes=[
            "A Mutex is a locking mechanism used to synchronize access."
        ],
        action_items=[
            ActionItem(
                category="exam_hint",
                detail="Coffman conditions are a guaranteed 5-mark question.",
                approximate_timestamp="12:40",
            )
        ],
        whatsapp_share_text="*Operating Systems*\n\n*Exam Hints:*\n⚠️ Coffman conditions 5-mark question (12:40)",
    )

    fake_lecture_id = "7a3e8b82-6228-4fbb-a128-4e5cb5bdfb04"

    with patch("app.services.quota_service.QuotaService.validate_fup_quota") as mock_validate, \
         patch("app.services.groq_transcription.GroqTranscriptionService.transcribe_audio", new_callable=AsyncMock) as mock_groq, \
         patch("app.services.gemini_structuring.GeminiStructuringService.structure_lecture", new_callable=AsyncMock) as mock_gemini, \
         patch("app.services.lecture_service.LectureService.persist_lecture_and_study_guide") as mock_persist, \
         patch("app.services.quota_service.QuotaService.deduct_fup_quota") as mock_deduct:

        mock_validate.return_value = {"is_allowed": True}
        mock_groq.return_value = mock_segments
        mock_gemini.return_value = mock_study_guide
        mock_persist.return_value = fake_lecture_id
        mock_deduct.return_value = 124580

        response = client.post("/api/v1/lectures/process", data=data, files=files, headers=headers)
        assert response.status_code == 200

        res_json = response.json()
        assert res_json["lecture_id"] == fake_lecture_id
        assert res_json["remaining_fup_seconds"] == 124580

        sg = res_json["study_guide"]
        assert sg["is_valid_lecture"] is True
        assert "Audio quality was low" in sg["warning_banner"]
        assert sg["overall_summary"] == "This lecture covered race conditions and mutex locks."
        assert len(sg["timestamped_timeline"]) == 1
        assert sg["timestamped_timeline"][0]["topic"] == "Four Conditions of Coffman Deadlock"
        assert len(sg["chronological_notes"]) == 1
        assert len(sg["action_items"]) == 1
        assert sg["action_items"][0]["category"] == "exam_hint"
        assert sg["action_items"][0]["approximate_timestamp"] == "12:40"
        assert "*Operating Systems*" in sg["whatsapp_share_text"]


def test_quality_gate_rejection(client: TestClient):
    """Assert Quality Gate rejection returns valid schema with is_valid_lecture=false."""
    user_id = str(uuid.uuid4())
    token = create_mock_jwt(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    files = {"audio_file": ("static_noise.m4a", b"static hiss sound", "audio/mp4")}
    data = {"duration_seconds": 600}

    # Empty segments simulate unintelligible noise
    mock_empty_segments = []

    with patch("app.services.quota_service.QuotaService.validate_fup_quota"), \
         patch("app.services.groq_transcription.GroqTranscriptionService.transcribe_audio", new_callable=AsyncMock) as mock_groq, \
         patch("app.services.lecture_service.LectureService.persist_lecture_and_study_guide") as mock_persist, \
         patch("app.services.quota_service.QuotaService.deduct_fup_quota") as mock_deduct:

        mock_groq.return_value = mock_empty_segments
        mock_persist.return_value = "dummy-uuid"
        mock_deduct.return_value = 10000

        response = client.post("/api/v1/lectures/process", data=data, files=files, headers=headers)
        assert response.status_code == 200
        res_json = response.json()
        assert res_json["study_guide"]["is_valid_lecture"] is False
        assert "Unusable audio" in res_json["study_guide"]["warning_banner"]
