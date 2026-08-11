"""Routes incoming messages through the ConversationEngine and replies."""

import logging
import os
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from app.ai import AIProviderInterface
from app.models.events import WhatsAppMessageReceivedEvent
from app.services.events import recorder
from app.services.interfaces.whatsapp import WhatsAppSenderInterface
from app.services.whatsapp.media import WhatsAppMediaDownloader
from app.services.workflow.engine import ConversationEngine
from app.services.workflow.states import SPLIT_MESSAGE
from app.sessions import SessionStore

logger = logging.getLogger("app.service.events.report_handler")

# Buttons offered alongside a reply, keyed by the marker the templates emit.
# Matching on a marker rather than on the prose means editing the copy no longer
# silently drops the buttons.
BUTTON_SETS: Dict[str, List[Dict[str, str]]] = {
    "welcome": [
        {"id": "btn_record_voice", "title": "Record Voice"},
        {"id": "btn_text_update", "title": "Text Update"},
    ],
    "photos_prompt": [
        {"id": "btn_add_photos", "title": "Add Photos"},
        {"id": "btn_skip_photos", "title": "Skip Photos"},
    ],
    "photos_collecting": [
        {"id": "btn_done", "title": "Done"},
        {"id": "btn_cancel", "title": "Cancel"},
    ],
    "format_choice": [
        {"id": "btn_generate_pdf", "title": "PDF Report"},
        {"id": "btn_generate_docx", "title": "DOCX Report"},
        {"id": "btn_cancel", "title": "Cancel"},
    ],
}

# Fallback: identify which button set a reply wants from its content. Ordered,
# first match wins.
_MARKERS = (
    ("Welcome to", "welcome"),
    ("how you would like to provide", "welcome"),
    ("Voice note processed successfully", "photos_prompt"),
    ("Would you like to add photos", "photos_prompt"),
    ("Text Update Received", "photos_prompt"),
    ("Upload one or more", "photos_collecting"),
    ("photo(s) attached", "photos_collecting"),
    ("Report Draft", "format_choice"),
)

_FORMAT_PROMPT = "Please review the draft above and choose a format:"


class _TTLSet:
    """Bounded, time-limited set of seen ids.

    Replaces a plain set that was emptied wholesale at 2,000 entries -- a Meta
    retry landing just after the flush was reprocessed as new.
    """

    def __init__(self, max_size: int = 5000, ttl_seconds: int = 86400):
        self._items: "OrderedDict[str, float]" = OrderedDict()
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds

    def add_if_new(self, key: str) -> bool:
        """Records a key. Returns True if it had not been seen before."""
        now = time.time()
        self._evict(now)

        if key in self._items:
            return False

        self._items[key] = now
        while len(self._items) > self._max_size:
            self._items.popitem(last=False)
        return True

    def _evict(self, now: float) -> None:
        """Drops entries older than the TTL, oldest first."""
        cutoff = now - self._ttl_seconds
        while self._items:
            key, stamp = next(iter(self._items.items()))
            if stamp >= cutoff:
                break
            self._items.pop(key, None)


