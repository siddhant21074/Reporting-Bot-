"""AI provider: speech-to-text and transcript structuring.

Both roles are configured independently (see ``app.ai.registry``) and every
network-backed provider speaks the OpenAI wire format, so one client class
serves OpenAI, OpenRouter, Groq, Together, DeepInfra, Ollama and any custom
compatible endpoint.

Every blocking call -- local Whisper inference, ffmpeg transcoding, the legacy
Google Web Speech request -- is pushed onto a worker thread with
``asyncio.to_thread`` so it never stalls the event loop.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol, Tuple

from openai import AsyncOpenAI

from app.ai.registry import provider_info
from app.ai.schemas import (
    ExtractedReport,
    FullProgressReport,
    IssueItem,
    NextDayPlanItem,
    ReportMetadata,
    ResourceItem,
    WorkSummaryItem,
)
from app.core.config import ModelSettings, settings

logger = logging.getLogger("app.ai.provider")

# Marks which path produced a report, so the dashboard can show AI success rate.
EXTRACTION_AI = "ai"
EXTRACTION_FALLBACK = "rule_based"


SYSTEM_INSTRUCTION = (
    "You are a professional report generation assistant that processes daily updates, voice notes, text messages, and meeting transcripts for ANY domain, project, industry, or topic.\n"
    "Your goal is to detect the context from the user's input and organize it into a structured, highly professional daily report.\n\n"
    "CORE MANDATORY RULES:\n"
    "1. STRICT INFORMATION PRESERVATION (ZERO-HALLUCINATION):\n"
    "   - Use ONLY information explicitly provided by the user.\n"
    "   - Do NOT invent, assume, fabricate, or extrapolate details, metrics, dates, or activities.\n"
    "   - You may organize, format, and polish grammar, but NEVER alter the meaning or insert unmentioned conclusions.\n"
    "   - If information for a field is not mentioned by the user, leave string fields as 'N/A' or lists as empty [].\n"
    "2. DOMAIN-AGNOSTIC ADAPTABILITY:\n"
    "   - Do NOT assume the project is construction-related unless explicitly stated by the user.\n"
    "   - Adapt to any field: Software Engineering, Sales, Healthcare, Marketing, Operations, Maintenance, General Business, etc.\n"
    "3. LANGUAGE & ENGLISH TRANSLATION:\n"
    "   - ALL OUTPUT FIELDS MUST BE GENERATED IN PROFESSIONAL ENGLISH.\n"
    "   - Even if the input is in Hindi, Hinglish, Marathi, Gujarati, or any other language, preserve exact facts and numbers while translating descriptions into clear, professional English.\n"
    "4. EXECUTIVE SUMMARY vs WORK SUMMARY (TASK SPLITTING):\n"
    "   - 'summary': a concise, professional 1-2 sentence overview of the day's accomplishments. Do NOT copy raw conversational intros or transcripts verbatim.\n"
    "   - 'work_summaries': identify EVERY separate task, activity, or accomplishment mentioned and split each into its OWN item. If 5 tasks are mentioned, return 5 items. NEVER combine multiple tasks into one row.\n"
    "5. STOP-WORD & FILLER FILTERING:\n"
    "   - Do NOT create entries in 'work_summaries' for conversational intros ('Hi good morning my name is...'), standalone dates, or filler ('Thank you').\n"
    "   - ONLY include actual, actionable work activities.\n"
    "6. DATE HANDLING:\n"
    "   - For 'date' fields, use the calendar date mentioned by the user or default to the report creation date. NEVER put quantities, equipment names, or non-date text in a date field.\n\n"
    "Return a raw JSON object with the following fields:\n"
    '  - "summary": a professional, concise executive summary (in English).\n'
    '  - "tasks": a list of clear, actionable tasks or work completed. If none, return [].\n'
    '  - "important_points": a list of key highlights, decisions, or critical notes. If none, return [].\n'
    '  - "report": a JSON object containing:\n'
    '      - "metadata": { "project_name", "location", "prepared_by" } (default "N/A")\n'
    '      - "work_summaries": [ { "area", "activity", "progress_percentage" (int 0-100 or null), "date", "responsible_person", "status" (one of "In Progress","Completed","Delayed","On Hold"), "remarks" } ]\n'
    '      - "resources": [ { "resource_type" (one of "Team/Labour","Equipment/Tools","Material/Software/Resources"), "description", "quantity" } ]\n'
    '      - "issues": [ { "issue", "impact", "action_taken", "responsible_person" } ]\n'
    '      - "next_day_plan": [ { "area", "planned_activity", "target_completion" } ]\n'
    '      - "overall_progress_percentage": int 0-100 or null\n'
    '      - "overall_status": one of "In Progress","Completed","Delayed","On Hold"\n'
    '      - "additional_remarks": any other notes or "N/A"\n\n'
    "Return a single valid raw JSON object with no markdown fencing. Never invent information."
)


class AIProviderInterface(Protocol):
    """Protocol defining the AI services the workflow depends on."""

    async def transcribe_audio_only(self, file_path: str) -> str:
        """Speech-to-text only: returns a raw transcript."""
        ...

    async def extract_from_text(
        self, text: str, existing_draft: Optional[ExtractedReport] = None
    ) -> ExtractedReport:
        """Structures free text into the report schema."""
        ...

    async def extract_from_audio(
        self, file_path: str, existing_draft: Optional[ExtractedReport] = None
    ) -> ExtractedReport:
        """Transcribes audio, then structures it."""
        ...

    async def extract_from_image(
        self, file_path: str, existing_draft: Optional[ExtractedReport] = None
    ) -> ExtractedReport:
        """Extracts report data from an image using a vision model."""
        ...


class AIProvider:
    """Configurable AI provider driving both the chat and speech-to-text roles."""

    def __init__(
        self,
        llm: Optional[ModelSettings] = None,
        stt: Optional[ModelSettings] = None,
        language: Optional[str] = None,
    ):
        """Initializes the provider from resolved model settings.

        Args:
            llm: Chat/structuring model settings. Defaults to ``settings.llm``.
            stt: Speech-to-text model settings. Defaults to ``settings.stt``.
            language: Optional ISO language hint passed to transcription.
        """
        self.llm = llm or settings.llm
        self.stt = stt or settings.stt
        self.language = language if language is not None else settings.stt_language

        self._chat_client: Optional[AsyncOpenAI] = None
        self._stt_client: Optional[AsyncOpenAI] = None
        self._local_whisper = None

        # Records which path produced the most recent extraction.
        self.last_extraction_path: str = EXTRACTION_AI

    # ------------------------------------------------------------------
    # Clients
    # ------------------------------------------------------------------

    @staticmethod
    def _build_client(config: ModelSettings) -> AsyncOpenAI:
        """Builds an OpenAI-compatible async client for the given role."""
        kwargs: Dict[str, Any] = {
            # Local servers accept any non-empty key; the SDK requires one.
            "api_key": config.api_key or "not-needed",
            "timeout": config.timeout,
        }
        if config.base_url:
            kwargs["base_url"] = config.base_url
        if config.provider == "openrouter":
            kwargs["default_headers"] = {
                "HTTP-Referer": settings.app.base_url,
                "X-Title": settings.app.name,
            }
        return AsyncOpenAI(**kwargs)

    def chat_client(self) -> AsyncOpenAI:
        """Returns the lazily-built chat client."""
        if self._chat_client is None:
            if not self.llm.is_configured:
                raise ValueError(
                    f"LLM provider '{self.llm.provider}' has no API key. "
                    "Set it on the Settings page or via LLM_API_KEY."
                )
            self._chat_client = self._build_client(self.llm)
        return self._chat_client

    def stt_client(self) -> AsyncOpenAI:
        """Returns the lazily-built speech-to-text client."""
        if self._stt_client is None:
            if not self.stt.is_configured:
                raise ValueError(
                    f"Speech-to-text provider '{self.stt.provider}' has no API key. "
                    "Set it on the Settings page or via STT_API_KEY."
                )
            self._stt_client = self._build_client(self.stt)
        return self._stt_client

    def describe(self) -> Dict[str, Any]:
        """Summarises what will actually run, for the dashboard status panel.

        The speech-to-text entry reports the *effective* engine, which may be a
        built-in library rather than the configured provider.
        """
        effective, reason = self.resolve_stt_engine()
        is_fallback = effective is not None and effective != self.stt.provider

        return {
            "chat": {
                "provider": self.llm.provider,
                "label": provider_info(self.llm.provider)["label"],
                "model": self.llm.model,
                "configured": self.llm.is_configured,
            },
            "stt": {
                "provider": self.stt.provider,
                "label": provider_info(self.stt.provider)["label"],
                "model": self.stt.model,
                "configured": effective is not None,
                "effective": effective,
                "effective_label": provider_info(effective)["label"] if effective else None,
                "is_fallback": is_fallback,
                "reason": reason,
            },
        }

    # ------------------------------------------------------------------
    # Audio preparation
    # ------------------------------------------------------------------

    @staticmethod
    def _ffmpeg_binary() -> Optional[str]:
        """Locates an ffmpeg executable, preferring the bundled wheel."""
        try:
            import imageio_ffmpeg

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return shutil.which("ffmpeg")

    def _convert_to_wav_sync(self, file_path: str) -> str:
        """Transcodes any audio file to 16 kHz mono WAV. Blocking.

        Returns the original path unchanged if no transcoder is available.
        """
        if file_path.lower().endswith(".wav"):
            return file_path

        wav_path = os.path.splitext(file_path)[0] + ".wav"
        ffmpeg = self._ffmpeg_binary()

        if ffmpeg:
            try:
                subprocess.run(
                    [ffmpeg, "-y", "-i", file_path, "-ac", "1", "-ar", "16000", wav_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                    timeout=120,
                )
                logger.info(f"Transcoded '{file_path}' to WAV via ffmpeg.")
                return wav_path
            except Exception as exc:
                logger.warning(f"ffmpeg transcode failed for '{file_path}': {exc}")

        try:
            import soundfile as sf

            data, samplerate = sf.read(file_path)
            sf.write(wav_path, data, samplerate)
            logger.info(f"Transcoded '{file_path}' to WAV via soundfile.")
            return wav_path
        except Exception as exc:
            logger.warning(
                f"No usable transcoder for '{file_path}' ({exc}). "
                "Install ffmpeg to support WhatsApp OGG/Opus voice notes."
            )

        return file_path

    async def convert_to_wav_if_needed(self, file_path: str) -> str:
        """Async wrapper around the blocking transcode."""
        return await asyncio.to_thread(self._convert_to_wav_sync, file_path)

    # ------------------------------------------------------------------
    # Speech-to-text
    # ------------------------------------------------------------------

    def resolve_stt_engine(self) -> Tuple[Optional[str], str]:
        """Decides which speech-to-text engine to actually use.

        Falls back to a built-in Python library whenever the configured
        provider cannot run -- either because ``auto`` was chosen, or because a
        hosted provider has no API key. Returning an empty transcript in that
        case would have looked like a bad recording rather than a missing key.

        Returns:
            ``(provider_id, reason)``. ``provider_id`` is ``None`` when nothing
            can transcribe at all.
        """
        from app.ai.registry import detect_local_stt, is_local_stt, local_stt_importable

        configured = self.stt.provider

        if configured == "auto":
            local = detect_local_stt()
            return local, "configured as automatic"

        # Choosing a local engine in the UI does not install its library.
        if is_local_stt(configured):
            if local_stt_importable(configured):
                return configured, "configured"
            local = detect_local_stt()
            if local:
                return local, f"'{configured}' is not installed"
            return None, f"'{configured}' is not installed and no other engine is available"

        if self.stt.is_configured:
            return configured, "configured"

        local = detect_local_stt()
        if local:
            return local, f"'{configured}' has no API key"

        return None, f"'{configured}' has no API key and no built-in engine is installed"

    async def transcribe_audio_only(self, file_path: str) -> str:
        """Transcribes a voice note.

        Args:
            file_path: Local path to the downloaded audio file.

        Returns:
            The transcript, or an empty string if transcription failed.
        """
        if not file_path or not os.path.exists(file_path):
            logger.error(f"Cannot transcribe: no file at '{file_path}'.")
            return ""

        provider, reason = self.resolve_stt_engine()

        if provider is None:
            logger.error(
                f"Cannot transcribe: {reason}. Set a speech-to-text key on the "
                "Settings page, or install one with: pip install faster-whisper",
                extra={"event": "stt_unavailable", "provider": self.stt.provider},
            )
            return ""

        if provider != self.stt.provider:
            logger.warning(
                f"Falling back to '{provider}' for transcription: {reason}.",
                extra={"event": "stt_fallback", "provider": provider},
            )

        try:
            if provider == "faster-whisper":
                return await asyncio.to_thread(self._transcribe_local_sync, file_path)
            if provider == "sphinx":
                return await asyncio.to_thread(self._transcribe_sphinx_sync, file_path)
            if provider == "google-web":
                return await asyncio.to_thread(self._transcribe_google_web_sync, file_path)
            return await self._transcribe_remote(file_path)
        except Exception as exc:
            logger.error(
                f"Transcription failed via '{provider}': {exc}",
                exc_info=True,
                extra={"event": "stt_failed", "provider": provider},
            )
            return ""

    async def _transcribe_remote(self, file_path: str) -> str:
        """Transcribes via an OpenAI-compatible ``/audio/transcriptions`` endpoint."""
        client = self.stt_client()

        request: Dict[str, Any] = {"model": self.stt.model}
        if self.language:
            request["language"] = self.language

        with open(file_path, "rb") as audio_file:
            result = await client.audio.transcriptions.create(file=audio_file, **request)

        transcript = (getattr(result, "text", "") or "").strip()
        logger.info(
            f"Transcribed {os.path.basename(file_path)} via {self.stt.provider}/{self.stt.model} "
            f"({len(transcript)} chars).",
            extra={"event": "stt_success", "provider": self.stt.provider},
        )
        return transcript

    def _transcribe_sphinx_sync(self, file_path: str) -> str:
        """Transcribes offline with PocketSphinx, via SpeechRecognition. Blocking.

        Free, needs no key and no network, but English-only and considerably
        less accurate than Whisper. Suitable as a stopgap, not as the plan.
        """
        import speech_recognition as sr

        wav_path = self._convert_to_wav_sync(file_path)
        recognizer = sr.Recognizer()

        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)

        transcript = (recognizer.recognize_sphinx(audio_data) or "").strip()
        logger.info(
            f"Transcribed offline with PocketSphinx ({len(transcript)} chars).",
            extra={"event": "stt_success", "provider": "sphinx"},
        )
        return transcript

    def _transcribe_local_sync(self, file_path: str) -> str:
        """Transcribes locally with faster-whisper. Blocking."""
        from faster_whisper import WhisperModel

        if self._local_whisper is None:
            # 'auto' leaves the model unset; 'base' is a sensible default that
            # runs on a small droplet.
            model_name = self.stt.model if self.stt.provider == "faster-whisper" else "base"
            if not model_name or model_name == "default":
                model_name = "base"
            logger.info(f"Loading local faster-whisper model '{model_name}'...")
            self._local_whisper = WhisperModel(model_name, device="auto", compute_type="int8")

        segments, info = self._local_whisper.transcribe(
            file_path,
            language=self.language or None,
            vad_filter=True,
        )
        transcript = " ".join(segment.text.strip() for segment in segments).strip()
        logger.info(
            f"Transcribed locally ({info.language}, {len(transcript)} chars).",
            extra={"event": "stt_success", "provider": "faster-whisper"},
        )
        return transcript

    def _transcribe_google_web_sync(self, file_path: str) -> str:
        """Transcribes via the legacy free Google Web Speech endpoint. Blocking.

        Retained for backwards compatibility only. The endpoint is unofficial,
        rate-limited and not intended for production use.
        """
        import speech_recognition as sr

        wav_path = self._convert_to_wav_sync(file_path)
        recognizer = sr.Recognizer()

        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)

        for language in (self.language or "en-IN", "en-US", "hi-IN"):
            try:
                transcript = recognizer.recognize_google(audio_data, language=language)
                if transcript:
                    logger.info(f"Google Web Speech transcript ({language}): {len(transcript)} chars.")
                    return transcript
            except Exception as exc:
                logger.warning(f"Google Web Speech returned nothing for {language}: {exc}")

        return ""

    # ------------------------------------------------------------------
    # Structuring
    # ------------------------------------------------------------------

    async def extract_from_text(
        self, text: str, existing_draft: Optional[ExtractedReport] = None
    ) -> ExtractedReport:
        """Structures a transcript or text update into the report schema.

        Falls back to a deterministic splitter if the model call fails, and
        records which path was taken in ``last_extraction_path``.
        """
        prompt = f'Please analyze the following update:\n\n"{text}"'
        if existing_draft:
            prompt += f"\n\nExisting draft report context to merge:\n{existing_draft.model_dump_json()}\n"

        try:
            content = await self._chat_json(SYSTEM_INSTRUCTION, prompt)
            extracted = self._build_extracted_report(json.loads(content))
            extracted = await self._ensure_english(extracted)
            self.last_extraction_path = EXTRACTION_AI
            return existing_draft.merge_with(extracted) if existing_draft else extracted
        except Exception as exc:
            logger.error(
                f"Structuring failed via {self.llm.provider}/{self.llm.model}: {exc}",
                exc_info=True,
                extra={"event": "llm_extraction_failed", "provider": self.llm.provider},
            )

        self.last_extraction_path = EXTRACTION_FALLBACK
        fallback = self._rule_based_report(text)
        return existing_draft.merge_with(fallback) if existing_draft else fallback

    async def _chat_json(self, system: str, user: str) -> str:
        """Calls the chat model and returns raw JSON text.

        Tries native JSON mode first and retries without it, since not every
        OpenAI-compatible provider supports ``response_format``.
        """
        client = self.chat_client()
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        try:
            response = await client.chat.completions.create(
                model=self.llm.model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.2,
            )
        except Exception as exc:
            logger.warning(
                f"JSON mode rejected by {self.llm.provider} ({exc}). Retrying without response_format."
            )
            response = await client.chat.completions.create(
                model=self.llm.model,
                messages=messages,
                temperature=0.2,
            )

        return _strip_json_fence(response.choices[0].message.content or "{}")

    async def _ensure_english(self, extracted: ExtractedReport) -> ExtractedReport:
        """Translates any residual Devanagari in the extracted report to English."""
        dumped = extracted.model_dump_json()
        if not any("ऀ" <= char <= "ॿ" for char in dumped):
            return extracted

        logger.info("Devanagari detected in extracted report. Translating fields to English.")
        try:
            content = await self._chat_json(
                "You translate daily progress reports into professional English. "
                "Return the same JSON object with identical keys and structure, "
                "with every text value translated to English.",
                dumped,
            )
            return self._build_extracted_report(json.loads(content))
        except Exception as exc:
            logger.error(f"Translation pass failed: {exc}")
            return extracted

    async def extract_from_audio(
        self, file_path: str, existing_draft: Optional[ExtractedReport] = None
    ) -> ExtractedReport:
        """Transcribes audio, then structures the transcript."""
        transcript = await self.transcribe_audio_only(file_path)
        if not transcript:
            transcript = "Voice note update received and recorded."
        return await self.extract_from_text(transcript, existing_draft=existing_draft)

    async def extract_from_image(
        self, file_path: str, existing_draft: Optional[ExtractedReport] = None
    ) -> ExtractedReport:
        """Extracts report data from an image using a vision-capable chat model."""
        import base64

        try:
            encoded = await asyncio.to_thread(_read_base64, file_path)
            client = self.chat_client()

            response = await client.chat.completions.create(
                model=self.llm.model,
                messages=[{
                    "role": "system",
                    "content": SYSTEM_INSTRUCTION,
                }, {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract the progress report details from this image."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
                    ],
                }],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            content = _strip_json_fence(response.choices[0].message.content or "{}")
            extracted = self._build_extracted_report(json.loads(content))
            return existing_draft.merge_with(extracted) if existing_draft else extracted
        except Exception as exc:
            logger.error(f"Vision extraction failed for '{file_path}': {exc}", exc_info=True)
            fallback = ExtractedReport(summary="Report document photo/image received.")
            return existing_draft.merge_with(fallback) if existing_draft else fallback

    # ------------------------------------------------------------------
    # Response shaping
    # ------------------------------------------------------------------

    @staticmethod
    def _build_extracted_report(data: Dict[str, Any]) -> ExtractedReport:
        """Maps a raw model JSON response onto the ``ExtractedReport`` schema."""
        report_dict = data.get("report") or {}
        metadata_dict = report_dict.get("metadata") or {}

        full_report = FullProgressReport(
            metadata=ReportMetadata(**metadata_dict) if metadata_dict else ReportMetadata(),
            work_summaries=[WorkSummaryItem(**i) for i in report_dict.get("work_summaries", []) if isinstance(i, dict)],
            resources=[ResourceItem(**i) for i in report_dict.get("resources", []) if isinstance(i, dict)],
            issues=[IssueItem(**i) for i in report_dict.get("issues", []) if isinstance(i, dict)],
            next_day_plan=[NextDayPlanItem(**i) for i in report_dict.get("next_day_plan", []) if isinstance(i, dict)],
            overall_progress_percentage=report_dict.get("overall_progress_percentage"),
            overall_status=report_dict.get("overall_status") or "In Progress",
            additional_remarks=report_dict.get("additional_remarks") or "N/A",
        )

        tasks = _coerce_str_list(
            data.get("tasks") or [w.activity for w in full_report.work_summaries if w.activity != "N/A"],
            ("activity", "description", "task"),
        )
        points = _coerce_str_list(
            data.get("important_points") or [i.issue for i in full_report.issues if i.issue],
            ("issue", "description", "point"),
        )

        location = metadata_dict.get("location")
        project = metadata_dict.get("project_name")
        site_name = location if location and location != "N/A" else project
        if site_name == "N/A":
            site_name = None

        return ExtractedReport(
            site_name=site_name,
            summary=data.get("summary") or "Daily progress update recorded.",
            tasks=tasks,
            important_points=points,
            report=full_report,
            work_completed=tasks,
            issues_and_blockers=points,
        )

    # ------------------------------------------------------------------
    # Deterministic fallback
    # ------------------------------------------------------------------

    def _rule_based_report(self, text: str) -> ExtractedReport:
        """Builds a report without a model, preserving the user's own wording."""
        summary, work_items = self._rule_based_task_splitter(text)
        tasks = [item.activity for item in work_items]

        return ExtractedReport(
            site_name=None,
            summary=summary,
            tasks=tasks,
            important_points=[],
            report=FullProgressReport(
                metadata=ReportMetadata(),
                work_summaries=work_items,
                overall_status="In Progress",
                additional_remarks="Generated without AI structuring; the model call did not succeed.",
            ),
            work_completed=tasks,
            issues_and_blockers=[],
        )

    @staticmethod
    def _rule_based_task_splitter(text: str) -> Tuple[str, List[WorkSummaryItem]]:
        """Splits raw text into work items using punctuation and action verbs.

        This is a last resort when the model is unreachable. It never invents
        content -- unmatched input is preserved verbatim as a single item.
        """
        if not text or not text.strip():
            return (
                "Daily progress update recorded.",
                [WorkSummaryItem(area="General", activity="Daily update recorded", status="Completed")],
            )

        raw_text = re.sub(r"^(?:Text Update|Voice Note|Transcript)\s*(?:#\d+)?\s*(?:Transcript)?:?\s*", "", text.strip(), flags=re.IGNORECASE)
        raw_text = re.sub(r"^[\s\-\*•●▸]+", "", raw_text).strip()
        today = datetime.now().strftime("%Y-%m-%d")

        action_verbs = (
            r"\b(set up|setup|developed|develop|designed|design|integrated|integrate|deployed|deploy|"
            r"worked|work|fixed|fix|attended|attend|configured|configure|tested|test|implemented|implement|"
            r"explored|explore|created|create|built|build|updated|update|modified|modify|resolved|resolve|"
            r"conducted|conduct|inspected|inspect|arranged|arrange|shifted|shift|prepared|prepare|"
            r"completed|complete|reviewed|review|installed|install|delivered|deliver)\b"
        )
        completed_verbs = (
            "completed", "done", "resolved", "fixed", "deployed", "delivered",
            "developed", "designed", "implemented", "explored", "set up",
            "conducted", "inspected", "arranged", "installed",
        )

        lines = [re.sub(r"^(?:Text Update|Voice Note|Transcript)\s*(?:#\d+)?\s*(?:Transcript)?:?\s*", "", line.strip(), flags=re.IGNORECASE).strip("-*•●▸ ").strip() for line in raw_text.splitlines() if line.strip()]
        segments = lines if len(lines) > 1 else re.split(r"(?<=[.!?])\s+", raw_text)

        work_items: List[WorkSummaryItem] = []
        for segment in segments:
            activity = segment.strip(" ,.-").strip()
            activity = re.sub(r"^[\s\-\*•●▸]+", "", activity).strip()
            if not activity or not re.search(action_verbs, activity, re.IGNORECASE):
                continue

            activity = activity[0].upper() + activity[1:]
            if not activity.endswith("."):
                activity += "."

            lowered = activity.lower()
            status = "Completed" if any(verb in lowered for verb in completed_verbs) else "In Progress"
            work_items.append(WorkSummaryItem(activity=activity, date=today, status=status))

        if not work_items:
            clean_activity = raw_text[0].upper() + raw_text[1:] if raw_text else "Daily update recorded."
            work_items = [WorkSummaryItem(activity=clean_activity, date=today, status="In Progress")]

        descriptions = [item.activity.rstrip(".") for item in work_items]
        if len(descriptions) == 1:
            summary = f"Summary of work: {descriptions[0]}."
        else:
            summary = f"Completed key activities: {'; '.join(descriptions[:4])}."

        return summary, work_items


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _read_base64(file_path: str) -> str:
    """Reads a file and returns its base64 encoding. Blocking."""
    import base64

    with open(file_path, "rb") as handle:
        return base64.b64encode(handle.read()).decode("utf-8")


def _strip_json_fence(content: str) -> str:
    """Removes ```json fencing that some models add despite instructions."""
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped or "{}"


def _coerce_str_list(values: Any, dict_keys: Tuple[str, ...]) -> List[str]:
    """Normalises a model-returned list into a list of strings."""
    if not isinstance(values, list):
        return []

    out: List[str] = []
    for value in values:
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, dict):
            for key in dict_keys:
                if value.get(key):
                    out.append(str(value[key]))
                    break
            else:
                out.append(str(value))
        else:
            out.append(str(value))
    return out


# Backwards-compatible alias -- earlier code imported this name.
OpenAIAIProvider = AIProvider
