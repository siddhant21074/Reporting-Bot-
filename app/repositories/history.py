"""Data access for contacts, message history and generated reports.

Every read helper takes an optional ``wa_id`` scope. Passing it is how the USER
role is confined to its own number: the filter is applied in the query, not in
the template, so a scoped caller cannot see another contact's rows even if a
view forgets to check.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    Contact,
    Message,
    MessageDirection,
    Report,
    ReportStatus,
    expires_in,
    utcnow,
)

logger = logging.getLogger("app.repositories.history")


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


async def upsert_contact(
    db: AsyncSession,
    wa_id: str,
    display_name: Optional[str] = None,
    channel: str = "whatsapp",
) -> Contact:
    """Creates or refreshes a contact and returns it."""
    contact = await db.get(Contact, wa_id)

    if contact is None:
        contact = Contact(
            wa_id=wa_id,
            channel=channel,
            display_name=display_name,
            first_seen_at=utcnow(),
            last_seen_at=utcnow(),
        )
        db.add(contact)
        await db.flush()
        logger.info(
            f"New contact recorded: {wa_id}",
            extra={"event": "contact_created", "sender": wa_id},
        )
    else:
        contact.last_seen_at = utcnow()
        # Only overwrite the name when the channel actually supplied one.
        if display_name and display_name != "Unknown Contact":
            contact.display_name = display_name

    return contact


async def get_contact(db: AsyncSession, wa_id: str) -> Optional[Contact]:
    """Returns one contact, or None."""
    return await db.get(Contact, wa_id)


async def list_contacts(
    db: AsyncSession,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    wa_id_scope: Optional[str] = None,
) -> Tuple[List[Contact], int]:
    """Lists contacts newest-active first.

    Args:
        db: Session.
        search: Matches against number or display name.
        limit: Page size.
        offset: Page offset.
        wa_id_scope: When set, restricts results to this single number.

    Returns:
        The page of contacts and the total row count.
    """
    query = select(Contact)
    count_query = select(func.count()).select_from(Contact)

    if wa_id_scope:
        query = query.where(Contact.wa_id == wa_id_scope)
        count_query = count_query.where(Contact.wa_id == wa_id_scope)

    if search:
        pattern = f"%{search.strip()}%"
        condition = or_(Contact.wa_id.ilike(pattern), Contact.display_name.ilike(pattern))
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = (await db.execute(count_query)).scalar_one()
    rows = (
        await db.execute(query.order_by(Contact.last_seen_at.desc()).limit(limit).offset(offset))
    ).scalars().all()

    return list(rows), int(total)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


async def record_message(
    db: AsyncSession,
    wa_id: str,
    direction: MessageDirection,
    message_type: str = "text",
    content: Optional[str] = None,
    media_path: Optional[str] = None,
    transcript: Optional[str] = None,
    provider_message_id: Optional[str] = None,
    channel: str = "whatsapp",
    display_name: Optional[str] = None,
) -> Optional[Message]:
    """Writes one message to the history.

    Returns ``None`` when the provider message id has already been stored --
    that is a webhook retry, not a new message.
    """
    if provider_message_id:
        existing = (
            await db.execute(
                select(Message.id).where(Message.provider_message_id == provider_message_id)
            )
        ).first()
        if existing:
            return None

    contact = await upsert_contact(db, wa_id, display_name=display_name, channel=channel)

    message = Message(
        wa_id=wa_id,
        channel=channel,
        direction=direction,
        message_type=message_type,
        content=content,
        media_path=media_path,
        transcript=transcript,
        provider_message_id=provider_message_id,
        created_at=utcnow(),
        expires_at=expires_in(settings.app.retention_days),
    )
    db.add(message)

    contact.total_messages = (contact.total_messages or 0) + 1
    await db.flush()
    return message


async def list_messages(
    db: AsyncSession,
    wa_id: str,
    limit: int = 200,
    offset: int = 0,
) -> List[Message]:
    """Returns a contact's messages oldest-first, so it reads as a transcript."""
    rows = (
        await db.execute(
            select(Message)
            .where(Message.wa_id == wa_id)
            .order_by(Message.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return list(rows)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


async def record_report(
    db: AsyncSession,
    wa_id: str,
    report_ref: str,
    output_format: str,
    file_path: Optional[str],
    status: ReportStatus,
    draft: Optional[Dict[str, Any]] = None,
    photo_count: int = 0,
    voice_note_count: int = 0,
    extraction_path: Optional[str] = None,
    generation_ms: int = 0,
    error: Optional[str] = None,
    channel: str = "whatsapp",
) -> Report:
    """Records a generated report, successful or failed."""
    contact = await upsert_contact(db, wa_id, channel=channel)

    file_size = 0
    if file_path and os.path.exists(file_path):
        try:
            file_size = os.path.getsize(file_path)
        except OSError:
            file_size = 0

    summary = None
    title = None
    if draft:
        summary = draft.get("summary")
        metadata = (draft.get("report") or {}).get("metadata") or {}
        title = draft.get("site_name") or metadata.get("project_name")
        if title == "N/A":
            title = None

    report = Report(
        report_ref=report_ref,
        wa_id=wa_id,
        channel=channel,
        output_format=output_format,
        file_path=file_path,
        file_size=file_size,
        status=status,
        error=error,
        title=title,
        summary=summary,
        draft_json=draft,
        photo_count=photo_count,
        voice_note_count=voice_note_count,
        extraction_path=extraction_path,
        generation_ms=generation_ms,
        created_at=utcnow(),
        expires_at=expires_in(settings.app.retention_days),
    )
    db.add(report)

    if status == ReportStatus.DELIVERED:
        contact.total_reports = (contact.total_reports or 0) + 1

    await db.flush()
    logger.info(
        f"Report {report_ref} recorded for {wa_id} ({status}).",
        extra={"event": "report_recorded", "sender": wa_id, "report_ref": report_ref},
    )
    return report


async def mark_report_delivered(db: AsyncSession, report_id: int) -> None:
    """Flags a report as delivered to the user."""
    report = await db.get(Report, report_id)
    if report is None:
        return
    report.status = ReportStatus.DELIVERED
    report.delivered_at = utcnow()
    await db.flush()


async def get_report(db: AsyncSession, report_id: int) -> Optional[Report]:
    """Returns one report, or None."""
    return await db.get(Report, report_id)


async def list_reports(
    db: AsyncSession,
    wa_id: Optional[str] = None,
    status: Optional[ReportStatus] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    wa_id_scope: Optional[str] = None,
) -> Tuple[List[Report], int]:
    """Lists reports newest-first.

    Args:
        db: Session.
        wa_id: Filter to one contact, chosen by the viewer.
        status: Filter by delivery status.
        search: Matches the report reference or title.
        limit: Page size.
        offset: Page offset.
        wa_id_scope: Hard restriction applied on top of everything else, used
            for the USER role.

    Returns:
        The page of reports and the total row count.
    """
    query = select(Report)
    count_query = select(func.count()).select_from(Report)

    def _apply(condition):
        nonlocal query, count_query
        query = query.where(condition)
        count_query = count_query.where(condition)

    if wa_id_scope:
        _apply(Report.wa_id == wa_id_scope)
    if wa_id:
        _apply(Report.wa_id == wa_id)
    if status:
        _apply(Report.status == status)
    if search:
        pattern = f"%{search.strip()}%"
        _apply(or_(Report.report_ref.ilike(pattern), Report.title.ilike(pattern)))

    total = (await db.execute(count_query)).scalar_one()
    rows = (
        await db.execute(query.order_by(Report.created_at.desc()).limit(limit).offset(offset))
    ).scalars().all()

    return list(rows), int(total)


# ---------------------------------------------------------------------------
# Dashboard statistics
# ---------------------------------------------------------------------------


async def dashboard_stats(db: AsyncSession, wa_id_scope: Optional[str] = None) -> Dict[str, Any]:
    """Aggregates the numbers shown on the dashboard.

    Args:
        db: Session.
        wa_id_scope: When set, every figure covers only that number.
    """
    now = utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    window_start = now - timedelta(days=settings.app.retention_days)

    def scoped(query, model):
        return query.where(model.wa_id == wa_id_scope) if wa_id_scope else query

    reports_today = (await db.execute(scoped(
        select(func.count()).select_from(Report).where(Report.created_at >= today_start), Report
    ))).scalar_one()

    reports_window = (await db.execute(scoped(
        select(func.count()).select_from(Report).where(Report.created_at >= window_start), Report
    ))).scalar_one()

    delivered = (await db.execute(scoped(
        select(func.count()).select_from(Report)
        .where(Report.created_at >= window_start, Report.status == ReportStatus.DELIVERED),
        Report,
    ))).scalar_one()

    failed = (await db.execute(scoped(
        select(func.count()).select_from(Report)
        .where(Report.created_at >= window_start, Report.status == ReportStatus.FAILED),
        Report,
    ))).scalar_one()

    messages_window = (await db.execute(scoped(
        select(func.count()).select_from(Message).where(Message.created_at >= window_start), Message
    ))).scalar_one()

    if wa_id_scope:
        active_contacts = 1 if await db.get(Contact, wa_id_scope) else 0
    else:
        active_contacts = (await db.execute(
            select(func.count()).select_from(Contact).where(Contact.last_seen_at >= window_start)
        )).scalar_one()

    avg_ms = (await db.execute(scoped(
        select(func.avg(Report.generation_ms))
        .where(Report.created_at >= window_start, Report.generation_ms > 0),
        Report,
    ))).scalar()

    ai_reports = (await db.execute(scoped(
        select(func.count()).select_from(Report)
        .where(Report.created_at >= window_start, Report.extraction_path == "ai"),
        Report,
    ))).scalar_one()

    total_reports = int(reports_window)
    success_rate = round(delivered / total_reports * 100) if total_reports else None
    ai_rate = round(ai_reports / total_reports * 100) if total_reports else None

    return {
        "reports_today": int(reports_today),
        "reports_window": total_reports,
        "delivered": int(delivered),
        "failed": int(failed),
        "messages_window": int(messages_window),
        "active_contacts": int(active_contacts),
        "success_rate": success_rate,
        "ai_rate": ai_rate,
        "avg_seconds": round(float(avg_ms) / 1000, 1) if avg_ms else None,
        "retention_days": settings.app.retention_days,
    }


async def reports_per_day(
    db: AsyncSession, days: int = 7, wa_id_scope: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Returns a per-day report count for the activity chart.

    Grouping is done in Python rather than SQL because the date functions differ
    between SQLite and Postgres, and the row count here is tiny.
    """
    now = utcnow()
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    query = select(Report.created_at, Report.status).where(Report.created_at >= start)
    if wa_id_scope:
        query = query.where(Report.wa_id == wa_id_scope)

    rows = (await db.execute(query)).all()

    buckets: Dict[str, Dict[str, int]] = {}
    for offset in range(days):
        day = (start + timedelta(days=offset)).date()
        buckets[day.isoformat()] = {"delivered": 0, "failed": 0}

    for created_at, status in rows:
        key = created_at.date().isoformat()
        if key not in buckets:
            continue
        is_failed = status == ReportStatus.FAILED or str(status) == "failed"
        buckets[key]["failed" if is_failed else "delivered"] += 1

    return [
        {
            "date": key,
            "label": datetime.fromisoformat(key).strftime("%a"),
            "delivered": value["delivered"],
            "failed": value["failed"],
            "total": value["delivered"] + value["failed"],
        }
        for key, value in buckets.items()
    ]


async def recent_activity(
    db: AsyncSession, limit: int = 12, wa_id_scope: Optional[str] = None
) -> List[Report]:
    """Returns the most recent reports for the dashboard feed."""
    query = select(Report).order_by(Report.created_at.desc()).limit(limit)
    if wa_id_scope:
        query = query.where(Report.wa_id == wa_id_scope)
    return list((await db.execute(query)).scalars().all())


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


async def purge_expired(db: AsyncSession) -> Dict[str, int]:
    """Deletes expired rows and the files they point at.

    Contact counters are deliberately left alone, so lifetime totals survive.

    Returns:
        Counts of what was removed.
    """
    now = utcnow()
    removed = {"messages": 0, "reports": 0, "files": 0}

    # Collect file paths before deleting the rows that reference them.
    expired_reports = (
        await db.execute(select(Report).where(Report.expires_at.is_not(None), Report.expires_at < now))
    ).scalars().all()

    expired_media = (
        await db.execute(
            select(Message.media_path).where(
                Message.expires_at.is_not(None),
                Message.expires_at < now,
                Message.media_path.is_not(None),
            )
        )
    ).scalars().all()

    for path in [r.file_path for r in expired_reports] + list(expired_media):
        if path and os.path.exists(path):
            try:
                os.remove(path)
                removed["files"] += 1
            except OSError as exc:
                logger.warning(f"Could not delete expired file '{path}': {exc}")

    result = await db.execute(delete(Report).where(Report.expires_at.is_not(None), Report.expires_at < now))
    removed["reports"] = result.rowcount or 0

    result = await db.execute(delete(Message).where(Message.expires_at.is_not(None), Message.expires_at < now))
    removed["messages"] = result.rowcount or 0

    await db.flush()

    if any(removed.values()):
        logger.info(
            f"Retention purge removed {removed['messages']} message(s), "
            f"{removed['reports']} report(s) and {removed['files']} file(s).",
            extra={"event": "retention_purge", **removed},
        )
    return removed


def purge_orphan_files() -> int:
    """Deletes media and report files older than the retention window.

    Catches files whose rows never got written -- a crash mid-flow, for example.
    Synchronous file IO: call it with ``asyncio.to_thread``.

    Returns:
        The number of files removed.
    """
    cutoff = (utcnow() - timedelta(days=settings.app.retention_days + 1)).timestamp()
    removed = 0

    for directory in (settings.app.media_dir, settings.app.reports_dir, settings.app.temp_dir):
        if not directory or not os.path.isdir(directory):
            continue
        for entry in os.listdir(directory):
            path = os.path.join(directory, entry)
            if entry.startswith(".") or not os.path.isfile(path):
                continue
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed += 1
            except OSError:
                continue

    return removed
