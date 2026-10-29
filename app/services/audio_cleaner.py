import asyncio
import shutil
from app.core.logging import logger

FFMPEG_AUDIO_FILTERS = "highpass=f=180,lowpass=f=4000,afftdn=nf=-25,speechnorm=e=4:r=0.0001:l=1"


class AudioCleanerService:
    """
    Automated In-Memory Digital Signal Processing (DSP) for Indian University Classrooms:
    - High-Pass Filter (180 Hz): Eliminates 50Hz mains hum, ceiling fan blade rumble, and desk vibrations.
    - Low-Pass Filter (4000 Hz): Eliminates high-frequency fan bearing whine, hiss, and electrical noise.
    - Adaptive FFT Noise Reduction (afftdn): Subtracts stationary fan and ambient room noise.
    - Dynamic Speech Normalizer (speechnorm): Amplifies distant, quiet professor speech to clear levels.
    """

    @classmethod
    async def clean_and_normalize(cls, audio_bytes: bytes, original_filename: str = "lecture.m4a") -> tuple[bytes, str]:
        if not shutil.which("ffmpeg"):
            logger.warning("[AudioCleaner] FFmpeg binary not found on host; passing original audio directly.")
            return audio_bytes, original_filename

        if len(audio_bytes) < 1000:
            return audio_bytes, original_filename

        logger.info(
            "[AudioCleaner] Applying classroom noise-cancellation (highpass 180Hz, lowpass 4kHz, afftdn, speechnorm) to %d bytes...",
            len(audio_bytes)
        )

        try:
            # We pipe audio_bytes into ffmpeg stdin, apply voice enhancement filters, and output MP3 to stdout
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "error",
                "-i", "pipe:0",
                "-af", FFMPEG_AUDIO_FILTERS,
                "-ar", "16000",
                "-ac", "1",
                "-c:a", "libmp3lame",
                "-b:a", "32k",
                "-f", "mp3",
                "pipe:1",
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await proc.communicate(input=audio_bytes)

            if proc.returncode == 0 and len(stdout) > 500:
                logger.info(
                    "[AudioCleaner] Audio cleaned successfully: %d bytes -> %d bytes (Speech boosted, fan noise stripped).",
                    len(audio_bytes),
                    len(stdout),
                )
                return stdout, "cleaned_lecture.mp3"
            else:
                err_msg = stderr.decode("utf-8", errors="ignore")
                logger.warning(
                    "[AudioCleaner] FFmpeg returned non-zero code %d (%s); falling back to raw audio.",
                    proc.returncode,
                    err_msg,
                )
                return audio_bytes, original_filename

        except Exception as exc:
            logger.warning("[AudioCleaner] Audio cleanup exception: %s; falling back to raw audio.", str(exc))
            return audio_bytes, original_filename
