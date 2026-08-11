"""Workflow states implementing the report-generation conversation.

Each state handler receives a ``WorkflowContext`` and returns the reply text.
Multiple messages are separated with ``SPLIT_MESSAGE``.
"""

import asyncio
import logging
import os
import time
from typing import Any, Optional

from app import templates
from app.ai import AIProviderInterface
from app.services.whatsapp.media import WhatsAppMediaDownloader
from app.sessions import WorkflowState

logger = logging.getLogger("app.service.workflow.states")

# Sentinel used to split one handler return value into several outbound messages.
SPLIT_MESSAGE = "===SPLIT_MESSAGE==="

# Greeting roots, matched loosely so 'hii', 'heyyy' and 'helloo' all count.
_GREETING_ROOTS = ("hi", "hello", "hey", "start", "begin", "menu", "new")

# Commands recognised in every state.
_RESET_COMMANDS = ("RESET", "CANCEL")

_AUDIO_EXTENSIONS = (
    ".m4a", ".mp3", ".wav", ".ogg", ".aac", ".opus", ".flac", ".mp4", ".wma", ".amr",
)


def _extract_clean_content(message: Any) -> str:
    """Normalises a message into a comparable command string.

    Interactive button and list replies are mapped onto stable command tokens so
    that state handlers never have to match on button copy.
    """
    if not message:
        return ""

    if getattr(message, "message_type", None) == "interactive":
        button_id = (getattr(message, "interactive_id", None) or "").lower()
        title = (getattr(message, "interactive_title", None) or "").upper()

        if "record" in button_id or "VOICE" in title:
            return "RECORD_VOICE"
        if "text" in button_id or "TEXT" in title:
            return "TEXT_UPDATE"
        if "skip" in button_id or "SKIP" in title:
            return "SKIP"
        if "add" in button_id or "ADD" in title or "UPLOAD" in title:
            return "ADD_PHOTOS"
        if "pdf" in button_id or "PDF" in title:
            return "CONFIRM_PDF"
        if "docx" in button_id or "DOCX" in title or "WORD" in title:
            return "CONFIRM_DOCX"
        if "done" in button_id or "DONE" in title:
            return "DONE"
        if "generate" in button_id or "GENERATE" in title or "CONFIRM" in title:
            return "CONFIRM"
        if "cancel" in button_id or "CANCEL" in title or "RESET" in title:
            return "RESET"
        return title or (getattr(message, "content", None) or "").strip()

    return (getattr(message, "content", None) or "").strip()


def _is_greeting(text: str) -> bool:
    """Checks whether text is a greeting, tolerating repeated trailing letters."""
    word = text.strip().lower()
    if len(word) < 2:
        return False

    for root in _GREETING_ROOTS:
        if word == root:
            return True
        # 'hi' -> 'hiii', 'hey' -> 'heyyy': same stem, final letter repeated.
        stem, final = root[:-1], root[-1]
        tail = word[len(stem):]
        if word.startswith(stem) and tail and all(char == final for char in tail):
            return True
    return False


def _is_audio(message: Any) -> bool:
    """Detects voice notes and audio files, including audio sent as a document."""
    if message.message_type in ("audio", "voice"):
        return True
    if (message.mime_type or "").lower().startswith("audio/"):
        return True
    return (message.filename or "").lower().endswith(_AUDIO_EXTENSIONS)


class WorkflowContext:
    """Execution context handed to each state handler."""

    def __init__(
        self,
        session: Any,
        message: Any,
        ai_provider: AIProviderInterface,
        media_downloader: Optional[WhatsAppMediaDownloader] = None,
        docx_generator: Optional[Any] = None,
    ):
        from app.reports.generator import DocxReportGenerator

        self.session = session
        self.message = message
        self.ai_provider = ai_provider
        self.media_downloader = media_downloader
        self.docx_generator = docx_generator or DocxReportGenerator()


