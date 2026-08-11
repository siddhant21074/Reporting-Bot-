"""Templates module exports."""

from app.templates.workflow_welcome import get_welcome_message
from app.templates.workflow_processing import (
    get_voice_received_ack,
    get_voice_processed_success,
    get_upload_photos_prompt,
    get_photo_received_ack,
    get_skip_photos_ack,
    get_text_update_ack,
    get_document_received_ack,
    get_empty_done_error,
    get_processing_report_status,
    get_media_unavailable_error,
    get_transcription_failed_error,
    get_report_failed_error,
)
from app.templates.workflow_preview import get_draft_preview
from app.templates.workflow_complete import get_report_generated_ack
from app.templates.workflow_reset import get_workflow_reset_ack

__all__ = [
    "get_welcome_message",
    "get_voice_received_ack",
    "get_voice_processed_success",
    "get_upload_photos_prompt",
    "get_photo_received_ack",
    "get_skip_photos_ack",
    "get_text_update_ack",
    "get_document_received_ack",
    "get_empty_done_error",
    "get_processing_report_status",
    "get_media_unavailable_error",
    "get_transcription_failed_error",
    "get_report_failed_error",
    "get_draft_preview",
    "get_report_generated_ack",
    "get_workflow_reset_ack",
]
