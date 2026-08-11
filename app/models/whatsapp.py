"""Internal business models representing domain entities."""

from typing import Optional
from pydantic import BaseModel


class ParsedMessage(BaseModel):
    """Domain model representing a structured, parsed incoming WhatsApp message."""
    message_id: str
    sender_id: str  # User's wa_id/phone number
    sender_name: str  # Profile name
    phone_number: str  # Business phone number that received it
    timestamp: int  # Epoch timestamp
    message_type: str  # text, audio, voice, image, video, document, interactive
    content: str  # Text body or media type summary string
    media_id: Optional[str] = None
    mime_type: Optional[str] = None
    caption: Optional[str] = None
    filename: Optional[str] = None
    interactive_type: Optional[str] = None  # button_reply, list_reply
    interactive_id: Optional[str] = None  # ID of button/list selection
    interactive_title: Optional[str] = None  # Title/Label of selection
