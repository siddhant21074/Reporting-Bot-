"""Writes conversation history and report records to the database.

Everything here is best-effort: a history write must never break the user's
conversation. Failures are logged and swallowed, because the bot replying is
more important than the dashboard being complete.
"""

import logging
import os
from typing import Any, Dict, Optional

from app.db.base import session_scope
from app.db.models import MessageDirection, ReportStatus
from app.repositories import history

logger = logging.getLogger("app.services.events.recorder")


async def record_inbound(message: Any) -> None:
    """Stores an incoming message.

    Args:
        message: The ``ParsedMessage`` from the webhook.
    """
    try:
        async with session_scope() as session:
            await history.record_message(
                session,
                wa_id=message.sender_id,
                direction=MessageDirection.INBOUND,
                message_type=message.message_type,
                content=_inbound_text(message),
                provider_message_id=message.message_id,
                display_name=message.sender_name,
            )
            await session.commit()
    except Exception as exc:
        logger.error(
            f"Could not record the inbound message from {message.sender_id}: {exc}",
            exc_info=True,
            extra={"event": "history_write_failed", "sender": message.sender_id},
        )


async def record_outbound(wa_id: str, text: str, message_type: str = "text") -> None:
    """Stores a message the bot sent."""
    try:
        async with session_scope() as session:
            await history.record_message(
                session,
                wa_id=wa_id,
                direction=MessageDirection.OUTBOUND,
                message_type=message_type,
                content=text,
            )
            await session.commit()
    except Exception as exc:
        logger.error(
            f"Could not record the outbound message to {wa_id}: {exc}",
            exc_info=True,
            extra={"event": "history_write_failed", "sender": wa_id},
        )


async def attach_transcript(wa_id: str, media_path: str, transcript: str) -> None:
    """Attaches a transcript to the most recent voice note from a contact.

    The transcript arrives after the message row is written, so it is patched on
    rather than inserted with it.
    """
    if not transcript:
        return

    try:
        from sqlalchemy import select

        from app.db.models import Message

        async with session_scope() as session:
            result = await session.execute(
                select(Message)
                .where(
                    Message.wa_id == wa_id,
                    Message.direction == MessageDirection.INBOUND,
                    Message.message_type.in_(("audio", "voice")),
                )
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            message = result.scalars().first()
            if message is not None:
                message.transcript = transcript
                message.media_path = media_path
                await session.commit()
    except Exception as exc:
        logger.error(
            f"Could not attach the transcript for {wa_id}: {exc}",
            extra={"event": "history_write_failed", "sender": wa_id},
        )


async def record_report(
    wa_id: str,
    report_path: Optional[str],
    output_format: str,
    draft: Optional[Dict[str, Any]],
    photo_count: int,
    voice_note_count: int,
    extraction_path: Optional[str],
    generation_ms: int,
    error: Optional[str] = None,
) -> Optional[int]:
    """Stores a generated report and returns its database id.

    Args:
        wa_id: Whose report this is.
        report_path: Path to the document, or ``None`` if generation failed.
        output_format: ``pdf`` or ``docx``.
        draft: The extracted report structure, kept so it can be inspected later.
        photo_count: Photos embedded.
        voice_note_count: Voice notes that fed the report.
        extraction_path: ``ai`` or ``rule_based``.
        generation_ms: Wall-clock time to build the document.
        error: Failure reason, when there is one.

    Returns:
        The report row id, or ``None`` if the write failed.
    """
    try:
        async with session_scope() as session:
            report = await history.record_report(
                session,
                wa_id=wa_id,
                report_ref=_reference_from(report_path),
                output_format=output_format,
                file_path=report_path,
                status=ReportStatus.FAILED if error else ReportStatus.GENERATING,
                draft=draft,
                photo_count=photo_count,
                voice_note_count=voice_note_count,
                extraction_path=extraction_path,
                generation_ms=generation_ms,
                error=error,
            )
            await session.commit()
            return report.id
    except Exception as exc:
        logger.error(
            f"Could not record the report for {wa_id}: {exc}",
            exc_info=True,
            extra={"event": "history_write_failed", "sender": wa_id},
        )
        return None


async def mark_delivered(report_id: Optional[int]) -> None:
    """Flags a report as delivered once WhatsApp has accepted the document."""
    if report_id is None:
        return
    try:
        async with session_scope() as session:
            await history.mark_report_delivered(session, report_id)
            await session.commit()
    except Exception as exc:
        logger.error(f"Could not mark report {report_id} as delivered: {exc}")


async def mark_failed(report_id: Optional[int], error: str) -> None:
    """Flags a report as failed, e.g. when delivery to WhatsApp did not succeed."""
    if report_id is None:
        return
    try:
        from app.db.models import Report

        async with session_scope() as session:
            report = await session.get(Report, report_id)
            if report is not None:
                report.status = ReportStatus.FAILED
                report.error = error[:500]
                await session.commit()
    except Exception as exc:
        logger.error(f"Could not mark report {report_id} as failed: {exc}")


def _inbound_text(message: Any) -> str:
    """Builds the text stored for an inbound message."""
    if message.message_type == "interactive":
        return message.interactive_title or message.content or ""
    return message.content or ""


def _reference_from(report_path: Optional[str]) -> str:
    """Extracts the RPT-... reference the generator puts in the filename."""
    if not report_path:
        return "RPT-FAILED"

    stem = os.path.splitext(os.path.basename(report_path))[0]
    for part in stem.split("_"):
        if part.startswith("RPT-"):
            return part
    return stem[:64]
