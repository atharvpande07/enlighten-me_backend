import json
from typing import List, Dict, Any, Optional
from google import genai
from google.genai import types
from fastapi import HTTPException, status
from app.core.config import settings
from app.core.logging import logger
from app.schemas.study_guide import StudyGuideContent, TimelineItem, ActionItem

GEMINI_SYSTEM_INSTRUCTION = """
You are an expert academic curriculum architect and multi-lingual technical scholar for 'Enlighten Me'.
You specialize in processing Indian university classroom recordings where the lecturer code-switches
between English, Hindi, and Marathi (Hinglish/Marathi).

YOUR OBJECTIVES:
1. THE AI QUALITY GATE:
   - Carefully evaluate the transcript intelligibility.
   - If the transcript is pure static, ambient noise, meaningless chatter, or inaudible, set:
     * is_valid_lecture = false
     * warning_banner = "Unusable audio: The recording was unintelligible or muffled. Please sit closer to the speaker for your next lecture."
     * overall_summary = "No clear academic lecture was detected in this recording."
     * timestamped_timeline = []
     * chronological_notes = []
     * action_items = []
     * whatsapp_share_text = "⚠️ Lecture note generation failed due to low/inaudible audio quality."
   - If the audio is partially clear but has significant dropouts or static sections, set:
     * is_valid_lecture = true
     * warning_banner = "Partial summary generated: Audio quality was low in certain sections of this lecture."
   - If the audio is clear and audible, set:
     * is_valid_lecture = true
     * warning_banner = null

2. TRANSLATION & NORMALIZATION:
   - Convert all informal, phonetic Hinglish/Marathi explanations into rigorous, clear, professional Academic English.
   - Preserve technical terminology, equations, theorems, and definitions accurately.

3. SUBJECT RELEVANCE & OFF-TOPIC RANT DETECTION:
   - You are provided with the student's inputted Subject / Lecture Title.
   - Cross-reference the professor's explanations against this subject.
   - Indian university professors frequently go on off-topic tangents, anecdotes, or rants that are completely unrelated to the academic curriculum (e.g., personal complaints, scolding the class on discipline/attendance, hostel/canteen food, administrative grievances, politics, cricket, Bollywood movies, or unrelated personal stories).
   - In 'overall_summary':
     * Provide a comprehensive, high-yield academic synthesis of the legitimate subject curriculum taught.
     * At the end of 'overall_summary', you MUST append a specific, dedicated section:
       "**Off-Topic Rants & Tangents:** <Describe precisely what the professor ranted about and why it was unrelated to the subject. Summarize the digression so the student is aware of it>".
     * If no off-topic tangents or rants occurred and the lecture stayed on topic throughout, explicitly write:
       "**Off-Topic Rants & Tangents:** None detected; the lecture remained focused on the subject."
   - In 'chronological_notes':
     * STRICTLY EXCLUDE all off-topic rants, scoldings, and personal anecdotes.
     * The study notes MUST contain ONLY curriculum-relevant concepts, definitions, derivations, formulas, and technical takeaways. Keep notes 100% academic and high-yield so students can study without distraction.
   - In 'timestamped_timeline':
     * If an entire segment was an off-topic rant or tangent, tag the topic with "[Off-Topic Tangent]" (e.g., "[Off-Topic Tangent] Professor rant on canteen food and discipline") and summarize it briefly as non-academic.

4. STRUCTURED EXTRACTIONS:
   - overall_summary: A comprehensive, cohesive academic synthesis of all topics taught, concluding with the '**Off-Topic Rants & Tangents:**' section.
   - timestamped_timeline: Array of entries with timestamp_start, timestamp_end, topic, and summary.
   - chronological_notes: Formatted markdown bullet points detailing core concepts, formulas, and definitions (strictly academic).
   - action_items: MUST strictly categorize each item as one of: 'exam_hint', 'assignment', 'deadline', or 'reading'.
   - whatsapp_share_text: Formatted viral study summary designed for student WhatsApp study groups (use bolding and emojis, e.g. ⚠️ for exam hints, 📅 for deadlines, 📚 for readings).
"""


