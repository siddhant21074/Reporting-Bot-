"""ORM models for contacts, message history, reports, logins and settings.

Retention: rows that expire carry an ``expires_at``, set at insert from
``RETENTION_DAYS``. The purge task deletes them and unlinks the files they
point at. Aggregate counters live on ``Contact`` so the dashboard keeps correct
lifetime totals after the underlying rows are gone.
"""

import enum
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(timezone.utc)


def expires_in(days: int) -> datetime:
    """Returns the expiry timestamp for a retention window."""
    return utcnow() + timedelta(days=days)


class UserRole(str, enum.Enum):
    """Who can see and change what.

    ADMIN  -- everything, including settings and user management.
    VIEWER -- read-only across every contact and report.
    USER   -- read-only, and only for the WhatsApp number linked to the account.
    """

    ADMIN = "admin"
    VIEWER = "viewer"
    USER = "user"

    @property
    def label(self) -> str:
        return {"admin": "Administrator", "viewer": "Viewer", "user": "User"}[self.value]

    @property
    def can_manage(self) -> bool:
        """True when the role may change settings or manage logins."""
        return self is UserRole.ADMIN

    @property
    def sees_everything(self) -> bool:
        """True when the role is not restricted to a single WhatsApp number."""
        return self in (UserRole.ADMIN, UserRole.VIEWER)


class MessageDirection(str, enum.Enum):
    """Which way a message travelled."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class ReportStatus(str, enum.Enum):
    """Lifecycle of a generated document."""

    GENERATING = "generating"
    DELIVERED = "delivered"
    FAILED = "failed"

    @property
    def label(self) -> str:
        return {"generating": "Generating", "delivered": "Delivered", "failed": "Failed"}[self.value]


class User(Base):
    """A dashboard login."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(String(16), default=UserRole.VIEWER)
    display_name: Mapped[Optional[str]] = mapped_column(String(128), default=None)

    # Set only for UserRole.USER: the WhatsApp number this login may see.
    # Everything the account can read is filtered on this value.
    wa_id: Mapped[Optional[str]] = mapped_column(String(32), index=True, default=None)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    created_by: Mapped[Optional[str]] = mapped_column(String(64), default=None)

    @property
    def name(self) -> str:
        """Best available human name for the account."""
        return self.display_name or self.username

    @property
    def role_enum(self) -> UserRole:
        """The role as an enum, tolerating a raw string from the database."""
        return self.role if isinstance(self.role, UserRole) else UserRole(str(self.role))


class Contact(Base):
    """Someone who has messaged the bot.

    Survives retention purges, so lifetime totals stay correct even after the
    individual messages and reports have been deleted.
    """

    __tablename__ = "contacts"

    wa_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    channel: Mapped[str] = mapped_column(String(16), default="whatsapp")
    display_name: Mapped[Optional[str]] = mapped_column(String(128), default=None)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    total_messages: Mapped[int] = mapped_column(Integer, default=0)
    total_reports: Mapped[int] = mapped_column(Integer, default=0)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="contact", cascade="all, delete-orphan", lazy="noload"
    )
    reports: Mapped[list["Report"]] = relationship(
        back_populates="contact", cascade="all, delete-orphan", lazy="noload"
    )

    @property
    def display(self) -> str:
        """Name if known, otherwise the number."""
        return self.display_name or self.wa_id


class Message(Base):
    """One message in or out. This is the conversation history."""

    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_wa_created", "wa_id", "created_at"),
        Index("ix_messages_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wa_id: Mapped[str] = mapped_column(String(32), ForeignKey("contacts.wa_id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(16), default="whatsapp")

    direction: Mapped[MessageDirection] = mapped_column(String(16))
    message_type: Mapped[str] = mapped_column(String(24), default="text")
    content: Mapped[Optional[str]] = mapped_column(Text, default=None)

    media_path: Mapped[Optional[str]] = mapped_column(String(512), default=None)
    transcript: Mapped[Optional[str]] = mapped_column(Text, default=None)

    # Meta/Telegram message id. Unique so a webhook retry cannot insert twice.
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(128), unique=True, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)

    contact: Mapped["Contact"] = relationship(back_populates="messages", lazy="joined")

    @property
    def is_inbound(self) -> bool:
        return self.direction == MessageDirection.INBOUND or self.direction == "inbound"

    @property
    def preview(self) -> str:
        """Short single-line summary for list views."""
        text = self.transcript or self.content or ""
        text = " ".join(text.split())
        return text[:117] + "..." if len(text) > 120 else text


class Report(Base):
    """A generated document."""

    __tablename__ = "reports"
    __table_args__ = (
        Index("ix_reports_wa_created", "wa_id", "created_at"),
        Index("ix_reports_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_ref: Mapped[str] = mapped_column(String(64), index=True)
    wa_id: Mapped[str] = mapped_column(String(32), ForeignKey("contacts.wa_id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(16), default="whatsapp")

    output_format: Mapped[str] = mapped_column(String(8), default="pdf")
    file_path: Mapped[Optional[str]] = mapped_column(String(512), default=None)
    file_size: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[ReportStatus] = mapped_column(String(16), default=ReportStatus.GENERATING, index=True)
    error: Mapped[Optional[str]] = mapped_column(Text, default=None)

    title: Mapped[Optional[str]] = mapped_column(String(255), default=None)
    summary: Mapped[Optional[str]] = mapped_column(Text, default=None)
    draft_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=None)

    photo_count: Mapped[int] = mapped_column(Integer, default=0)
    voice_note_count: Mapped[int] = mapped_column(Integer, default=0)
    # 'ai' or 'rule_based' -- lets the dashboard show how often the model was
    # actually reachable.
    extraction_path: Mapped[Optional[str]] = mapped_column(String(24), default=None)
    generation_ms: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)

    contact: Mapped["Contact"] = relationship(back_populates="reports", lazy="joined")

    @property
    def status_enum(self) -> ReportStatus:
        """The status as an enum, tolerating a raw string from the database."""
        return self.status if isinstance(self.status, ReportStatus) else ReportStatus(str(self.status))

    @property
    def file_exists(self) -> bool:
        """True when the document is still on disk and downloadable."""
        import os

        return bool(self.file_path) and os.path.exists(self.file_path)

    @property
    def size_label(self) -> str:
        """Human-readable file size."""
        if not self.file_size:
            return "—"
        if self.file_size < 1024:
            return f"{self.file_size} B"
        if self.file_size < 1024 * 1024:
            return f"{self.file_size / 1024:.0f} KB"
        return f"{self.file_size / (1024 * 1024):.1f} MB"


class ConversationSession(Base):
    """Persisted workflow state, so an in-flight report survives a restart."""

    __tablename__ = "conversation_sessions"

    wa_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    channel: Mapped[str] = mapped_column(String(16), default="whatsapp")
    state: Mapped[str] = mapped_column(String(32), default="IDLE")
    payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)


class AppSetting(Base):
    """A configuration value saved from the Settings page.

    These override the environment at runtime -- see
    ``app.core.config.apply_runtime_overrides``.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text, default=None)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    updated_by: Mapped[Optional[str]] = mapped_column(String(64), default=None)


class AuditLog(Base):
    """Record of who changed what, so settings edits are attributable."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[Optional[str]] = mapped_column(String(128), default=None)
    detail: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
