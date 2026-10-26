import uuid
from typing import Optional, Dict, Any
from fastapi import HTTPException, status
from app.core.logging import logger
from app.db.supabase_client import get_supabase_admin_client
from app.schemas.study_guide import StudyGuideContent


class LectureService:
    @staticmethod
    def persist_lecture_and_study_guide(
        user_id: str,
        duration_seconds: int,
        study_guide: StudyGuideContent,
        title: Optional[str] = None,
        db_client=None,
    ) -> str:
        """Persists the processed lecture metadata and synthesized study guide to Supabase PostgreSQL."""
        client = db_client or get_supabase_admin_client()
        lecture_id = str(uuid.uuid4())
        lecture_title = title or (
            study_guide.overall_summary[:60] + "..." if study_guide.is_valid_lecture else "Untitled Recording"
        )

        try:
            # 1. Insert Lecture Metadata
            lecture_payload = {
                "id": lecture_id,
                "user_id": user_id,
                "title": lecture_title,
                "status": "COMPLETED" if study_guide.is_valid_lecture else "FAILED",
                "duration_seconds": duration_seconds,
            }
            client.table("lectures").insert(lecture_payload).execute()
            logger.info("Created lecture record: %s for user: %s", lecture_id, user_id)

            # 2. Insert Structured Study Notes
            study_notes_payload = {
                "lecture_id": lecture_id,
                "is_valid_lecture": study_guide.is_valid_lecture,
                "warning_banner": study_guide.warning_banner,
                "overall_summary": study_guide.overall_summary,
                "timestamped_timeline": [item.model_dump() for item in study_guide.timestamped_timeline],
                "chronological_notes": study_guide.chronological_notes,
                "action_items": [item.model_dump() for item in study_guide.action_items],
                "whatsapp_share_text": study_guide.whatsapp_share_text,
            }
            client.table("study_notes").insert(study_notes_payload).execute()
            logger.info("Persisted study notes for lecture: %s", lecture_id)

            return lecture_id

        except Exception as err:
            logger.error("Failed to persist lecture and study notes to database: %s", str(err))
            # Cleanup lecture row if study_notes insertion failed to prevent orphaned records
            try:
                client.table("lectures").delete().eq("id", lecture_id).execute()
            except Exception:
                pass
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database transaction failed while saving synthesized study guide.",
            )
