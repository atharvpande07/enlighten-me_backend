from typing import List, Dict, Any, Optional
from groq import AsyncGroq
from fastapi import HTTPException, status
from app.core.config import settings
from app.core.logging import logger

INITIAL_PROMPT = (
    "Indian university classroom lecture. The professor is speaking from the front of the hall in a mix of "
    "English, Hindi, and Marathi (Hinglish/Marathi). Ignore background ceiling fan hum, room echo, and distant acoustics. "
    "Focus on vocabulary, understand topics: "
    "Ye concept samajh aaya? Next point bagha."
)


def format_seconds_to_timestamp(seconds: float) -> str:
    """Helper to convert floating point seconds to MM:SS or HH:MM:SS timestamp strings."""
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class GroqTranscriptionService:
    def __init__(self, api_key: Optional[str] = None):
        self.client = AsyncGroq(api_key=api_key or settings.GROQ_API_KEY)

    async def transcribe_audio(
        self,
        audio_bytes: bytes,
        filename: str = "lecture.m4a",
    ) -> List[Dict[str, Any]]:
        """Sends audio bytes directly in-memory to Groq Whisper Large V3 Turbo.
        
        Zero disk persistence is performed. Audio is flushed from RAM after this operation.
        """
        if len(audio_bytes) > settings.MAX_AUDIO_BYTES:
            logger.warning("Audio payload exceeded limit: %d bytes", len(audio_bytes))
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Audio file exceeds 24MB limit.",
            )

        groq_model = getattr(settings, "GROQ_MODEL", "whisper-large-v3-turbo")
        logger.info(
            "Dispatching %d bytes of compressed audio in-memory to Groq (%s)...",
            len(audio_bytes),
            groq_model
        )

        try:
            transcription = await self.client.audio.transcriptions.create(
                file=(filename, audio_bytes),
                model=groq_model,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
                prompt=INITIAL_PROMPT,
                temperature=0.0,
            )
            
            raw_segments = getattr(transcription, "segments", []) or []
            duration_sec = getattr(transcription, "duration", None)
            duration_str = f"{duration_sec:.2f}s ({(duration_sec/60):.2f} mins)" if isinstance(duration_sec, (int, float)) else "N/A"
            normalized_segments: List[Dict[str, Any]] = []

            for seg in raw_segments:
                start = getattr(seg, "start", 0.0) if hasattr(seg, "start") else seg.get("start", 0.0)
                end = getattr(seg, "end", 0.0) if hasattr(seg, "end") else seg.get("end", 0.0)
                text = getattr(seg, "text", "") if hasattr(seg, "text") else seg.get("text", "")

                normalized_segments.append({
                    "start_seconds": start,
                    "end_seconds": end,
                    "timestamp_start": format_seconds_to_timestamp(start),
                    "timestamp_end": format_seconds_to_timestamp(end),
                    "text": text.strip(),
                })

            logger.info(
                "Groq Transcription Usage: Model=%s | Audio Duration=%s | Segments Extracted=%d",
                groq_model,
                duration_str,
                len(normalized_segments)
            )
            return normalized_segments

        except HTTPException:
            raise
        except Exception as err:
            logger.error("Groq Whisper API transcription error: %s", str(err))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Speech transcription failed via Groq API: {str(err)}",
            )
