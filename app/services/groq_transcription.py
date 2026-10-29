import os
import shutil
import tempfile
import asyncio
import subprocess
from typing import List, Dict, Any, Optional, Tuple
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
    total_seconds = max(0, int(seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class GroqTranscriptionService:
    def __init__(self, api_key: Optional[str] = None):
        self.client = AsyncGroq(api_key=api_key or settings.GROQ_API_KEY)
        self.chunk_size_limit = getattr(settings, "GROQ_CHUNK_SIZE_LIMIT", 19_000_000)
        self.chunk_duration_sec = getattr(settings, "GROQ_CHUNK_DURATION_SECONDS", 600)

    async def transcribe_audio(
        self,
        audio_bytes: bytes,
        filename: str = "lecture.m4a",
    ) -> List[Dict[str, Any]]:
        """Transcribes audio using Groq Whisper Large V3 Turbo.
        
        Zero compression policy:
        - If the file is within Groq's 19MB boundary, it is dispatched in a single call.
        - If the file exceeds 19MB (e.g. 30-90 min lecture in original 128kbps quality),
          it is automatically sliced into 10-minute chunks without re-encoding, transcribed
          in chunks, and seamlessly merged with continuous timestamps.
        """
        if len(audio_bytes) > settings.MAX_AUDIO_BYTES:
            max_mb = round(settings.MAX_AUDIO_BYTES / (1024 * 1024))
            logger.warning("Audio payload exceeded upload limit: %d bytes (limit: %dMB)", len(audio_bytes), max_mb)
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Audio file exceeds {max_mb}MB limit.",
            )

        if len(audio_bytes) <= self.chunk_size_limit:
            # Single call path for audio under 19MB
            segments, _ = await self._transcribe_single_chunk(
                audio_bytes=audio_bytes,
                filename=filename,
                prompt=INITIAL_PROMPT,
                time_offset=0.0,
            )
            return segments

        # Chunked path for large/long original-quality lectures
        logger.info(
            "Audio payload (%d bytes) exceeds %d byte limit. Slicing into %ds chunks for Groq...",
            len(audio_bytes),
            self.chunk_size_limit,
            self.chunk_duration_sec,
        )
        return await self._transcribe_chunked_audio(audio_bytes, filename=filename)

    async def _transcribe_single_chunk(
        self,
        audio_bytes: bytes,
        filename: str,
        prompt: str,
        time_offset: float = 0.0,
    ) -> Tuple[List[Dict[str, Any]], float]:
        """Dispatches a single audio segment to Groq Whisper and offsets segment timestamps."""
        groq_model = getattr(settings, "GROQ_MODEL", "whisper-large-v3-turbo")
        logger.info(
            "Dispatching %d bytes to Groq (%s) [Offset: %.2fs]...",
            len(audio_bytes),
            groq_model,
            time_offset,
        )

        try:
            transcription = await self.client.audio.transcriptions.create(
                file=(filename, audio_bytes),
                model=groq_model,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
                prompt=prompt,
                temperature=0.0,
            )

            raw_segments = getattr(transcription, "segments", []) or []
            reported_duration = getattr(transcription, "duration", None)
            duration_sec = float(reported_duration) if reported_duration is not None else float(self.chunk_duration_sec)

            normalized_segments: List[Dict[str, Any]] = []
            for seg in raw_segments:
                raw_start = float(getattr(seg, "start", 0.0) if hasattr(seg, "start") else seg.get("start", 0.0))
                raw_end = float(getattr(seg, "end", 0.0) if hasattr(seg, "end") else seg.get("end", 0.0))
                text = str(getattr(seg, "text", "") if hasattr(seg, "text") else seg.get("text", "")).strip()

                start = round(raw_start + time_offset, 2)
                end = round(raw_end + time_offset, 2)

                normalized_segments.append({
                    "start_seconds": start,
                    "end_seconds": end,
                    "timestamp_start": format_seconds_to_timestamp(start),
                    "timestamp_end": format_seconds_to_timestamp(end),
                    "text": text,
                })

            logger.info(
                "Chunk Transcribed: Segments=%d | Chunk Duration=%.2fs | Total Offset Now=%.2fs",
                len(normalized_segments),
                duration_sec,
                time_offset + duration_sec,
            )
            return normalized_segments, duration_sec

        except HTTPException:
            raise
        except Exception as err:
            logger.error("Groq Whisper API chunk transcription error: %s", str(err))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Speech transcription failed via Groq API: {str(err)}",
            )

    async def _transcribe_chunked_audio(
        self,
        audio_bytes: bytes,
        filename: str = "lecture.m4a",
    ) -> List[Dict[str, Any]]:
        """Splits audio into slices using FFmpeg stream copy and merges transcripts."""
        if not shutil.which("ffmpeg"):
            logger.warning("[GroqTranscription] FFmpeg not found on host; attempting single chunk dispatch.")
            segments, _ = await self._transcribe_single_chunk(
                audio_bytes=audio_bytes,
                filename=filename,
                prompt=INITIAL_PROMPT,
                time_offset=0.0,
            )
            return segments

        # Run file I/O and FFmpeg segmentation in thread pool to avoid blocking async event loop
        chunk_results = await asyncio.to_thread(self._split_audio_into_chunks, audio_bytes, filename)
        if not chunk_results:
            logger.warning("[GroqTranscription] Segmentation produced no chunks; falling back to raw dispatch.")
            segments, _ = await self._transcribe_single_chunk(
                audio_bytes=audio_bytes,
                filename=filename,
                prompt=INITIAL_PROMPT,
                time_offset=0.0,
            )
            return segments

        all_segments: List[Dict[str, Any]] = []
        accumulated_offset = 0.0
        current_prompt = INITIAL_PROMPT

        for idx, (chunk_bytes, chunk_filename, probed_duration) in enumerate(chunk_results):
            logger.info(
                "[GroqTranscription] Processing chunk %d/%d (%d bytes, estimated duration: %.2fs)...",
                idx + 1,
                len(chunk_results),
                len(chunk_bytes),
                probed_duration,
            )

            chunk_segments, chunk_duration = await self._transcribe_single_chunk(
                audio_bytes=chunk_bytes,
                filename=chunk_filename,
                prompt=current_prompt,
                time_offset=accumulated_offset,
            )

            all_segments.extend(chunk_segments)

            # Advance offset by actual chunk duration (prefer reported Whisper duration or probed duration)
            effective_duration = chunk_duration if chunk_duration > 0 else probed_duration
            accumulated_offset += effective_duration

            # Provide continuity prompt to the next chunk using trailing text from this chunk
            if chunk_segments:
                trailing_text = " ".join(s["text"] for s in chunk_segments[-3:])[-200:]
                current_prompt = f"{INITIAL_PROMPT} Context: ...{trailing_text}"

        logger.info(
            "Completed multi-chunk transcription: Total Segments=%d | Total Duration=%.2fs (%.2f mins)",
            len(all_segments),
            accumulated_offset,
            accumulated_offset / 60,
        )
        return all_segments

    def _split_audio_into_chunks(
        self,
        audio_bytes: bytes,
        filename: str,
    ) -> List[Tuple[bytes, str, float]]:
        """Synchronously segments audio into chunks using FFmpeg stream copy."""
        ext = os.path.splitext(filename)[1] or ".m4a"
        chunk_data: List[Tuple[bytes, str, float]] = []

        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = os.path.join(tmp_dir, f"source{ext}")
            with open(input_path, "wb") as f:
                f.write(audio_bytes)

            chunk_pattern = os.path.join(tmp_dir, f"chunk_%03d{ext}")

            # 1. Attempt lossless stream copy first (instantaneous, zero quality loss)
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "error",
                "-y",
                "-i", input_path,
                "-f", "segment",
                "-segment_time", str(self.chunk_duration_sec),
                "-reset_timestamps", "1",
                "-c", "copy",
                chunk_pattern,
            ]

            proc = subprocess.run(cmd, capture_output=True)

            # 2. Fallback to AAC encoding if container cannot be copied directly
            if proc.returncode != 0:
                logger.warning(
                    "[GroqTranscription] Lossless copy chunking failed (%s); retrying with standard AAC container...",
                    proc.stderr.decode("utf-8", errors="ignore"),
                )
                chunk_pattern = os.path.join(tmp_dir, "chunk_%03d.m4a")
                fallback_cmd = [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel", "error",
                    "-y",
                    "-i", input_path,
                    "-f", "segment",
                    "-segment_time", str(self.chunk_duration_sec),
                    "-reset_timestamps", "1",
                    "-c:a", "aac",
                    "-b:a", "128k",
                    chunk_pattern,
                ]
                subprocess.run(fallback_cmd, capture_output=True, check=True)

            # 3. Read generated chunk files in sorted chronological order
            chunk_files = sorted(
                [f for f in os.listdir(tmp_dir) if f.startswith("chunk_") and (f.endswith(ext) or f.endswith(".m4a"))]
            )

            for c_file in chunk_files:
                c_path = os.path.join(tmp_dir, c_file)
                size = os.path.getsize(c_path)
                if size < 1000:
                    # Ignore tiny empty padding files
                    continue

                duration = self._probe_duration(c_path)
                if duration < 0.5:
                    continue

                with open(c_path, "rb") as cf:
                    chunk_bytes = cf.read()

                chunk_data.append((chunk_bytes, c_file, duration))

        return chunk_data

    @staticmethod
    def _probe_duration(file_path: str) -> float:
        """Probes audio duration in seconds using ffprobe."""
        if not shutil.which("ffprobe"):
            return 600.0
        try:
            res = subprocess.run(
                [
                    "ffprobe",
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    file_path,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            return float(res.stdout.strip())
        except Exception:
            return 600.0
