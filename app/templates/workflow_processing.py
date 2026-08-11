"""Processing and input acknowledgment message templates."""

from typing import Optional


def get_voice_received_ack() -> str:
    """Returns immediate voice note receipt response."""
    return (
        "🎤 Voice note received.\n\n"
        "⏳ Processing your update..."
    )


def get_voice_processed_success() -> str:
    """Returns voice transcription completion message."""
    return (
        "✅ Voice note processed successfully.\n\n"
        "Would you like to add photos or attachments?"
    )


def get_upload_photos_prompt() -> str:
    """Returns photo upload prompt message."""
    return (
        "📷 Upload one or more photos or attachments.\n\n"
        "When you've finished uploading, tap \"Done\"."
    )


def get_photo_received_ack(photo_count: int) -> str:
    """Returns photo upload acknowledgment message."""
    return (
        f"📷 {photo_count} photo(s) attached.\n\n"
        "Upload more photos or tap \"Done\" when finished."
    )


def get_skip_photos_ack() -> str:
    """Returns acknowledgment when user replies SKIP."""
    return (
        "👍 No problem.\n\n"
        "⚙️ Generating your report draft...\n\n"
        "Please wait..."
    )


def get_text_update_ack() -> str:
    """Returns text message update acknowledgment."""
    return (
        "✍️ Text Update Received\n\n"
        "Now please send\n"
        "🎤 Voice Note\n"
        "or\n"
        "📷 Photographs & Attachments\n"
        "to complete the report."
    )


def get_document_received_ack(filename: Optional[str] = None) -> str:
    """Returns document file acknowledgment."""
    name_str = f" ({filename})" if filename else ""
    return (
        f"📄 Document Received{name_str}.\n\n"
        "You can send voice notes, text, or photos."
    )


def get_empty_done_error() -> str:
    """Returns error message when DONE is called without voice or text updates."""
    return (
        "No project update found.\n"
        "Please send a Voice Note or Text Update first."
    )


def get_media_unavailable_error() -> str:
    """Returns the message shown when an attachment could not be downloaded."""
    return (
        "⚠️ That attachment didn't reach me.\n\n"
        "Please send it again. If it keeps failing, type your update as text instead."
    )


def get_transcription_failed_error() -> str:
    """Returns the message shown when a voice note could not be transcribed."""
    return (
        "⚠️ I couldn't make out that voice note.\n\n"
        "Try recording again somewhere quieter, or send your update as text."
    )


def get_report_failed_error() -> str:
    """Returns the message shown when document generation failed."""
    return (
        "⚠️ Something went wrong while building your report.\n\n"
        "Your update is still saved — tap a format again to retry, or send RESET to start over."
    )


def get_processing_report_status(has_voice: bool, has_text: bool, photo_count: int) -> str:
    """Returns status text when report generation begins."""
    items = []
    if has_voice:
        items.append("✔ Voice Note")
    if has_text:
        items.append("✔ Text Update")
    items.append(f"✔ {photo_count} Photos")
    items.append("✔ Draft Reviewed")
    
    checklist = "\n".join(items)
    return (
        "⏳ Generating your report...\n\n"
        f"{checklist}"
    )
