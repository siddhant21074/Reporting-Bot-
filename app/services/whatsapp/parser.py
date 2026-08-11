"""Parses raw Meta webhook payloads into domain models."""

import logging
import time
from typing import Dict, List, Optional

from app.core.constants import SUPPORTED_MESSAGE_TYPES
from app.models.whatsapp import ParsedMessage
from app.schemas.webhook import Message, WebhookPayload

logger = logging.getLogger("app.service.whatsapp.parser")


class WhatsAppParser:
    """Extracts the messages we can act on from a webhook payload."""

    def parse_payload(self, payload: WebhookPayload) -> List[ParsedMessage]:
        """Walks a payload and parses every supported message it contains.

        Args:
            payload: The validated webhook payload.

        Returns:
            A list of ``ParsedMessage`` objects, possibly empty.
        """
        parsed_messages: List[ParsedMessage] = []

        for entry in payload.entry:
            for change in entry.changes:
                value = change.value

                # Status-only and non-message events carry no messages array.
                if not value.messages:
                    continue

                contacts_map: Dict[str, str] = {}
                for contact in value.contacts or []:
                    if not contact.wa_id:
                        continue
                    profile_name = contact.profile.name if contact.profile else None
                    contacts_map[contact.wa_id] = profile_name or "Unknown Contact"

                display_phone = value.metadata.display_phone_number if value.metadata else ""

                for message in value.messages:
                    if message.type not in SUPPORTED_MESSAGE_TYPES:
                        logger.info(
                            f"Ignoring unsupported message type '{message.type}'.",
                            extra={
                                "event": "unsupported_message_ignored",
                                "whatsapp_message_id": message.id,
                                "message_type": message.type,
                            },
                        )
                        continue

                    parsed = self._parse_single_message(message, contacts_map, display_phone or "")
                    if parsed:
                        parsed_messages.append(parsed)

        return parsed_messages

    def _parse_single_message(
        self, message: Message, contacts_map: Dict[str, str], display_phone: str
    ) -> Optional[ParsedMessage]:
        """Maps one webhook message onto ``ParsedMessage``.

        Args:
            message: A single message from ``value.messages``.
            contacts_map: wa_id to profile name lookup built from ``value.contacts``.
            display_phone: The business number that received the message.

        Returns:
            The parsed message, or ``None`` when the payload is missing the node
            its declared type requires.
        """
        parsed = ParsedMessage(
            message_id=message.id,
            sender_id=message.from_number,
            sender_name=contacts_map.get(message.from_number, "Unknown Contact"),
            phone_number=display_phone,
            timestamp=_safe_timestamp(message.timestamp),
            message_type=message.type,
            content="",
        )

        if message.type == "text" and message.text:
            parsed.content = message.text.body or ""

        elif message.type in ("audio", "voice"):
            media = message.audio or message.voice
            if not media:
                return _missing_node(message)
            parsed.media_id = media.id
            parsed.mime_type = media.mime_type
            parsed.content = f"Media attachment: {message.type} ({media.mime_type})"

        elif message.type == "image" and message.image:
            parsed.media_id = message.image.id
            parsed.mime_type = message.image.mime_type
            parsed.caption = message.image.caption
            parsed.content = message.image.caption or f"Media attachment: image ({message.image.mime_type})"

        elif message.type == "video" and message.video:
            parsed.media_id = message.video.id
            parsed.mime_type = message.video.mime_type
            parsed.caption = message.video.caption
            parsed.content = message.video.caption or f"Media attachment: video ({message.video.mime_type})"

        elif message.type == "document" and message.document:
            parsed.media_id = message.document.id
            parsed.mime_type = message.document.mime_type
            parsed.filename = message.document.filename
            parsed.caption = message.document.caption
            parsed.content = (
                message.document.filename
                or message.document.caption
                or f"Media attachment: document ({message.document.mime_type})"
            )

        elif message.type == "interactive" and message.interactive:
            interactive = message.interactive
            parsed.interactive_type = interactive.type
            reply = interactive.button_reply or interactive.list_reply

            if not reply:
                logger.warning(
                    f"Interactive reply of type '{interactive.type}' carried no selection.",
                    extra={"event": "unsupported_interactive_reply_format"},
                )
                return None

            parsed.interactive_id = reply.id
            parsed.interactive_title = reply.title
            parsed.content = f"Interactive reply: {reply.title}"

        else:
            return _missing_node(message)

        return parsed


def _missing_node(message: Message) -> None:
    """Logs a message whose declared type has no matching payload node."""
    logger.warning(
        f"Message declared type '{message.type}' but carried no matching node.",
        extra={
            "event": "missing_message_payload_nodes",
            "message_type": message.type,
            "whatsapp_message_id": message.id,
        },
    )
    return None


def _safe_timestamp(raw: Optional[str]) -> int:
    """Converts Meta's string epoch timestamp, falling back to now."""
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return int(time.time())