class WorkflowStateBase:
    """Base class for the state handlers."""

    async def handle_message(self, ctx: WorkflowContext) -> str:
        raise NotImplementedError

    async def _download_media_if_present(self, ctx: WorkflowContext) -> Optional[str]:
        """Downloads an attachment, returning ``None`` when it is unavailable."""
        if not (ctx.media_downloader and ctx.message.media_id):
            return None
        try:
            return await ctx.media_downloader.download_media(
                media_id=ctx.message.media_id,
                mime_type=ctx.message.mime_type or "application/octet-stream",
                filename=ctx.message.filename,
            )
        except Exception as exc:
            logger.error(f"Media download failed for {ctx.message.media_id}: {exc}", exc_info=True)
            return None

    @staticmethod
    def _handle_universal_commands(ctx: WorkflowContext, command: str) -> Optional[str]:
        """Handles greetings and reset, which are accepted in every state.

        Returns:
            The reply to send, or ``None`` if the command was not universal.
        """
        if _is_greeting(command):
            ctx.session.clear_workflow()
            ctx.session.state = WorkflowState.WAITING_FOR_INPUT
            return templates.get_welcome_message()

        if command.upper() in _RESET_COMMANDS:
            ctx.session.clear_workflow()
            return templates.get_workflow_reset_ack()

        return None


class IdleState(WorkflowStateBase):
    """Entry state: greets the user or forwards straight into input collection."""

    async def handle_message(self, ctx: WorkflowContext) -> str:
        content = _extract_clean_content(ctx.message)

        if _is_greeting(content):
            ctx.session.state = WorkflowState.WAITING_FOR_INPUT
            return templates.get_welcome_message()

        return await WaitingForInputState().handle_message(ctx)


class WaitingForInputState(WorkflowStateBase):
    """Collects voice notes, text updates, photos and documents."""

    async def handle_message(self, ctx: WorkflowContext) -> str:
        message = ctx.message
        content = _extract_clean_content(message)
        command = content.upper()

        universal = self._handle_universal_commands(ctx, content)
        if universal is not None:
            return universal

        if command == "RECORD_VOICE":
            return (
                "🎤 Please send your voice note now.\n\n"
                "Once received, I'll transcribe and structure it into your report draft."
            )

        if command == "TEXT_UPDATE":
            return (
                "📝 Please type and send your text update now.\n\n"
                "Once received, I'll structure it into your report draft."
            )

        if command in ("DONE", "SKIP"):
            return await self._process_done_command(ctx)

        if _is_audio(message):
            return await self._handle_voice_note(ctx)

        if message.message_type == "image":
            return await self._handle_photo(ctx)

        if message.message_type == "text" and content:
            ctx.session.text_updates.append(content)
            # Text used to leave the session here with no buttons and no route
            # forward; it now advances exactly as a voice note does.
            ctx.session.state = WorkflowState.WAITING_FOR_PHOTOS
            logger.info(
                f"Text update received from {message.sender_id}.",
                extra={"event": "workflow_text_processed", "sender": message.sender_id},
            )
            return templates.get_text_update_ack()

        if message.message_type == "document":
            media_path = await self._download_media_if_present(ctx)
            if media_path is None:
                return templates.get_media_unavailable_error()
            ctx.session.documents.append({
                "filename": message.filename,
                "media_id": message.media_id,
                "file_path": media_path,
            })
            return templates.get_document_received_ack(message.filename)

        return templates.get_welcome_message()

    async def _handle_voice_note(self, ctx: WorkflowContext) -> str:
        """Downloads and transcribes a voice note, then asks about photos."""
        message = ctx.message
        media_path = await self._download_media_if_present(ctx)

        if media_path is None:
            return templates.get_media_unavailable_error()

        transcription = ""
        try:
            transcription = await ctx.ai_provider.transcribe_audio_only(media_path)
        except Exception as exc:
            logger.error(f"Voice note transcription failed: {exc}", exc_info=True)

        if not transcription:
            # Keep the note so the user's effort is not lost, but say plainly
            # that the audio could not be read.
            ctx.session.voice_notes.append({
                "media_id": message.media_id,
                "transcription": "",
                "file_path": media_path,
            })
            ctx.session.state = WorkflowState.WAITING_FOR_PHOTOS
            return templates.get_transcription_failed_error()

        ctx.session.voice_notes.append({
            "media_id": message.media_id,
            "transcription": transcription,
            "file_path": media_path,
        })
        ctx.session.state = WorkflowState.WAITING_FOR_PHOTOS
        logger.info(
            f"Voice note processed for {message.sender_id}.",
            extra={"event": "workflow_voice_processed", "sender": message.sender_id},
        )
        return templates.get_voice_processed_success()

    async def _handle_photo(self, ctx: WorkflowContext) -> str:
        """Stores a photo and acknowledges it."""
        media_path = await self._download_media_if_present(ctx)
        if media_path is None:
            return templates.get_media_unavailable_error()

        ctx.session.photos.append(media_path)
        ctx.session.state = WorkflowState.WAITING_FOR_PHOTOS
        count = len(ctx.session.photos)
        logger.info(
            f"Photo collected for {ctx.message.sender_id}. Total={count}",
            extra={
                "event": "workflow_photo_collected",
                "sender": ctx.message.sender_id,
                "photo_count": count,
            },
        )
        return templates.get_photo_received_ack(count)

    async def _generate_draft_preview_only(self, ctx: WorkflowContext) -> str:
        """Runs AI extraction over everything collected and returns the preview."""
        combined_inputs = []
        for index, voice in enumerate(ctx.session.voice_notes):
            transcript = (voice.get("transcription") or "").strip()
            if transcript:
                combined_inputs.append(f"Voice Note #{index + 1} Transcript: {transcript}")
        for index, text in enumerate(ctx.session.text_updates):
            if text.strip():
                combined_inputs.append(f"Text Update #{index + 1}: {text.strip()}")

        combined_text = "\n\n".join(combined_inputs) if combined_inputs else "Daily progress updates recorded."

        extracted = await ctx.ai_provider.extract_from_text(combined_text)
        ctx.session.draft_report = extracted.model_dump()
        ctx.session.extraction_path = getattr(ctx.ai_provider, "last_extraction_path", "ai")
        ctx.session.state = WorkflowState.WAITING_FOR_CONFIRMATION

        logger.info(
            f"Draft report generated for {ctx.message.sender_id}.",
            extra={
                "event": "workflow_draft_generated",
                "sender": ctx.message.sender_id,
                "photos": len(ctx.session.photos),
            },
        )

        return templates.get_draft_preview(
            site_name=extracted.site_name,
            report_date=extracted.report_date,
            summary=extracted.summary,
            work_completed=extracted.work_completed,
            issues=extracted.issues_and_blockers,
            photo_count=len(ctx.session.photos),
        )

    async def _process_done_command(self, ctx: WorkflowContext) -> str:
        """Acknowledges the collected inputs, then returns the draft preview."""
        if not ctx.session.has_voice_or_text():
            return templates.get_empty_done_error()

        # The status checklist used to be built and discarded, leaving the user
        # with silence through the slowest step. It is now actually sent.
        status = templates.get_processing_report_status(
            has_voice=len(ctx.session.voice_notes) > 0,
            has_text=len(ctx.session.text_updates) > 0,
            photo_count=len(ctx.session.photos),
        )
        preview = await self._generate_draft_preview_only(ctx)
        return f"{status}{SPLIT_MESSAGE}{preview}"


