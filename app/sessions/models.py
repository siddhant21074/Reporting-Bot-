"""Models and enums describing a user's in-flight report session."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class WorkflowState(str, Enum):
    """States the report-generation conversation moves through."""
    IDLE = "IDLE"
    WAITING_FOR_INPUT = "WAITING_FOR_INPUT"
    WAITING_FOR_PHOTOS = "WAITING_FOR_PHOTOS"
    WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
    GENERATING_REPORT = "GENERATING_REPORT"
    REPORT_GENERATED = "REPORT_GENERATED"
    CANCELLED = "CANCELLED"

    # Aliases kept for older call sites; Enum resolves these to the members above.
    COLLECTING = "WAITING_FOR_INPUT"
    AWAITING_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
    SUBMITTED = "REPORT_GENERATED"


# Backwards-compatible alias.
SessionState = WorkflowState


class UserSession(BaseModel):
    """An in-flight report session for one sender, on one channel."""

    sender_id: str
    channel: str = "whatsapp"
    sender_name: Optional[str] = None
    state: WorkflowState = WorkflowState.IDLE
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Collected inputs
    voice_notes: List[Dict[str, Any]] = Field(default_factory=list)
    photos: List[str] = Field(default_factory=list)
    text_updates: List[str] = Field(default_factory=list)
    documents: List[Dict[str, Any]] = Field(default_factory=list)
    last_photo_time: float = 0.0

    # Extraction output
    draft_report: Optional[Dict[str, Any]] = None
    generated_report_path: Optional[str] = None
    requested_format: str = "pdf"
    extraction_path: Optional[str] = None
    # Row id of the report in the history table, so delivery can be marked.
    report_record_id: Optional[int] = None

    def touch(self) -> None:
        """Marks the session as active as of now."""
        self.updated_at = datetime.now(timezone.utc)

    def is_expired(self, timeout_seconds: int = 1800) -> bool:
        """Checks whether the session has been idle past the timeout."""
        elapsed = (datetime.now(timezone.utc) - self.updated_at).total_seconds()
        return elapsed > timeout_seconds

    def has_voice_or_text(self) -> bool:
        """True when there is at least one input worth building a report from."""
        return bool(self.voice_notes or self.text_updates or self.photos)

    def collected_media_paths(self) -> List[str]:
        """Every local file this session downloaded, for cleanup."""
        paths = list(self.photos)
        paths.extend(note["file_path"] for note in self.voice_notes if note.get("file_path"))
        paths.extend(doc["file_path"] for doc in self.documents if doc.get("file_path"))
        return paths

    def clear_workflow(self) -> None:
        """Discards all collected input and returns the session to IDLE."""
        self.state = WorkflowState.IDLE
        self.voice_notes.clear()
        self.photos.clear()
        self.text_updates.clear()
        self.documents.clear()
        self.draft_report = None
        self.generated_report_path = None
        self.extraction_path = None
        self.report_record_id = None
