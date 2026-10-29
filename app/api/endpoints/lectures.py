from typing import Optional
from fastapi import APIRouter, Depends, Form, File, UploadFile, HTTPException, status
from app.core.config import settings
from app.core.logging import logger
from app.core.security import get_current_user_id
from app.schemas.study_guide import LectureProcessResponse
from app.services.quota_service import QuotaService
from app.services.audio_cleaner import AudioCleanerService
from app.services.groq_transcription import GroqTranscriptionService
from app.services.gemini_structuring import GeminiStructuringService
from app.services.lecture_service import LectureService

router = APIRouter()


@router.post(
    "/lectures/process",
    response_model=LectureProcessResponse,
    status_code=status.HTTP_200_OK,
    summary="Core Audio Processing Pipeline",
    description=(
        "Uploads pre-compressed hardware-filtered audio, blocks while Groq and Gemini process "
        "in-memory, and returns the final structured study guide."
    ),
)
async def process_lecture(
    duration_seconds: int = Form(..., ge=1, description="Total recording duration in seconds"),
    audio_file: UploadFile = File(..., description="Audio file binary (.m4a, 16kHz mono, 32kbps)"),
    user_id: str = Depends(get_current_user_id),
):
    # 1. Payload Size Validation Guard (Groq 24MB ceiling)
    # Check Content-Length header or file size if available prior to buffer read
    if audio_file.size and audio_file.size > settings.MAX_AUDIO_BYTES:
        logger.warning("Upload rejected: Audio file size %d exceeds 24MB", audio_file.size)
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Audio file exceeds 24MB limit.",
        )

    # 2. Fair Usage Policy (FUP) Atomic Verification
    logger.info("Verifying FUP quota for user %s (attempted: %ds)...", user_id, duration_seconds)
    QuotaService.validate_fup_quota(user_id, duration_seconds)

    # 3. Read Binary Stream In-Memory (Zero Disk Write Policy)
    audio_bytes = await audio_file.read()
    if len(audio_bytes) > settings.MAX_AUDIO_BYTES:
        logger.warning("Upload rejected: Read %d bytes exceeding 24MB limit", len(audio_bytes))
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Audio file exceeds 24MB limit.",
        )

    if len(audio_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded audio file is empty (0 bytes).",
        )

    try:
        # 3.5 Automated In-Memory Classroom Noise Filtering (High-pass fan cutoff & speech normalization)
        clean_bytes, clean_filename = await AudioCleanerService.clean_and_normalize(
            audio_bytes,
            original_filename=audio_file.filename or "lecture.m4a",
        )

        # 4. In-Memory Groq Transcription (Whisper Large V3 Turbo)
        groq_service = GroqTranscriptionService()
        segments = await groq_service.transcribe_audio(
            clean_bytes,
            filename=clean_filename,
        )

        # 5. Flush audio bytes from memory immediately after transcription
        del audio_bytes
        del clean_bytes

        # 6. Gemini 2.5 Flash Structuring & Quality Gate
        gemini_service = GeminiStructuringService()
        study_guide = await gemini_service.structure_lecture(
            segments=segments,
            lecture_title=audio_file.filename,
        )

        # 7. Persist to Supabase PostgreSQL (Lectures & Study Notes)
        lecture_id = LectureService.persist_lecture_and_study_guide(
            user_id=user_id,
            duration_seconds=duration_seconds,
            study_guide=study_guide,
        )

        # 8. Deduct FUP Quota
        remaining_fup_seconds = QuotaService.deduct_fup_quota(
            user_id=user_id,
            duration_seconds=duration_seconds,
        )

        logger.info("Successfully processed lecture %s for user %s. Remaining FUP: %ds", lecture_id, user_id, remaining_fup_seconds)

        return LectureProcessResponse(
            lecture_id=lecture_id,
            remaining_fup_seconds=remaining_fup_seconds,
            study_guide=study_guide,
        )

    except HTTPException:
        raise
    except Exception as err:
        logger.error("Unexpected error in lecture processing pipeline: %s", str(err))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal pipeline failure: {str(err)}",
        )