class WaitingForPhotosState(WorkflowStateBase):
    """Collects photos until the user is finished."""

    async def handle_message(self, ctx: WorkflowContext) -> str:
        message = ctx.message
        content = _extract_clean_content(message)
        command = content.upper()

        universal = self._handle_universal_commands(ctx, content)
        if universal is not None:
            return universal

        if command == "ADD_PHOTOS":
            return templates.get_upload_photos_prompt()

        if command == "SKIP":
            waiting_for_input = WaitingForInputState()
            draft = await waiting_for_input._generate_draft_preview_only(ctx)
            return f"{templates.get_skip_photos_ack()}{SPLIT_MESSAGE}{draft}"

        if command == "DONE":
            return await WaitingForInputState()._process_done_command(ctx)

        if message.message_type == "image":
            return await WaitingForInputState()._handle_photo(ctx)

        # Additional voice notes, text updates and documents stay welcome here.
        return await WaitingForInputState().handle_message(ctx)


class WaitingForConfirmationState(WorkflowStateBase):
    """Waits for the user to choose an output format, then builds the document."""

    _CONFIRM_COMMANDS = (
        "CONFIRM", "CONFIRM_PDF", "CONFIRM_DOCX", "YES", "APPROVE", "GENERATE", "PDF", "DOCX", "WORD",
    )

    async def handle_message(self, ctx: WorkflowContext) -> str:
        content = _extract_clean_content(ctx.message)
        command = content.upper()

        universal = self._handle_universal_commands(ctx, content)
        if universal is not None:
            return universal

        if command in self._CONFIRM_COMMANDS:
            return await self._generate(ctx, command)

        return templates.get_draft_preview(
            site_name=(ctx.session.draft_report or {}).get("site_name"),
            report_date=(ctx.session.draft_report or {}).get("report_date"),
            summary=(ctx.session.draft_report or {}).get("summary"),
            work_completed=(ctx.session.draft_report or {}).get("work_completed") or [],
            issues=(ctx.session.draft_report or {}).get("issues_and_blockers") or [],
            photo_count=len(ctx.session.photos),
        )

    async def _generate(self, ctx: WorkflowContext, command: str) -> str:
        """Builds the report document off the event loop.

        On failure the session is rolled back to ``WAITING_FOR_CONFIRMATION`` so
        the user can retry. Leaving it in ``GENERATING_REPORT`` used to lock them
        out until the session expired.
        """
        from app.services.events import recorder

        output_format = "docx" if command in ("CONFIRM_DOCX", "DOCX", "WORD") else "pdf"

        ctx.session.state = WorkflowState.GENERATING_REPORT
        ctx.session.requested_format = output_format

        started = time.monotonic()

        try:
            # python-docx, fpdf2 and LibreOffice are all synchronous and slow;
            # running them inline froze every other conversation.
            report_path = await asyncio.to_thread(
                ctx.docx_generator.generate_report_by_format,
                sender_id=ctx.message.sender_id,
                draft=ctx.session.draft_report or {},
                photo_paths=list(ctx.session.photos),
                output_format=output_format,
            )
        except Exception as exc:
            ctx.session.state = WorkflowState.WAITING_FOR_CONFIRMATION
            logger.error(
                f"Report generation failed for {ctx.message.sender_id}: {exc}",
                exc_info=True,
                extra={
                    "event": "workflow_report_failed",
                    "sender": ctx.message.sender_id,
                    "format": output_format,
                },
            )
            await recorder.record_report(
                wa_id=ctx.message.sender_id,
                report_path=None,
                output_format=output_format,
                draft=ctx.session.draft_report,
                photo_count=len(ctx.session.photos),
                voice_note_count=len(ctx.session.voice_notes),
                extraction_path=ctx.session.extraction_path,
                generation_ms=int((time.monotonic() - started) * 1000),
                error=str(exc)[:500],
            )
            return templates.get_report_failed_error()

        ctx.session.report_record_id = await recorder.record_report(
            wa_id=ctx.message.sender_id,
            report_path=report_path,
            output_format=output_format,
            draft=ctx.session.draft_report,
            photo_count=len(ctx.session.photos),
            voice_note_count=len(ctx.session.voice_notes),
            extraction_path=ctx.session.extraction_path,
            generation_ms=int((time.monotonic() - started) * 1000),
        )
        ctx.session.generated_report_path = report_path
        ctx.session.state = WorkflowState.REPORT_GENERATED

        logger.info(
            f"Report generated ({output_format}) for {ctx.message.sender_id}.",
            extra={
                "event": "workflow_report_complete",
                "sender": ctx.message.sender_id,
                "report_path": report_path,
            },
        )
        return templates.get_report_generated_ack(os.path.basename(report_path))


class GeneratingReportState(WorkflowStateBase):
    """Holding state while a document is being built."""

    async def handle_message(self, ctx: WorkflowContext) -> str:
        content = _extract_clean_content(ctx.message)

        # Reset must always work here. Without it, a generation that died left
        # the user permanently stuck on 'please wait'.
        universal = self._handle_universal_commands(ctx, content)
        if universal is not None:
            return universal

        return (
            "⚙️ Your report is being generated. Please wait a moment.\n\n"
            "If nothing arrives, send RESET to start again."
        )


class ReportGeneratedState(WorkflowStateBase):
    """Terminal state after a report has been delivered."""

    async def handle_message(self, ctx: WorkflowContext) -> str:
        content = _extract_clean_content(ctx.message)

        universal = self._handle_universal_commands(ctx, content)
        if universal is not None:
            return universal

        return (
            "✅ Your report has already been generated.\n\n"
            "Send RESET or say hi to start a new one."
        )


class CancelledState(WorkflowStateBase):
    """State reached after cancellation."""

    async def handle_message(self, ctx: WorkflowContext) -> str:
        ctx.session.clear_workflow()
        return templates.get_workflow_reset_ack()
