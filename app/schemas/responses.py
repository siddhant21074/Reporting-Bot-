"""Pydantic schemas for standardized API responses."""

from typing import List, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Schema representing application health check state."""
    status: str = Field(default="running")
    version: str
    environment: str
    timestamp: str
    uptime_seconds: float
    whatsapp_config_status: bool


class WebhookVerificationResponse(BaseModel):
    """Schema representing webhook verification responses."""
    status: str
    message: str


class SentContact(BaseModel):
    """Contact reference returned by Meta after sending a message."""
    input: str
    wa_id: str


class SentMessage(BaseModel):
    """Message details returned by Meta after successful message processing."""
    id: str


class MessageResponse(BaseModel):
    """Schema representing Meta API response format for outbound messages."""
    messaging_product: str = "whatsapp"
    contacts: List[SentContact]
    messages: List[SentMessage]