class GeminiStructuringService:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.client = genai.Client(api_key=self.api_key)

    async def structure_lecture(
        self,
        segments: List[Dict[str, Any]],
        lecture_title: Optional[str] = None,
    ) -> StudyGuideContent:
        """Passes transcript segments to Gemini 2.5 Flash to enforce the Quality Gate and synthesize the Study Guide."""
        # Immediate Quality Gate: If no transcript segments or empty text
        total_text = " ".join(seg.get("text", "") for seg in segments).strip()
        if not total_text or len(total_text) < 15:
            logger.warning("Quality Gate failed early: Insufficient transcript text (%d chars).", len(total_text))
            return StudyGuideContent(
                is_valid_lecture=False,
                warning_banner="Unusable audio: The recording was unintelligible or muffled. Please sit closer to the speaker for your next lecture.",
                overall_summary="No clear academic lecture was detected in this recording.",
                timestamped_timeline=[],
                chronological_notes=[],
                action_items=[],
                whatsapp_share_text="⚠️ Lecture note generation failed due to low/inaudible audio quality.",
            )

        # Build formatted transcript prompt with timestamp anchors
        formatted_transcript_lines = []
        for seg in segments:
            t_start = seg.get("timestamp_start", "00:00")
            t_end = seg.get("timestamp_end", "00:00")
            text = seg.get("text", "")
            formatted_transcript_lines.append(f"[{t_start} - {t_end}] {text}")
        
        full_transcript = "\n".join(formatted_transcript_lines)
        user_prompt = (
            f"Subject / Lecture Title (Inputted by Student): {lecture_title or 'Untitled Lecture'}\n\n"
            f"Instructions:\n"
            f"1. Evaluate the transcript against the specified Subject Title.\n"
            f"2. Identify any off-topic professor rants, discipline scoldings, or personal tangents.\n"
            f"3. In 'overall_summary', synthesize the academic lecture and explicitly state the off-topic rants under '**Off-Topic Rants & Tangents:**'.\n"
            f"4. In 'chronological_notes', strictly exclude non-academic rants so notes remain 100% exam-focused.\n\n"
            f"Raw Transcript Segments:\n{full_transcript}"
        )

        logger.info("Passing %d transcript segments to Gemini (%s) for structuring...", len(segments), settings.GEMINI_MODEL)

        config = types.GenerateContentConfig(
            system_instruction=GEMINI_SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=StudyGuideContent,
            temperature=0.2,
        )

        response = None
        models_to_try = [settings.GEMINI_MODEL]
        if settings.GEMINI_FALLBACK_MODEL and settings.GEMINI_FALLBACK_MODEL != settings.GEMINI_MODEL:
            models_to_try.append(settings.GEMINI_FALLBACK_MODEL)

        last_error = None
        for model_name in models_to_try:
            try:
                response = await self.client.aio.models.generate_content(
                    model=model_name,
                    contents=user_prompt,
                    config=config,
                )
                um = getattr(response, "usage_metadata", None)
                if um:
                    p_tok = getattr(um, "prompt_token_count", 0)
                    c_tok = getattr(um, "candidates_token_count", 0)
                    t_tok = getattr(um, "total_token_count", 0)
                    logger.info(
                        "Gemini Usage: Model=%s | Prompt Tokens=%d | Output Tokens=%d | Total Tokens=%d",
                        model_name, p_tok, c_tok, t_tok
                    )
                else:
                    logger.info("Structuring succeeded using Gemini model: %s", model_name)
                break
            except Exception as err:
                last_error = err
                logger.warning("Gemini model %s failed: %s. Attempting fallback if available...", model_name, str(err))

        if not response:
            logger.error("All Gemini structuring attempts failed: %s", str(last_error))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Semantic structuring failed via Gemini AI: {str(last_error)}",
            )

        try:
            # Parse returned JSON
            raw_json = response.text
            data = json.loads(raw_json)
            study_guide = StudyGuideContent(**data)
            logger.info("Gemini structuring complete. Valid lecture: %s", study_guide.is_valid_lecture)
            return study_guide
        except Exception as parse_err:
            logger.error("Failed to parse Gemini structured response: %s", str(parse_err))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Semantic structuring output validation error: {str(parse_err)}",
            )
