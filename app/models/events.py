"""Internal event models for event-driven backend communication."""

import time
import uuid
from typing import Any, Dict
from pydantic import BaseModel, Field

from app.models.whatsapp import ParsedMessage
from app.schemas.webhook import Status


class BaseEvent(BaseModel):
    """Base class for all internal events in the application."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = Field(default_factory=time.time)
    event_type: str


class WhatsAppMessageReceivedEvent(BaseEvent):
    """Emitted when an incoming WhatsApp message is successfully received and parsed."""
    event_type: str = "whatsapp.message_received"
    message: ParsedMessage


class WhatsAppStatusReceivedEvent(BaseEvent):
    """Emitted when a delivery status update is received from Meta (sent, delivered, read, failed)."""
    event_type: str = "whatsapp.status_received"
    status: Status