class ReportSessionHandler:
    """Event handler that drives the ConversationEngine and sends its replies."""

    def __init__(
        self,
        sender: WhatsAppSenderInterface,
        session_store: SessionStore,
        ai_provider: AIProviderInterface,
        media_downloader: Optional[WhatsAppMediaDownloader] = None,
        engine: Optional[ConversationEngine] = None,
    ):
        """Initializes the handler.

        Args:
            sender: Outbound message service.
            session_store: Store holding conversation state.
            ai_provider: Configured AI provider.
            media_downloader: Downloader for audio, images and documents.
            engine: Conversation state machine.
        """
        self.sender = sender
        self.session_store = session_store
        self.ai_provider = ai_provider
        self.media_downloader = media_downloader
        self.engine = engine or ConversationEngine()
        self._seen_message_ids = _TTLSet()

    async def __call__(self, event: WhatsAppMessageReceivedEvent) -> None:
        """Handles one parsed inbound message."""
        message = event.message
        sender_id = message.sender_id

        if message.message_id and not self._seen_message_ids.add_if_new(message.message_id):
            logger.info(
                f"Duplicate message '{message.message_id}' ignored.",
                extra={"event": "duplicate_message_ignored", "whatsapp_message_id": message.message_id},
            )
            return

        # History is written before processing, so an inbound message is
        # recorded even if the workflow later fails.
        await recorder.record_inbound(message)

        try:
            # The transaction holds a per-sender lock and saves on exit, so two
            # messages from the same person cannot interleave.
            async with self.session_store.transaction(sender_id) as session:
                session.sender_name = message.sender_name or session.sender_name

                reply_text = await self.engine.process_message(
                    session=session,
                    message=message,
                    ai_provider=self.ai_provider,
                    media_downloader=self.media_downloader,
                )
                generated_doc_path = session.generated_report_path
                report_id = session.report_record_id

                # Attach the transcript to the voice note we just stored.
                if session.voice_notes:
                    latest = session.voice_notes[-1]
                    if latest.get("transcription") and latest.get("file_path"):
                        await recorder.attach_transcript(
                            sender_id, latest["file_path"], latest["transcription"]
                        )

            if reply_text:
                await self._send_reply(sender_id, reply_text)

            if generated_doc_path:
                await self._deliver_document(sender_id, generated_doc_path, report_id)

        except Exception as exc:
            logger.error(
                f"Unhandled error processing message for {sender_id}: {exc}",
                exc_info=True,
                extra={"event": "workflow_handler_error", "sender": sender_id},
            )
            await self._try_send(
                sender_id,
                "⚠️ Something went wrong on our side. Send RESET to start again.",
            )

    async def _send_reply(self, sender_id: str, reply_text: str) -> None:
        """Sends each part of a reply, attaching buttons where the flow needs them."""
        for part in reply_text.split(SPLIT_MESSAGE):
            part = part.strip()
            if not part:
                continue

            button_key = _button_key_for(part)
            buttons = BUTTON_SETS.get(button_key) if button_key else None

            await recorder.record_outbound(sender_id, part)

            if not buttons or not hasattr(self.sender, "send_interactive_buttons"):
                await self.sender.send_text(to=sender_id, text=part)
                continue

            try:
                if button_key == "format_choice":
                    # The draft is long; send it as text, then a short prompt
                    # carrying the buttons.
                    await self.sender.send_text(to=sender_id, text=part)
                    await self.sender.send_interactive_buttons(
                        to=sender_id, body_text=_FORMAT_PROMPT, buttons=buttons
                    )
                else:
                    await self.sender.send_interactive_buttons(
                        to=sender_id, body_text=part, buttons=buttons
                    )
            except Exception as exc:
                logger.warning(
                    f"Interactive buttons failed ({exc}); falling back to plain text.",
                    extra={"event": "interactive_send_failed", "sender": sender_id},
                )
                await self._try_send(sender_id, part)

    async def _deliver_document(
        self, sender_id: str, path: str, report_id: Optional[int] = None
    ) -> None:
        """Uploads the generated report to Meta and sends it as an attachment."""
        if not os.path.exists(path):
            logger.error(
                f"Generated report is missing from disk: '{path}'.",
                extra={"event": "report_file_missing", "sender": sender_id},
            )
            await recorder.mark_failed(report_id, "The generated file was missing from disk.")
            return

        client = getattr(self.sender, "client", None)
        if not (client and hasattr(client, "upload_media")):
            logger.error("Sender has no media-capable client; cannot deliver the document.")
            await recorder.mark_failed(report_id, "No media-capable client configured.")
            return

        is_pdf = path.lower().endswith(".pdf")
        mime_type = (
            "application/pdf" if is_pdf
            else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        caption = f"{'📕' if is_pdf else '📘'} Daily Progress Report ({'PDF' if is_pdf else 'DOCX'})"

        try:
            media_id = await client.upload_media(file_path=path, mime_type=mime_type)
            await self.sender.send_document(
                to=sender_id,
                media_id=media_id,
                filename=os.path.basename(path),
                caption=caption,
            )
            logger.info(
                f"Delivered report to {sender_id}.",
                extra={"event": "report_delivered", "sender": sender_id},
            )
            await recorder.mark_delivered(report_id)
        except Exception as exc:
            logger.error(
                f"Failed to deliver the report to {sender_id}: {exc}",
                exc_info=True,
                extra={"event": "report_delivery_failed", "sender": sender_id},
            )
            await recorder.mark_failed(report_id, f"Delivery failed: {exc}")
            await self._try_send(
                sender_id,
                "⚠️ Your report was built but couldn't be sent. Send RESET and try once more.",
            )
            return

        # Clear the path so the document is not resent on the next message.
        async with self.session_store.transaction(sender_id) as session:
            if session.generated_report_path == path:
                session.generated_report_path = None
                session.report_record_id = None

    async def _try_send(self, sender_id: str, text: str) -> None:
        """Sends a message, swallowing transport errors."""
        try:
            await self.sender.send_text(to=sender_id, text=text)
        except Exception as exc:
            logger.error(
                f"Could not send a message to {sender_id}: {exc}",
                extra={"event": "outbound_send_failed", "sender": sender_id},
            )


def _button_key_for(text: str) -> Optional[str]:
    """Returns the button set a reply should carry, or ``None`` for plain text."""
    for marker, key in _MARKERS:
        if marker in text:
            return key
    return None
